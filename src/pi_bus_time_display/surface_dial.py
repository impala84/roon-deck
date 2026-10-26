"""Optional Linux evdev reader. No OS mixer, synthetic keys or audio processing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import struct
import time
import urllib.request
import urllib.error

from .remote_access import DEFAULT_DIAL, atomic_json, dial_config, load_json

EVENT = struct.Struct("@llHHi")
EV_KEY, EV_REL, EV_SYN = 1, 2, 0
REL_DIAL, REL_WHEEL, BTN_0, BTN_LEFT, SYN_DROPPED = 7, 8, 256, 272, 3


# REL_DIAL counts are tenths of a degree (3600 per turn). One volume step needs this much turning, so a
# full turn is roughly 12 / 18 / 30 steps. Smaller movements accumulate instead of being rounded up.
COUNTS_PER_STEP = {"fine": 300, "normal": 200, "fast": 120}
MAX_STEPS_PER_COMMAND = 3
STALE_ROTATION_SECONDS = .5


class Gestures:
    """Button edges become exclusive single/double/long actions; drops reset all."""
    def __init__(self, counts_per_step=COUNTS_PER_STEP["normal"]):
        self.counts_per_step = counts_per_step
        self.reset()

    def reset(self):
        self.pressed_at = None
        self.single_at = None
        self.long_sent = False
        self.rotation = 0
        self.last_motion = None
        self.last_rotation = None
        self.second_press = False
        self.synchronising = False

    def event(self, kind, code, value, now):
        if kind == EV_SYN and code == SYN_DROPPED:
            self.reset()
            self.synchronising = True
            return
        if self.synchronising:
            if kind == EV_SYN and code == 0: self.synchronising = False
            return
        if kind == EV_REL and code in {REL_DIAL, REL_WHEEL}:
            # Some kernels report both axes for one movement; REL_DIAL is the precise one.
            if code == REL_DIAL: self.dial_seen = True
            if code == REL_DIAL or not getattr(self, "dial_seen", False):
                if self.rotation and self.last_motion is not None and now - self.last_motion > STALE_ROTATION_SECONDS: self.rotation = 0
                self.rotation = max(-24 * self.counts_per_step, min(24 * self.counts_per_step, self.rotation + value))
                self.last_motion = now
        if kind != EV_KEY or code not in {BTN_0, BTN_LEFT} or value not in {0, 1}: return
        if value == 1:
            if self.pressed_at is None:
                self.second_press = self.single_at is not None and now <= self.single_at
                self.pressed_at, self.long_sent = now, False
        elif self.pressed_at is not None:
            if not self.long_sent:
                if now - self.pressed_at >= .75:
                    self.single_at = self.pressed_at = None
                    return "long"
                if self.second_press:
                    self.single_at = None
                    self.pressed_at = None
                    return "double"
                self.single_at = now + .32
            self.pressed_at = None

    def tick(self, now):
        if self.pressed_at is not None and not self.long_sent and now - self.pressed_at >= .75:
            self.long_sent, self.single_at = True, None
            return {"kind": "long"}
        if self.single_at is not None and self.pressed_at is None and now >= self.single_at:
            self.single_at = None
            return {"kind": "single"}
        if self.rotation and self.last_motion is not None and now - self.last_motion > STALE_ROTATION_SECONDS:
            self.rotation = 0   # a slight nudge that never reached a full step is forgotten
        whole = int(self.rotation / self.counts_per_step)
        if whole:
            steps = max(-MAX_STEPS_PER_COMMAND, min(MAX_STEPS_PER_COMMAND, whole))
            self.rotation -= steps * self.counts_per_step
            fast = self.last_rotation is not None and now - self.last_rotation < .12
            self.last_rotation = now
            return {"kind": "rotate", "steps": steps, "fast": fast}
        return None


def input_paths(address, sysroot=Path("/sys/class/input")):
    """Input nodes for the explicitly paired Dial.

    Bluetooth HID devices carry the adapter-visible address as "uniq", which is exact. Some kernels leave it
    blank, so a device named Surface Dial with no address is accepted too. Vendor/product IDs differ between
    USB and Bluetooth, so they are not required.
    """
    result = []
    for node in sysroot.glob("event*"):
        device = node / "device"
        try: uniq = (device / "uniq").read_text().strip().upper()
        except OSError: uniq = ""
        try: name = (device / "name").read_text().strip().lower()
        except OSError: name = ""
        if uniq == address.upper() or (not uniq and "surface dial" in name):
            result.append(Path("/dev/input") / node.name)
    return sorted(result)


def send(event):
    request = urllib.request.Request("http://127.0.0.1:8766/api/accessory/control", data=json.dumps(event).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)


def status(message):
    path = Path("/var/lib/pi-home/dial-status.json")
    try:
        if load_json(path, {}).get("message") != message:
            atomic_json(path, {"message": message[:200], "updated": round(time.time())})
    except OSError:
        pass


def apply_event(event):
    try:
        send(event)
        status("Roon control applied.")
        return True
    except urllib.error.HTTPError as error:
        try: message = json.load(error).get("error", "Roon control is unavailable.")
        except (OSError, ValueError): message = "Roon control is unavailable."
        status(str(message))
    except (OSError, ValueError):
        status("Roon is unavailable. No volume changes are queued.")
    return False


def main():
    settings = Path("/var/lib/pi-home/accessories.json")
    gestures = Gestures()
    while True:
        try:
            config = dial_config(load_json(settings, DEFAULT_DIAL))
            if not config["enabled"]:
                status("Disabled")
                time.sleep(2)
                continue
            gestures.counts_per_step = COUNTS_PER_STEP.get(config["sensitivity"], COUNTS_PER_STEP["normal"])
            paths = input_paths(config["address"])
            if not paths:
                status("Waiting for paired Surface Dial input." if Path("/dev/uhid").exists() else
                       "Bluetooth HID support (uhid) is missing. In web Settings choose Disconnect, then Connect.")
                time.sleep(2)
                continue
            # A Surface Dial may expose more than one collection. Open all
            # matching nodes, but never grab or alter the touchscreen devices.
            files = []
            try:
                for path in paths: files.append(open(path, "rb", buffering=0))
                status("Connected. Waiting for Dial input.")
                gestures.reset()
                next_config = time.monotonic() + 1
                last_send = 0.0
                while True:
                    now = time.monotonic()
                    if now >= next_config:
                        # Compare normalised values so extra or missing keys cannot make this restart every second.
                        if dial_config(load_json(settings, DEFAULT_DIAL)) != config: break
                        next_config = now + 1
                        if any(not path.exists() for path in paths): break
                    ready, _, _ = select.select(files, [], [], .04)
                    for stream in ready:
                        raw = os.read(stream.fileno(), EVENT.size * 64)
                        if not raw or len(raw) % EVENT.size: raise OSError("Input disconnected")
                        for offset in range(0, len(raw), EVENT.size):
                            sec, usec, kind, code, value = EVENT.unpack_from(raw, offset)
                            # Don't replay buffered movements after a stalled
                            # controller, a reconnect, or a suspended device.
                            if abs(time.time() - sec - usec / 1_000_000) > .5:
                                gestures.reset()
                                continue
                            action = gestures.event(kind, code, value, now)
                            if action and not apply_event({"kind": action}): gestures.reset()
                    if now - last_send >= .08:
                        event = gestures.tick(now)
                        if event:
                            if not apply_event(event): gestures.reset()
                            last_send = time.monotonic()
            finally:
                for stream in files: stream.close()
        except (OSError, ValueError):
            # No private settings or music metadata in service logs.
            gestures.reset()
            status("Dial input unavailable. Check pairing and input permissions.")
            time.sleep(2)


if __name__ == "__main__": main()
