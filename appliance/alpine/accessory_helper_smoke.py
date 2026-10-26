"""Real unprivileged HTTP -> root socket with Bluetooth installed but stopped.

Runs only in a disposable appliance container. A deliberately blocking client
stands in for bluetoothctl waiting for org.bluez; status must never invoke it.
No pairing, package download or device/network configuration is performed.
"""
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    root = Path(os.environ.get("PI_HOME_REVIEW_ROOT", "/opt/pi-home"))
    progress = Path("/var/lib/pi-home-setup/progress.json")
    progress.parent.mkdir(mode=0o700, exist_ok=True)
    progress.write_text('{"complete":true}'); progress.chmod(0o600)
    flags = Path("/var/lib/roondeck-remote/features.json")
    flags.parent.mkdir(mode=0o700, exist_ok=True)
    flags.write_text('{"dial":true,"vpn":false}')
    for path, text in ((Path("/usr/bin/bluetoothctl"), "#!/bin/sh\nexec sleep 120\n"),
                       (Path("/etc/init.d/bluetooth"), "#!/sbin/openrc-run\n"),
                       (Path("/etc/init.d/roondeck-dial"), "#!/sbin/openrc-run\n")):
        path.write_text(text); path.chmod(0o755)
    account = pwd.getpwnam("morningbus")
    processes = []
    with tempfile.TemporaryFile(mode="w+") as log:
        try:
            environment = {**os.environ, "PI_HOME_APPLIANCE_PLATFORM": "alpine-prototype", "PYTHONPATH": str(root / "src")}
            helper = subprocess.Popen(["python3", str(root / "appliance/alpine/setup_service.py")], stdout=log, stderr=log, env=environment)
            processes.append(helper)
            for _ in range(100):
                if helper.poll() is not None: raise AssertionError("Root helper did not start")
                if Path("/run/pi-home-setup.sock").exists(): break
                time.sleep(.05)
            executable = Path("/opt/pi-home/.venv/bin/pi-home")
            api = subprocess.Popen([str(executable), "--simulate", "--config", "/etc/pi-home/config.toml", "--env", "/etc/pi-home/secrets.env",
                                    "--state-dir", "/var/lib/pi-home", "--host", "127.0.0.1"],
                                   user=account.pw_uid, group=account.pw_gid, env=environment, stdout=log, stderr=log)
            processes.append(api)
            for attempt in range(100):
                started = time.monotonic()
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8765/api/admin/accessories", timeout=4) as response:
                        result = json.load(response)
                    assert time.monotonic() - started < 3, "Stopped Bluetooth blocked the helper"
                    assert result["ok"] and result["features"]["dial"]
                    assert result["bluetooth_service"] == "Stopped" and result["devices"] == []
                    break
                except urllib.error.URLError:
                    if attempt == 99: raise
                    time.sleep(.05)
            # A client abandoning its request must not kill the root service.
            script = ('import socket; s=socket.socket(socket.AF_UNIX); s.connect("/run/pi-home-setup.sock"); '
                      's.sendall(b\'{"action":"accessories","operation":"status"}\\n\'); s.shutdown(socket.SHUT_RDWR); s.close()')
            subprocess.run(["python3", "-c", script], user=account.pw_uid, group=account.pw_gid, check=True, timeout=5)
            time.sleep(.1)
            assert helper.poll() is None, "Disconnected client terminated the helper"
            with urllib.request.urlopen("http://127.0.0.1:8765/api/admin/accessories", timeout=4) as response:
                assert json.load(response)["ok"]
            print("Accessory helper: real HTTP/UID-restricted root socket stays responsive with stopped Bluetooth and abandoned clients.")
        except Exception:
            log.seek(0); print(log.read()[-4000:])
            raise
        finally:
            for process in reversed(processes): process.terminate()
            for process in reversed(processes): process.wait(timeout=5)


if __name__ == "__main__": main()
