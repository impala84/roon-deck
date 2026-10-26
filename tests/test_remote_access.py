import base64
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from pi_bus_time_display.remote_access import AccessoryManager, DEFAULT_DIAL, atomic_json, dial_config, keyfile, parse_profile
from pi_bus_time_display.surface_dial import Gestures, EV_KEY, EV_REL, EV_SYN, REL_DIAL, BTN_0, SYN_DROPPED, input_paths
from pi_bus_time_display.server import State, make_handler
from pi_bus_time_display.config import Config

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = base64.b64encode(b"private-test-key-not-a-secret!!!!"[:32]).decode()
PUBLIC = base64.b64encode(b"public-test-key-not-a-secret!!!!!"[:32]).decode()
PROFILE = f"""[Interface]
PrivateKey = {PRIVATE}
Address = 10.10.10.2/32
DNS = 192.168.1.1
[Peer]
PublicKey = {PUBLIC}
AllowedIPs = 0.0.0.0/0
Endpoint = vpn.example.com:51820
PersistentKeepalive = 25
"""


class ProfileTests(unittest.TestCase):
    def test_unifi_profile_and_root_keyfile(self):
        profile = parse_profile(PROFILE)
        text = keyfile(profile, "00000000-0000-4000-8000-000000000001")
        self.assertIn("autoconnect=false", text)
        self.assertIn("address1=10.10.10.2/32", text)
        self.assertIn("dns=192.168.1.1;", text)
        self.assertIn("[wireguard-peer." + PUBLIC + "]", text)
        self.assertNotIn("PostUp", text)

    def test_split_routes_are_explicit_not_default(self):
        profile = parse_profile(PROFILE, "split", "192.168.1.0/24,10.0.0.0/8")
        self.assertEqual(profile["routes"], ["192.168.1.0/24", "10.0.0.0/8"])
        self.assertIn("never-default=true", keyfile(profile, "id"))
        for routes in ("", "0.0.0.0/0", "::/0", "not a subnet"):
            with self.subTest(routes=routes), self.assertRaises(ValueError): parse_profile(PROFILE, "split", routes)

    def test_rejects_hooks_duplicates_and_unbounded_profiles(self):
        for text in (PROFILE.replace("Address =", "PostUp = touch /tmp/pwned\nAddress ="), PROFILE + "\n[Peer]\n", PROFILE + "x" * 17000,
                     PROFILE.replace("Address = 10.10.10.2/32", "Address = nonsense"), PROFILE.replace("vpn.example.com:51820", "-x;echo pwned:51820"), PROFILE.replace(PRIVATE, "bad-private-key")):
            with self.subTest(text=text[:20]):
                with self.assertRaises(ValueError) as error: parse_profile(text)
                self.assertNotIn(PRIVATE, str(error.exception))
                self.assertNotIn("bad-private-key", str(error.exception))

    def test_only_plain_client_profile_sections(self):
        for suffix in ("\n[DEFAULT]\ncommand=abc", "\n[Extra]\nkey=abc"):
            with self.assertRaises(ValueError): parse_profile(PROFILE + suffix)

    def test_dial_config_is_opt_in_and_rejects_invalid_limits(self):
        self.assertEqual(dial_config({}), DEFAULT_DIAL)
        for value in (float("nan"), float("inf"), True, "100", 101):
            with self.assertRaises(ValueError): dial_config({"maximum_volume": value})
        for data in ({"enabled": True}, {"enabled": "yes"}, {"target": "output"}, {"single": "shell"}, []):
            with self.assertRaises(ValueError): dial_config(data)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.calls, self.trials, self.active = [], [], False
        self.manager = AccessoryManager(Path(self.temp.name), self.run_system, self.trials.append)
        self.manager.handle({"operation": "features_save", "features": {"vpn": True, "dial": True}})

    def run_system(self, args):
        self.calls.append(args)
        if args[:3] == ["nmcli", "-g", "GENERAL.STATE"]: return "100 (connected)" if self.active else "30 (disconnected)"
        return ""

    def configure(self):
        self.manager.handle({"operation": "vpn_import", "profile": PROFILE, "auto_connect": True})

    def test_import_never_connects_or_exposes_keys(self):
        self.configure()
        self.assertEqual(self.manager.profile_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manager.private.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(PRIVATE, json.dumps(self.manager.status()))
        self.assertNotIn(PRIVATE, json.dumps(self.calls))
        self.assertFalse(any("up" in call for call in self.calls))
        self.assertNotIn("autoconnect=true", self.manager.profile_path.read_text())

    def test_connection_arms_independent_rollback_before_activation(self):
        self.configure(); result = self.manager.handle({"operation": "vpn_connect"})
        self.assertEqual(self.trials, [result["pending_token"]])
        self.assertTrue(self.manager.pending_path.exists())
        self.manager.rollback(result["pending_token"])
        self.assertFalse(self.manager.pending_path.exists())
        self.assertIn(["nmcli", "--wait", "10", "connection", "down", "roondeck-remote"], self.calls)

    def test_only_correct_live_trial_can_enable_boot_connection(self):
        self.configure(); result = self.manager.handle({"operation": "vpn_connect"})
        with self.assertRaises(ValueError): self.manager.handle({"operation": "vpn_confirm", "token": "wrong"})
        self.active = True
        self.manager.handle({"operation": "vpn_confirm", "token": result["pending_token"]})
        self.assertIn(["nmcli", "connection", "modify", "roondeck-remote", "connection.autoconnect", "yes"], self.calls)
        before = len(self.calls); self.manager.rollback(result["pending_token"])
        self.assertEqual(len(self.calls), before)

    def test_expired_trial_cannot_be_confirmed(self):
        self.configure(); result = self.manager.handle({"operation": "vpn_connect"})
        atomic_json(self.manager.pending_path, {"token": result["pending_token"], "deadline": time.time() - 1})
        with self.assertRaises(ValueError): self.manager.handle({"operation": "vpn_confirm", "token": result["pending_token"]})

    def test_active_profile_cannot_be_replaced(self):
        self.configure(); original = self.manager.profile_path.read_text(); self.active = True
        with self.assertRaises(ValueError): self.configure()
        self.assertEqual(original, self.manager.profile_path.read_text())

    def test_failed_activation_disables_trial(self):
        self.configure()
        def fail(args):
            if args == ["nmcli", "--wait", "20", "connection", "up", "roondeck-remote"]: raise ValueError("private failure")
            return self.run_system(args)
        self.manager.run = fail
        with self.assertRaisesRegex(ValueError, "trial has been cancelled"): self.manager.handle({"operation": "vpn_connect"})
        self.assertFalse(self.manager.pending_path.exists())

    def test_unknown_or_unpaired_dial_cannot_be_enabled(self):
        with self.assertRaises(ValueError): self.manager.handle({"operation": "bluetooth_pair", "address": "AA:BB:CC:DD:EE:FF"})
        with self.assertRaises(ValueError): self.manager.handle({"operation": "dial_save", "config": {"enabled": True, "address": "AA:BB:CC:DD:EE:FF"}})
        self.assertFalse(any(call[:2] == ["rc-service", "roonbridge"] for call in self.calls))

    def test_disconnect_removes_boot_autoconnect(self):
        self.configure(); self.manager.handle({"operation": "vpn_disconnect"})
        self.assertIn(["nmcli", "connection", "modify", "roondeck-remote", "connection.autoconnect", "no"], self.calls)

    def test_backend_feature_off_stops_vpn_and_blocks_future_connections(self):
        self.configure()
        self.manager.handle({"operation": "features_save", "features": {"vpn": False, "dial": False}})
        self.assertEqual(self.manager.status()["features"], {"vpn": False, "dial": False})
        self.assertFalse(json.loads(self.manager.dial_path.read_text())["enabled"])
        self.assertIn(["nmcli", "--wait", "10", "connection", "down", "roondeck-remote"], self.calls)
        with self.assertRaisesRegex(ValueError, "web Settings"): self.manager.handle({"operation": "vpn_connect"})
        with self.assertRaisesRegex(ValueError, "web Settings"): self.manager.handle({"operation": "bluetooth_scan"})

    def test_new_installations_have_no_enabled_features(self):
        self.manager.features_path.unlink()
        self.assertEqual(self.manager.status()["features"], {"vpn": False, "dial": False})
        with self.assertRaisesRegex(ValueError, "web Settings"): self.manager.handle({"operation": "dial_save", "config": {}})


class GestureTests(unittest.TestCase):
    def test_single_and_double_press_are_exclusive(self):
        g = Gestures(); g.event(EV_KEY, BTN_0, 1, 0); g.event(EV_KEY, BTN_0, 0, .1)
        self.assertIsNone(g.tick(.2)); self.assertEqual(g.tick(.43), {"kind": "single"})
        g.reset(); g.event(EV_KEY, BTN_0, 1, 0); g.event(EV_KEY, BTN_0, 0, .1)
        g.event(EV_KEY, BTN_0, 1, .3)
        self.assertEqual(g.event(EV_KEY, BTN_0, 0, .5), "double")
        self.assertIsNone(g.tick(1))

    def test_long_press_does_not_also_pause_on_release(self):
        g = Gestures(); g.event(EV_KEY, BTN_0, 1, 0)
        self.assertEqual(g.tick(.8), {"kind": "long"})
        self.assertIsNone(g.event(EV_KEY, BTN_0, 0, 1)); self.assertIsNone(g.tick(2))

    def test_rotation_is_bounded_and_acceleration_resets(self):
        g = Gestures(); g.event(EV_REL, REL_DIAL, 10000, 0)
        self.assertEqual(g.tick(1), {"kind": "rotate", "steps": 24, "fast": False})
        g.event(EV_REL, REL_DIAL, -1, 1.05)
        self.assertEqual(g.tick(1.05), {"kind": "rotate", "steps": -1, "fast": True})
        g.reset(); self.assertIsNone(g.tick(2))

    def test_dropped_events_wait_for_sync_and_do_not_replay(self):
        g = Gestures(); g.event(EV_REL, REL_DIAL, 3, 0); g.event(EV_SYN, SYN_DROPPED, 0, 0)
        g.event(EV_REL, REL_DIAL, 4, 0); self.assertIsNone(g.tick(1))
        g.event(EV_SYN, 0, 0, 1); g.event(EV_REL, REL_DIAL, 1, 1)
        self.assertEqual(g.tick(1)["steps"], 1)

    def test_input_matches_vendor_product_and_paired_address(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); device = root / "event3/device"; (device / "id").mkdir(parents=True)
            (device / "id/vendor").write_text("045e\n"); (device / "id/product").write_text("091b\n"); (device / "uniq").write_text("AA:BB:CC:DD:EE:FF\n")
            self.assertEqual(input_paths("AA:BB:CC:DD:EE:FF", root), [Path("/dev/input/event3")])
            self.assertEqual(input_paths("11:22:33:44:55:66", root), [])


class AccessoryHttpTests(unittest.TestCase):
    def test_authentication_precedes_profile_reads_or_system_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = State(Config(), root)
            handler_type = make_handler(state, root / "config.toml", root / "env", root / "mode")
            for method in ("do_GET", "do_POST"):
                handler = object.__new__(handler_type); handler.path = "/api/admin/accessories"
                handler.authorised = lambda: False
                with patch("pi_bus_time_display.server.accessory_request") as request:
                    getattr(handler, method)(); request.assert_not_called()

    def test_authenticated_import_uses_only_privileged_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); handler_type = make_handler(State(Config(), root), root / "config", root / "env", root / "mode")
            handler = object.__new__(handler_type); handler.path = "/api/admin/accessories"; handler.authorised = lambda: True
            payload = json.dumps({"operation": "vpn_import", "profile": PROFILE}).encode()
            handler.headers = {"Content-Length": str(len(payload))}; handler.rfile = io.BytesIO(payload)
            replies = []; handler.send_json = lambda status, body: replies.append((status, body))
            with patch("pi_bus_time_display.server.accessory_request", return_value={"ok": True}) as request:
                handler.do_POST(); request.assert_called_once()
            self.assertEqual(replies, [(200, b'{"ok": true}')])


class BetaReleaseTests(unittest.TestCase):
    def test_next_patch_beta_orders_after_previous_stable(self):
        loader = importlib.machinery.SourceFileLoader("beta_release_test", str(ROOT / "tools/release-beta"))
        spec = importlib.util.spec_from_loader(loader.name, loader); module = importlib.util.module_from_spec(spec); loader.exec_module(module)
        self.assertGreater(module.version_order("1.1.8-beta.1"), module.version_order("1.1.7"))
        self.assertLess(module.version_order("1.1.8-beta.1"), module.version_order("1.1.8"))
        self.assertGreater(module.version_order("1.1.8-beta.10"), module.version_order("1.1.8-beta.9"))
