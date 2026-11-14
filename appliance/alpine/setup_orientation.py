"""Apply the DSI setup orientation before GTK starts, without changing HDMI."""
from pathlib import Path
import re
import subprocess
import time

TOUCH2_10_OVERLAY = "dtoverlay=vc4-kms-dsi-ili79600-10-1inch"


def choose_output(text):
    name = None
    for line in text.splitlines():
        if line and not line[0].isspace(): name = line.split()[0]
        mode = re.search(r"(\d+)x(\d+).*current", line)
        if name and name.startswith("DSI-") and mode:
            return name, int(mode[1]) < int(mode[2])
    return None, False


def configured_rotation(root=Path("/")):
    profile_file = root / "etc/pi-home/display-profile"
    saved = root / "etc/pi-home/display-transform"
    profile = profile_file.read_text().strip() if profile_file.exists() else None
    rotation = saved.read_text().strip() if saved.exists() else None
    try: dedicated_touch2_10 = TOUCH2_10_OVERLAY in (root / "boot/config.txt").read_text()
    except OSError: dedicated_touch2_10 = False
    return "90" if dedicated_touch2_10 and profile in (None, "", "auto") else rotation


def main():
    rotation = configured_rotation()
    for _ in range(30):
        try:
            result = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=3)
            output, portrait = choose_output(result.stdout)
            if output:
                # First screen stays native: no output-only rotation before choice.
                transform = {"90": "270", "270": "90"}.get(rotation, rotation) if rotation else "normal"
                if transform in {"normal", "90", "180", "270"}:
                    subprocess.run(["wlr-randr", "--output", output, "--transform", transform], check=True, timeout=3)
                    print(f"RoonDeck setup orientation: {output} transform={transform}", flush=True)
                return
        except (OSError, subprocess.SubprocessError): pass
        time.sleep(.1)
    print("RoonDeck setup orientation: no DSI output ready; unchanged", flush=True)


if __name__ == "__main__": main()
