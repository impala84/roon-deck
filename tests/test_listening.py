import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pi_bus_time_display.config import Config
from pi_bus_time_display.listening import KefLSX, ListeningControls, load_settings
from pi_bus_time_display.server import State, make_handler
from pi_bus_time_display.streamdeck import dispatch


class ListeningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "listening.json"
        self.settings = {"enabled": True, "kef_host": "10.12.0.125", "maximum_volume": 40,
                         "modes": [{"id": "pi", "kef_input": "aux", "topping_input": "coaxial", "volume": 20}]}
        self.write()
        self.speaker = Mock()
        self.speaker.status.return_value = {"connected": True, "powered": True, "input": "aux", "volume": 20, "muted": False}
        self.controls = ListeningControls(self.path, lambda *args: self.speaker)

    def write(self):
        self.path.write_text(json.dumps(self.settings))

    def test_topping_mode_preflight_changes_no_hardware(self):
        with self.assertRaisesRegex(ValueError, "Topping"):
            self.controls.command("mode", "pi")
        self.speaker.command.assert_not_called()
        self.assertIsNone(self.controls.snapshot()["last_mode"])

    def test_cached_status_does_not_wait_for_network_lock(self):
        with self.controls.lock:
            self.assertFalse(self.controls.snapshot()["kef"]["connected"])

    @patch("pi_bus_time_display.listening.time.sleep")
    def test_mode_requires_readback_and_external_changes_clear_selection(self, _sleep):
        del self.settings["modes"][0]["topping_input"]
        self.write()
        self.controls.refresh()
        self.assertEqual(self.controls.command("mode", "pi")["last_mode"], "pi")
        self.speaker.status.return_value["input"] = "optical"
        self.assertIsNone(self.controls.refresh()["last_mode"])
        with self.assertRaisesRegex(OSError, "confirm"):
            self.controls.command("mode", "pi")
        self.assertIsNone(self.controls.snapshot()["last_mode"])

    def test_malformed_settings_disable_controls_and_report_error(self):
        self.controls.refresh()
        self.path.write_text('{"enabled":true,"modes":"bad"}')
        result = self.controls.refresh()
        self.assertFalse(result["enabled"])
        self.assertFalse(result["kef"]["connected"])
        self.assertTrue(result["error"])

    def test_settings_save_is_atomic_private_and_preserves_valid_config_on_error(self):
        self.controls.save(self.settings)
        self.assertEqual(load_settings(self.path), self.settings)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): self.controls.save({**self.settings, "maximum_volume": 101})
        self.assertEqual(load_settings(self.path), self.settings)
        for extra in ({"buttons":[{"action":"shell"}]}, {"dials":[{"action":"volume_delta","step":0}]},
                      {"buttons":[{"image":"../escape.png"}]}, {"enabled":"true"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.controls.save({**self.settings, **extra})

    def test_volume_limit_and_types_validate_before_hardware(self):
        self.settings["modes"][0]["volume"] = 41
        self.write()
        with self.assertRaises(ValueError): load_settings(self.path)
        speaker = KefLSX("unused", 40); speaker.exchange = Mock(return_value=39)
        speaker.command("volume_delta", 10)
        self.assertEqual(speaker.exchange.call_args.args[0], bytes([83, 37, 129, 40]))
        speaker.exchange.reset_mock()
        with self.assertRaises(ValueError): speaker.command("volume", True)
        speaker.exchange.assert_not_called()

    def test_source_preserves_dsp_bits_and_rejects_lsx_usb(self):
        speaker = KefLSX("unused"); speaker.exchange = Mock(return_value=0xD2)
        speaker.command("input", "aux")
        self.assertEqual(speaker.exchange.call_args.args[0], bytes([83, 48, 129, 0x5A]))
        speaker.exchange.reset_mock()
        with self.assertRaises(ValueError): speaker.command("input", "usb")
        speaker.exchange.assert_not_called()

    @patch("pi_bus_time_display.listening.socket.create_connection")
    def test_tcp_partial_reply_is_assembled_and_timeout_is_bounded(self, connect):
        connection = connect.return_value.__enter__.return_value
        connection.recv.side_effect = [b"R", b"%", b"\x81", b"\x14\xff"]
        self.assertEqual(KefLSX("10.12.0.125").exchange(bytes.fromhex("472580")), 20)
        self.assertTrue(all(0 < call.args[0] <= 2 for call in connection.settimeout.call_args_list))
        connection.recv.side_effect = [b"R\x11", b"\xff"]
        self.assertEqual(KefLSX("10.12.0.125").exchange(bytes.fromhex("53258114")), 17)
        connection.recv.side_effect = [b"G", b""]
        with self.assertRaises(OSError): KefLSX("10.12.0.125").exchange(bytes.fromhex("472580"))

    def handler(self, payload, authorised=True, forwarded=False):
        state = State(Config(), Path(self.directory.name)); state.listening = self.controls
        Handler = make_handler(state, self.path, self.path, self.path)
        handler = Handler.__new__(Handler)
        handler.path = "/api/listening/command"; handler.client_address = ("127.0.0.1", 1)
        body = json.dumps(payload).encode()
        handler.headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if forwarded: handler.headers["X-Forwarded-For"] = "10.0.0.2"
        handler.rfile = io.BytesIO(body); handler.authorised = Mock(return_value=authorised); handler.send_json = Mock()
        return handler

    def test_http_rejects_forwarded_control_and_invalid_shapes(self):
        handler = self.handler({}, forwarded=True); handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 403)
        handler = self.handler([]); handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 400)
        handler = self.handler({"action": []}); handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 400)
        handler = self.handler({"action": "power", "value": True}, authorised=False); handler.do_POST()
        self.speaker.command.assert_not_called()

    def test_http_reports_device_failure(self):
        self.speaker.command.side_effect = OSError("unreachable")
        handler = self.handler({"action": "power", "value": True}); handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 502)

    @patch("pi_bus_time_display.server.home_assistant_request")
    def test_scenes_require_an_explicit_allowlist(self, home_request):
        handler = self.handler({"action": "scene", "value": "scene.unlisted"})
        handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 400)
        home_request.assert_not_called()

    @patch("pi_bus_time_display.streamdeck.request")
    def test_deck_maps_music_and_home_controls_without_arbitrary_urls(self, request):
        dispatch("http://localhost", {"action": "next"})
        request.assert_called_with("http://localhost", "/roon/api/control", {"action": "next"})
        dispatch("http://localhost", {"action": "volume_delta", "step": 2}, -3)
        request.assert_called_with("http://localhost", "/api/listening/command", {"action": "volume_delta", "value": -6})
        request.return_value = {"home": {"entities": [{"entity_id": "light.desk", "supports_level": True, "brightness": 255}]}}
        dispatch("http://localhost", {"action": "home_level", "entity_id": "light.desk", "step": 2}, 5)
        request.assert_called_with("http://localhost", "/api/device/home-value", {"entity_id": "light.desk", "value": 100})
        with self.assertRaises(ValueError): dispatch("http://localhost", {"action": "https://example.com"})


if __name__ == "__main__":
    unittest.main()
