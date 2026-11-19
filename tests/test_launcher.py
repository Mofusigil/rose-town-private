import http.server
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request


PROJECT = Path(__file__).resolve().parents[1]


class ServiceStub(http.server.BaseHTTPRequestHandler):
    ready = True

    def do_GET(self):
        data = json.dumps({"service": "rose-town-local" if self.ready else "unrelated-service",
                           "status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.env = {**os.environ, "ROSE_HOST": "127.0.0.1", "ROSE_PORT": str(self.port),
                    "ROSE_STATE_FILE": str(Path(self.directory.name) / "player.json"),
                    "ROSE_STDOUT_LOG": str(Path(self.directory.name) / "server.log")}

    def run_launcher(self, *args, env=None):
        return subprocess.run(["bash", str(PROJECT / "start_rose.sh"), *args],
                              env=env or self.env, capture_output=True, text=True, timeout=15)

    def stub(self, ready):
        handler = type("Stub", (ServiceStub,), {"ready": ready})
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def close():
            httpd.shutdown()
            httpd.server_close()
            thread.join()

        self.addCleanup(close)
        return httpd

    def healthy(self):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://127.0.0.1:%d/healthz" % self.port, timeout=0.5) as response:
                return json.load(response).get("service") == "rose-town-local"
        except (OSError, ValueError):
            return False

    def port_open(self):
        with socket.socket() as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", self.port)) == 0

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail("Service did not reach the expected state")

    def test_reusing_server_only_exits_cleanly_without_stopping_service(self):
        self.stub(True)
        result = self.run_launcher("--server-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("使用已有服务", result.stdout)
        self.assertTrue(self.healthy())

    def test_unrelated_occupied_port_is_rejected(self):
        self.stub(False)
        result = self.run_launcher("--server-only", "--no-wait")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("被其他程序或旧版服务占用", result.stderr)
        self.assertTrue(self.port_open())

    def test_invalid_ports_fail_with_actionable_message(self):
        for port in ("0", "65536", "abc", "-1", "99999999999999999999"):
            with self.subTest(port=port):
                result = self.run_launcher("--server-only", env={**self.env, "ROSE_PORT": port})
                self.assertEqual(result.returncode, 2)
                self.assertIn("ROSE_PORT", result.stderr)

    def test_background_service_survives_launcher_exit_and_hangup(self):
        result = self.run_launcher("--server-only", "--no-wait")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        match = re.search(r"pid (\d+)", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        pid = int(match[1])

        def terminate():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.wait_until(lambda: not self.port_open())

        self.addCleanup(terminate)
        self.assertTrue(self.healthy())
        os.kill(pid, signal.SIGHUP)
        time.sleep(0.1)
        self.assertTrue(self.healthy())

    def test_foreground_termination_stops_owned_server(self):
        output_path = Path(self.directory.name) / "launcher.log"
        saved_path = Path(self.env["ROSE_STATE_FILE"])
        self.env["ROSE_STATE_FILE"] = os.path.relpath(saved_path, PROJECT)
        with output_path.open("w") as output:
            process = subprocess.Popen(["bash", str(PROJECT / "start_rose.sh"), "--server-only"],
                                       env=self.env, stdout=output, stderr=output)
            try:
                self.wait_until(self.healthy)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request("http://127.0.0.1:%d/local_payments" % self.port,
                    data=b'{"action":"recharge","count":7}',
                    headers={"Content-Type": "application/json"})
                with opener.open(request, timeout=3) as response:
                    self.assertEqual(json.load(response)["result"], 0)
                self.assertEqual(json.loads(saved_path.read_text())["balance"], 7)
                process.terminate()
                self.assertEqual(process.wait(timeout=5), 143)
                self.wait_until(lambda: not self.port_open())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
