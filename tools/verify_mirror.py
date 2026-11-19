#!/usr/bin/env python3
"""Audit this Cocos 2.4 mirror without executing scripts or downloading assets.

The default is fully offline. --probe-missing checks only exact missing native
URLs on the two original CDN bases, without saving response bodies. SHA-256 is a
local baseline, not an assertion of identity with an unpublished upstream digest.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "site/h5/meigui"
BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
TEXTURE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".webp", ".pvr", ".pkm"]
KNOWN_MISSING = {
    "assets/Flowers/native/94/94af83ad-ee00-4de8-b4d4-91493f084ca1.b472a.bin"
}
EXTERNAL_ASSETS = [
    "music/mgBGMusic.mp3", "music/music_v1.mp3", "lib/base64.js",
    "img/blurred_bg.jpg", "img/mark_bg.jpg", "img/fuzzyBg.png",
    "icon/IconSmall/TaskAIcon1213.png",
]


def decode_uuid(value):
    if len(value) != 22:
        return value
    digits = value[:2] + "".join(
        f"{(BASE64.index(value[i]) << 6) | BASE64.index(value[i + 1]):03x}"
        for i in range(2, 22, 2)
    )
    return "-".join([digits[:8], digits[8:12], digits[12:16], digits[16:20], digits[20:]])


def read_bundle_versions(path):
    """Read the shipped literal map, never eval/execute the settings script."""
    source = path.read_text(encoding="utf-8")
    match = re.search(r"\bbundleVers\s*:\s*\{([^}]+)\}", source)
    if not match:
        raise ValueError(f"bundleVers literal not found: {path}")
    pattern = re.compile(r'\s*(?:"([^"\\]+)"|([A-Za-z_$][\w$]*))\s*:\s*"([a-f0-9]+)"\s*(?:,|$)')
    result, cursor = {}, 0
    while cursor < len(match[1]):
        entry = pattern.match(match[1], cursor)
        if not entry:
            raise ValueError(f"Unsupported bundleVers syntax: {path}")
        name = entry[1] or entry[2]
        if name in result:
            raise ValueError(f"Duplicate bundle: {name}")
        result[name] = entry[3]
        cursor = entry.end()
    return result


def version_pairs(values):
    if len(values) % 2:
        raise ValueError("Odd-length asset version table")
    return dict(zip(values[::2], values[1::2]))


def native_extensions(document):
    """Decode Cocos compiled imports and texture packs from shipped metadata.

    The engine uses Texture2D.extnames for image formats, and the serialized
    Asset._native property for every other native extension. A generic cc.Asset
    can be .bytes or .py; guessing from its class name silently loses resources.
    """
    if isinstance(document, dict):
        asset_type, data = document["type"], document["data"]
    else:
        data = document[5][0]
        if isinstance(data, list):
            mask = document[4][data[0]]
            class_info = document[3][mask[0]]
            properties = dict(zip((class_info[1][i] for i in mask[1:-1]), data[1:]))
            extension = properties["_native"]
            if not re.fullmatch(r"\.[A-Za-z0-9]+", extension):
                raise ValueError(f"Unsupported native name: {extension!r}")
            return [extension]
        asset_type = document[3][document[6][0]]
    if asset_type != "cc.Texture2D":
        raise ValueError(f"Unsupported native serialization: {asset_type}")
    result = []
    for format_spec in data.split(",")[0].split("_"):
        extension = format_spec.split("@")[0]
        extension = TEXTURE_EXTENSIONS[int(extension)] if extension.isdigit() else extension
        if not re.fullmatch(r"\.[A-Za-z0-9]+", extension):
            raise ValueError(f"Unsupported texture extension: {extension!r}")
        result.append(extension)
    return result


def imported_native(config, bundle_dir, asset_id, cache):
    versions = version_pairs(config["versions"]["import"])
    for pack, ids in config["packs"].items():
        if asset_id in ids:
            key, ordinal = pack, ids.index(asset_id)
            break
    else:
        key, ordinal = asset_id, None
    uuid = decode_uuid(config["uuids"][key]) if isinstance(key, int) else key
    path = bundle_dir / config["importBase"] / uuid[:2] / f"{uuid}.{versions[key]}.json"
    if path not in cache:
        cache[path] = json.loads(path.read_text(encoding="utf-8"))
    document = cache[path]
    if ordinal is not None:
        if isinstance(document, dict):
            document = {"type": document["type"], "data": document["data"].split("|")[ordinal]}
        else:
            document = document[:5] + document[5][ordinal]
    return native_extensions(document)


def inspect_file(path):
    """Hash every byte and catch empty files, truncated images and invalid JSON."""
    digest, size, head, tail = hashlib.sha256(), 0, b"", b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            if not head:
                head = chunk[:64]
            tail = chunk[-32:]
    if not size:
        raise ValueError("empty file")
    suffix = path.suffix.lower()
    # The shipped mark_bg.jpg actually contains a PNG. Browsers decode by the
    # content signature; validate that format rather than treating it as corrupt.
    if suffix in (".png", ".jpg", ".jpeg"):
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            if not tail.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                raise ValueError("truncated PNG IEND")
        elif head.startswith(b"\xff\xd8"):
            if not tail.endswith(b"\xff\xd9"):
                raise ValueError("truncated JPEG EOI")
        else:
            raise ValueError("unrecognized image header")
    if suffix == ".json":
        json.loads(path.read_text(encoding="utf-8"))
    if suffix in (".js", ".bin", ".bytes") and head.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("HTML error response stored as an asset")
    return {"size": size, "sha256": digest.hexdigest()}


def probe_missing(relative_path, timeout=15):
    suffix = relative_path.removeprefix("act/main/")
    observations = []
    for prefix in ("", "act/main/"):
        url = "https://baobaocdn.qq.com/cdn/h5/meigui/" + prefix + suffix
        result = {"url": url}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "rose-town-mirror-audit/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result.update(status=response.status, content_type=response.headers.get("Content-Type"),
                              content_length=response.headers.get("Content-Length"))
                response.read(1)
        except urllib.error.HTTPError as error:
            result["status"] = error.code
        except (OSError, urllib.error.URLError) as error:
            result["error"] = str(error)
        observations.append(result)
    return observations


def audit(root, probe=False):
    root = Path(root).resolve()
    report = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root), "counts": {}, "bundles": [], "missing": [], "errors": [],
        "limitations": [
            "SHA-256 records local bytes; no authoritative upstream hash manifest is available.",
            "PNG/JPEG validation checks headers and end markers, not a full image decode.",
            "Opaque native payloads are hashed, not executed or semantically validated.",
            "Dynamic runtime asset names beyond the explicit external list are not exhaustively inferred.",
        ],
    }
    expected, cache = {}, {}
    def expect(path, category):
        relative = path.relative_to(root).as_posix()
        expected[relative] = category
        if not path.is_file():
            item = {"path": relative, "category": category, "known": relative in KNOWN_MISSING}
            if probe and category == "native":
                item["cdn"] = probe_missing(relative)
            report["missing"].append(item)

    settings = [("rose", root / "src/settings.c8d1c.js"),
                ("act", root / "act/main/src/settings.2dbf4.js")]
    configs = set()
    rose_versions = read_bundle_versions(settings[0][1])
    for role, path in settings:
        expect(path, "settings")
        versions = read_bundle_versions(path)
        for name, version in versions.items():
            base = root / "assets" / name
            if role == "act" and version != rose_versions.get(name):
                base = root / "act/main/assets" / name
            configs.add(base / f"config.{version}.json")
    for path in sorted(configs):
        expect(path, "config")
        version = path.name.split(".")[1]
        expect(path.parent / f"index.{version}.js", "index")
        if not path.is_file():
            continue
        counts = Counter(config=1, index=1)
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if config["isZip"] or config["encrypted"]:
                raise ValueError("zip/encrypted bundle requires a separate decoder")
            for key, version in version_pairs(config["versions"]["import"]).items():
                uuid = decode_uuid(config["uuids"][key]) if isinstance(key, int) else key
                expect(path.parent / config["importBase"] / uuid[:2] / f"{uuid}.{version}.json", "import")
                counts["import"] += 1
            for key, version in version_pairs(config["versions"]["native"]).items():
                uuid = decode_uuid(config["uuids"][key]) if isinstance(key, int) else key
                extensions = imported_native(config, path.parent, key, cache)
                for extension in extensions:
                    expect(path.parent / config["nativeBase"] / uuid[:2] / f"{uuid}.{version}{extension}", "native")
                    counts["native"] += 1
            report["bundles"].append({"config": path.relative_to(root).as_posix(), "expected": dict(counts)})
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            report["errors"].append({"path": path.relative_to(root).as_posix(), "error": str(error)})
    for relative in EXTERNAL_ASSETS:
        expect(root / relative, "external")
    unreferenced = sorted(str(path.relative_to(root)) for path in root.rglob("config.*.json") if path not in configs)
    if unreferenced:
        report["errors"].append({"unreferenced_configs": unreferenced})
    inventory = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            if path.is_symlink():
                raise ValueError("symlink in mirror")
            inventory[relative] = inspect_file(path)
        except (OSError, ValueError) as error:
            report["errors"].append({"path": relative, "error": str(error)})
    for category in sorted(set(expected.values())):
        paths = [p for p, value in expected.items() if value == category]
        present = sum(path in inventory for path in paths)
        report["counts"][category] = {"expected": len(paths), "verified": present, "missing_or_invalid": len(paths) - present}
    report["inventory"] = {"files": len(inventory), "bytes": sum(v["size"] for v in inventory.values())}
    report["status"] = "failed" if report["errors"] or any(not item["known"] for item in report["missing"]) else ("pass_with_known_missing" if report["missing"] else "pass")
    return report, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "verification/mirror-audit.json")
    parser.add_argument("--manifest", type=Path, help="optional complete local SHA-256 JSON manifest")
    parser.add_argument("--probe-missing", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit nonzero for even known missing assets")
    args = parser.parse_args()
    report, inventory = audit(args.root, args.probe_missing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "counts", "inventory", "missing", "errors")}, ensure_ascii=False, indent=2))
    return int(report["status"] == "failed" or bool(args.strict and report["missing"]))


if __name__ == "__main__":
    sys.exit(main())
