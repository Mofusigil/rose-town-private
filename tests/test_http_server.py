import contextlib
import http.client
import http.server
import io
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

import private_server as server


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name) / "site"
        self.root.mkdir()
        self.secret = pathlib.Path(self.directory.name) / "private.json"
        self.secret.write_text('{"secret":"outside mirror"}')
        self.source = (b'const cgi="https://cgi.meigui.qq.com/cgi-bin/";'
                       b'const image="https://baobaocdn.qq.com/cdn/h5/meigui/icon.png";')
        (self.root / "main.js").write_bytes(self.source)
        (self.root / "index.html").write_bytes(self.source)
        for name, value in {"ROOT": str(self.root), "LOG": str(self.root / "requests.log")}.items():
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = "http://127.0.0.1:%d" % self.httpd.server_port

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
        with contextlib.closing(connection):
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_traversal_cannot_read_or_cache_outside_mirror(self):
        before = self.secret.read_bytes()
        with patch.object(server.urllib.request, "urlopen") as upstream:
            for path in ("/../private.json", "/%2e%2e/private.json", "/..%2fprivate.json",
                         "/%2e%2e/new.js", "/main.js%00.txt"):
                with self.subTest(path=path):
                    self.assertEqual(self.request("GET", path)[0], 400)
            upstream.assert_not_called()
        self.assertEqual(self.secret.read_bytes(), before)
        self.assertFalse((self.root.parent / "new.js").exists())

    def test_symlinks_cannot_escape_mirror_in_get_head_or_cache(self):
        (self.root / "linked.json").symlink_to(self.secret)
        (self.root / "linked").symlink_to(self.root.parent, target_is_directory=True)
        with patch.object(server.urllib.request, "urlopen") as upstream:
            for method, path in (("GET", "/linked.json"), ("HEAD", "/linked.json"),
                                 ("GET", "/linked/new.js")):
                self.assertEqual(self.request(method, path)[0], 400)
            upstream.assert_not_called()

    def test_first_proxy_response_is_rewritten_and_cache_retains_original(self):
        upstream = io.BytesIO(self.source)
        upstream.headers = {"Content-Type": "application/javascript"}
        with patch.object(server.urllib.request, "urlopen", return_value=upstream) as fetch:
            status, headers, first = self.request("GET", "/assets/new.js")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn((self.origin + "/cgi-bin/").encode(), first)
            self.assertNotIn(b"baobaocdn.qq.com", first)
            self.assertEqual((self.root / "assets/new.js").read_bytes(), self.source)
            self.assertEqual(self.request("GET", "/assets/new.js")[2], first)
            fetch.assert_called_once()

    def test_proxy_response_still_rewritten_when_cache_write_fails(self):
        upstream = io.BytesIO(self.source)
        upstream.headers = {"Content-Type": "application/javascript"}
        with patch.object(server.urllib.request, "urlopen", return_value=upstream), \
                patch.object(server.os, "replace", side_effect=OSError("disk full")):
            status, _, body = self.request("GET", "/missing.js")
        self.assertEqual(status, 200)
        self.assertIn((self.origin + "/cgi-bin/").encode(), body)
        self.assertFalse((self.root / "missing.js").exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_unusual_native_extensions_fall_back_to_the_activity_cdn(self):
        for extension in ("py", "bytes"):
            with self.subTest(extension=extension):
                payload = b"opaque native asset\x00\xff"
                upstream = io.BytesIO(payload)
                upstream.headers = {"Content-Type": "application/octet-stream"}
                missing = urllib.error.HTTPError("https://baobaocdn.qq.com", 404, "missing", {}, None)
                path = "/assets/Activity/native/example." + extension
                with patch.object(server.urllib.request, "urlopen", side_effect=[missing, upstream]) as fetch:
                    status, _, first = self.request("GET", path)
                    self.assertEqual(status, 200)
                    self.assertEqual(first, payload)
                    self.assertEqual(self.request("GET", path)[2], payload)
                self.assertEqual(fetch.call_count, 2)
                self.assertIn("/act/main/assets/Activity/", fetch.call_args_list[1].args[0].full_url)
                self.assertEqual((self.root / path.lstrip("/")).read_bytes(), payload)

    def test_activity_directory_entry_and_encoded_script_get_local_routes(self):
        activity = self.root / "act"
        activity.mkdir()
        (activity / "index.html").write_bytes(self.source)
        status, headers, _ = self.request("GET", "/act?x=1")
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], "/act/?x=1")
        for path in ("/act/", "/main%2ejs"):
            status, _, data = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn((self.origin + "/cgi-bin/").encode(), data)

    def test_root_adds_login_parameters_and_head_matches_rewritten_get(self):
        status, headers, _ = self.request("GET", "/?act=example")
        self.assertEqual(status, 302)
        self.assertIn("PingPong=448984620", headers["Location"])
        self.assertIn("act=example", headers["Location"])
        target = headers["Location"]
        status, headers, body = self.request("GET", target)
        self.assertEqual(status, 200)
        self.assertIn((self.origin + "/cgi-bin/").encode(), body)
        status, head_headers, empty = self.request("HEAD", target)
        self.assertEqual(status, 200)
        self.assertEqual(head_headers["Content-Length"], str(len(body)))
        self.assertEqual(head_headers["Cache-Control"], headers["Cache-Control"])
        self.assertEqual(empty, b"")

    def test_unrelated_routes_never_dispatch_game_commands(self):
        with patch.object(server, "handle_cmd") as dispatch:
            for method, path in (("POST", "/not-an-endpoint"),
                                 ("POST", "/nested/cgi-bin/rosary_diamond"),
                                 ("GET", "/cgi-bin/rosary_diamond/extra"),
                                 ("POST", "/cgi-bin/rosary_diamond/extra")):
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.request(method, path)[0], 404)
            self.assertEqual(self.request("HEAD", "/cgi-bin/rosary_diamond")[0], 405)
            dispatch.assert_not_called()

    def test_invalid_bodies_have_clear_errors_without_dispatch(self):
        with patch.object(server, "local_payment") as pay:
            for body, headers, expected in (
                (b"", {"Content-Length": "abc"}, 400),
                (b"", {"Content-Length": "-1"}, 400),
                (b"", {"Content-Length": "1048577"}, 413),
                (b"{}", {"Transfer-Encoding": "chunked"}, 400),
                (b"[]", {"Content-Type": "application/json"}, 400),
                (b"{", {"Content-Type": "application/json"}, 400),
                (b"\xff", {"Content-Type": "application/x-www-form-urlencoded"}, 400),
            ):
                with self.subTest(headers=headers):
                    status, _, data = self.request("POST", "/local_payments", body, headers)
                    self.assertEqual(status, expected)
                    self.assertNotEqual(json.loads(data)["result"], 0)
            pay.assert_not_called()

    def test_cross_origin_requests_cannot_mutate_single_player_save(self):
        with patch.object(server, "handle_cmd", return_value={"result": 0}) as dispatch:
            for method, headers in (("POST", {"Origin": "https://other.example"}),
                                    ("GET", {"Sec-Fetch-Site": "cross-site"}),
                                    ("OPTIONS", {"Origin": "null"})):
                status, response_headers, _ = self.request(method, "/cgi-bin/rosary_diamond", headers=headers)
                self.assertEqual(status, 403)
                self.assertNotIn("Access-Control-Allow-Origin", response_headers)
            dispatch.assert_not_called()
            status, headers, _ = self.request("POST", "/cgi-bin/rosary_diamond",
                                              headers={"Origin": self.origin})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Access-Control-Allow-Origin"], self.origin)
            dispatch.assert_called_once()

    def test_health_identifies_service_and_logs_redact_login_credentials(self):
        status, _, data = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["service"], "rose-town-local")
        self.request("POST", "/cgi-bin/rosary_diamond", body=(
            "token=secret-token&openid=secret-id&openkey=secret-key&count=2"))
        log = (self.root / "requests.log").read_text()
        self.assertNotIn("secret-", log)
        self.assertIn("count=2", log)


if __name__ == "__main__":
    unittest.main()
