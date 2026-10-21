"""Calibrate built-in DSI touch before Cage; recover failed Goodix probes."""
from pathlib import Path
import re
import subprocess
import time
from setup_service import atomic


def connected_output(root):
    outputs = set()
    for status in (root / "sys/class/drm").glob("card*-DSI-*/status"):
        if status.read_text().strip() == "connected":
            match = re.fullmatch(r"card\d+-(DSI-\d+)", status.parent.name)
            if match: outputs.add(match[1])
    return next(iter(outputs)) if len(outputs) == 1 else None


MATRICES = {"normal": "1 0 0 0 1 0", "90": "0 1 0 -1 0 1",
            "180": "-1 0 1 0 -1 1", "270": "0 -1 1 1 0 0"}


def touch_names(profile):
    if profile == "original":
        # The original DSI panel has shipped under several kernel input names.
        # The explicitly selected display profile and udev's touchscreen class
        # are the stable identity; do not couple calibration to a driver name.
        return [None]
    names = ["*Goodix Capacitive TouchScreen"]
    if profile == "touch2-10": names.append("* ili_v3")
    return names


def mapping_rule(output, rotation="normal", profile=None):
    if not re.fullmatch(r"DSI-\d+", output): raise ValueError("Invalid DSI output")
    if rotation not in MATRICES: raise ValueError("Invalid touch rotation")
    # The 5/7-inch Touch Display 2 uses Goodix. The 10-inch uses ILI79600A,
    # whose kernel input name is "<I2C address> ili_v3", not Goodix.
    rules = []
    for name in touch_names(profile):
        device = f'ATTRS{{name}}=="{name}", ' if name else ""
        rules.append(
            'ACTION!="remove", SUBSYSTEM=="input", KERNEL=="event*", '
            f'ENV{{ID_INPUT_TOUCHSCREEN}}=="1", {device}'
            f'ENV{{WL_OUTPUT}}="", ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{MATRICES[rotation]}"\n'
        )
    return '# RoonDeck: libinput owns touch rotation; kernel and Cage mapping stay unrotated.\n' + ''.join(rules)


def touch_present(root):
    return any(name.read_text().strip().endswith("Goodix Capacitive TouchScreen")
               for name in (root / "sys/class/input").glob("event*/device/name"))


def recover_touch(root, run=subprocess.run, sleep=time.sleep):
    if touch_present(root): return True
    # Do not reload touch drivers on unrelated HDMI/USB installations.
    nodes = (root / "sys/bus/i2c/devices").glob("*/of_node/compatible")
    if not any(b"goodix,gt911" in node.read_bytes() for node in nodes): return False
    for attempt in range(2):
        sleep(1)
        print(f"RoonDeck Goodix boot-probe recovery attempt {attempt + 1}", flush=True)
        for args in (["modprobe", "-r", "goodix_ts"], ["modprobe", "goodix_ts"]):
            result = run(args, check=False, timeout=10)
            if result.returncode: break
        else:
            run(["udevadm", "settle", "--timeout=10"], check=False, timeout=15)
            if touch_present(root): return True
    print("RoonDeck Goodix recovery failed; inspect kernel log", flush=True)
    return False


def main():
    root = Path("/")
    output = None
    for _ in range(30):
        output = connected_output(root)
        if output: break
        time.sleep(.1)
    rules = root / "etc/udev/rules.d/99-pi-home-dsi-touch.rules"
    rules.parent.mkdir(parents=True, exist_ok=True)
    saved = root / "etc/pi-home/display-transform"
    rotation = saved.read_text().strip() if saved.exists() else "normal"
    profile_file = root / "etc/pi-home/display-profile"
    profile = profile_file.read_text().strip() if profile_file.exists() else None
    atomic(rules, mapping_rule(output, rotation, profile) if output else "# No single connected DSI output; leave external touch devices unchanged.\n")
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True, timeout=10)
    subprocess.run(["udevadm", "trigger", "--subsystem-match=input", "--action=change"], check=True, timeout=10)
    subprocess.run(["udevadm", "settle", "--timeout=10"], check=True, timeout=15)
    if output:
        try: recovered = recover_touch(root)
        except (OSError, subprocess.SubprocessError) as error:
            recovered = False
            print(f"RoonDeck Goodix recovery unavailable: {error}", flush=True)
        print(f"RoonDeck touch calibration: profile={profile}, rotation={rotation}, matrix={MATRICES[rotation]}, goodix_detected={recovered}", flush=True)
        for name in (root / "sys/class/input").glob("event*/device/name"):
            print(f"RoonDeck input: {name.parent.parent.name}: {name.read_text().strip()}", flush=True)
    else: print("RoonDeck touch mapping: no unambiguous DSI output", flush=True)


if __name__ == "__main__": main()
