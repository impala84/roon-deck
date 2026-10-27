import tempfile
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pi_bus_time_display.config import Config, load_config
from pi_bus_time_display.server import State, active_wifi_ssid, automatic_display_target, clear_sleep_mode_on_start, connected_network_snapshot, display_config_dir, display_orientation, display_target, home_assistant_activate, home_assistant_entity_available, home_assistant_set_state, home_assistant_set_value, netdata_snapshot, read_display_mode, service_state, set_display_mode, system_snapshot, within_sleep_window, write_config, write_control_request


class DisplayModeTests(unittest.TestCase):
    def test_automatic_update_settings_round_trip_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(auto_update_enabled=True, auto_update_time="02:45", release_channel="beta"))
            saved = load_config(path)
            self.assertTrue(saved.auto_update_enabled)
            self.assertEqual(saved.auto_update_time, "02:45")
            self.assertEqual(saved.release_channel, "beta")
            for values in ({"auto_update_time": "24:00"}, {"auto_update_time": "3:00"}, {"auto_update_enabled": "false"}):
                import json
                path.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()))
                with self.assertRaises(ValueError): load_config(path)

    def test_home_assistant_tile_colours_are_persisted_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(home_assistant_color_mode="single", home_assistant_single_color="#334455", home_assistant_light_color="#112233", home_assistant_scene_color="#abcdef"))
            loaded = load_config(path)
            self.assertEqual(loaded.home_assistant_color_mode, "single")
            self.assertEqual(loaded.home_assistant_single_color, "#334455")
            self.assertEqual(loaded.home_assistant_light_color, "#112233")
            self.assertEqual(loaded.home_assistant_scene_color, "#abcdef")
            path.write_text(path.read_text().replace("#112233", "orange"))
            with self.assertRaisesRegex(ValueError, "tile colours"):
                load_config(path)

    def test_home_assistant_colour_mode_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(home_assistant_color_mode="rainbow"))
            with self.assertRaisesRegex(ValueError, "colour mode"):
                load_config(path)

    def test_overnight_wake_schedule_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(scheduled_wake_enabled=False, weekend_wake_enabled=True, weekend_wake_time="09:15"))
            saved = load_config(path)
            self.assertFalse(saved.scheduled_wake_enabled)
            self.assertTrue(saved.weekend_wake_enabled)
            self.assertEqual(saved.weekend_wake_time, "09:15")

    def test_home_assistant_title_can_be_custom_or_blank(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for title in ("Bedroom", ""):
                write_config(path, Config(home_assistant_title=title))
                self.assertEqual(load_config(path).home_assistant_title, title)

    def test_home_assistant_scene_configuration_is_allowed_and_still_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(home_assistant_entities=("scene.bedroom_energize", "scene.bedroom_ruby_romance")))
            self.assertEqual(load_config(path).home_assistant_entities, ("scene.bedroom_energize", "scene.bedroom_ruby_romance"))
            write_config(path, Config(home_assistant_entities=("lock.front_door",)))
            with self.assertRaisesRegex(ValueError, "Unsupported Home Assistant entity"):
                load_config(path)
    def test_browsing_return_timeout_persists_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(browse_idle_return_seconds=150))
            self.assertEqual(load_config(path).browse_idle_return_seconds, 150)
            write_config(path, Config(settings_layout="simple"))
            self.assertEqual(load_config(path).settings_layout, "simple")
            write_config(path, Config(settings_layout="fancy"))
            with self.assertRaises(ValueError): load_config(path)
            write_config(path, Config(roon_core_host="192.168.1.20"))
            self.assertEqual(load_config(path).roon_core_host, "192.168.1.20")
            write_config(path, Config(roon_core_host="http://bad"))
            with self.assertRaises(ValueError): load_config(path)
            write_config(path, Config(touch_airplay=True, touch_netdata=False))
            loaded = load_config(path)
            self.assertEqual((loaded.touch_roon_bridge, loaded.touch_airplay, loaded.touch_netdata), (True, True, False))
            path.write_text(path.read_text().replace("touch_airplay = true", 'touch_airplay = "yes"'))
            with self.assertRaises(ValueError): load_config(path)
            write_config(path, Config(browse_idle_return_seconds=7201))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_landscape_music_clock_persists_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for style in ("icon", "full"):
                write_config(path, Config(landscape_music_clock=style))
                self.assertEqual(load_config(path).landscape_music_clock, style)
            write_config(path, Config(landscape_music_clock="invalid"))
            with self.assertRaises(ValueError): load_config(path)

    def test_portrait_discovery_columns_persist_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for columns in (2, 3):
                write_config(path, Config(portrait_discovery_columns=columns))
                self.assertEqual(load_config(path).portrait_discovery_columns, columns)
            write_config(path, Config(portrait_discovery_columns=4))
            with self.assertRaises(ValueError): load_config(path)

    def test_saved_theme_is_in_initial_html_before_scripts_run(self):
        import io
        from unittest.mock import Mock
        from pi_bus_time_display.server import make_handler
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            state = State(Config(display_theme="roon"), path)
            Handler = make_handler(state, path / "config.toml", path / "env", path / "mode")
            for page in ("/admin.html", "/admin.html?test=1", "/", "/home.html"):
                handler = Handler.__new__(Handler); handler.path = page
                handler.wfile = io.BytesIO(); handler.is_authorised = Mock(return_value=True); handler.authorised = Mock(return_value=True)
                handler.send_response = Mock(); handler.send_header = Mock(); handler.end_headers = Mock()
                handler.do_GET()
                html = handler.wfile.getvalue().decode()
                self.assertIn('<body data-theme="roon"', html)
                self.assertNotIn('href="/favicon.svg"', html)
                state.config = Config(display_theme="fresh-mint")
                handler.wfile = io.BytesIO(); handler.do_GET()
                self.assertIn('<body data-theme="fresh-mint"', handler.wfile.getvalue().decode())
                state.config = Config(display_theme="roon")

    def test_touchscreen_bridge_reaches_alpine_helper_and_rejects_remote_requests(self):
        import io
        from unittest.mock import Mock
        from pi_bus_time_display.server import make_handler
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            Handler = make_handler(State(Config(), path), path / "config.toml", path / "env", path / "mode")
            for enabled in (True, False):
                handler = Handler.__new__(Handler)
                handler.path = "/api/device/roon-bridge"
                handler.client_address = ("127.0.0.1", 1)
                payload = b'{"enabled":true}' if enabled else b'{"enabled":false}'
                handler.headers = {"Content-Length": str(len(payload))}
                handler.rfile = io.BytesIO(payload); handler.send_json = Mock()
                with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.write_control_request") as action:
                    handler.do_POST()
                    action.assert_called_once_with(path, {"action":"roon_start" if enabled else "roon_stop"})
                    self.assertEqual(handler.send_json.call_args.args[0], 200)
                    handler.client_address = ("10.0.0.2", 1)
                    handler.do_POST()
                    self.assertEqual(handler.send_json.call_args.args[0], 403)
                    self.assertEqual(action.call_count, 1)

    def test_touchscreen_netdata_switch_reaches_alpine_helper(self):
        import io
        from unittest.mock import Mock
        from pi_bus_time_display.server import make_handler
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            Handler = make_handler(State(Config(), path), path / "config.toml", path / "env", path / "mode")
            for enabled in (True, False):
                handler = Handler.__new__(Handler)
                handler.path = "/api/device/netdata"
                handler.client_address = ("127.0.0.1", 1)
                payload = b'{"enabled":true}' if enabled else b'{"enabled":false}'
                handler.headers = {"Content-Length": str(len(payload))}
                handler.rfile = io.BytesIO(payload); handler.send_json = Mock()
                with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.write_control_request") as action:
                    handler.do_POST()
                    action.assert_called_once_with(path, {"action":"netdata_enable" if enabled else "netdata_disable"})
                    self.assertEqual(handler.send_json.call_args.args[0], 200)

    def test_touchscreen_airplay_switch_reaches_alpine_helper(self):
        import io
        from unittest.mock import Mock
        from pi_bus_time_display.server import make_handler
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            Handler = make_handler(State(Config(), path), path / "config.toml", path / "env", path / "mode")
            for enabled in (True, False):
                handler = Handler.__new__(Handler)
                handler.path = "/api/device/airplay"
                handler.client_address = ("127.0.0.1", 1)
                payload = b'{"enabled":true}' if enabled else b'{"enabled":false}'
                handler.headers = {"Content-Length": str(len(payload))}
                handler.rfile = io.BytesIO(payload); handler.send_json = Mock()
                with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.write_control_request") as action:
                    handler.do_POST()
                    action.assert_called_once_with(path, {"action":"airplay_start" if enabled else "airplay_stop"})
                    self.assertEqual(handler.send_json.call_args.args[0], 200)

    def test_display_orientation_is_derived_from_each_panels_native_shape(self):
        self.assertEqual(display_orientation("original", "normal"), "landscape")
        self.assertEqual(display_orientation("original", "90"), "portrait")
        self.assertEqual(display_orientation("touch2-10", "normal"), "portrait")
        self.assertEqual(display_orientation("touch2-10", "90"), "landscape")

    def test_alpine_display_settings_use_the_appliance_configuration(self):
        with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}):
            self.assertEqual(display_config_dir(), Path("/etc/pi-home"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(display_config_dir(), Path("/etc/pi-bus-time-display"))

    def test_alpine_diagnostics_uses_openrc_service_names(self):
        from pi_bus_time_display.server import diagnostics_snapshot
        with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.command_output", return_value=""), patch("pi_bus_time_display.server.service_state", return_value="running") as services:
            data = diagnostics_snapshot()
        self.assertTrue(all(process["active"] for process in data["processes"]))
        self.assertEqual({call.args[0] for call in services.call_args_list}, {"pi-home-roon", "pi-home-api", "pi-home-display", "roonbridge", "shairport-sync"})

    def test_diagnostics_includes_netdata_and_collectors_only_when_running(self):
        from pi_bus_time_display.server import diagnostics_snapshot
        output = "12 204800 1.2 /opt/netdata/bin/netdata -D\n13 10240 0.3 /opt/netdata/usr/libexec/netdata/plugins.d/apps.plugin\n14 99999 9.9 grep netdata\n"
        with patch("pi_bus_time_display.server.command_output", return_value=output), patch("pi_bus_time_display.server.service_state", return_value="stopped"):
            data = diagnostics_snapshot()
        netdata = next(process for process in data["processes"] if process["label"] == "Netdata")
        self.assertEqual(netdata["rss_kb"], 215040)
        self.assertAlmostEqual(netdata["cpu_percent"], 1.5)
        self.assertEqual(netdata["pids"], [12, 13])
        with patch("pi_bus_time_display.server.command_output", return_value=""), patch("pi_bus_time_display.server.service_state", return_value="stopped"):
            self.assertNotIn("Netdata", [process["label"] for process in diagnostics_snapshot()["processes"]])

    def test_diagnostics_detects_alpine_packaged_netdata(self):
        from pi_bus_time_display.server import diagnostics_snapshot
        with patch("pi_bus_time_display.server.command_output", return_value="22 1024 0.1 /usr/sbin/netdata"), patch("pi_bus_time_display.server.service_state", return_value="stopped"):
            self.assertTrue(next(process for process in diagnostics_snapshot()["processes"] if process["label"] == "Netdata")["active"])

    def test_diagnostics_hides_unconfigured_music_and_stopped_optional_tools(self):
        from pi_bus_time_display.server import diagnostics_snapshot
        with patch("pi_bus_time_display.server.command_output", return_value=""), patch("pi_bus_time_display.server.service_state", return_value="stopped"):
            labels = [p["label"] for p in diagnostics_snapshot(Config(bus_enabled=False))["processes"]]
            self.assertNotIn("Roon controller", labels)
            self.assertNotIn("Roon Bridge", labels)
            self.assertNotIn("AirPlay · Shairport Sync", labels)
            self.assertNotIn("Netdata", labels)
            self.assertIn("RoonDeck backend", labels)
            configured = diagnostics_snapshot(Config(roon_zone_name="NAD M33"))["processes"]
            self.assertIn("Roon controller", [p["label"] for p in configured])

    def test_bus_disabled_persists_and_automatic_stays_on_music(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            mode = Path(directory) / "mode"
            write_config(path, Config(bus_enabled=False))
            config = load_config(path)
            self.assertFalse(config.bus_enabled)
            state = State(config, Path(directory))
            self.assertFalse(state.snapshot()["bus_enabled"])
            noon = datetime(2026, 10, 4, 12, tzinfo=ZoneInfo(config.timezone))
            self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, noon), "http://127.0.0.1:8766/")
            self.assertEqual(display_target(config, mode, {"zone": {"state": "paused"}}, noon), "http://127.0.0.1:8766/")
            self.assertTrue(Config().bus_enabled)

    def test_display_theme_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            self.assertEqual(Config().display_theme, "fresh-mint")
            write_config(path, Config(display_theme="roon"))
            self.assertEqual(load_config(path).display_theme, "roon")
            self.assertEqual(State(Config(display_theme="roon"), Path(directory)).snapshot()["display_theme"], "roon")
            write_config(path, Config(display_theme="invalid"))
            with self.assertRaises(ValueError): load_config(path)

    def test_display_background_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            self.assertEqual(Config().display_background, "current")
            write_config(path, Config(display_background="black"))
            self.assertEqual(load_config(path).display_background, "black")
            self.assertEqual(State(Config(display_background="black"), Path(directory)).snapshot()["display_background"], "black")
            write_config(path, Config(display_background="invalid"))
            with self.assertRaises(ValueError): load_config(path)

    def test_interface_size_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            self.assertEqual(Config().interface_size, "standard")
            write_config(path, Config(interface_size="larger"))
            self.assertEqual(load_config(path).interface_size, "larger")
            self.assertEqual(State(Config(interface_size="larger"), Path(directory)).snapshot()["interface_size"], "larger")
            write_config(path, Config(interface_size="enormous"))
            with self.assertRaises(ValueError): load_config(path)

    def test_custom_roon_display_name_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(roon_display_name="Hi-Fi"))
            self.assertEqual(load_config(path).roon_display_name, "Hi-Fi")

    def test_custom_roon_view_names_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(roon_now_playing_name="Roon", roon_queue_name="Q"))
            loaded = load_config(path)
            self.assertEqual(loaded.roon_now_playing_name, "Roon")
            self.assertEqual(loaded.roon_queue_name, "Q")

    def test_roon_browser_visibility_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(roon_show_browser=False))
            self.assertFalse(load_config(path).roon_show_browser)

    def test_openobserve_settings_persist_without_a_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, Config(openobserve_enabled=True, openobserve_url="http://observe.local:5080", openobserve_username="admin"))
            loaded = load_config(path)
            self.assertTrue(loaded.openobserve_enabled)
            self.assertEqual(loaded.openobserve_url, "http://observe.local:5080")
            self.assertEqual(loaded.openobserve_username, "admin")
            self.assertNotIn("password", path.read_text(encoding="utf-8"))

    def test_system_summary_skips_diagnostics_unless_requested(self):
        with tempfile.TemporaryDirectory() as directory, patch("pi_bus_time_display.server.command_output", return_value=""), patch("pi_bus_time_display.server.diagnostics_snapshot", return_value={"checked": True}) as diagnostics:
            self.assertNotIn("diagnostics", system_snapshot(Path(directory)))
            self.assertEqual(system_snapshot(Path(directory), include_diagnostics=True)["diagnostics"], {"checked": True})
            diagnostics.assert_called_once_with()

    def test_system_summary_reports_same_boot_reboot_requirement(self):
        with tempfile.TemporaryDirectory() as directory, patch("pi_bus_time_display.server.command_output", return_value=""), patch("pi_bus_time_display.server.current_boot_id", return_value="test-boot"):
            state_dir = Path(directory)
            (state_dir / "reboot-required-boot-id").write_text("test-boot\n", encoding="ascii")
            self.assertTrue(system_snapshot(state_dir)["reboot_required"])

    def test_missing_mode_defaults_to_auto(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(read_display_mode(Path(directory) / "display-mode"), "auto")

    def test_valid_mode_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("bus\n", encoding="utf-8")
            self.assertEqual(read_display_mode(path), "bus")

    def test_sleep_mode_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("sleep\n", encoding="utf-8")
            self.assertEqual(read_display_mode(path), "sleep")

    def test_manual_sleep_is_cleared_when_service_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("sleep\n", encoding="utf-8")
            clear_sleep_mode_on_start(path)
            self.assertEqual(read_display_mode(path), "auto")

    def test_visible_manual_mode_survives_service_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("home\n", encoding="utf-8")
            clear_sleep_mode_on_start(path)
            self.assertEqual(read_display_mode(path), "home")

    def test_home_mode_targets_native_home_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("home\n", encoding="utf-8")
            self.assertEqual(display_target(Config(), path), "/home")

    def test_touchscreen_can_hide_a_configured_service(self):
        state = State(Config(services=("40", "42"), roon_display_name="Nowplay"))
        state.data = {"status": "ok", "services": [{"service": "40"}, {"service": "42"}]}
        state.enabled_services.discard("42")
        self.assertEqual([item["service"] for item in state.snapshot()["services"]], ["40"])
        self.assertEqual(state.snapshot()["roon_display_name"], "Nowplay")

    def test_touchscreen_bus_visibility_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Config(services=("40", "42")), Path(directory))
            state.enabled_services.discard("42")
            state.save_enabled_services()
            restored = State(Config(services=("40", "42")), Path(directory))
            self.assertEqual(restored.enabled_services, {"40"})

    def test_display_brightness_is_clamped_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Config(), Path(directory))
            state.save_display_brightness(3)
            self.assertEqual(state.display_brightness, 10)
            self.assertEqual(State(Config(), Path(directory)).display_brightness, 10)

    def test_netdata_state_comes_from_systemd(self):
        with patch("pi_bus_time_display.server.command_output", side_effect=["loaded", "active"]):
            self.assertEqual(service_state("netdata.service"), "running")
        with patch("pi_bus_time_display.server.command_output", side_effect=["not-found"]):
            self.assertEqual(service_state("netdata.service"), "not_installed")

    def test_netdata_state_uses_openrc_on_alpine(self):
        with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.Path.is_file", return_value=True), patch("pi_bus_time_display.server.command_output", return_value=" * status: started") as command:
            self.assertEqual(service_state("netdata.service"), "running")
            command.assert_called_once_with(["rc-service", "netdata", "status"])
        with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.Path.is_file", return_value=False):
            self.assertEqual(service_state("netdata.service"), "not_installed")

    def test_netdata_snapshot_reports_installed_version_and_cloud_state(self):
        with patch("pi_bus_time_display.server.service_state", return_value="running"), patch("pi_bus_time_display.server.urllib.request.urlopen", side_effect=OSError), patch("pi_bus_time_display.server.command_output", side_effect=["netdata v2.1.0", "Available: Yes\nClaimed: Yes\nClaimed Id: node-123\nOnline: Yes\n"]):
            details = netdata_snapshot()
        self.assertEqual(details["version"], "v2.1.0")
        self.assertEqual(details["cloud_status"], "online")
        self.assertEqual(details["claim_id"], "node-123")

    def test_netdata_snapshot_adopts_live_official_static_agent(self):
        response = unittest.mock.MagicMock(); response.__enter__.return_value = response
        with patch("pi_bus_time_display.server.service_state", return_value="not_installed"), patch("pi_bus_time_display.server.Path.is_file", return_value=True), patch("pi_bus_time_display.server.command_output", return_value="netdata v2.12.0-2-nightly"), patch("pi_bus_time_display.server.urllib.request.urlopen", return_value=response), patch("pi_bus_time_display.server.json.load", return_value={"agent-claimed": True, "online": True, "claimed-id": "static-node"}):
            details = netdata_snapshot()
        self.assertTrue(details["installed"])
        self.assertEqual(details["service"], "running")
        self.assertEqual(details["version"], "v2.12.0-2-nightly")
        self.assertEqual(details["cloud_status"], "online")

    def test_unknown_mode_defaults_to_auto(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("surprise\n", encoding="utf-8")
            self.assertEqual(read_display_mode(path), "auto")

    def test_roon_mode_targets_custom_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("roon\n", encoding="utf-8")
            self.assertEqual(display_target(Config(), path, {"zone": {"state": "playing"}}), "http://127.0.0.1:8766/")

    def test_roon_mode_uses_dark_fallback_when_controller_is_down(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("roon\n", encoding="utf-8")
            self.assertEqual(display_target(Config(), path, None), "/roon-unavailable.html")

    def test_sleep_mode_targets_black_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("sleep\n", encoding="utf-8")
            self.assertEqual(display_target(Config(), path), "/sleep.html")

    def test_overnight_sleep_window_crosses_midnight(self):
        config = Config(sleep_start="23:00", sleep_end="06:00")
        timezone = ZoneInfo("Asia/Singapore")
        self.assertTrue(within_sleep_window(config, datetime(2026, 9, 28, 23, 30, tzinfo=timezone)))
        self.assertTrue(within_sleep_window(config, datetime(2026, 9, 29, 5, 59, tzinfo=timezone)))
        self.assertFalse(within_sleep_window(config, datetime(2026, 9, 29, 6, 0, tzinfo=timezone)))

    def test_auto_sleeps_when_configured_zone_is_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-mode"
            path.write_text("auto\n", encoding="utf-8")
            config = Config(sleep_when_roon_idle=True)
            evening = datetime(2026, 9, 28, 20, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            self.assertEqual(display_target(config, path, {"zone": {"state": "paused"}}, evening), "/sleep.html")
            self.assertEqual(display_target(config, path, {"zone": {"state": "playing"}}, evening), "http://127.0.0.1:8766/")

    def test_touchscreen_update_request_is_atomically_queued(self):
        import json
        with patch.dict(os.environ, {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}), patch("pi_bus_time_display.server.socket.socket") as sock:
            client = sock.return_value.__enter__.return_value
            client.makefile.return_value.readline.return_value = b'{"ok":true}\n'
            self.assertTrue(write_control_request(Path("/unused"), {"action": "netdata_lightweight", "enabled": True}))
            self.assertEqual(json.loads(client.sendall.call_args.args[0]), {"action": "netdata_lightweight", "enabled": True})
            self.assertTrue(write_control_request(Path("/unused"), {"action": "airplay_configure", "name": "Listening Room"}))
            self.assertEqual(json.loads(client.sendall.call_args.args[0]), {"action": "airplay_configure", "name": "Listening Room"})
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            self.assertTrue(write_control_request(state_dir, {"action": "update"}))
            requests = list((state_dir / "system-action-queue").glob("*.json"))
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].read_text(encoding="utf-8"), '{"action": "update"}')
            self.assertTrue((state_dir / "system-action-trigger").read_text(encoding="ascii").strip())
            self.assertFalse(list((state_dir / "system-action-queue").glob("*.tmp")))
            self.assertEqual((state_dir / "update-status").read_text(encoding="utf-8"), "Update · Queued…\n")

    def test_duplicate_update_request_is_not_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            self.assertTrue(write_control_request(state_dir, {"action": "update"}))
            self.assertFalse(write_control_request(state_dir, {"action": "update"}))
            self.assertEqual(len(list((state_dir / "system-action-queue").glob("*.json"))), 1)

    def test_quick_privileged_actions_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            write_control_request(state_dir, {"action": "display_off"})
            write_control_request(state_dir, {"action": "display_on", "brightness": 63})
            requests = sorted((state_dir / "system-action-queue").glob("*.json"))
            self.assertEqual(len(requests), 2)
            self.assertEqual(
                [path.read_text(encoding="utf-8") for path in requests],
                ['{"action": "display_off"}', '{"action": "display_on", "brightness": 63}'],
            )

    def test_playback_temporarily_takes_over_automatic_bus_display(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("auto\n", encoding="utf-8")
            state = State(Config(auto_switch_to_roon=True, roon_idle_return_seconds=300))
            morning = datetime(2026, 9, 29, 8, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1000):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "playing"}}, morning), "http://127.0.0.1:8766/")
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1200):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, morning), "http://127.0.0.1:8766/")
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1400):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, morning), "/")

    def test_active_playback_keeps_automatic_display_on_even_overnight(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("auto\n", encoding="utf-8")
            state = State(Config(auto_switch_to_roon=False))
            overnight = datetime(2026, 9, 29, 1, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "playing"}}, overnight), "http://127.0.0.1:8766/")
            self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, overnight), "/sleep.html")

    def test_temporary_wake_expires_during_sleep_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("auto\n", encoding="utf-8")
            state = State(Config(outside_hours_wake_seconds=600))
            overnight = datetime(2026, 9, 29, 1, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            state.awake_until = 1600
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1200):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, overnight), "/")
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1700):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, overnight), "/sleep.html")

    def test_scheduled_wake_can_be_disabled_but_tap_and_music_still_wake(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"; mode.write_text("auto\n", encoding="utf-8")
            now = datetime(2026, 9, 29, 8, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            state = State(Config(scheduled_wake_enabled=False))
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1200):
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, now), "/sleep.html")
                state.awake_until = 1300
                self.assertEqual(automatic_display_target(state, mode, {"zone": {"state": "paused"}}, now), "/")
            self.assertEqual(automatic_display_target(State(Config(scheduled_wake_enabled=False)), mode, {"zone": {"state": "playing"}}, now), "http://127.0.0.1:8766/")

    def test_weekend_stays_dark_unless_enabled_and_waits_for_weekend_time(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"; mode.write_text("auto\n", encoding="utf-8")
            early = datetime(2026, 10, 24, 8, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            late = datetime(2026, 10, 24, 9, 30, tzinfo=ZoneInfo("Asia/Singapore"))
            self.assertEqual(automatic_display_target(State(Config()), mode, None, late), "/sleep.html")
            config = Config(weekend_wake_enabled=True, weekend_wake_time="09:00")
            self.assertEqual(automatic_display_target(State(config), mode, None, early), "/sleep.html")
            self.assertEqual(automatic_display_target(State(config), mode, None, late), "/")

    def test_manual_view_returns_to_automatic_at_next_schedule_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("home\n", encoding="utf-8")
            state = State(Config(morning_start="07:00", morning_end="09:30", sleep_start="22:00", sleep_end="07:00"))
            state.manual_mode_signature = (mode.stat().st_mtime_ns, "home")
            state.manual_mode_period = "morning"
            morning = datetime(2026, 9, 29, 8, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            daytime = datetime(2026, 9, 29, 9, 30, tzinfo=ZoneInfo("Asia/Singapore"))
            self.assertEqual(automatic_display_target(state, mode, None, morning), "/home")
            self.assertEqual(automatic_display_target(state, mode, None, daytime), "/")
            self.assertEqual(read_display_mode(mode), "auto")

    def test_manual_sleep_returns_to_automatic_at_morning_wake(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("sleep\n", encoding="utf-8")
            state = State(Config(morning_start="07:00", morning_end="09:30", sleep_start="22:00", sleep_end="07:00"))
            state.manual_mode_signature = (mode.stat().st_mtime_ns, "sleep")
            state.manual_mode_period = "sleep"
            morning = datetime(2026, 9, 29, 7, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            self.assertEqual(automatic_display_target(state, mode, None, morning), "/")
            self.assertEqual(read_display_mode(mode), "auto")

    def test_touch_can_temporarily_wake_a_manual_sleep_before_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            mode.write_text("sleep\n", encoding="utf-8")
            state = State(Config(sleep_start="22:00", sleep_end="07:00"))
            state.manual_mode_signature = (mode.stat().st_mtime_ns, "sleep")
            state.manual_mode_period = "sleep"
            state.awake_until = 1600
            overnight = datetime(2026, 9, 29, 1, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1200):
                self.assertEqual(automatic_display_target(state, mode, None, overnight), "/")

    def test_explicit_sleep_cancels_a_temporary_wake(self):
        with tempfile.TemporaryDirectory() as directory:
            mode = Path(directory) / "display-mode"
            state = State(Config(sleep_start="22:00", sleep_end="07:00"))
            state.awake_until = 1600
            set_display_mode(state, mode, "sleep")
            self.assertEqual(state.awake_until, 0.0)
            overnight = datetime(2026, 9, 29, 1, 0, tzinfo=ZoneInfo("Asia/Singapore"))
            with patch("pi_bus_time_display.server.time.monotonic", return_value=1200):
                self.assertEqual(automatic_display_target(state, mode, None, overnight), "/sleep.html")

    def test_wifi_reports_ssid_not_netplan_profile_name(self):
        with patch("pi_bus_time_display.server.command_output", side_effect=["netplan-wlan0-Boogaloo:802-11-wireless", "Boogaloo"]):
            self.assertEqual(active_wifi_ssid(), "Boogaloo")

    def test_connected_wifi_reports_link_metrics(self):
        outputs = [
            "wlan0:wifi:connected:netplan-wlan0-Boogaloo",
            "netplan-wlan0-Boogaloo:802-11-wireless",
            "Boogaloo",
            "2: wlan0 inet 10.12.0.50/24 brd 10.12.0.255 scope global wlan0",
            "yes:72:866 Mbit/s",
        ]
        with patch("pi_bus_time_display.server.command_output", side_effect=outputs):
            details = connected_network_snapshot()
        self.assertEqual(details, {"name": "Boogaloo", "interface": "wlan0", "type": "Wi-Fi", "address": "10.12.0.50/24", "signal": "72%", "speed": "866 Mbit/s"})

    def test_diagnostics_includes_running_airplay(self):
        from pi_bus_time_display.server import diagnostics_snapshot
        output = "24 4096 0.2 /usr/bin/shairport-sync -c /etc/shairport-sync.conf\n"
        with patch("pi_bus_time_display.server.command_output", return_value=output), patch("pi_bus_time_display.server.service_state", return_value="stopped"):
            airplay = next(process for process in diagnostics_snapshot(Config())["processes"] if process["label"] == "AirPlay · Shairport Sync")
        self.assertTrue(airplay["active"])
        self.assertEqual(airplay["pids"], [24])

    def test_home_light_level_uses_brightness_percentage(self):
        with patch("pi_bus_time_display.server.home_assistant_request", return_value=[]) as request:
            home_assistant_set_value(Config(), "light.living_room", 63)
            request.assert_called_once_with(Config(), "/api/services/light/turn_on", {"entity_id": "light.living_room", "brightness_pct": 63})

    def test_home_fan_level_is_clamped(self):
        with patch("pi_bus_time_display.server.home_assistant_request", return_value=[]) as request:
            home_assistant_set_value(Config(), "fan.living_room", 140)
            request.assert_called_once_with(Config(), "/api/services/fan/set_percentage", {"entity_id": "fan.living_room", "percentage": 100})

    def test_home_switch_swipe_sets_explicit_state(self):
        with patch("pi_bus_time_display.server.home_assistant_request", return_value=[]) as request:
            home_assistant_set_state(Config(), "switch.pi_hole", False)
            request.assert_called_once_with(Config(), "/api/services/switch/turn_off", {"entity_id": "switch.pi_hole"})

    def test_home_scene_uses_momentary_turn_on_service(self):
        with patch("pi_bus_time_display.server.home_assistant_request", return_value=[]) as request:
            home_assistant_activate(Config(), "scene.bedroom_energize")
            request.assert_called_once_with(Config(), "/api/services/scene/turn_on", {"entity_id": "scene.bedroom_energize"})
        with self.assertRaisesRegex(ValueError, "not a scene"):
            home_assistant_activate(Config(), "switch.bedroom")

    def test_unactivated_home_scene_remains_available(self):
        self.assertTrue(home_assistant_entity_available("scene", "unknown"))
        self.assertTrue(home_assistant_entity_available("scene", "2026-10-23T00:15:00+00:00"))
        self.assertFalse(home_assistant_entity_available("scene", "unavailable"))
        self.assertFalse(home_assistant_entity_available("light", "unknown"))


if __name__ == "__main__":
    unittest.main()
