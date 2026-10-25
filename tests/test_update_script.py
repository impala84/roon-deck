import unittest
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


class UpdateScriptTests(unittest.TestCase):
    def test_updater_includes_installer_touchscreen_dependencies(self):
        script = (ROOT / "scripts" / "pi-bus-update").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install-pi.sh").read_text(encoding="utf-8")
        required = set(re.search(r"required_packages=\(([^)]+)\)", script).group(1).split())
        installed = set(re.search(r"apt-get install -y ([^\n]+)", installer).group(1).split())
        graphics = {package for package in installed if package.startswith(("python3-gi", "gir1.2-"))}
        self.assertIn("python3-gi-cairo", graphics)
        self.assertTrue(graphics <= required)

    def test_graphics_are_checked_before_restart_and_native_startup_is_verified(self):
        script = (ROOT / "scripts" / "pi-bus-update").read_text(encoding="utf-8")
        self.assertLess(script.index('gi.require_foreign("cairo")'), script.index('progress "Restarting RoonDeck services…"'))
        self.assertIn("--property=NRestarts --value", script)
        self.assertIn("systemctl is-active --quiet pi-bus-native.service", script)
        self.assertLess(script.index('progress "Touchscreen is running."'), script.index('progress "Complete'))

    def test_native_startup_check_rejects_stopped_and_restarting_services(self):
        script = (ROOT / "scripts" / "pi-bus-update").read_text(encoding="utf-8")
        start = script.index('  restart_count=$(systemctl show pi-bus-native.service')
        end = script.index('\nfi', start)
        check = script[start:end]
        mocks = '''
test_restarts=0; test_active=0
systemctl() {
  case "$*" in
    *NRestarts*) echo "$test_restarts" ;;
    *is-active*) return "$test_active" ;;
  esac
}
sleep() {
  if [[ $mode == restarting ]]; then test_restarts=1; fi
  if [[ $mode == stopped ]]; then test_active=1; fi
}
progress() { echo "$1"; }
journalctl() { :; }
'''
        for mode in ("healthy", "stopped", "restarting"):
            with self.subTest(mode=mode):
                result = subprocess.run(["bash", "-c", f"mode={mode}\n{mocks}\n{check}"], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if mode == "healthy" else 1)
                self.assertEqual("Touchscreen is running." in result.stdout, mode == "healthy")

    def test_system_package_refresh_only_runs_for_missing_packages(self):
        script = (ROOT / "scripts" / "pi-bus-update").read_text(encoding="utf-8")
        self.assertIn("dpkg-query -W", script)
        self.assertIn('if ((${#missing_packages[@]})); then', script)
        self.assertIn('apt-get install -y "${missing_packages[@]}"', script)
        self.assertIn("--prefer-offline --no-audit --no-fund", script)

    def test_update_has_lock_timeouts_and_dependency_stamp(self):
        script = (ROOT / "scripts" / "pi-bus-update").read_text(encoding="utf-8")
        service = (ROOT / "systemd" / "pi-bus-system-action.service").read_text(encoding="utf-8")
        self.assertIn("flock -n 9", script)
        self.assertIn("timeout --signal=TERM --kill-after=10s 2m git", script)
        self.assertIn("roon-package-lock.sha256", script)
        self.assertIn('npm --prefix "${app_dir}/roon-controller" ci', script)
        self.assertIn("CPUQuota=100%", service)
        self.assertIn("TimeoutStartSec=15min", service)


if __name__ == "__main__":
    unittest.main()
