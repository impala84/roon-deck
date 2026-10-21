import importlib.util
import io
import fcntl
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alpine_setup", ROOT / "appliance/alpine/setup_service.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class AlpineSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / "etc/pi-home"; config.mkdir(parents=True)
        (config / "config.toml").write_text((ROOT / "config.example.toml").read_text())
        (config / "secrets.env").write_text("ADMIN_PASSWORD=old\nADMIN_USERNAME=admin\n")
        boot = self.root / "boot"; (boot / "overlays").mkdir(parents=True)
        (boot / "config.txt").write_text("arm_64bit=1\ndisplay_auto_detect=1\nkernel=vmlinuz-rpi\n")
        for overlay in module.PROFILES.values():
            if overlay: (boot / "overlays" / (overlay + ".dtbo")).touch()
        self.run = Mock(return_value="connected")
        self.login_credentials = Mock()
        self.setup = module.Setup(self.root, self.run, lambda: {"zones": [{"name": "Lounge"}]}, self.login_credentials)

    def test_full_setup_persists_password_and_does_not_play_audio(self):
        self.setup.handle({"action": "name", "hostname": "Pi-Home-Lounge"})
        self.setup.handle({"action": "network"})
        self.setup.handle({"action": "roon", "zone": "Lounge"})
        self.setup.handle({"action": "display", "profile": "touch2-10", "rotation": "90", "timezone": "Europe/London", "theme": "roon"})
        self.setup.handle({"action": "finish", "password": "my-private-password", "confirmation": "my-private-password"})
        self.assertTrue(self.setup.saved()["complete"])
        self.assertEqual((self.root / "etc/hostname").read_text(), "pi-home-lounge\n")
        config = (self.root / "etc/pi-home/config.toml").read_text()
        self.assertIn('roon_zone_name = "Lounge"', config); self.assertIn('timezone = "Europe/London"', config)
        boot = (self.root / "boot/config.txt").read_text()
        self.assertIn("ili79600-10-1inch\n", boot); self.assertNotIn("swapxy", boot); self.assertIn("kernel=vmlinuz-rpi", boot)
        self.assertNotIn("password", self.setup.progress.read_text())
        env = self.root / "etc/pi-home/secrets.env"
        self.assertIn("ADMIN_PASSWORD=my-private-password", env.read_text()); self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run.call_args.args[0], ["rc-service", "pi-home-api", "restart"])
        self.login_credentials.assert_called_once_with("admin", "my-private-password", self.root, self.run)

    def test_invalid_names_never_execute_commands(self):
        for name in ("-bad", "bad-", "x;reboot", "a b", "../root", "x\n", "x" * 64):
            with self.assertRaises(ValueError): self.setup.handle({"action": "name", "hostname": name})
        self.run.assert_not_called()

    def test_completed_device_can_change_wifi_and_name_but_not_wizard(self):
        self.setup.save({"complete": True})
        self.setup.handle({"action": "set_wifi", "ssid": "Living Room", "password": "private-password"})
        self.run.assert_any_call(["nmcli", "--wait", "30", "device", "wifi", "connect", "Living Room", "password", "private-password"])
        self.setup.handle({"action": "set_hostname", "hostname": "pi-home-lounge"})
        self.assertTrue(self.setup.saved()["complete"])
        self.assertNotIn("private-password", self.setup.progress.read_text())
        with self.assertRaisesRegex(ValueError, "already complete"):
            self.setup.handle({"action": "display", "profile": "touch2-10", "rotation": "90"})

    def test_optional_software_skip_is_persisted_without_installing(self):
        self.setup.save({"network": True})
        result = self.setup.handle({"action": "software", "roon_bridge": False, "netdata": False})
        self.assertTrue(result["progress"]["software"])
        self.run.assert_not_called()

    def test_optional_software_cannot_finish_setup_while_installing(self):
        self.setup.save({"network": True})
        with patch.object(module.threading, "Thread"):
            self.setup.handle({"action": "software", "roon_bridge": True, "netdata": False})
        with self.assertRaisesRegex(ValueError, "Wait for"):
            self.setup.handle({"action": "finish"})
        self.assertFalse(self.setup.saved().get("complete", False))

    def test_failed_optional_install_can_be_retried(self):
        self.setup.save({"network": True})
        choices = {"roon_bridge": True, "netdata": False}
        self.setup.software_lock.acquire()
        def failure():
            path = self.root / "var/lib/pi-home/roonbridge-install-status"
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text("Failed: download failed")
            self.setup.roon_install_lock.release()
        with patch.object(self.setup, "install_roon_bridge", side_effect=failure):
            self.setup.install_setup_software(choices)
        self.assertFalse(self.setup.saved()["software"])
        self.assertFalse(self.setup.software_lock.locked())
        self.assertNotIn("complete", self.setup.saved())

    def test_password_minimum_is_eight_characters(self):
        module.validate_password("abcdefgh")
        with self.assertRaisesRegex(ValueError, "8–128"):
            module.validate_password("abcdefg")

    def test_tools_install_is_fixed_and_requires_completed_setup(self):
        with self.assertRaises(ValueError): self.setup.handle({"action": "install_tools"})
        self.setup.save({"complete": True})
        (self.root / "var/lib/pi-home").mkdir(parents=True, exist_ok=True)
        (self.root / "usr/local/bin").mkdir(parents=True, exist_ok=True)
        with patch.object(module.threading, "Thread") as thread:
            self.assertTrue(self.setup.handle({"action": "install_tools", "packages": ["untrusted"]})["queued"])
            self.assertFalse(self.setup.handle({"action": "install_tools"})["queued"])
            thread.assert_called_once()
        with patch.object(module.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.setup.install_tools()
            self.assertEqual(run.call_args.args[0], ["apk", "add", "--no-cache", "grim", "procps", "curl", "ca-certificates", "chrony", "chrony-openrc"])
        self.assertIn("installed", (self.root / "var/lib/pi-home/tools-status").read_text())
        self.assertFalse(self.setup.tools_lock.locked())

    def test_tools_install_failure_is_visible_and_retryable(self):
        (self.root / "var/lib/pi-home").mkdir(parents=True, exist_ok=True)
        self.setup.tools_lock.acquire()
        with patch.object(module.subprocess, "run", return_value=Mock(returncode=1)):
            self.setup.install_tools()
        self.assertIn("failed", (self.root / "var/lib/pi-home/tools-status").read_text())
        self.assertFalse(self.setup.tools_lock.locked())

    def test_transparent_cursor_theme_file(self):
        import struct
        spec = importlib.util.spec_from_file_location("cursor_theme", ROOT / "appliance/alpine/cursor_theme.py")
        cursor = importlib.util.module_from_spec(spec); spec.loader.exec_module(cursor)
        theme = cursor.prepare(self.root / "cursors")
        data = (theme / "cursors/left_ptr").read_bytes()
        self.assertEqual(struct.unpack("<4I", data[:16]), (0x72756358, 16, 0x10000, 1))
        self.assertEqual(len(data), 68)
        self.assertEqual(data[-4:], b"\0\0\0\0")

    def test_version_label_identifies_alpine_only(self):
        from pi_bus_time_display import server, __version__
        with patch.dict("os.environ", {"PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype"}):
            self.assertEqual(server.display_version(), __version__ + " Alpine")
        with patch.dict("os.environ", {"PI_HOME_APPLIANCE_PLATFORM": ""}):
            self.assertEqual(server.display_version(), __version__)

    def test_incomplete_and_invalid_finishes_are_rejected(self):
        with self.assertRaises(ValueError): self.setup.handle({"action": "finish", "password": "valid-password"})
        self.assertFalse(self.setup.progress.exists())

    def test_failed_wifi_does_not_save_network_or_password(self):
        self.run.side_effect = ValueError("Connection failed")
        with self.assertRaises(ValueError): self.setup.handle({"action": "wifi", "ssid": "Home", "password": "secret"})
        self.assertFalse(self.setup.progress.exists())

    def test_failed_api_restart_leaves_finish_retryable(self):
        self.setup.save({"hostname": "pi-home", "network": True, "roon": True, "display": True})
        self.run.side_effect = ValueError("Service restart failed")
        with self.assertRaises(ValueError):
            self.setup.handle({"action": "finish", "password": "valid-password", "confirmation": "valid-password"})
        self.assertFalse(self.setup.saved().get("complete", False))
        self.run.side_effect = None
        self.setup.handle({"action": "finish", "password": "valid-password", "confirmation": "valid-password"})
        self.assertTrue(self.setup.saved()["complete"])

    def test_wifi_uses_argument_list_not_shell_and_keeps_secrets_out_of_progress(self):
        self.run.side_effect = lambda args: "Home\n" if "GENERAL.CONNECTION" in args else "connected"
        self.setup.handle({"action": "wifi", "ssid": "Home;not-a-command", "password": "private-secret"})
        self.assertEqual(self.run.call_args_list[0].args[0][-3:], ["Home;not-a-command", "password", "private-secret"])
        self.run.assert_any_call(["nmcli", "connection", "modify", "Home", "802-11-wireless.powersave", "2"])
        self.assertNotIn("private-secret", self.setup.progress.read_text())

    def test_display_block_is_idempotent_and_preserves_kernel(self):
        for rotation in ("90", "270"):
            self.setup.handle({"action": "display", "profile": "touch2-7", "rotation": rotation})
        text = (self.root / "boot/config.txt").read_text()
        self.assertEqual(text.count("# BEGIN PI HOME SETUP"), 1); self.assertNotIn("swapxy", text)
        self.assertIn("kernel=vmlinuz-rpi", text)

    def test_invalid_zone_rotation_and_timezone_are_rejected(self):
        with self.assertRaises(ValueError): self.setup.handle({"action": "roon", "zone": "Missing"})
        with self.assertRaises(ValueError): self.setup.handle({"action": "display", "profile": "original", "rotation": "upsideways"})
        with self.assertRaises(ValueError): self.setup.handle({"action": "display", "profile": "auto", "rotation": "normal", "timezone": "../etc/shadow"})

    def test_original_display_accepts_180_degree_rotation_in_wizard(self):
        result = self.setup.handle({"action": "orientation", "profile": "original", "rotation": "180"})
        self.assertTrue(result["progress"]["orientation"])
        self.assertEqual(result["progress"]["profile"], "original")
        self.assertEqual(result["progress"]["rotation"], "180")
        self.assertEqual(result["progress"]["display_orientation"], "landscape")
        config = self.root / "etc/pi-home"
        self.assertEqual((config / "display-profile").read_text(), "original")
        self.assertEqual((config / "display-transform").read_text(), "180")
        self.assertEqual((config / "display-orientation").read_text(), "landscape")

    def test_resume_and_completed_lock(self):
        self.setup.handle({"action": "name", "hostname": "pi-home"})
        resumed = module.Setup(self.root, self.run, lambda: {"zones": []})
        self.assertEqual(resumed.saved()["hostname"], "pi-home")
        self.setup.save({"complete": True})
        with self.assertRaises(ValueError): self.setup.handle({"action": "name", "hostname": "other"})
        self.assertTrue(self.setup.handle({"action": "status"})["progress"]["complete"])

    def test_symlink_read_is_refused(self):
        target = self.root / "outside"; target.write_text("secret")
        link = self.root / "link"; link.symlink_to(target)
        with self.assertRaises(OSError): module.read(link)

    def test_confirmation_and_ambiguous_passwords_are_rejected_before_changes(self):
        self.setup.save({"hostname": "pi-home", "network": True, "roon": True, "display": True})
        before = (self.root / "etc/pi-home/secrets.env").read_text()
        for password, confirmation in (("valid-password", "different-password"), (" valid-password", " valid-password"), ('"valid-password"', '"valid-password"')):
            with self.assertRaises(ValueError): self.setup.handle({"action": "finish", "password": password, "confirmation": confirmation})
        self.assertEqual(before, (self.root / "etc/pi-home/secrets.env").read_text())
        self.login_credentials.assert_not_called()

    def test_ssh_can_be_disabled_explicitly(self):
        self.setup.save({"hostname": "pi-home", "network": True, "roon": True, "display": True})
        self.setup.handle({"action": "finish", "password": "valid-password", "confirmation": "valid-password", "ssh": False})
        self.assertFalse(self.setup.saved()["ssh"])
        self.assertIn(unittest.mock.call(["rc-update", "del", "sshd", "default"]), self.run.call_args_list)

    def test_ssh_password_is_stdin_not_process_arguments(self):
        etc = self.root / "etc"; etc.mkdir(exist_ok=True)
        (etc / "passwd").write_text("admin:x:1000:1000::/home/admin:/bin/ash\n")
        (etc / "ssh/sshd_config.d").mkdir(parents=True)
        with patch.object(module.subprocess, "run", return_value=Mock(returncode=0)) as run:
            module.set_login_credentials("admin", "safe-private-password", self.root, self.run)
        self.assertEqual(run.call_args.args[0], ["chpasswd"])
        self.assertEqual(run.call_args.kwargs["input"], "admin:safe-private-password\n")
        self.assertIs(run.call_args.kwargs["stdout"], module.subprocess.DEVNULL)
        self.assertNotIn("safe-private-password", " ".join(run.call_args.args[0]))

    def test_custom_device_username_and_simple_password_are_allowed(self):
        self.setup.save({"hostname": "pi-home", "network": True, "roon": True, "display": True})
        self.setup.handle({"action": "finish", "username": "philip", "password": "12345678", "confirmation": "12345678"})
        self.login_credentials.assert_called_once_with("philip", "12345678", self.root, self.run)
        self.assertEqual(self.setup.saved()["username"], "philip")
        self.assertNotIn("12345678", self.setup.progress.read_text())

    def test_changing_device_username_locks_the_previous_local_account(self):
        self.setup.save({"complete": True, "username": "admin"})
        self.setup.handle({"action": "device_credentials", "username": "philip", "password": "12345678", "confirmation": "12345678"})
        self.login_credentials.assert_called_once_with("philip", "12345678", self.root, self.run)
        self.assertIn(unittest.mock.call(["passwd", "-l", "admin"]), self.run.call_args_list)
        self.assertEqual(self.setup.saved()["username"], "philip")

    def test_netdata_cloud_claim_writes_private_config_and_restarts_only_agent(self):
        self.setup.save({"complete": True})
        service = self.root / "etc/init.d/netdata"; service.parent.mkdir(parents=True); service.touch()
        self.setup.handle({"action": "netdata_claim", "token": "private-token", "rooms": "room-1234"})
        claim = self.root / "etc/netdata/claim.conf"
        self.assertIn("rooms = room-1234", claim.read_text())
        self.assertEqual(claim.stat().st_mode & 0o777, 0o640)
        self.assertNotIn("private-token", self.setup.progress.read_text())
        self.assertEqual(self.run.call_args.args[0], ["rc-service", "netdata", "start"])

    def test_netdata_claim_installs_missing_helper_dependencies_before_stopping_agent(self):
        self.setup.save({"complete": True})
        service = self.root / "etc/init.d/netdata"; service.parent.mkdir(parents=True); service.touch()
        wget = self.root / "usr/bin/wget"; wget.parent.mkdir(parents=True); wget.touch()
        with patch.object(module, "run_netdata_claim_helper", return_value=True):
            self.setup.handle({"action": "netdata_claim", "token": "private-token", "rooms": "room-1234"})
        calls = [call.args[0] for call in self.run.call_args_list]
        self.assertIn(["apk", "add", "--no-cache", "openssl"], calls)
        self.assertLess(calls.index(["apk", "add", "--no-cache", "openssl"]), calls.index(["rc-service", "netdata", "stop"]))

    def test_installed_netdata_claim_helper_receives_only_validated_values(self):
        helper = self.root / "usr/sbin/netdata-claim.sh"; helper.parent.mkdir(parents=True); helper.touch()
        completed = Mock(returncode=0)
        with patch.object(module.subprocess, "run", return_value=completed) as run:
            self.assertTrue(module.run_netdata_claim_helper(self.root, "private-token", "room-1234"))
        self.assertEqual(run.call_args.args[0], [str(helper), "-token=private-token", "-url=https://app.netdata.cloud", "-daemon-not-running", "-rooms=room-1234"])
        self.assertIs(run.call_args.kwargs["stdout"], module.subprocess.DEVNULL)

    def test_duplicate_netdata_identity_retries_once_with_fresh_node_id(self):
        helper = self.root / "usr/sbin/netdata-claim.sh"; helper.parent.mkdir(parents=True); helper.touch()
        with patch.object(module.subprocess, "run", side_effect=[Mock(returncode=13), Mock(returncode=0)]) as run, patch.object(module.uuid, "uuid4", return_value="fresh-node-id"):
            self.assertTrue(module.run_netdata_claim_helper(self.root, "private-token", "room-1234"))
        self.assertEqual(run.call_count, 2)
        self.assertIn("-id=fresh-node-id", run.call_args.args[0])

    def test_netdata_claim_reports_expired_token_accurately(self):
        helper = self.root / "usr/sbin/netdata-claim.sh"; helper.parent.mkdir(parents=True); helper.touch()
        with patch.object(module.subprocess, "run", return_value=Mock(returncode=12)):
            with self.assertRaisesRegex(ValueError, "expired or invalid"):
                module.run_netdata_claim_helper(self.root, "private-token", "room-1234")

    def test_cloud_generated_command_is_parsed_but_never_executed(self):
        command = "bash <(curl -Ss https://get.netdata.cloud/kickstart.sh) --stable-channel --claim-token 'private-token' --claim-rooms room-1234,room-5678 --claim-url https://app.netdata.cloud"
        self.assertEqual(module.parse_netdata_connection_command(command), ("private-token", "room-1234,room-5678", "https://app.netdata.cloud"))
        self.setup.save({"complete": True})
        service = self.root / "etc/init.d/netdata"; service.parent.mkdir(parents=True); service.touch()
        self.setup.handle({"action": "netdata_claim_command", "command": command})
        claim = self.root / "etc/netdata/claim.conf"
        self.assertIn("token = private-token", claim.read_text())
        self.assertIn("rooms = room-1234,room-5678", claim.read_text())
        self.assertNotIn("private-token", self.setup.progress.read_text())

    def test_cloud_command_rejects_non_netdata_script_or_non_cloud_url(self):
        with self.assertRaisesRegex(ValueError, "official Netdata"):
            module.parse_netdata_connection_command("bash <(curl -Ss https://example.com/script) --claim-token private-token")
        with self.assertRaisesRegex(ValueError, "official Netdata Cloud"):
            module.parse_netdata_connection_command("bash <(curl -Ss https://get.netdata.cloud/kickstart.sh) --claim-token private-token --claim-url https://example.com")

    def test_official_agent_install_is_explicit_async_and_does_not_execute_pasted_shell(self):
        self.setup.save({"complete": True})
        command = "wget -qO- https://get.netdata.cloud/kickstart.sh | sh -s -- --claim-token private-token --claim-rooms room-1234"
        with patch.object(module.threading, "Thread") as thread:
            result = self.setup.handle({"action": "netdata_official_install", "command": command})
        self.assertTrue(result["queued"])
        thread.assert_called_once_with(target=self.setup.install_official_netdata, args=("private-token", "room-1234", "https://app.netdata.cloud"), daemon=True)
        thread.return_value.start.assert_called_once()
        self.run.assert_any_call(["apk", "add", "--no-cache", "curl", "ca-certificates"])
        self.assertNotIn("private-token", (self.root / "var/lib/pi-home/netdata-operation-status").read_text())

    def test_official_agent_can_be_installed_without_cloud_credentials(self):
        self.setup.save({"complete": True})
        with patch.object(module.threading, "Thread") as thread:
            result = self.setup.handle({"action": "netdata_install"})
        self.assertTrue(result["queued"])
        thread.assert_called_once_with(target=self.setup.install_official_netdata, args=("", "", "https://app.netdata.cloud"), daemon=True)
        thread.return_value.start.assert_called_once()

    def test_official_agent_replaces_packaged_agent_and_uses_current_stable_flags(self):
        packaged = self.root / "usr/sbin/netdata"; packaged.parent.mkdir(parents=True); packaged.touch()
        (self.root / "var/lib/pi-home").mkdir(parents=True)
        self.setup.netdata_install_lock.acquire()
        with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(b"#!/bin/sh\n")), patch.object(module.subprocess, "run", return_value=Mock(returncode=1)) as run:
            self.setup.install_official_netdata("private-token", "room-1234")
        calls = [call.args[0] for call in self.run.call_args_list]
        self.assertIn(["apk", "del", "netdata"], calls)
        self.assertIn(["apk", "add", "--no-cache", "netdata"], calls)
        installer = next(call.args[0] for call in run.call_args_list if call.args[0][0] == "/bin/bash")
        self.assertIn("--release-channel", installer)
        self.assertEqual(installer[installer.index("--release-channel") + 1], "stable")
        self.assertNotIn("--stable-channel", installer)

    def test_official_agent_explicit_upgrade_reinstalls_static_agent(self):
        static = self.root / "opt/netdata/bin/netdata"; static.parent.mkdir(parents=True); static.touch()
        (self.root / "var/lib/pi-home").mkdir(parents=True)
        self.setup.netdata_install_lock.acquire()
        with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(b"#!/bin/sh\n")), patch.object(module.subprocess, "run", return_value=Mock(returncode=1)) as run:
            self.setup.install_official_netdata()
        installer = next(call.args[0] for call in run.call_args_list if call.args[0][0] == "/bin/bash")
        self.assertIn("--reinstall", installer)
        self.assertNotIn(["apk", "del", "netdata"], [call.args[0] for call in self.run.call_args_list])

    def test_netdata_lightweight_preserves_other_settings_and_is_idempotent(self):
        agent = self.root / "opt/netdata/bin/netdata"; agent.parent.mkdir(parents=True); agent.touch()
        config = self.root / "opt/netdata/etc/netdata/netdata.conf"; config.parent.mkdir(parents=True)
        original = "[ml]\n    enabled = yes\n[db]\n    update every = 1\n    db = dbengine\n[web]\n    bind to = localhost\n"
        config.write_text(original)
        module.configure_netdata_lightweight(self.root, True)
        first = config.read_text()
        module.configure_netdata_lightweight(self.root, True)
        self.assertEqual(first, config.read_text())
        self.assertIn("enabled = no", first)
        self.assertIn("update every = 3", first)
        self.assertIn("db = dbengine", first)
        self.assertIn("bind to = localhost", first)
        for plugin in ("netflow", "otel", "scripts.d", "nfacct", "network-viewer", "debugfs"):
            self.assertIn(plugin + " = no", first)
        self.assertIn("apps = yes", first)
        self.assertIn("go.d = yes", first)
        self.assertEqual(config.with_name("netdata.conf.pi-home-backup").read_text(), original)
        module.configure_netdata_lightweight(self.root, False)
        self.assertIn("enabled = auto", config.read_text())
        self.assertIn("update every = 1", config.read_text())
        self.assertNotIn("netflow =", config.read_text())
        with self.assertRaises(ValueError): module.configure_netdata_lightweight(self.root, "yes")

    def test_update_requires_completed_setup_and_uses_fixed_updater(self):
        with patch.object(module.subprocess, "Popen") as spawn:
            with self.assertRaises(ValueError): self.setup.handle({"action": "update"})
            spawn.assert_not_called()
            (self.root / "var/lib/pi-home").mkdir()
            self.setup.save({"complete": True})
            self.assertTrue(self.setup.handle({"action": "update"})["queued"])
            self.assertEqual(spawn.call_args.args[0], ["/usr/bin/python3", "/opt/pi-home/appliance/alpine/updater.py"])

    def test_repeated_update_tap_does_not_spawn_overlapping_updater(self):
        (self.root / "var/lib/pi-home").mkdir()
        self.setup.save({"complete": True})
        process = Mock(); process.poll.return_value = None
        with patch.object(module.subprocess, "Popen", return_value=process) as spawn:
            self.assertTrue(self.setup.handle({"action": "update"})["queued"])
            self.assertFalse(self.setup.handle({"action": "update"})["queued"])
            spawn.assert_called_once()

    def test_update_lock_survives_setup_helper_restart(self):
        (self.root / "var/lib/pi-home").mkdir()
        self.setup.save({"complete": True})
        path = self.root / "run/pi-home-update.lock"; path.parent.mkdir()
        with path.open("a") as lock, patch.object(module.subprocess, "Popen") as spawn:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(self.setup.handle({"action": "update"})["queued"])
            spawn.assert_not_called()

    def test_clock_support_migrates_existing_image_and_seeds_valid_time(self):
        source = ROOT / "appliance/alpine/init.d/pi-home-clock"
        chrony = self.root / "etc/chrony/chrony.conf"; chrony.parent.mkdir(parents=True)
        chrony.write_text("pool pool.ntp.org\nmakestep 1.0 3\n")
        hwclock = self.root / "etc/runlevels/boot/hwclock"; hwclock.parent.mkdir(parents=True)
        hwclock.symlink_to("/etc/init.d/hwclock")
        module.install_clock_support(self.root, self.run, now=1800000000)
        service = self.root / "etc/init.d/pi-home-clock"
        self.assertEqual(service.read_bytes(), source.read_bytes())
        self.assertEqual(service.stat().st_mode & 0o777, 0o755)
        self.assertFalse(hwclock.exists())
        self.assertEqual(self.run.call_args.args[0], ["rc-update", "add", "pi-home-clock", "boot"])
        self.assertEqual(chrony.read_text(), "pool pool.ntp.org iburst\nmakestep 0.1 -1\n")
        self.assertEqual((self.root / "var/lib/pi-home/clock-seed").read_text(), "1800000000\n")

    def test_daily_update_check_is_installed_once_at_three_am(self):
        path = self.root / "etc/crontabs/root"
        path.parent.mkdir(parents=True)
        path.write_text("15 2 * * * existing-job\n")
        module.ensure_daily_update_check(self.root)
        module.ensure_daily_update_check(self.root)
        self.assertEqual(path.read_text().splitlines(), ["15 2 * * * existing-job", module.UPDATE_CHECK_CRON])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_netdata_controls_require_setup_and_use_only_fixed_openrc_commands(self):
        with self.assertRaises(ValueError): self.setup.handle({"action": "netdata_enable"})
        self.setup.save({"complete": True})
        with self.assertRaisesRegex(ValueError, "not installed"): self.setup.handle({"action": "netdata_enable"})
        agent = self.root / "usr/sbin/netdata"; agent.parent.mkdir(parents=True); agent.touch()
        service = self.root / "etc/init.d/netdata"; service.parent.mkdir(parents=True); service.touch()
        self.setup.handle({"action": "netdata_enable"})
        self.assertEqual(self.run.call_args.args[0], ["rc-service", "netdata", "start"])
        self.setup.handle({"action": "netdata_disable"})
        self.assertEqual(self.run.call_args.args[0], ["rc-update", "del", "netdata", "default"])

    def test_official_static_netdata_gets_a_managed_openrc_service(self):
        agent = self.root / "opt/netdata/bin/netdata"; agent.parent.mkdir(parents=True); agent.touch()
        service = module.ensure_netdata_service(self.root)
        self.assertIn("command=/opt/netdata/bin/netdata", service.read_text())
        self.assertIn('command_args="-D"', service.read_text())
        self.assertEqual(service.stat().st_mode & 0o777, 0o755)

    def test_roon_bridge_controls_create_and_use_only_the_openrc_service(self):
        self.setup.save({"complete": True})
        start = self.root / "opt/RoonBridge/start.sh"; start.parent.mkdir(parents=True); start.touch()
        self.setup.handle({"action": "roon_start"})
        service = self.root / "etc/init.d/roonbridge"
        self.assertTrue(service.is_file())
        self.assertIn("command=/opt/RoonBridge/start.sh", service.read_text())
        self.assertEqual(service.stat().st_mode & 0o777, 0o755)
        self.run.assert_any_call(["rc-update", "add", "roonbridge", "default"])
        self.run.assert_any_call(["rc-service", "roonbridge", "start"])
        self.setup.handle({"action": "roon_restart"})
        self.run.assert_any_call(["rc-service", "roonbridge", "restart"])

    def test_roon_bridge_start_reports_when_the_official_files_are_absent(self):
        self.setup.save({"complete": True})
        with self.assertRaisesRegex(ValueError, "not installed"):
            self.setup.handle({"action": "roon_start"})

    def test_official_roon_bridge_payload_is_validated_and_installed_for_openrc(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:bz2") as package:
            for name in ("RoonBridge/start.sh", "RoonBridge/check.sh", "RoonBridge/Bridge/RoonBridge.exe"):
                data = b"#!/bin/sh\nexit 0\n" if name.endswith(".sh") else b"ELF"
                member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o755
                package.addfile(member, io.BytesIO(data))
        response = io.BytesIO(payload.getvalue())
        status = self.root / "var/lib/pi-home"; status.mkdir(parents=True)
        self.setup.roon_install_lock.acquire()
        with patch.object(module.platform, "machine", return_value="aarch64"), patch.object(module.urllib.request, "urlopen", return_value=response):
            self.setup.install_roon_bridge()
        self.assertTrue((self.root / "opt/RoonBridge/start.sh").is_file())
        self.assertIn("command=/opt/RoonBridge/start.sh", (self.root / "etc/init.d/roonbridge").read_text())
        self.run.assert_any_call(["apk", "add", "--no-cache", "gcompat", "libstdc++", "icu-libs", "alsa-lib", "bzip2"])
        self.run.assert_any_call(["rc-service", "roonbridge", "start"])
        self.assertIn("installed and running", (status / "roonbridge-install-status").read_text())

    def test_roon_bridge_install_is_explicit_and_non_overlapping(self):
        self.setup.save({"complete": True})
        with patch.object(module.threading, "Thread") as thread:
            self.assertTrue(self.setup.handle({"action": "roon_install"})["queued"])
            self.assertFalse(self.setup.handle({"action": "roon_install"})["queued"])
        thread.assert_called_once()

    def test_airplay_install_uses_alpine_package_and_managed_configuration(self):
        binary = self.root / "usr/bin/shairport-sync"
        binary.parent.mkdir(parents=True)
        self.setup.airplay_install_lock.acquire()
        def install_packages(arguments):
            self.run(arguments)
            binary.touch()
        with patch.object(self.setup, "run", side_effect=install_packages) as run:
            self.setup.install_airplay()
        run.assert_any_call(["apk", "add", "--no-cache", "shairport-sync", "shairport-sync-openrc"])
        run.assert_any_call(["rc-update", "add", "shairport-sync", "default"])
        run.assert_any_call(["rc-service", "shairport-sync", "start"])
        configuration = (self.root / "etc/shairport-sync.conf").read_text()
        self.assertIn('name = "RoonDeck"', configuration)
        self.assertIn('output_backend = "alsa"', configuration)

    def test_airplay_name_is_validated_and_restart_is_bounded(self):
        self.setup.save({"complete": True})
        binary = self.root / "usr/bin/shairport-sync"; binary.parent.mkdir(parents=True); binary.touch()
        result = self.setup.handle({"action": "airplay_configure", "name": "Listening Room"})
        self.assertEqual(result["name"], "Listening Room")
        self.run.assert_called_with(["rc-service", "shairport-sync", "restart"])
        with self.assertRaisesRegex(ValueError, "1–50"):
            self.setup.handle({"action": "airplay_configure", "name": 'bad"name'})

    def test_airplay_controls_require_an_installed_receiver(self):
        self.setup.save({"complete": True})
        with self.assertRaisesRegex(ValueError, "not installed"):
            self.setup.handle({"action": "airplay_start"})

    def test_sleep_extinguishes_backlight_and_wake_restores_saved_brightness(self):
        backlight = self.root / "sys/class/backlight/rpi_backlight"; backlight.mkdir(parents=True)
        (backlight / "brightness").write_text("255"); (backlight / "max_brightness").write_text("255"); (backlight / "bl_power").write_text("0")
        self.setup.save({"complete": True})
        self.setup.handle({"action": "display_off"})
        self.assertEqual((backlight / "brightness").read_text(), "0")
        self.assertEqual((backlight / "bl_power").read_text(), "0")
        self.setup.handle({"action": "display_on", "brightness": 63})
        self.assertEqual((backlight / "brightness").read_text(), "161")
        self.assertEqual((backlight / "bl_power").read_text(), "0")
        with self.assertRaisesRegex(ValueError, "between 10 and 100"):
            self.setup.handle({"action": "set_brightness", "brightness": 0})

    def test_dsi_orientation_only_selects_current_dsi_mode(self):
        spec = importlib.util.spec_from_file_location("orientation", ROOT / "appliance/alpine/setup_orientation.py")
        orientation = importlib.util.module_from_spec(spec); spec.loader.exec_module(orientation)
        self.assertEqual(orientation.choose_output('HDMI-A-1 "HDMI"\n  1920x1080 px, 60 Hz (current)\nDSI-1 "DSI"\n  720x1280 px, 60 Hz (preferred, current)\n'), ("DSI-1", True))
        self.assertEqual(orientation.choose_output('HDMI-A-1 "HDMI"\n  720x1280 px, 60 Hz (current)\n'), (None, False))
        with patch.object(orientation.Path, "exists", return_value=False), patch.object(orientation.subprocess, "run", return_value=Mock(stdout='DSI-1 "DSI"\n  720x1280 px, 60 Hz (current)\n')) as run:
            orientation.main()
        self.assertEqual(run.call_args.args[0], ["wlr-randr", "--output", "DSI-1", "--transform", "normal"])

    def test_touch_mapping_is_scoped_to_goodix_and_one_connected_dsi(self):
        import sys
        spec = importlib.util.spec_from_file_location("input_mapping", ROOT / "appliance/alpine/input_mapping.py")
        mapping = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"setup_service": module}): spec.loader.exec_module(mapping)
        drm = self.root / "sys/class/drm"; drm.mkdir(parents=True)
        for name, status in (("card1-DSI-1", "connected"), ("card1-HDMI-A-1", "connected"), ("card2-DSI-2", "disconnected")):
            connector = drm / name; connector.mkdir(); (connector / "status").write_text(status)
        self.assertEqual(mapping.connected_output(self.root), "DSI-1")
        rule = mapping.mapping_rule("DSI-1")
        self.assertIn('ATTRS{name}=="*Goodix Capacitive TouchScreen"', rule)
        self.assertIn('ENV{WL_OUTPUT}=""', rule)
        self.assertIn('LIBINPUT_CALIBRATION_MATRIX}="1 0 0 0 1 0"', rule)
        self.assertIn('LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"', mapping.mapping_rule("DSI-1", "90"))
        import fnmatch
        for rotation, matrix in mapping.MATRICES.items():
            rule10 = mapping.mapping_rule("DSI-1", rotation, "touch2-10")
            self.assertIn('ATTRS{name}=="* ili_v3"', rule10)
            self.assertTrue(fnmatch.fnmatch("10-0041 ili_v3", "* ili_v3"))
            self.assertIn(f'LIBINPUT_CALIBRATION_MATRIX}}="{matrix}"', rule10)
            self.assertIn('ENV{WL_OUTPUT}=""', rule10)
        self.assertNotIn("ili_v3", mapping.mapping_rule("DSI-1", "90", "touch2-7"))
        for rotation in mapping.MATRICES:
            values = [float(v) for v in mapping.MATRICES[rotation].split()]
            for x, y in ((0, 0), (0, 1), (1, 0), (1, 1)):
                result = (values[0]*x + values[1]*y + values[2], values[3]*x + values[4]*y + values[5])
                expected = {"normal": (x, y), "90": (y, 1-x), "180": (1-x, 1-y), "270": (1-y, x)}[rotation]
                self.assertEqual(result, expected)
        runner = Mock(return_value=Mock(returncode=0))
        self.assertFalse(mapping.recover_touch(self.root, runner, lambda _: None))
        runner.assert_not_called()
        node = self.root / "sys/bus/i2c/devices/10-005d/of_node"; node.mkdir(parents=True)
        (node / "compatible").write_bytes(b"goodix,gt911\0")
        name = self.root / "sys/class/input/event4/device/name"
        def recovered(args, **kwargs):
            if args == ["modprobe", "goodix_ts"]:
                name.parent.mkdir(parents=True); name.write_text("10-005d Goodix Capacitive TouchScreen\n")
            return Mock(returncode=0)
        runner.side_effect = recovered
        self.assertTrue(mapping.recover_touch(self.root, runner, lambda _: None))
        runner.reset_mock()
        self.assertTrue(mapping.recover_touch(self.root, runner, lambda _: None))
        runner.assert_not_called()
        name.unlink(); runner.side_effect = None
        self.assertFalse(mapping.recover_touch(self.root, runner, lambda _: None))
        self.assertEqual(sum(c.args[0] == ["modprobe", "goodix_ts"] for c in runner.call_args_list), 2)
        (drm / "card2-DSI-2/status").write_text("connected")
        self.assertIsNone(mapping.connected_output(self.root))
        with self.assertRaises(ValueError): mapping.mapping_rule('DSI-1", RUN+="bad')

    def test_orientation_is_first_and_does_not_complete_region(self):
        self.setup.handle({"action": "orientation", "profile": "touch2-7", "rotation": "90"})
        state = self.setup.saved()
        self.assertTrue(state["orientation"])
        self.assertNotIn("display", state)
        self.assertNotIn("timezone", state)
        self.assertIn("ili9881-7inch\n", (self.root / "boot/config.txt").read_text())
        with patch.object(module.threading, "Timer") as timer:
            self.assertTrue(self.setup.handle({"action": "reboot"})["ok"])
            timer.assert_called_once()

    def test_completed_appliance_applies_semantic_orientation_with_automatic_reboot(self):
        self.setup.save({"complete": True, "profile": "touch2-10"})
        config = self.root / "etc/pi-home"; (config / "display-profile").write_text("touch2-10\n")
        with patch.object(module.threading, "Timer") as timer:
            result = self.setup.handle({"action": "set_display", "profile": "touch2-10", "orientation": "landscape", "mounting": "inverted"})
        self.assertEqual(result["rotation"], "270")
        self.assertEqual((config / "display-orientation").read_text(), "landscape\n")
        self.assertEqual((config / "display-mounting").read_text(), "inverted\n")
        self.assertTrue(result["reboot_required"])
        timer.assert_called_once()
        timer.call_args.args[1]()
        self.run.assert_called_with(["/sbin/reboot"])

    def test_semantic_orientation_accounts_for_native_panel_shape(self):
        self.assertEqual(module.orientation_transform("original", "landscape"), "normal")
        self.assertEqual(module.orientation_transform("original", "portrait"), "90")
        self.assertEqual(module.orientation_transform("touch2-10", "portrait"), "normal")
        self.assertEqual(module.orientation_transform("touch2-10", "landscape"), "90")
        self.assertEqual(module.orientation_transform("original", "landscape", "inverted"), "180")
        self.assertEqual(module.orientation_transform("original", "portrait", "inverted"), "270")
        self.assertEqual(module.orientation_transform("touch2-10", "portrait", "inverted"), "180")
        self.assertEqual(module.orientation_transform("touch2-10", "landscape", "inverted"), "270")

    def test_panel_profile_change_automatically_reboots_after_saving(self):
        self.setup.save({"complete": True, "profile": "touch2-7"})
        with patch.object(module.threading, "Timer") as timer:
            result = self.setup.handle({"action": "set_display", "profile": "touch2-10", "orientation": "portrait"})
            self.assertTrue(result["reboot_required"])
            timer.assert_called_once()
            timer.call_args.args[1]()
            self.run.assert_called_with(["/sbin/reboot"])
        self.assertEqual((self.root / "etc/pi-home/display-profile").read_text(), "touch2-10\n")

    def test_kernel_never_double_rotates_calibrated_touch(self):
        for rotation in ("normal", "90", "180", "270"):
            self.setup.handle({"action": "orientation", "profile": "touch2-7", "rotation": rotation})
            boot = (self.root / "boot/config.txt").read_text()
            self.assertIn("dtoverlay=vc4-kms-dsi-ili9881-7inch\n", boot)
            for flag in ("swapxy", "invx", "invy"): self.assertNotIn(flag, boot)

    def test_original_display_touch_rule_receives_saved_rotation(self):
        import sys
        spec = importlib.util.spec_from_file_location("input_mapping_original", ROOT / "appliance/alpine/input_mapping.py")
        mapping = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"setup_service": module}): spec.loader.exec_module(mapping)
        rule = mapping.mapping_rule("DSI-1", "180", "original")
        self.assertNotIn('ATTRS{name}', rule)
        self.assertIn('ENV{ID_INPUT_TOUCHSCREEN}=="1"', rule)
        self.assertEqual(rule.count('LIBINPUT_CALIBRATION_MATRIX}="-1 0 1 0 -1 1"'), 1)


if __name__ == "__main__": unittest.main()
