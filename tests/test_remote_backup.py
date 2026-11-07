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
