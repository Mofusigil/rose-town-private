import json
from pathlib import Path
import tempfile
import unittest

from tools import verify_mirror as mirror


class MirrorTests(unittest.TestCase):
    def test_real_native_metadata_preserves_unusual_extensions(self):
        cases = (
            ("Flowers", "94af83ad-ee00-4de8-b4d4-91493f084ca1", ".bin"),
            ("Act_2609ShuangHuiYingChangAn", "c686e4cc-29b1-4156-b3bb-2b482daf847b", ".py"),
            ("2201HappyDumplingsRes", "6da83eaa-2f9a-463a-afe9-d3fde2df63f7", ".bytes"),
        )
        for bundle, uuid, extension in cases:
            with self.subTest(bundle=bundle):
                directory = mirror.DEFAULT_ROOT / "assets" / bundle
                config = json.loads(next(directory.glob("config.*.json")).read_text())
                index = next(i for i, item in enumerate(config["uuids"]) if mirror.decode_uuid(item) == uuid)
                self.assertEqual(mirror.imported_native(config, directory, index, {}), [extension])

    def test_real_background_uses_png_signature_despite_jpg_suffix(self):
        path = mirror.DEFAULT_ROOT / "img/mark_bg.jpg"
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(mirror.inspect_file(path)["size"], path.stat().st_size)

    def test_truncated_image_and_html_error_body_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, content in (("image.jpg", b"\xff\xd8truncated"),
                                  ("data.bytes", b"<!DOCTYPE html><html>404</html>")):
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(content)
                    with self.assertRaises(ValueError):
                        mirror.inspect_file(path)

    def test_settings_are_parsed_as_literals_without_executing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.js"
            path.write_text('window._CCSettings={bundleVers:{main:"abcde","flowers":"12345"}};')
            self.assertEqual(mirror.read_bundle_versions(path), {"main": "abcde", "flowers": "12345"})
            path.write_text('window._CCSettings={bundleVers:{main:arbitraryFunction()}};')
            with self.assertRaises(ValueError):
                mirror.read_bundle_versions(path)


if __name__ == "__main__":
    unittest.main()
