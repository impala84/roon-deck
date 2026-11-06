"""Optional direct USB Stream Deck + driver; runs without Elgato or a Mac."""
from __future__ import annotations

import io
import json
import logging
import math
import queue
import time
from datetime import datetime
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

LOG = logging.getLogger(__name__)


def request(base, path, payload=None):
    req = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try: reason = json.load(error).get("error", str(error))
        except (ValueError, AttributeError): reason = str(error)
        raise ValueError(reason) from error


def fetch_bytes(base, path):
    with urllib.request.urlopen(base + path, timeout=6) as response:
        return response.read(3 * 1024 * 1024)


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


_toggles = {}  # (remote, device) -> is the aircon on (assumed: the deck cannot read it back)
_steps = {}   # (remote, command pattern) -> current value of an IR "steps" dial (e.g. aircon temperature)


def step_value(binding):
    return _steps.get((binding.get("entity_id"), binding.get("command")), binding.get("start", binding.get("min", 0)))


def in_window(start, end, now):
    """True when now (a datetime) falls inside start..end ("HH:MM"), including windows that cross midnight."""
    if not start or not end or start == end: return False
    moment = now.strftime("%H:%M")
    return start <= moment < end if start < end else moment >= start or moment < end


_pending_levels = {}   # entity_id -> (target percent, when): Home Assistant's reported level lags behind quick dial turns


def home_level_of(entity):
    pending = _pending_levels.get(entity.get("entity_id"))
    if pending and time.monotonic() - pending[1] < 4: return pending[0]
    level = entity.get("percentage")
    if level is None: level = round((entity.get("brightness") or 0) / 2.55)
    return level


def _home_entities(home):
    """Entities shown on the touchscreen plus the ones that exist only for the Stream Deck."""
    return [*home.get("entities", []), *home.get("deck_entities", [])]


def dispatch(base, binding, delta=None):
    """Run a binding, then its optional "also" follow-up (pause/play Roon or run a Home script)."""
    result = _dispatch(base, binding, delta)
    also = binding.get("also") or {}
    if also.get("action") in {"pause", "play"}:
        request(base, "/roon/api/control", {"action": also["action"]})
    elif also.get("action") == "home_script" and also.get("entity_id"):
        request(base, "/api/listening/command", {"action": "scene", "value": also["entity_id"]})
    return result


def _dispatch(base, binding, delta=None):
    """An allowlist of existing controls, never arbitrary URLs or shell commands."""
    action = binding.get("action")
    if action in {None, "none"}:
        return {}
    if action in {"mode", "power", "input", "volume", "volume_delta", "mute"}:
        value = binding.get("value")
        if action == "volume_delta" and delta is not None:
            value = delta * int(binding.get("step", 1))
        return request(base, "/api/listening/command", {"action": action, "value": value})
    if action == "home_scene":
        return request(base, "/api/listening/command", {"action": "scene", "value": binding.get("entity_id")})
    if action in {"home_script", "home_script_dial"}:
        # A dial turned up runs the first script, turned down the second; one run per click, up to 10 per burst.
        entity = binding.get("entity_id") if not delta or delta > 0 else binding.get("entity_id_ccw")
        if not entity:
            return {}
        result = {}
        for _ in range(max(1, min(10, abs(delta or 1)))):
            result = request(base, "/api/listening/command", {"action": "scene", "value": entity})
        return result
    if action in {"previous", "playpause", "next"}:
        return request(base, "/roon/api/control", {"action": action})
    if action == "home_toggle":
        return request(base, "/api/device/home-toggle", {"entity_id": binding.get("entity_id")})
    if action == "remote_toggle":
        key = (binding["entity_id"], binding["device"])
        on = True if binding.get("off_only") else _toggles.get(key, bool(binding.get("initial_on")))
        result = request(base, "/api/listening/command", {"action": "remote", "value": {
            "entity_id": binding["entity_id"], "device": binding["device"], "command": binding["command_off"] if on else binding["command_on"]}})
        _toggles[key] = not on
        return result
    if action == "remote_steps":
        current = step_value(binding)
        value = max(binding["min"], min(binding["max"], current + (delta or 0) * int(binding.get("step", 1))))
        if value == current: return {"ok": True}
        result = request(base, "/api/listening/command", {"action": "remote", "value": {
            "entity_id": binding["entity_id"], "device": binding["device"], "command": binding["command"].replace("{n}", str(value))}})
        _steps[(binding.get("entity_id"), binding.get("command"))] = value
        _toggles[(binding["entity_id"], binding["device"])] = True   # a temperature command switches the unit on
        return result
    if action == "home_level":
        entity = next((item for item in _home_entities(request(base, "/api/device/controls").get("home", {}))
                       if item["entity_id"] == binding.get("entity_id")), None)
        if not entity or not entity.get("supports_level"):
            raise ValueError("This home device has no level control")
        level = home_level_of(entity)
        # A fan with three speeds ignores a 2% nudge (Home Assistant rounds back up), so never step by less than the fan's own step.
        step = max(int(binding.get("step", 2)), int(round(entity.get("percentage_step") or 0)) if entity.get("domain") == "fan" else 0)
        value = max(0, min(100, level + (delta or 0) * step))
        result = request(base, "/api/device/home-value", {"entity_id": entity["entity_id"], "value": value})
        _pending_levels[entity["entity_id"]] = (value, time.monotonic())
        return result
    raise ValueError("Unsupported Stream Deck action")


class Painter:
    """Draws the key and strip pictures. Drawing problems never take the USB connection down."""

    FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

    def __init__(self, art_dir):
        self.art_dir = Path(art_dir)
        self.fonts = {}
        self.reported = set()

    def load_font(self, size):
        from PIL import ImageFont
        if size in self.fonts: return self.fonts[size]
        face = None
        for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            if Path(self.FONT_DIR + name).exists():
                face = ImageFont.truetype(self.FONT_DIR + name, size); break
        if face is None:
            for found in sorted(Path("/usr/share/fonts").glob("**/*.[ot]tf")):
                if "Bold" in found.name and "Italic" not in found.name:
                    try: face = ImageFont.truetype(str(found), size); break
                    except OSError: continue
        if face is None:
            try: face = ImageFont.load_default(size)  # scalable on Pillow >= 10.1
            except TypeError: face = ImageFont.load_default()
        self.fonts[size] = face
        return face

    def fit_lines(self, draw, text, width, sizes, max_lines):
        """Largest size whose word-wrapped text fits width and max_lines."""
        for size in sizes:
            face = self.load_font(size)
            lines, line = [], ""
            for word in text.split():
                trial = (line + " " + word).strip()
                if draw.textlength(trial, font=face) <= width or not line: line = trial
                else: lines.append(line); line = word
            if line: lines.append(line)
            if len(lines) <= max_lines and all(draw.textlength(item, font=face) <= width for item in lines):
                return face, lines, size
        return face, lines[:max_lines], size

    @staticmethod
    def jpeg(image):
        output = io.BytesIO(); image.save(output, format="JPEG"); return output.getvalue()

    def safe(self, name, size, color, draw_function):
        from PIL import Image
        try: return self.jpeg(draw_function())
        except Exception:
            if name not in self.reported:
                self.reported.add(name); LOG.exception("Stream Deck could not draw %s", name)
            return self.jpeg(Image.new("RGB", size, color))

    def key(self, binding, state, home, cover, elapsed):
        return self.safe(f"key {binding.get('label', '')}", (120, 120), "#11201d", lambda: self._key(binding, state, home, cover, elapsed))

    def strip(self, dials, state, home, error):
        return self.safe("strip", (800, 100), "#11201d", lambda: self._strip(dials, state, home, error))

    def _key(self, binding, state, home, cover, elapsed):
        from PIL import Image, ImageDraw
        selected = binding.get("action") == "mode" and binding.get("value") == state.get("last_mode")
        entity = next((item for item in _home_entities(home) if item.get("entity_id") == binding.get("entity_id")), {})
        active = selected or entity.get("state") == "on"
        # A switched-on key gets its own "on" colour (or a brighter green) instead of an outline.
        image = Image.new("RGB", (120, 120), (binding.get("active_color") or "#236650") if active else (binding.get("color") or "#11201d"))
        playpause = binding.get("action") == "playpause"
        if playpause and cover is not None:
            # Current album artwork behind the control, dimmed so the icon and time stay readable.
            image = Image.blend(cover, Image.new("RGB", (120, 120), "#000000"), .5)
        art = binding.get("image")
        if art:
            # Only operator-controlled artwork adjacent to listening.json.
            path = (self.art_dir / art).resolve()
            if path.is_relative_to(self.art_dir.resolve()) and path.is_file():
                with Image.open(path) as custom:
                    overlay = custom.convert("RGBA").resize((120, 120), getattr(Image, "Resampling", Image).LANCZOS)
                    image.paste(overlay, (0, 0), overlay)
        draw = ImageDraw.Draw(image)
        timed = playpause and elapsed is not None
        if timed:
            draw.text((60, 100), clock(elapsed), fill="white", font=self.load_font(17), anchor="ms", stroke_width=2, stroke_fill="#000000")
        if binding.get("label") and not timed:
            face, lines, size = self.fit_lines(draw, str(binding.get("label", ""))[:30], 104, (20, 18, 16, 14, 12), 3)
            top = 106 - len(lines) * (size + 3)
            for number, text in enumerate(lines):
                draw.text((60, top + number * (size + 3)), text, fill="white", font=face, anchor="ma", stroke_width=2 if art else 0, stroke_fill="#000000")
        if binding.get("action") == "mode" and not next((mode.get("available") for mode in state.get("modes", []) if mode["id"] == binding.get("value")), False):
            draw.text((8, 8), "Unavailable", fill="#f2b991", font=self.load_font(14))
        # Rounded corners: the corners are always the darkest black, whatever the key colour.
        mask = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 119, 119), radius=16, fill=255)
        rounded = Image.new("RGB", (120, 120), "#000000")
        rounded.paste(image, (0, 0), mask)
        return rounded

    def _strip(self, dials, state, home, error):
        from PIL import Image, ImageDraw
        speaker = state.get("kef", {})
        strip = Image.new("RGB", (800, 100), "#11201d"); draw = ImageDraw.Draw(strip)
        for index, binding in enumerate(dials):
            action = binding.get("action")
            if binding.get("color"): draw.rectangle((index * 200, 0, index * 200 + 199, 99), fill=binding["color"])
            if action in {None, "none"}: continue
            left = index * 200 + 12
            text_colour = binding.get("text_color")
            face, lines, _ = self.fit_lines(draw, str(binding.get("label", ""))[:20], 176, (20, 18, 16, 14), 1)
            draw.text((left, 8), lines[0] if lines else "", fill=text_colour or "white", font=face)
            level, detail = None, ""
            if action == "home_level":
                entity = next((item for item in _home_entities(home) if item.get("entity_id") == binding.get("entity_id")), {})
                if entity: level = home_level_of(entity)
                else: detail = "Unavailable"
            elif action == "remote_steps":
                value = step_value(binding); span = max(1, binding["max"] - binding["min"])
                draw.text((left, 32), f"{value}{binding.get('unit', '')}", fill=text_colour or "#a4dcc7", font=self.load_font(30))
                draw.rounded_rectangle((left, 80, left + 172, 85), radius=3, fill="#2c4a42")
                draw.rounded_rectangle((left, 80, left + max(6, round(172 * (value - binding["min"]) / span)), 85), radius=3, fill="#6ef0be")
                press = binding.get("press") or {}
                if press.get("action") == "remote_toggle":
                    is_on = _toggles.get((press.get("entity_id"), press.get("device")), bool(press.get("initial_on")))
                    draw.text((left + 172, 34), "On" if is_on else "Off", fill="#6ef0be" if is_on else "#f2b991", font=self.load_font(26), anchor="ra")
                continue
            elif action == "home_script_dial":
                centre_x, centre_y, radius = left + 88, 60, 22
                draw.arc((centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius), 40, 320, fill="#a4dcc7", width=2)
                for end, direction in ((320, 1), (40, -1)):
                    angle = math.radians(end)
                    px, py = centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle)
                    tx, ty = -math.sin(angle) * direction, math.cos(angle) * direction
                    nx, ny = math.cos(angle), math.sin(angle)
                    draw.polygon([(px + tx * 9, py + ty * 9), (px + nx * 5, py + ny * 5), (px - nx * 5, py - ny * 5)], fill="#a4dcc7")
                continue
            elif speaker.get("connected"):
                level = speaker.get("volume")
                if speaker.get("muted"): detail = "Muted"
            else:
                detail = error or "Offline"
            if level is not None:
                level = max(0, min(100, int(level)))
                draw.text((left, 32), f"{level}%", fill=text_colour or "#a4dcc7", font=self.load_font(30))
                draw.rounded_rectangle((left, 80, left + 172, 85), radius=3, fill="#2c4a42")
                if level: draw.rounded_rectangle((left, 80, left + max(6, round(172 * level / 100)), 85), radius=3, fill="#6ef0be")
                if detail: draw.text((left + 172, 36), detail, fill="#f2b991", font=self.load_font(14), anchor="ra")
            elif detail:
                face, lines, _ = self.fit_lines(draw, detail[:22], 176, (22, 18, 14), 1)
                draw.text((left, 40), lines[0] if lines else "", fill=text_colour or "#a4dcc7", font=face)
        return strip


def run(controls, base, stop):
    """Reconnect after unplug/reboot; serialize commands and coalesce dial bursts."""
    while not stop.is_set():
        deck = None
        try:
            settings = controls.settings()
            if not settings.get("streamdeck_enabled"):
                controls.state["streamdeck"] = {"enabled": False, "connected": False, "error": ""}
                stop.wait(5)
                continue
            controls.state["streamdeck"] = {"enabled": True, "connected": False, "error": "Waiting for Stream Deck +"}
            from StreamDeck.DeviceManager import DeviceManager
            from StreamDeck.Devices.StreamDeck import DialEventType
            from PIL import Image
            decks = DeviceManager().enumerate()
            deck = next((item for item in decks if item.deck_type() == "Stream Deck +"), None)
            if deck is None:
                stop.wait(3)
                continue
            deck.open()
            controls.state["streamdeck"] = {"enabled": True, "connected": True, "error": ""}
            deck.set_brightness(settings.get("streamdeck_brightness", 70))
            events = queue.Queue(maxsize=64)
            buttons = settings.get("buttons", [])[:8]
            dials = settings.get("dials", [])[:4]
            def enqueue(kind, index, amount=1):
                try: events.put_nowait((kind, index, amount))
                except queue.Full: LOG.warning("Stream Deck input queue full")

            deck.set_key_callback(lambda _deck, key, down: enqueue("button", key) if down else None)
            def dial_event(_deck, dial, event, value):
                if event == DialEventType.TURN: enqueue("turn", dial, value)
                elif event == DialEventType.PUSH and value: enqueue("press", dial)
            deck.set_dial_callback(dial_event)
            def touch_event(_deck, event, value):
                if getattr(event, "name", "") == "SHORT": enqueue("press", min(3, value["x"] // 200))
            deck.set_touchscreen_callback(touch_event)

            previous = None
            cover = ["", None]
            painter = Painter(controls.path.parent / "deck-art")
            shown = {}
            refreshed = 0.0
            lit, deck_awake_until = True, 0.0
            error = ""
            settings_signature = json.dumps(settings, sort_keys=True)
            while deck.is_open() and not stop.is_set():
                if json.dumps(controls.settings(), sort_keys=True) != settings_signature:
                    break
                pending = []
                try: pending.append(events.get(timeout=.25))
                except queue.Empty: pass
                while not events.empty():
                    try: pending.append(events.get_nowait())
                    except queue.Empty: break
                # Combine only adjacent turns so button/press ordering is retained.
                combined = []
                for item in pending:
                    if combined and item[0] == "turn" and combined[-1][:2] == item[:2]:
                        old = combined[-1]; combined[-1] = (old[0], old[1], old[2] + item[2])
                    else: combined.append(item)
                for kind, index, amount in combined:
                    bindings = buttons if kind == "button" else dials
                    binding = bindings[index] if index < len(bindings) else {}
                    if kind == "press": binding = binding.get("press", {})
                    if not binding: continue
                    if not lit:
                        # First touch on a sleeping deck only wakes it, so nothing fires blind.
                        deck_awake_until = time.monotonic() + settings.get("streamdeck_awake_seconds", 30); refreshed = 0.0
                        continue
                    try:
                        dispatch(base, binding, amount if kind == "turn" else None)
                        error = ""
                    except (OSError, ValueError, TypeError) as exc:
                        error = str(exc)[:80]; LOG.warning("Stream Deck command failed: %s", exc)
                    controls.state["streamdeck"] = {"enabled": True, "connected": True, "error": error}
                preview = getattr(controls, "brightness_preview", None)
                if preview is not None:
                    controls.brightness_preview = None
                    if lit: deck.set_brightness(preview)
                # Poll the Pi's services once a second (or straight after a press), not four times a second.
                if not combined and time.monotonic() - refreshed < 1.0: continue
                refreshed = time.monotonic()
                sleeping = False
                if time.monotonic() >= deck_awake_until:
                    sleeping = in_window(settings.get("streamdeck_sleep_start"), settings.get("streamdeck_sleep_end"), datetime.now())
                    if not sleeping and settings.get("streamdeck_sleep_with_display", True):
                        try: sleeping = request(base, "/api/display-target").get("target") == "/sleep.html"
                        except (ValueError, OSError): sleeping = False
                if sleeping == lit:
                    lit = not sleeping
                    deck.set_brightness(settings.get("streamdeck_brightness", 70) if lit else 0)
                state = controls.snapshot()
                try: home = request(base, "/api/device/controls").get("home", {})
                except (ValueError, OSError): home = {}
                playing = {}
                if any(item.get("action") == "playpause" for item in buttons):
                    try: playing = request(base, "/roon/api/state").get("zone") or {}
                    except (ValueError, OSError): playing = {}
                track = playing.get("now_playing") or {}
                cover_key = track.get("image_key") or ""
                elapsed = int(playing.get("seek_position") or 0) if track else None
                fresh = {key: value[0] for key, value in _pending_levels.items() if time.monotonic() - value[1] < 4}
                signature = json.dumps([state, home, error, cover_key, elapsed, fresh, sorted(map(str, _steps.items())), sorted(map(str, _toggles.items()))], sort_keys=True)
                if signature == previous: continue
                previous = signature
                if cover_key != cover[0]:
                    cover[0] = cover_key; cover[1] = None
                    if cover_key:
                        try: cover[1] = Image.open(io.BytesIO(fetch_bytes(base, "/roon/api/image?size=240&key=" + urllib.parse.quote(cover_key)))).convert("RGB").resize((120, 120))
                        except Exception: cover[1] = None
                speaker = state.get("kef", {})
                for key in range(8):
                    binding = buttons[key] if key < len(buttons) else {}
                    data = painter.key(binding, state, home, cover[1], elapsed)
                    if shown.get(key) != data:
                        shown[key] = data; deck.set_key_image(key, data)
                strip_data = painter.strip(dials, state, home, error)
                # The elapsed-time tick must not rewrite the strip: needless USB writes are what make the deck drop out.
                if shown.get("strip") != strip_data:
                    shown["strip"] = strip_data; deck.set_touchscreen_image(strip_data, 0, 0, 800, 100)
        except ImportError:
            controls.state["streamdeck"] = {"enabled": True, "connected": False, "error": "Install the optional Stream Deck support packages on the Pi"}
            stop.wait(30)
        except Exception as exc:
            controls.state["streamdeck"] = {"enabled": True, "connected": False, "error": str(exc)[:160]}
            LOG.warning("Stream Deck unavailable: %s", exc)
        finally:
            if deck is not None:
                try: deck.close()
                except Exception: LOG.exception("Could not close Stream Deck")
        stop.wait(3)
