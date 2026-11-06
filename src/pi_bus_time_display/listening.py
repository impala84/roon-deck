"""Shared physical/touch listening controls. No speculative Topping writes."""
from __future__ import annotations

import re
import json
import socket
import threading
import time
import tempfile
import os
from pathlib import Path


class KefLSX:
    SOURCES = {"wifi": 2, "bluetooth": 9, "aux": 10, "optical": 11}

    def __init__(self, host, maximum_volume=50):
        self.host = host
        self.maximum_volume = maximum_volume

    def exchange(self, request):
        with socket.create_connection((self.host, 50001), timeout=2) as connection:
            connection.settimeout(2)
            connection.sendall(request)
            reply = bytearray()
            deadline = time.monotonic() + 2
            while len(reply) < 128:
                connection.settimeout(max(.01, deadline - time.monotonic()))
                part = connection.recv(64)
                if not part:
                    raise OSError("KEF closed the control connection")
                reply.extend(part)
                if request[0] == 83:
                    if b"R\x11\xff" in reply:
                        return 17
                else:
                    offset = reply.find(bytes([82, request[1], 129]))
                    if offset >= 0 and len(reply) >= offset + 5:
                        if reply[offset + 4] != 255:
                            raise OSError("Malformed KEF response")
                        return reply[offset + 3]
                if time.monotonic() >= deadline:
                    raise OSError("KEF control response timed out")
            raise OSError("Unexpected KEF response")

    def status(self):
        source = self.exchange(bytes.fromhex("473080"))
        volume = self.exchange(bytes.fromhex("472580"))
        if volume & 127 > 100:
            raise OSError("Invalid KEF volume response")
        return {"connected": True, "powered": not bool(source & 128),
                "input": next((name for name, code in self.SOURCES.items() if source & 15 == code), "unknown"),
                "volume": volume & 127, "muted": bool(volume & 128)}

    def command(self, action, value=None):
        if action in {"power", "input"}:
            if action == "power" and type(value) is not bool:
                raise ValueError("Power requires true or false")
            if action == "input" and value not in self.SOURCES:
                raise ValueError("Choose wifi, bluetooth, aux or optical")
            source = self.exchange(bytes.fromhex("473080"))
            if action == "input":
                source = (source & 112) | self.SOURCES[value]
            elif value:
                source &= 127
            else:
                # Avoid the original speaker's 20-minute standby shutdown bug.
                if source & 48 == 0:
                    source |= 16
                    self.exchange(bytes([83, 48, 129, source]))
                source |= 128
            self.exchange(bytes([83, 48, 129, source]))
        elif action in {"volume", "volume_delta", "mute"}:
            if action != "mute" and (type(value) is not int or not -100 <= value <= 100):
                raise ValueError("Volume requires an integer between -100 and 100")
            current = self.exchange(bytes.fromhex("472580"))
            volume, muted = current & 127, current & 128
            if volume > 100:
                raise OSError("Invalid KEF volume response")
            if action == "mute":
                muted ^= 128
            else:
                volume = max(0, min(self.maximum_volume, value if action == "volume" else volume + value))
            self.exchange(bytes([83, 37, 129, volume | muted]))
        else:
            raise ValueError("Unsupported KEF action")


def load_settings(path: Path):
    if not path.exists():
        return {"enabled": False, "modes": [], "buttons": [], "dials": []}
    data = json.loads(path.read_text())
    return validate_settings(data)


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Listening configuration must be an object")
    if set(data) - {"enabled", "kef_host", "maximum_volume", "streamdeck_enabled", "modes", "buttons", "dials"}:
        raise ValueError("Unknown listening setting")
    host = data.get("kef_host", "")
    if not isinstance(host, str) or len(host) > 253 or any(character.isspace() or character in "/\\@" for character in host):
        raise ValueError("Enter a speaker IP address or hostname")
    if data.get("enabled") and not host:
        raise ValueError("Enter the KEF speaker address before enabling controls")
    maximum = data.get("maximum_volume", 50)
    if type(maximum) is not int or not 0 <= maximum <= 100:
        raise ValueError("maximum_volume must be between 0 and 100")
    for name in ("enabled", "streamdeck_enabled"):
        if name in data and type(data[name]) is not bool:
            raise ValueError(f"{name} must be true or false")
    for name, limit in (("buttons", 8), ("dials", 4)):
        bindings = data.get(name, [])
        if not isinstance(bindings, list) or len(bindings) > limit or any(not isinstance(item, dict) for item in bindings):
            raise ValueError(f"{name} must be a list of up to {limit} bindings")
        def validate_binding(binding, is_press=False):
            allowed = {"none", "mode", "power", "input", "volume", "volume_delta", "mute", "previous", "playpause", "next", "home_toggle", "home_level", "home_scene", "home_script", "home_script_dial"}
            if not isinstance(binding.get("action", "none"), str) or binding.get("action", "none") not in allowed:
                raise ValueError("Choose a supported control action")
            if not isinstance(binding.get("label", ""), str) or len(binding.get("label", "")) > 40:
                raise ValueError("Control labels must be at most 40 characters")
            if type(binding.get("step", 1)) is not int or not 1 <= binding.get("step", 1) <= 10:
                raise ValueError("Dial steps must be between 1 and 10")
            if "image" in binding and (not isinstance(binding["image"], str) or len(binding["image"]) > 120 or Path(binding["image"]).name != binding["image"]):
                raise ValueError("Artwork must be a filename in the deck-art folder")
            if "color" in binding and (not isinstance(binding["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", binding["color"])):
                raise ValueError("Button colours must look like #236650")
            if "press" in binding:
                if is_press or not isinstance(binding["press"], dict): raise ValueError("Invalid dial press binding")
                validate_binding(binding["press"], True)
            if binding.get("action") == "power" and type(binding.get("value")) is not bool:
                raise ValueError("Power targets must be true or false")
            if binding.get("action") == "input" and binding.get("value") not in KefLSX.SOURCES:
                raise ValueError("Choose a supported KEF input")
            if binding.get("action", "").startswith("home_") and (not isinstance(binding.get("entity_id"), str) or len(binding["entity_id"]) > 200):
                raise ValueError("Enter a Home Assistant entity ID")
            if binding.get("action") in {"home_script", "home_script_dial"} and not binding["entity_id"].startswith("script."):
                raise ValueError("Choose a Home Assistant script")
            if "entity_id_ccw" in binding and (not isinstance(binding["entity_id_ccw"], str) or len(binding["entity_id_ccw"]) > 200
                                               or (binding["entity_id_ccw"] and not binding["entity_id_ccw"].startswith("script."))):
                raise ValueError("Choose a Home Assistant script")
        for binding in bindings: validate_binding(binding)
    modes = data.get("modes", [])
    if not isinstance(modes, list) or len(modes) > 8:
        raise ValueError("Choose up to eight listening modes")
    identifiers = set()
    for mode in modes:
        if not isinstance(mode, dict) or not isinstance(mode.get("id"), str) or not mode["id"] or mode["id"] in identifiers:
            raise ValueError("Listening mode IDs must be unique nonempty strings")
        identifiers.add(mode["id"])
        if len(mode["id"]) > 40 or not isinstance(mode.get("name", ""), str) or len(mode.get("name", "")) > 60:
            raise ValueError("Listening mode names are too long or invalid")
        if mode.get("kef_input") not in KefLSX.SOURCES:
            raise ValueError("Each mode needs a supported KEF input")
        if type(mode.get("volume")) is not int or not 0 <= mode["volume"] <= maximum:
            raise ValueError("Starting volume exceeds the configured limit")
        if mode.get("topping_input") not in {None, "usb", "coaxial", "optical", "bluetooth"}:
            raise ValueError("Unsupported Topping input")
    return data


class ListeningControls:
    def __init__(self, settings_path, kef_factory=KefLSX):
        self.path = Path(settings_path)
        self.factory = kef_factory
        self.lock = threading.Lock()
        self.state = {"enabled": False, "kef": {"connected": False}, "modes": [],
                      "streamdeck": {"enabled": False, "connected": False, "error": ""},
                      "topping": {"available": False, "reason": "Bluetooth commands have not been verified"},
                      "last_mode": None, "error": ""}

    def settings(self):
        return load_settings(self.path)

    def save(self, data):
        data = validate_settings(data)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".listening-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(data, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self.state["last_mode"] = None
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        return data

    def speaker(self, settings):
        host = settings.get("kef_host")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("Configure kef_host before enabling listening controls")
        return self.factory(host, settings.get("maximum_volume", 50))

    def refresh(self):
        with self.lock:
            try:
                settings = self.settings()
                self.state["enabled"] = bool(settings.get("enabled"))
                self.state["modes"] = [{"id": mode["id"], "name": mode.get("name", mode["id"]),
                    "available": not bool(mode.get("topping_input")),
                    "reason": "Topping input switching is not available yet" if mode.get("topping_input") else ""}
                    for mode in settings.get("modes", [])]
                self.state["kef"] = self.speaker(settings).status() if self.state["enabled"] else {"connected": False}
                mode = next((mode for mode in settings.get("modes", []) if mode["id"] == self.state["last_mode"]), None)
                status = self.state["kef"]
                if mode and (not status.get("connected") or not status.get("powered") or status.get("input") != mode["kef_input"] or status.get("volume") != mode["volume"]):
                    self.state["last_mode"] = None
                self.state["error"] = ""
            except (OSError, ValueError, TypeError) as error:
                self.state["kef"] = {"connected": False}
                self.state["last_mode"] = None
                if isinstance(error, (ValueError, TypeError)):
                    self.state["enabled"] = False
                    self.state["modes"] = []
                self.state["error"] = str(error)
            return self.snapshot_unlocked()

    def snapshot_unlocked(self):
        return json.loads(json.dumps(self.state))

    def snapshot(self):
        # Poll/command serialization must never stall the native display's
        # short HTTP timeout when an unreachable speaker takes seconds to fail.
        # Values are replaced, never mutated in place; take a shallow copy first.
        return json.loads(json.dumps(dict(self.state)))

    def command(self, action, value=None):
        with self.lock:
            settings = self.settings()
            if not settings.get("enabled"):
                raise ValueError("Listening controls are disabled")
            if not isinstance(action, str):
                raise ValueError("Action must be a string")
            speaker = self.speaker(settings)
            try:
                self.state["last_mode"] = None
                if action == "mode":
                    mode = next((item for item in settings.get("modes", []) if item["id"] == value), None)
                    if mode is None:
                        raise ValueError("Unknown listening mode")
                    # Preflight every dependency before touching any hardware.
                    if mode.get("topping_input"):
                        raise ValueError("Mode unavailable: Topping Bluetooth commands are not verified")
                    speaker.command("power", True)
                    time.sleep(.3)
                    speaker.command("input", mode["kef_input"])
                    time.sleep(.3)
                    speaker.command("volume", mode["volume"])
                else:
                    speaker.command(action, value)
                status = speaker.status()
                if action == "mode":
                    if not status["powered"] or status["input"] != mode["kef_input"] or status["volume"] != mode["volume"]:
                        raise OSError("Speaker did not confirm the listening mode")
                    self.state["last_mode"] = value
                self.state["kef"] = status
                self.state["error"] = ""
            except (OSError, ValueError) as error:
                self.state["error"] = str(error)
                raise
            return self.snapshot_unlocked()

    def poll(self, stop):
        while not stop.is_set():
            self.refresh()
            stop.wait(3)
