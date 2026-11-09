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
        self.settings = {"enabled": True, "kef_roon_output_id": "study-output", "maximum_volume": 40}
        self.write()
        self.speaker = Mock()
        self.speaker.status.return_value = {"connected": True, "powered": True, "input": "aux", "volume": 20, "muted": False}
        self.controls = ListeningControls(self.path, lambda *args: self.speaker)

    def write(self):
        self.path.write_text(json.dumps(self.settings))


    def test_cached_status_does_not_wait_for_network_lock(self):
        with self.controls.lock:
            self.assertFalse(self.controls.snapshot()["kef"]["connected"])


    def test_malformed_settings_disable_controls_and_report_error(self):
        self.controls.refresh()
        self.path.write_text('{"enabled":true,"kef_roon_output_id":"study-output","maximum_volume":500}')
        result = self.controls.refresh()
        self.assertFalse(result["enabled"])
        self.assertFalse(result["kef"]["connected"])
        self.assertTrue(result["error"])



    @patch("pi_bus_time_display.listening.time.sleep")
    def test_power_and_volume_commands_require_actual_state_change(self, _sleep):
        for action, value in (("power", False), ("volume", 30)):
            with self.subTest(action=action):
                self.speaker.reset_mock()
                with self.assertRaisesRegex(OSError, "not confirmed"):
                    self.controls.command(action, value)
                self.speaker.command.assert_called_once_with(action, value)

    def test_network_command_failure_clears_previously_connected_state(self):
        self.controls.refresh()
        self.speaker.command.side_effect = ConnectionRefusedError("connection refused")
        with self.assertRaises(OSError): self.controls.command("power", True)
        self.assertFalse(self.controls.snapshot()["kef"]["connected"])

    def test_settings_save_is_atomic_private_and_preserves_valid_config_on_error(self):
        self.controls.save(self.settings)
        self.assertEqual(load_settings(self.path), self.settings)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): self.controls.save({**self.settings, "maximum_volume": 101})
        self.assertEqual(load_settings(self.path), self.settings)
        for extra in ({"buttons":[{"action":"shell"}]}, {"dials":[{"action":"volume_delta","step":0}]},
                      {"buttons":[{"image":"../escape.png"}]}, {"buttons":[{"color":"red"}]},
                      {"buttons":[{"color":"#12345"}]}, {"enabled":"true"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.controls.save({**self.settings, **extra})

    def test_button_colour_and_artwork_are_saved(self):
        saved = self.controls.save({**self.settings, "buttons": [{"label": "A", "action": "mute", "color": "#236650", "image": "icon-mute.png"}]})
        self.assertEqual(saved["buttons"][0]["color"], "#236650")

    def test_kef_uses_roon_and_never_opens_the_speakers_own_port(self):
        from pi_bus_time_display.listening import KefRoon
        speaker = KefRoon("", 40, "study-output")
        with patch("pi_bus_time_display.listening.socket", create=True) as sock, patch.object(KefRoon, "roon_request") as request:
            speaker.command("volume_delta", 10)
            request.assert_called_once_with("volume_delta", 10)
            sock.create_connection.assert_not_called()
            request.reset_mock()
            with self.assertRaises(ValueError): speaker.command("volume", True)
            with self.assertRaisesRegex(ValueError, "Broadlink"): speaker.command("input", "aux")
            with self.assertRaises(ValueError): speaker.command("shell", None)
            request.assert_not_called()
            speaker.command("input", "wifi")
            request.assert_called_once_with("input", "wifi")
        with self.assertRaisesRegex(OSError, "Choose the KEF"): KefRoon("", 40, "").status()

    def test_old_settings_without_a_roon_output_still_load_with_the_speaker_off(self):
        self.path.write_text(json.dumps({"enabled": True, "kef_host": "10.12.0.125", "modes": [{"id": "pi", "kef_input": "aux", "volume": 20}]}))
        loaded = load_settings(self.path)
        self.assertFalse(loaded["enabled"]); self.assertNotIn("modes", loaded)

    def test_listening_modes_are_gone_and_old_mode_keys_are_migrated(self):
        saved = self.controls.save({**self.settings, "modes": [{"id": "pi"}], "buttons": [{"label": "Pi", "action": "mode", "value": "pi"}]})
        self.assertNotIn("modes", saved)
        self.assertEqual(saved["buttons"][0]["action"], "none")
        with self.assertRaisesRegex(ValueError, "Roon output"): self.controls.save({"enabled": True})







    def test_infrared_input_uses_only_the_saved_remote_without_claiming_readback(self):
        self.settings["kef_ir_remote"] = "remote.study"
        self.write()
        send = Mock()
        self.speaker.status.return_value = {"connected": True, "powered": True, "input": "wifi", "volume": 20, "muted": False}
        controls = ListeningControls(self.path, lambda *args: self.speaker, ir_sender=send)
        result = controls.command("input", "aux")
        send.assert_called_once_with("remote.study", "aux")
        self.speaker.command.assert_not_called()
        self.assertIn("Sent AUX via infrared", result["notice"])
        self.assertTrue(result["ir_available"])
        self.assertFalse(result["kef"]["connected"])
        self.settings["kef_ir_remote"] = "light.desk"
        with self.assertRaises(ValueError): controls.save(self.settings)

    @patch("pi_bus_time_display.listening.time.sleep")
    def test_preset_wakes_a_standby_speaker_then_toggles_between_two_inputs(self, _sleep):
        self.settings.update(kef_ir_remote="remote.study")
        tile = {"primary": "aux", "alt": "wifi"}
        self.write()
        send = Mock()
        self.speaker.status.side_effect = [{"connected": True, "powered": False}, {"connected": True, "powered": True}] + [{"connected": True, "powered": True}] * 10
        controls = ListeningControls(self.path, lambda *args: self.speaker, ir_sender=send)
        result = controls.command("preset", tile)
        self.speaker.command.assert_called_once_with("power", True)
        send.assert_called_once_with("remote.study", "aux")
        self.assertIn("Woke the KEF", result["notice"])
        controls.command("preset", tile)
        self.assertEqual(send.call_args.args, ("remote.study", "wifi"))
        controls.command("preset", tile)
        self.assertEqual(send.call_args.args, ("remote.study", "aux"))
        self.assertEqual(self.speaker.command.call_count, 1)

    @patch("pi_bus_time_display.listening.time.sleep")
    def test_a_kef_not_on_wifi_is_woken_unless_an_input_was_sent_recently(self, _sleep):
        self.settings.update(kef_ir_remote="remote.study")
        self.write()
        send = Mock()
        self.speaker.status.return_value = {"connected": True, "powered": True, "input": "unknown", "volume": 20, "muted": False}
        controls = ListeningControls(self.path, lambda *args: self.speaker, ir_sender=send)
        controls.command("input", "aux")
        self.speaker.command.assert_called_once_with("power", True)
        controls.command("input", "optical")
        self.assertEqual(self.speaker.command.call_count, 1)

    def test_settings_saved_by_beta_136_with_preset_keys_still_load(self):
        self.settings.update(kef_ir_remote="remote.study", kef_input_preset="aux", kef_input_alt="wifi")
        self.write()
        loaded = load_settings(self.path)
        self.assertNotIn("kef_input_preset", loaded)
        self.assertEqual(loaded["kef_ir_remote"], "remote.study")

    def test_preset_needs_a_chosen_input(self):
        self.settings.update(kef_ir_remote="remote.study")
        self.write()
        controls = ListeningControls(self.path, lambda *args: self.speaker, ir_sender=Mock())
        for bad in (None, {}, {"primary": "hdmi"}, {"primary": "aux", "alt": "hdmi"}):
            with self.assertRaisesRegex(ValueError, "tile's options"): controls.command("preset", bad)

    @patch("pi_bus_time_display.server.home_assistant_request")
    def test_infrared_control_uses_home_assistant_and_only_the_fixed_kef_input_codes(self, home):
        from pi_bus_time_display.kef_ir import input_command
        state = State(Config(), Path(self.directory.name))
        with self.assertRaisesRegex(ValueError, "Enable Home Assistant"):
            state.send_kef_input("remote.study", "aux")
        home.assert_not_called()
        state.config = Config(home_assistant_enabled=True)
        state.send_kef_input("remote.study", "aux")
        self.assertEqual(home.call_args.args[1:], ("/api/services/remote/send_command", {
            "entity_id": "remote.study", "command": input_command("aux"), "num_repeats": 1}))

    def test_kef_ir_signal_decodes_to_the_published_msb_first_address_and_inputs(self):
        import base64
        from pi_bus_time_display.kef_ir import input_command
        for source, command in (("aux", 0x02), ("optical", 0x0A), ("wifi", 0x30), ("bluetooth", 0x2A)):
            packet = base64.b64decode(input_command(source)[4:])
            self.assertEqual(packet[0], 0x26)
            body = packet[4:4 + int.from_bytes(packet[2:4], "little")]
            pulses = []; offset = 0
            while offset < len(body) - 2:
                value = body[offset]; offset += 1
                if value == 0:
                    value = int.from_bytes(body[offset:offset + 2], "big"); offset += 2
                pulses.append(value)
            decoded = []
            for start in range(2, 66, 16):
                value = 0
                for space in pulses[start + 1:start + 16:2]: value = (value << 1) | (space > 30)
                decoded.append(value)
            self.assertEqual(decoded, [0x01, 0xFE, command, command ^ 0xFF])
        with self.assertRaises(ValueError): input_command("usb")


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

    def art_request(self, path, body, content_type="image/png"):
        handler = self.handler({}); handler.path = path
        handler.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body); handler.do_POST()
        return handler.send_json.call_args.args[0]

    def test_stream_deck_artwork_upload_accepts_only_small_named_pngs(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 40
        self.assertEqual(self.art_request("/api/admin/listening/art?name=icon-play.png", png), 200)
        self.assertEqual((Path(self.directory.name) / "deck-art/icon-play.png").read_bytes(), png)
        self.assertEqual(self.art_request("/api/admin/listening/art?name=../evil.png", png), 400)
        self.assertEqual(self.art_request("/api/admin/listening/art?name=x.svg", png), 400)
        self.assertEqual(self.art_request("/api/admin/listening/art?name=a.png", b"<svg/>"), 400)
        self.assertEqual(self.art_request("/api/admin/listening/art?name=a.png", png, "text/html"), 400)
        self.assertEqual(self.art_request("/api/admin/listening/art?name=big.png", b"\x89PNG\r\n\x1a\n" + b"0" * 300000), 400)

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

    @patch("pi_bus_time_display.streamdeck.request")
    def test_deck_volume_changes_are_tagged_so_the_screen_stays_put(self, request):
        dispatch("http://localhost", {"action": "roon_volume", "step": 1}, 2)
        self.assertEqual(request.call_args_list[0].args[1:], ("/api/listening/command", {"action": "deck_volume"}))
        request.reset_mock()
        dispatch("http://localhost", {"action": "next"})
        self.assertEqual(request.call_count, 1)

    @patch("pi_bus_time_display.streamdeck.request")
    def test_home_scripts_run_once_per_click_and_dials_choose_a_script_by_direction(self, request):
        dial = {"action": "home_script_dial", "entity_id": "script.topping_vol_up", "entity_id_ccw": "script.topping_vol_down"}
        dispatch("http://localhost", dial, 3)
        self.assertEqual(request.call_count, 3)
        request.assert_called_with("http://localhost", "/api/listening/command", {"action": "scene", "value": "script.topping_vol_up"})
        request.reset_mock()
        dispatch("http://localhost", dial, -2)
        self.assertEqual(request.call_count, 2)
        request.assert_called_with("http://localhost", "/api/listening/command", {"action": "scene", "value": "script.topping_vol_down"})
        request.reset_mock()
        dispatch("http://localhost", {"action": "home_script_dial", "entity_id": "script.up"}, -1)
        request.assert_not_called()
        dispatch("http://localhost", {"action": "home_script", "entity_id": "script.topping_mute"})
        request.assert_called_once_with("http://localhost", "/api/listening/command", {"action": "scene", "value": "script.topping_mute"})

    def test_home_script_bindings_must_name_a_script(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.mute"}],
                           "dials": [{"action": "home_script_dial", "entity_id": "script.up", "entity_id_ccw": "script.down"}]})
        for bad in ({"action": "home_script", "entity_id": "light.desk"},):
            with self.assertRaises(ValueError): validate_settings({"buttons": [bad]})
        with self.assertRaises(ValueError):
            validate_settings({"dials": [{"action": "home_script_dial", "entity_id": "script.up", "entity_id_ccw": "light.x"}]})


if __name__ == "__main__":
    unittest.main()


class StreamDeckDisplayHelpersTests(unittest.TestCase):
    def test_elapsed_time_is_minutes_and_seconds(self):
        from pi_bus_time_display import streamdeck
        self.assertEqual(streamdeck.clock(0), "0:00")
        self.assertEqual(streamdeck.clock(75), "1:15")
        self.assertEqual(streamdeck.clock(None), "0:00")


class PlayTriggerSettingsTests(unittest.TestCase):
    def test_play_trigger_must_run_a_script(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"on_play": {"script": "script.topping_optical", "helper": "input_select.topping_input", "value": "Optical"}})
        with self.assertRaises(ValueError): validate_settings({"on_play": {"script": "light.kitchen"}})
        with self.assertRaises(ValueError): validate_settings({"on_play": {"script": "script.a", "helper": "switch.x"}})
        with self.assertRaises(ValueError): validate_settings({"on_play": {"other": "x"}})


class StreamDeckPainterTests(unittest.TestCase):
    def setUp(self):
        try: import PIL  # noqa: F401
        except ImportError: self.skipTest("Pillow is not installed")
        import tempfile
        from pi_bus_time_display.streamdeck import Painter
        self.folder = tempfile.mkdtemp()
        self.painter = Painter(self.folder)

    def test_every_kind_of_key_and_strip_draws(self):
        from PIL import Image
        import io
        cover = Image.new("RGB", (120, 120), "#336699")
        state = {"kef": {"connected": False}, "modes": [], "last_mode": None}
        home = {"entities": [{"entity_id": "light.lamp", "state": "on", "percentage": 60}]}
        for binding in ({}, {"label": "Mute", "action": "mute"}, {"label": "A very long label that wraps", "action": "mode", "value": "pi", "color": "#236650"},
                        {"action": "playpause", "label": "Play / Pause"}, {"action": "home_toggle", "entity_id": "light.lamp", "label": "Lamp", "color": "#222222"}):
            for elapsed, art in ((None, None), (75, cover)):
                data = self.painter.key(binding, state, home, art, elapsed)
                self.assertEqual(Image.open(io.BytesIO(data)).size, (120, 120))
        dials = [{"action": "volume_delta", "label": "Volume", "color": "#6b2d7a"}, {"action": "home_level", "label": "Lights", "entity_id": "light.lamp"},
                 {"action": "home_script_dial", "label": "Topping"}, {"action": "none"}]
        for kef in ({"connected": True, "volume": 30, "muted": True}, {"connected": False}):
            data = self.painter.strip(dials, {**state, "kef": kef}, home, "")
            self.assertEqual(Image.open(io.BytesIO(data)).size, (800, 100))
        self.assertFalse(self.painter.reported, "drawing raised an error that was swallowed")

    def test_drawing_works_without_the_dejavu_fonts(self):
        from pi_bus_time_display.streamdeck import Painter
        class NoDejaVu(Painter): FONT_DIR = "/nonexistent/"
        painter = NoDejaVu(self.folder)
        painter.key({"action": "playpause", "label": "Play"}, {}, {}, None, 5)
        painter.strip([{"action": "home_level", "label": "Lights", "entity_id": "x"}], {}, {}, "")
        self.assertFalse(painter.reported, "drawing failed without DejaVu")


class StreamDeckHomeLevelTests(unittest.TestCase):
    def run_turns(self, entity, deltas, step):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        streamdeck._pending_levels.clear()
        sent = []
        def fake(base, path, payload=None):
            if path == "/api/device/controls": return {"home": {"entities": [entity]}}
            sent.append(payload["value"]); return {}
        with mock.patch.object(streamdeck, "request", fake):
            for delta in deltas:
                streamdeck.dispatch("http://x", {"action": "home_level", "entity_id": entity["entity_id"], "step": step}, delta)
        return sent

    def test_quick_turns_build_on_the_last_target_not_stale_state(self):
        light = {"entity_id": "light.desk", "domain": "light", "brightness": 128, "supports_level": True}
        self.assertEqual(self.run_turns(light, [1, 1, 1], 10), [60, 70, 80])

    def test_a_fan_steps_by_its_own_speed_increment_both_ways(self):
        fan = {"entity_id": "fan.study", "domain": "fan", "percentage": 66, "percentage_step": 33.33, "supports_level": True}
        up_then_down = self.run_turns(fan, [-1, -1], 2)
        self.assertEqual(up_then_down, [33, 0])


class StreamDeckExtrasTests(unittest.TestCase):
    def test_a_key_can_also_pause_roon_or_run_a_script(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        calls = []
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: calls.append((path, payload)) or {}):
            streamdeck.dispatch("b", {"action": "home_script", "entity_id": "script.mac", "also": {"action": "pause"}})
            streamdeck.dispatch("b", {"action": "home_script", "entity_id": "script.usb", "also": {"action": "home_script", "entity_id": "script.lamp"}})
        self.assertEqual(calls[1], ("/roon/api/control", {"action": "pause"}))
        self.assertEqual(calls[3], ("/api/listening/command", {"action": "scene", "value": "script.lamp"}))

    def test_a_key_runs_several_follow_up_steps_in_order(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        calls = []
        key = {"action": "input", "value": "aux", "also": [{"action": "pause", "zone": "Study"}, {"action": "home_script", "entity_id": "script.topping_mac"}, {"action": "kef_input", "value": "optical"}]}
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: calls.append((path, payload)) or {}):
            streamdeck.dispatch("b", key)
        self.assertEqual(calls[1:], [("/roon/api/control", {"action": "pause", "zone": "Study"}), ("/api/listening/command", {"action": "scene", "value": "script.topping_mac"}), ("/api/listening/command", {"action": "input", "value": "optical"})])
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"buttons": [key]})
        with self.assertRaises(ValueError): validate_settings({"buttons": [{**key, "also": [{"action": "pause"}] * 5}]})
        with self.assertRaises(ValueError): validate_settings({"buttons": [{**key, "also": [{"action": "kef_input", "value": "hdmi"}]}]})

    @patch("pi_bus_time_display.listening.time.sleep")
    def test_a_roon_wake_timeout_does_not_stop_the_input_change(self, _sleep):
        import tempfile, json
        from pathlib import Path
        folder = Path(tempfile.mkdtemp()); path = folder / "listening.json"
        path.write_text(json.dumps({"enabled": True, "kef_roon_output_id": "o", "kef_ir_remote": "remote.study"}))
        speaker = Mock(); send = Mock()
        speaker.status.side_effect = [{"connected": True, "powered": False}, {"connected": True, "powered": True}]
        speaker.command.side_effect = OSError("Roon KEF control timed out.")
        controls = ListeningControls(path, lambda *args: speaker, ir_sender=send)
        result = controls.command("input", "aux")
        send.assert_called_once_with("remote.study", "aux")
        self.assertIn("Woke the KEF", result["notice"])

    def test_also_follow_up_is_validated(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "also": {"action": "pause"}}]})
        with self.assertRaises(ValueError): validate_settings({"buttons": [{"action": "mute", "also": {"action": "reboot"}}]})
        with self.assertRaises(ValueError): validate_settings({"buttons": [{"action": "mute", "also": {"action": "home_script", "entity_id": "light.x"}}]})

    def test_key_corners_are_always_black(self):
        try: from pi_bus_time_display.streamdeck import Painter
        except ImportError: self.skipTest("no Pillow")
        import io, tempfile
        from PIL import Image
        data = Painter(tempfile.mkdtemp()).key({"color": "#ffffff", "label": "X"}, {}, {}, None, None)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        self.assertLess(sum(image.getpixel((0, 0))), 40)
        self.assertGreater(sum(image.getpixel((60, 60))), 600)


class StreamDeckSleepSettingTests(unittest.TestCase):
    def test_deck_sleep_mode_follows_screen_or_own_schedule(self):
        from datetime import datetime
        from pi_bus_time_display.streamdeck import deck_should_sleep
        noon, night = datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 23, 30)
        awake = {"target": "/", "screen_powered": True}
        match = {"streamdeck_sleep_mode": "match", "streamdeck_sleep_start": "23:00", "streamdeck_sleep_end": "06:00"}
        self.assertTrue(deck_should_sleep(match, noon, {"target": "/sleep.html", "screen_powered": False}))
        # The panel's own idle timeout never changes the controller's target, only the reported power.
        self.assertTrue(deck_should_sleep(match, noon, {"target": "http://127.0.0.1:8766/", "screen_powered": False}))
        self.assertFalse(deck_should_sleep(match, noon, awake))
        self.assertFalse(deck_should_sleep(match, noon, {"target": "/"}))   # state not reported yet
        self.assertFalse(deck_should_sleep(match, night, awake))            # match ignores the deck's own times
        own = {"streamdeck_sleep_mode": "schedule", "streamdeck_sleep_start": "23:00", "streamdeck_sleep_end": "06:00"}
        self.assertTrue(deck_should_sleep(own, night, awake))
        self.assertFalse(deck_should_sleep(own, noon, {"target": "/sleep.html", "screen_powered": False}))
        self.assertFalse(deck_should_sleep({"streamdeck_sleep_mode": "schedule"}, night, awake))   # no times: never sleeps
        self.assertFalse(deck_should_sleep({"streamdeck_sleep_with_display": False}, night, awake))  # older save, no times
        self.assertTrue(deck_should_sleep({}, noon, {"target": "/sleep.html"}))                      # older default follows the screen

    def test_sleep_mode_is_validated(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"streamdeck_sleep_mode": "match"}); validate_settings({"streamdeck_sleep_mode": "schedule"})
        with self.assertRaises(ValueError): validate_settings({"streamdeck_sleep_mode": "both"})

    def test_sleep_with_display_must_be_a_boolean(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"streamdeck_sleep_with_display": False})
        with self.assertRaises(ValueError): validate_settings({"streamdeck_sleep_with_display": "yes"})


class StreamDeckRemoteStepsAndSleepTests(unittest.TestCase):
    AIRCON = {"action": "remote_steps", "label": "Aircon", "entity_id": "remote.wi_fi_universal_remote", "device": "aircon",
              "command": "cool_{n}", "min": 16, "max": 30, "start": 24, "unit": "°", "step": 1, "press": {"action": "none"}}

    def test_remote_steps_validation(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"dials": [dict(self.AIRCON)]})
        for change in ({"entity_id": "light.x"}, {"command": "cool_24"}, {"min": 30, "max": 16}, {"start": 40}, {"device": "a;b"}):
            with self.assertRaises(ValueError): validate_settings({"dials": [{**self.AIRCON, **change}]})

    def test_only_commands_a_saved_dial_can_produce_are_allowed(self):
        from pi_bus_time_display.listening import remote_step_allowed
        settings = {"dials": [dict(self.AIRCON)]}
        good = {"entity_id": "remote.wi_fi_universal_remote", "device": "aircon", "command": "cool_22"}
        self.assertTrue(remote_step_allowed(settings, good))
        self.assertFalse(remote_step_allowed(settings, {**good, "command": "power_off"}))
        self.assertFalse(remote_step_allowed(settings, {**good, "device": "topping"}))
        self.assertFalse(remote_step_allowed({"dials": []}, good))

    def test_turning_the_dial_sends_the_next_temperature(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        streamdeck._steps.clear()
        sent = []
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: sent.append(payload["value"]["command"]) or {}):
            streamdeck.dispatch("b", dict(self.AIRCON), 1)
            streamdeck.dispatch("b", dict(self.AIRCON), 2)
            streamdeck.dispatch("b", dict(self.AIRCON), -20)
            streamdeck.dispatch("b", dict(self.AIRCON), -1)
        self.assertEqual(sent, ["cool_25", "cool_27", "cool_16"])

    def test_sleep_window_handles_midnight(self):
        from datetime import datetime
        from pi_bus_time_display.streamdeck import in_window
        self.assertTrue(in_window("23:00", "06:00", datetime(2026, 1, 1, 23, 30)))
        self.assertTrue(in_window("23:00", "06:00", datetime(2026, 1, 1, 2, 0)))
        self.assertFalse(in_window("23:00", "06:00", datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(in_window("", "06:00", datetime(2026, 1, 1, 2, 0)))

    def test_wake_settings_are_validated(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"streamdeck_sleep_start": "23:00", "streamdeck_sleep_end": "", "streamdeck_awake_seconds": 45, "streamdeck_brightness": 60})
        for bad in ({"streamdeck_sleep_start": "25:00"}, {"streamdeck_awake_seconds": 2}, {"streamdeck_brightness": 5}):
            with self.assertRaises(ValueError): validate_settings(bad)


class StreamDeckRemoteToggleTests(unittest.TestCase):
    PRESS = {"action": "remote_toggle", "entity_id": "remote.wi_fi_universal_remote", "device": "aircon", "command_on": "power_on", "command_off": "power_off", "initial_on": False}

    def test_pressing_alternates_the_on_and_off_commands(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        streamdeck._toggles.clear()
        sent = []
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: sent.append(payload["value"]["command"]) or {}):
            for _ in range(3): streamdeck.dispatch("b", dict(self.PRESS))
        self.assertEqual(sent, ["power_on", "power_off", "power_on"])

    def test_a_temperature_step_counts_as_switching_on(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        streamdeck._toggles.clear(); streamdeck._steps.clear()
        sent = []
        dial = dict(StreamDeckRemoteStepsAndSleepTests.AIRCON)
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: sent.append(payload["value"]["command"]) or {}):
            streamdeck.dispatch("b", dial, 1)
            streamdeck.dispatch("b", dict(self.PRESS))
        self.assertEqual(sent, ["cool_25", "power_off"])

    def test_toggle_commands_are_validated_and_allowed(self):
        from pi_bus_time_display.listening import validate_settings, remote_step_allowed
        dial = {**StreamDeckRemoteStepsAndSleepTests.AIRCON, "press": dict(self.PRESS)}
        validate_settings({"dials": [dial]})
        with self.assertRaises(ValueError): validate_settings({"dials": [{**dial, "press": {**self.PRESS, "command_on": "bad command"}}]})
        settings = {"dials": [dial]}
        target = {"entity_id": self.PRESS["entity_id"], "device": "aircon"}
        self.assertTrue(remote_step_allowed(settings, {**target, "command": "power_off"}))
        self.assertFalse(remote_step_allowed(settings, {**target, "command": "reboot"}))


class StreamDeckOffOnlyTests(unittest.TestCase):
    def test_off_only_press_always_sends_the_off_command(self):
        from unittest import mock
        from pi_bus_time_display import streamdeck
        streamdeck._toggles.clear()
        press = {**StreamDeckRemoteToggleTests.PRESS, "off_only": True}
        sent = []
        with mock.patch.object(streamdeck, "request", lambda base, path, payload=None: sent.append(payload["value"]["command"]) or {}):
            for _ in range(2): streamdeck.dispatch("b", dict(press))
        self.assertEqual(sent, ["power_off", "power_off"])
        self.assertFalse(streamdeck._toggles[("remote.wi_fi_universal_remote", "aircon")])

    def test_deck_brightness_preview_accepts_only_sane_values(self):
        from pi_bus_time_display.listening import validate_settings
        with self.assertRaises(ValueError): validate_settings({"dials": [{"action": "remote_toggle", "off_only": "yes"}]})


class ReferencedEntitiesTests(unittest.TestCase):
    def test_collects_every_entity_a_design_uses(self):
        from pi_bus_time_display.listening import referenced_entities
        found = referenced_entities({
            "buttons": [{"action": "home_script", "entity_id": "script.study_desk_cycle", "also": {"action": "home_script", "entity_id": "script.b"}}],
            "dials": [{"action": "home_level", "entity_id": "light.study_uplight", "press": {"action": "home_toggle", "entity_id": "switch.desk_lamp_none"}}],
            "on_play": {"script": "script.topping_input_optical"}})
        self.assertEqual(found, {"script.study_desk_cycle", "script.b", "light.study_uplight", "switch.desk_lamp_none", "script.topping_input_optical"})


class LevelKeyTests(unittest.TestCase):
    def setUp(self):
        global Painter
        try: from pi_bus_time_display.streamdeck import Painter
        except ImportError: self.skipTest('no Pillow')

    def draw(self, painter, state, brightness):
        from io import BytesIO
        from PIL import Image
        home = {"entities": [{"entity_id": "light.study_uplight", "state": state, "brightness": brightness}]}
        raw = painter.key({"action": "home_script", "entity_id": "script.cycle", "label": "Study", "level_entity": "light.study_uplight"}, {}, home, None, None)
        return Image.open(BytesIO(raw)).convert("RGB")

    def test_background_warms_as_the_light_gets_brighter(self):
        centre = lambda image: image.getpixel((12, 60))
        off = centre(self.draw(Painter(tempfile.mkdtemp()), "off", 0))
        low = centre(self.draw(Painter(tempfile.mkdtemp()), "on", 26))
        full = centre(self.draw(Painter(tempfile.mkdtemp()), "on", 255))
        self.assertLess(sum(off), sum(low)); self.assertLess(sum(low), sum(full))

    def test_fades_between_levels_instead_of_jumping(self):
        painter = Painter(tempfile.mkdtemp())
        self.draw(painter, "off", 0)
        step = self.draw(painter, "on", 255).getpixel((12, 60))
        settled = step
        for _ in range(12): settled = self.draw(painter, "on", 255).getpixel((12, 60))
        self.assertLess(sum(step), sum(settled))

    def test_fade_finishes_within_a_second_of_frames(self):
        painter = Painter(tempfile.mkdtemp())
        self.draw(painter, "off", 0)
        frames = 0
        self.draw(painter, "on", 255); frames += 1
        while painter.animating() and frames < 40:
            self.draw(painter, "on", 255); frames += 1
        self.assertFalse(painter.animating()); self.assertLessEqual(frames, 12)

    def test_a_running_script_never_flashes_the_green_on_colour(self):
        from io import BytesIO
        from PIL import Image
        home = {"entities": [{"entity_id": "script.cycle", "state": "on"}, {"entity_id": "light.study_uplight", "state": "off", "brightness": 0}]}
        raw = Painter(tempfile.mkdtemp()).key({"action": "home_script", "entity_id": "script.cycle", "level_entity": "light.study_uplight", "color": "#000000"}, {}, home, None, None)
        red, green, blue = Image.open(BytesIO(raw)).convert("RGB").getpixel((12, 60))
        self.assertLess(green, 20)

    def test_glow_colour_is_used_and_validated(self):
        from io import BytesIO
        from PIL import Image
        from pi_bus_time_display.listening import validate_settings
        home = {"entities": [{"entity_id": "light.study_uplight", "state": "on", "brightness": 255}]}
        raw = Painter(tempfile.mkdtemp()).key({"action": "home_script", "entity_id": "script.c", "level_entity": "light.study_uplight", "level_color": "#3d8bff", "color": "#000000"}, {}, home, None, None)
        red, green, blue = Image.open(BytesIO(raw)).convert("RGB").getpixel((12, 60))
        self.assertGreater(blue, red)
        with self.assertRaises(ValueError):
            validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "level_color": "blue"}]})

    def test_only_lights_and_fans_can_show_a_level(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "level_entity": "light.study_uplight"}]})
        with self.assertRaises(ValueError):
            validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "level_entity": "switch.lamp"}]})
