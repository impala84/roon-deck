import base64, json, tempfile, unittest
from pathlib import Path
from pi_bus_time_display.backup import build_backup, check_backup, restore_backup

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

class BackupTests(unittest.TestCase):
    def make(self, root):
        state = root / "state"; (state / "deck-art").mkdir(parents=True)
        (state / "listening.json").write_text(json.dumps({"enabled": False, "modes": [], "buttons": [], "dials": []}))
        (state / "home-layout.json").write_text(json.dumps({"tiles": {"light.a": {"size": "half"}}}))
        (state / "deck-art" / "icon-x.png").write_bytes(PNG)
        config = root / "config.toml"; config.write_text('bus_stop_code = "12345"\n')
        env = root / "env"; env.write_text("HOME_ASSISTANT_TOKEN=abc\nADMIN_PASSWORD=zzz\n")
        return config, state, env

    def test_round_trip_and_secrets_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config, state, env = self.make(root)
            bundle = build_backup(config, state, env, "1")
            self.assertNotIn("secrets", bundle)
            with_secrets = build_backup(config, state, env, "1", True)
            self.assertEqual(with_secrets["secrets"], {"HOME_ASSISTANT_TOKEN": "abc"})
            checked = check_backup(json.loads(json.dumps(with_secrets)))
            other = root / "other"; (other / "state").mkdir(parents=True)
            restore_backup(checked, other / "config.toml", other / "state")
            self.assertEqual((other / "state" / "deck-art" / "icon-x.png").read_bytes(), PNG)
            self.assertIn("12345", (other / "config.toml").read_text())
            self.assertIn("half", (other / "state" / "home-layout.json").read_text())

    def test_bad_files_rejected(self):
        good = {"format": "roondeck-backup", "version": 1, "config": "", "files": {}, "art": {}}
        check_backup(good)
        for change in ({"format": "other"}, {"files": {"evil.json": "{}"}}, {"art": {"../x.png": base64.b64encode(PNG).decode()}},
                       {"art": {"a.png": base64.b64encode(b"notpng").decode()}}, {"secrets": {"PATH": "x"}}, {"config": "unknown_key = 1"},
                       {"files": {"home-layout.json": '{"tiles": 5}'}}):
            with self.assertRaises(Exception): check_backup({**good, **change})
