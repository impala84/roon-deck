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
                      {"buttons":[{"image":"../escape.png"}]}, {"buttons":[{"color":"red"}]},
                      {"buttons":[{"color":"#12345"}]}, {"enabled":"true"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.controls.save({**self.settings, **extra})

    def test_button_colour_and_artwork_are_saved(self):
        saved = self.controls.save({**self.settings, "buttons": [{"label": "A", "action": "mute", "color": "#236650", "image": "icon-mute.png"}]})
        self.assertEqual(saved["buttons"][0]["color"], "#236650")

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

    def test_only_lights_and_fans_can_show_a_level(self):
        from pi_bus_time_display.listening import validate_settings
        validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "level_entity": "light.study_uplight"}]})
        with self.assertRaises(ValueError):
            validate_settings({"buttons": [{"action": "home_script", "entity_id": "script.a", "level_entity": "switch.lamp"}]})
