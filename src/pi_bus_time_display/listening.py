"""Shared listening controls for the KEF: Roon for power, volume and mute; Home Assistant infrared for input."""
from __future__ import annotations

import re
import json
import socket
import threading
import time
import tempfile
import os
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


INPUTS = ("wifi", "bluetooth", "aux", "optical")


class KefRoon:
    """The KEF LSX as Roon sees it: wake, standby, volume and mute go through the Roon output.

    The speaker's own network control port is not used. Input selection is sent
    separately as infrared by ListeningControls, through a Home Assistant
    Broadlink remote, because the LSX cannot be asked which input is playing.
    """

    def __init__(self, host="", maximum_volume=50, roon_output_id=""):
        self.host = host
        self.maximum_volume = maximum_volume
        self.roon_output_id = roon_output_id

    def roon_request(self, action=None, value=None):
        if not self.roon_output_id: raise OSError("Choose the KEF's output under Listening & KEF")
        if action is None:
            request = "http://127.0.0.1:8766/api/kef/status?" + urllib.parse.urlencode({"output_id": self.roon_output_id})
        else:
            request = urllib.request.Request("http://127.0.0.1:8766/api/kef/command",
                json.dumps({"output_id": self.roon_output_id, "action": action, "value": value,
                            "maximum_volume": self.maximum_volume}).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            try: message = json.load(error).get("error", "Roon KEF control failed")
            except (ValueError, AttributeError): message = "Roon KEF control failed"
            raise OSError(message) from error
        except (urllib.error.URLError, ValueError) as error:
            raise OSError("Roon KEF connection is unavailable") from error

    def status(self):
        return self.roon_request()

    def command(self, action, value=None):
        if action == "power" and type(value) is not bool: raise ValueError("Power requires true or false")
        if action in {"volume", "volume_delta"} and (type(value) is not int or not -100 <= value <= 100):
            raise ValueError("Volume requires an integer between -100 and 100")
        if action == "input":
            if value not in INPUTS: raise ValueError("Choose wifi, bluetooth, aux or optical")
            if value != "wifi": raise ValueError("Set the Broadlink remote under Listening & KEF to switch to this input")
        elif action not in {"power", "volume", "volume_delta", "mute"}:
            raise ValueError("Unsupported KEF action")
        self.roon_request(action, value)


KefLSX = KefRoon   # the old name, for anything still importing it


def load_settings(path: Path):
    if not path.exists():
        return {"enabled": False, "buttons": [], "dials": []}
    data = json.loads(path.read_text())
    # Settings saved before the Roon output was required: keep them loadable, with the speaker switched off until an output is chosen.
    if isinstance(data, dict) and data.get("enabled") is True and not data.get("kef_roon_output_id"): data["enabled"] = False
    return validate_settings(data)


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Listening configuration must be an object")
    for retired in ("kef_input_preset", "kef_input_alt"): data.pop(retired, None)   # beta.136 saved these here; the input now belongs to the Home tile
    if set(data) - {"enabled", "kef_host", "kef_roon_output_id", "kef_ir_remote", "maximum_volume", "streamdeck_enabled", "streamdeck_sleep_with_display", "streamdeck_sleep_mode", "streamdeck_sleep_start", "streamdeck_sleep_end", "streamdeck_awake_seconds", "streamdeck_brightness", "on_play", "modes", "buttons", "dials"}:
        raise ValueError("Unknown listening setting")
    data.pop("modes", None)   # listening modes were removed: input is switched by infrared, volume by Roon
    host = data.get("kef_host", "")
    if not isinstance(host, str) or len(host) > 253 or any(character.isspace() or character in "/\\@" for character in host):
        raise ValueError("Enter a speaker IP address or hostname")
    output_id = data.get("kef_roon_output_id", "")
    if not isinstance(output_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,128}", output_id):
        raise ValueError("Choose a valid KEF Roon output")
    if data.get("enabled") and not output_id:
        raise ValueError("Choose the KEF's Roon output before enabling controls")
    remote = data.get("kef_ir_remote", "")
    if not isinstance(remote, str) or (remote and not re.fullmatch(r"remote\.[a-z0-9_]{1,100}", remote)):
        raise ValueError("Choose a Broadlink remote entity")
    maximum = data.get("maximum_volume", 50)
    if type(maximum) is not int or not 0 <= maximum <= 100:
        raise ValueError("maximum_volume must be between 0 and 100")
    for name in ("enabled", "streamdeck_enabled", "streamdeck_sleep_with_display"):
        if name in data and type(data[name]) is not bool:
            raise ValueError(f"{name} must be true or false")
    if "streamdeck_sleep_mode" in data and data["streamdeck_sleep_mode"] not in ("match", "schedule"):
        raise ValueError("Deck sleep must follow RoonDeck (match) or its own schedule")
    for name in ("streamdeck_sleep_start", "streamdeck_sleep_end"):
        if name in data and not (isinstance(data[name], str) and re.fullmatch(r"(|([01]\d|2[0-3]):[0-5]\d)", data[name])):
            raise ValueError("Sleep times must look like 23:00, or be empty")
    if "streamdeck_awake_seconds" in data and (type(data["streamdeck_awake_seconds"]) is not int or not 5 <= data["streamdeck_awake_seconds"] <= 3600):
        raise ValueError("The awake period must be between 5 and 3600 seconds")
    if "streamdeck_brightness" in data and (type(data["streamdeck_brightness"]) is not int or not 10 <= data["streamdeck_brightness"] <= 100):
        raise ValueError("Deck brightness must be between 10 and 100")
    on_play = data.get("on_play", {})
    if not isinstance(on_play, dict) or set(on_play) - {"script", "helper", "value"} or any(not isinstance(item, str) or len(item) > 200 for item in on_play.values()):
        raise ValueError("Invalid play trigger")
    if on_play.get("script") and not on_play["script"].startswith("script."):
        raise ValueError("The play trigger must run a Home Assistant script")
    if on_play.get("helper") and not on_play["helper"].startswith(("input_select.", "sensor.", "input_text.")):
        raise ValueError("The input helper must be an input_select, input_text or sensor")
    for name, limit in (("buttons", 8), ("dials", 4)):
        bindings = data.get(name, [])
        if not isinstance(bindings, list) or len(bindings) > limit or any(not isinstance(item, dict) for item in bindings):
            raise ValueError(f"{name} must be a list of up to {limit} bindings")
        def validate_binding(binding, is_press=False):
            if binding.get("action") == "mode": binding["action"] = "none"   # a saved listening-mode button: that action no longer exists
            allowed = {"none", "power", "input", "preset", "volume", "volume_delta", "mute", "previous", "playpause", "next", "roon_volume", "roon_mute", "home_toggle", "home_level", "home_scene", "home_script", "home_script_dial", "remote_steps", "remote_toggle"}
            if not isinstance(binding.get("action", "none"), str) or binding.get("action", "none") not in allowed:
                raise ValueError("Choose a supported control action")
            if not isinstance(binding.get("label", ""), str) or len(binding.get("label", "")) > 40:
                raise ValueError("Control labels must be at most 40 characters")
            if type(binding.get("step", 1)) is not int or not 1 <= binding.get("step", 1) <= 10:
                raise ValueError("Dial steps must be between 1 and 10")
            if "image" in binding and (not isinstance(binding["image"], str) or len(binding["image"]) > 120 or Path(binding["image"]).name != binding["image"]):
                raise ValueError("Artwork must be a filename in the deck-art folder")
            for colour_name in ("color", "active_color", "text_color", "level_color"):
                if colour_name in binding and (not isinstance(binding[colour_name], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", binding[colour_name])):
                    raise ValueError("Button colours must look like #236650")
            if "level_entity" in binding and (not isinstance(binding["level_entity"], str) or not re.fullmatch(r"(light|fan)\.[a-z0-9_]{1,100}", binding["level_entity"])):
                raise ValueError("Choose a light or fan to show the level of")
            if "also" in binding:
                also = binding["also"]
                if not isinstance(also, dict) or set(also) - {"action", "entity_id"} or also.get("action", "none") not in {"none", "pause", "play", "home_script"}:
                    raise ValueError("Choose a supported follow-up action")
                if also.get("action") == "home_script" and not (isinstance(also.get("entity_id"), str) and also["entity_id"].startswith("script.") and len(also["entity_id"]) <= 200):
                    raise ValueError("Choose a Home Assistant script")
            if "press" in binding:
                if is_press or not isinstance(binding["press"], dict): raise ValueError("Invalid dial press binding")
                validate_binding(binding["press"], True)
            if binding.get("action") == "power" and type(binding.get("value")) is not bool:
                raise ValueError("Power targets must be true or false")
            if binding.get("action") == "input" and binding.get("value") not in INPUTS:
                raise ValueError("Choose a supported KEF input")
            if binding.get("action") == "remote_toggle":
                text = lambda name, pattern: isinstance(binding.get(name), str) and re.fullmatch(pattern, binding[name])
                if not (text("entity_id", r"remote\.[a-z0-9_]{1,80}") and text("device", r"[A-Za-z0-9_ -]{1,40}") and text("command_on", r"[a-z0-9_]{1,40}") and text("command_off", r"[a-z0-9_]{1,40}")):
                    raise ValueError("Choose a remote, a device name and the on and off commands")
                for flag in ("initial_on", "off_only"):
                    if flag in binding and type(binding[flag]) is not bool: raise ValueError(f"{flag} must be true or false")
            if binding.get("action") == "remote_steps":
                if is_press: raise ValueError("Remote steps belong on a dial turn")
                text = lambda name, pattern: isinstance(binding.get(name), str) and re.fullmatch(pattern, binding[name])
                if not (text("entity_id", r"remote\.[a-z0-9_]{1,80}") and text("device", r"[A-Za-z0-9_ -]{1,40}") and text("command", r"[a-z0-9_]{0,30}\{n\}[a-z0-9_]{0,10}")):
                    raise ValueError("Choose a remote, a device name and a command like cool_{n}")
                numbers = [binding.get(name) for name in ("min", "max", "start")]
                if any(type(value) is not int or not -50 <= value <= 200 for value in numbers) or not binding["min"] < binding["max"] or not binding["min"] <= binding["start"] <= binding["max"]:
                    raise ValueError("The lowest, highest and starting values must make sense")
                if not isinstance(binding.get("unit", ""), str) or len(binding.get("unit", "")) > 4:
                    raise ValueError("The unit must be at most 4 characters")
            if binding.get("action", "").startswith("home_") and (not isinstance(binding.get("entity_id"), str) or len(binding["entity_id"]) > 200):
                raise ValueError("Enter a Home Assistant entity ID")
            if binding.get("action") in {"home_script", "home_script_dial"} and not binding["entity_id"].startswith("script."):
                raise ValueError("Choose a Home Assistant script")
            if "entity_id_ccw" in binding and (not isinstance(binding["entity_id_ccw"], str) or len(binding["entity_id_ccw"]) > 200
                                               or (binding["entity_id_ccw"] and not binding["entity_id_ccw"].startswith("script."))):
                raise ValueError("Choose a Home Assistant script")
        for binding in bindings: validate_binding(binding)
    return data


class ListeningControls:
    def __init__(self, settings_path, kef_factory=KefLSX, ir_sender=None):
        self.path = Path(settings_path)
        self.factory = kef_factory
        self.ir_sender = ir_sender
        self.lock = threading.Lock()
        self.brightness_preview = None   # a slider move waiting for the Stream Deck thread to show it
        self.state = {"enabled": False, "kef": {"connected": False},
                      "streamdeck": {"enabled": False, "connected": False, "error": ""},
                      "error": "", "notice": "", "ir_available": False, "presets": {"last": ""}}
        self.last_ir = -1e9   # when an input was last sent by infrared
        self.wake_delay = 3.0   # the LSX needs a moment after wake before it listens to infrared

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
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        return data

    def speaker(self, settings):
        output_id = settings.get("kef_roon_output_id")
        if not output_id: raise ValueError("Choose the KEF's Roon output before enabling listening controls")
        return self.factory(settings.get("kef_host", ""), settings.get("maximum_volume", 50), output_id)

    def refresh(self):
        with self.lock:
            try:
                settings = self.settings()
                self.state["enabled"] = bool(settings.get("enabled"))
                self.state["ir_available"] = bool(settings.get("kef_ir_remote") and self.ir_sender)
                self.state["kef"] = self.speaker(settings).status() if self.state["enabled"] else {"connected": False}
                self.state["error"] = ""
            except (OSError, ValueError, TypeError) as error:
                self.state["kef"] = {"connected": False}
                if isinstance(error, (ValueError, TypeError)):
                    self.state["enabled"] = False
                self.state["error"] = str(error)
            return self.snapshot_unlocked()

    def snapshot_unlocked(self):
        return json.loads(json.dumps(self.state))

    def snapshot(self):
        # Poll/command serialization must never stall the native display's
        # short HTTP timeout when an unreachable speaker takes seconds to fail.
        # Values are replaced, never mutated in place; take a shallow copy first.
        snap = json.loads(json.dumps(dict(self.state)))
        try: snap["streamdeck_brightness"] = int(self.settings().get("streamdeck_brightness", 70))
        except Exception: snap["streamdeck_brightness"] = 70
        return snap

    def command(self, action, value=None):
        with self.lock:
            settings = self.settings()
            if not settings.get("enabled"):
                raise ValueError("Listening controls are disabled")
            if not isinstance(action, str):
                raise ValueError("Action must be a string")
            speaker = self.speaker(settings)
            try:
                self.state["notice"] = ""
                if action == "preset":
                    # One tap: the main input, or toggle between the two presets when an alternate is set.
                    # The presets belong to the Home tile (set in the layout builder) and arrive with the tap.
                    value = value if isinstance(value, dict) else {}
                    primary, alt = value.get("primary") or "", value.get("alt") or ""
                    if primary not in INPUTS or alt not in ("", *INPUTS): raise ValueError("Choose the KEF input in the tile's options")
                    last = self.state.get("presets", {}).get("last", "")
                    action, value = "input", (alt if alt and last == primary else primary)
                if action == "input" and settings.get("kef_ir_remote"):
                    # Inputs are switched with the KEF's own infrared codes, sent by a Home Assistant Broadlink remote.
                    if value not in INPUTS: raise ValueError("Choose a supported KEF input")
                    if self.ir_sender is None: raise ValueError("Home Assistant infrared control is unavailable")
                    woke = False
                    try: status = speaker.status()
                    except OSError: status = {}
                    # Roon only reports "selected" while the KEF is on its Wi-Fi input; on AUX or in a light sleep it can look the same as "on".
                    # So wake unless the KEF is on Wi-Fi, or we sent it an input a few minutes ago (it has not had time to doze off).
                    recent = time.monotonic() - self.last_ir < 600
                    if status.get("powered") is False or (status.get("input") != "wifi" and not recent):
                        speaker.command("power", True)
                        self.confirm(speaker, lambda status: status.get("powered") is True, "The KEF did not wake up")
                        woke = True
                        time.sleep(self.wake_delay)
                    self.ir_sender(settings["kef_ir_remote"], value)
                    self.last_ir = time.monotonic()
                    self.state["ir_available"] = True
                    self.state.setdefault("presets", {})["last"] = value
                    label = value.upper() if value == "aux" else value.title()
                    self.state["notice"] = f"{'Woke the KEF and sent' if woke else 'Sent'} {label} via infrared."
                    self.state["error"] = ""
                    # An IR transmission has no device acknowledgement. Do not invent input feedback.
                    return self.snapshot_unlocked()
                speaker.command(action, value)
                if action in {"power", "volume"}:
                    def confirmed(status):
                        if action == "power": return status.get("powered") == value
                        return status.get("volume") == max(0, min(settings.get("maximum_volume", 50), value))
                    status = self.confirm(speaker, confirmed, f"Roon has not confirmed {action}")
                else:
                    status = speaker.status()
                self.state["kef"] = status
                self.state["error"] = ""
            except (OSError, ValueError) as error:
                if isinstance(error, OSError):
                    self.state["kef"] = {"connected": False}
                self.state["error"] = str(error)
                raise
            return self.snapshot_unlocked()

    def confirm(self, speaker, predicate, message):
        # Poll readback only: never repeat a write, particularly a relative
        # volume or mute command. Acknowledgement alone is not state acceptance.
        for attempt in range(5):
            status = speaker.status()
            self.state["kef"] = status
            if predicate(status): return status
            if attempt < 4: time.sleep(.25)
        raise OSError(message)

    def poll(self, stop):
        while not stop.is_set():
            self.refresh()
            stop.wait(3)


def referenced_entities(settings):
    """Home Assistant entities a saved Stream Deck design uses, so they work without also being listed under Home settings."""
    found = set()
    if settings.get("kef_ir_remote"): found.add(settings["kef_ir_remote"])
    def add(value):
        if isinstance(value, str) and "." in value: found.add(value)
    for binding in [*(settings.get("buttons") or []), *(settings.get("dials") or [])]:
        if not isinstance(binding, dict): continue
        add(binding.get("entity_id")); add(binding.get("entity_id_ccw")); add(binding.get("level_entity"))
        if isinstance(binding.get("press"), dict): add(binding["press"].get("entity_id"))
        if isinstance(binding.get("also"), dict): add(binding["also"].get("entity_id"))
    if isinstance(settings.get("on_play"), dict): add(settings["on_play"].get("script"))
    return found


def remote_step_allowed(settings, value):
    """A remote command may only be one a saved "remote steps" dial can itself produce."""
    if not isinstance(value, dict): return False
    dials = settings.get("dials", [])
    for binding in (*settings.get("buttons", []), *dials, *(dial.get("press") or {} for dial in dials)):
        if value.get("entity_id") != binding.get("entity_id") or value.get("device") != binding.get("device"): continue
        if binding.get("action") == "remote_steps" and any(value.get("command") == binding["command"].replace("{n}", str(number)) for number in range(binding["min"], binding["max"] + 1)):
            return True
        if binding.get("action") == "remote_toggle" and value.get("command") in {binding.get("command_on"), binding.get("command_off")}:
            return True
    return False
