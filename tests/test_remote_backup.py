import json, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from pi_bus_time_display import remote_backup as rb

FILES = {}
class Dav(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_MKCOL(self): self.send_response(201); self.send_header("Content-Length", "0"); self.end_headers()
    def do_PUT(self):
        FILES[self.path.rsplit("/", 1)[-1]] = self.rfile.read(int(self.headers["Content-Length"])); self.send_response(201); self.send_header("Content-Length", "0"); self.end_headers()
    def do_DELETE(self): FILES.pop(self.path.rsplit("/", 1)[-1], None); self.send_response(204); self.end_headers()
    def do_PROPFIND(self):
        body = "<d:multistatus xmlns:d='DAV:'>" + "".join(f"<d:response><d:href>/RoonDeck/{n}</d:href></d:response>" for n in FILES) + "</d:multistatus>"
        self.send_response(207); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body.encode())

class RemoteBackupTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(rb.validate_target({})["folder"], "RoonDeck")
        for bad in ({"enabled": True, "url": "ftp://x", "username": "a"}, {"folder": "../x"}, {"keep": 0}, {"time": "25:00"}, {"enabled": True, "url": "http://nas:5005"}):
            with self.assertRaises(ValueError): rb.validate_target(bad)

    def test_upload_and_prune(self):
        FILES.clear(); server = HTTPServer(("127.0.0.1", 0), Dav); threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "state").mkdir(); config = root / "c.toml"; config.write_text('bus_stop_code = "12345"\n')
            target = rb.validate_target({"enabled": True, "url": f"http://127.0.0.1:{server.server_port}", "username": "u", "keep": 2})
            import time
            for day in range(1, 5):
                rb.run_backup(target, "pw", config, root / "state", root / "env", "1", time.strptime(f"2026-11-0{day} 03:30", "%Y-%m-%d %H:%M"))
        server.shutdown()
        self.assertEqual(sorted(FILES), ["roondeck-backup-2026-11-03-0330.json", "roondeck-backup-2026-11-04-0330.json"])
        self.assertEqual(json.loads(FILES["roondeck-backup-2026-11-04-0330.json"])["format"], "roondeck-backup")


class GoogleTests(unittest.TestCase):
    def test_google_upload_prunes_and_signin(self):
        calls = []; files = {"a": "roondeck-backup-2026-11-01-0330.json", "b": "roondeck-backup-2026-11-02-0330.json"}
        def fake(method, url, headers=None, body=None):
            calls.append((method, url))
            if "oauth2.googleapis.com/token" in url: return 200, {"access_token": "t", "refresh_token": "r"}
            if "uploadType=multipart" in url: files["c"] = "roondeck-backup-2026-11-03-0330.json"; return 200, {"id": "c"}
            if method == "DELETE": files.pop(url.rsplit("/", 1)[-1]); return 204, {}
            if "mimeType%3D" in url or "mimeType" in url: return 200, {"files": [{"id": "F"}]}
            if "in%20parents" in url: return 200, {"files": [{"id": i, "name": n} for i, n in files.items()]}
            return 200, {}
        original = rb._http; rb._http = fake
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / "state").mkdir(); config = root / "c.toml"; config.write_text('bus_stop_code = "12345"\n')
                target = rb.validate_target({"google_enabled": True, "google_client_id": "1-x.apps.googleusercontent.com", "keep": 2})
                rb.run_google(target, "s", "r", config, root / "state", root / "env", "1", __import__("time").strptime("2026-11-03 03:30", "%Y-%m-%d %H:%M"))
            self.assertEqual(sorted(files), ["b", "c"])
            self.assertEqual(rb.google_poll("id", "s", "d"), "r")
        finally: rb._http = original

    def test_google_needs_client_id(self):
        with self.assertRaises(ValueError): rb.validate_target({"google_enabled": True, "google_client_id": "nope"})
        self.assertTrue(rb.validate_target({"google_enabled": True, "google_client_id": "1-x.apps.googleusercontent.com"})["google_enabled"])
