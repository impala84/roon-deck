"""Optional direct USB Stream Deck + driver; runs without Elgato or a Mac."""
from __future__ import annotations

import io
import json
import logging
import math
import queue
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


def _home_entities(home):
    """Entities shown on the touchscreen plus the ones that exist only for the Stream Deck."""
    return [*home.get("entities", []), *home.get("deck_entities", [])]


def dispatch(base, binding, delta=None):
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
    if action == "home_level":
        entity = next((item for item in _home_entities(request(base, "/api/device/controls").get("home", {}))
                       if item["entity_id"] == binding.get("entity_id")), None)
        if not entity or not entity.get("supports_level"):
            raise ValueError("This home device has no level control")
        level = entity.get("percentage")
        if level is None:
            level = round((entity.get("brightness") or 0) / 2.55)
        value = max(0, min(100, level + (delta or 0) * int(binding.get("step", 2))))
        return request(base, "/api/device/home-value", {"entity_id": entity["entity_id"], "value": value})
    raise ValueError("Unsupported Stream Deck action")


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
            from PIL import Image, ImageDraw, ImageFont
            decks = DeviceManager().enumerate()
            deck = next((item for item in decks if item.deck_type() == "Stream Deck +"), None)
            if deck is None:
                stop.wait(3)
                continue
            deck.open()
            controls.state["streamdeck"] = {"enabled": True, "connected": True, "error": ""}
            deck.set_brightness(70)
            events = queue.Queue(maxsize=64)
            buttons = settings.get("buttons", [])[:8]
            dials = settings.get("dials", [])[:4]
            font_dir = "/usr/share/fonts/truetype/dejavu/"

            def load_font(size, bold=True):
                for name in (("DejaVuSans-Bold.ttf", "DejaVuSans.ttf") if bold else ("DejaVuSans.ttf",)):
                    if Path(font_dir + name).exists():
                        return ImageFont.truetype(font_dir + name, size)
                for found in sorted(Path("/usr/share/fonts").glob("**/*.[ot]tf")):
                    if "Bold" in found.name and "Italic" not in found.name:
                        return ImageFont.truetype(str(found), size)
                try: return ImageFont.load_default(size)  # scalable on Pillow >= 10.1
                except TypeError: return ImageFont.load_default()

            def fit_lines(draw, text, width, sizes, max_lines):
                # Largest size whose word-wrapped text fits width and max_lines.
                for size in sizes:
                    face = load_font(size)
                    lines, line = [], ""
                    for word in text.split():
                        trial = (line + " " + word).strip()
                        if draw.textlength(trial, font=face) <= width or not line: line = trial
                        else: lines.append(line); line = word
                    if line: lines.append(line)
                    if len(lines) <= max_lines and all(draw.textlength(item, font=face) <= width for item in lines):
                        return face, lines, size
                return face, lines[:max_lines], size

            font = load_font(18)

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

            def jpeg(image):
                output = io.BytesIO(); image.save(output, format="JPEG"); return output.getvalue()

            previous = None
            cover = ["", None]
            shown = {}
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
                    try:
                        dispatch(base, binding, amount if kind == "turn" else None)
                        error = ""
                    except (OSError, ValueError, TypeError) as exc:
                        error = str(exc)[:80]; LOG.warning("Stream Deck command failed: %s", exc)
                    controls.state["streamdeck"] = {"enabled": True, "connected": True, "error": error}
                state = controls.snapshot()
                home = request(base, "/api/device/controls").get("home", {})
                playing = {}
                if any(item.get("action") == "playpause" for item in buttons):
                    try: playing = request(base, "/roon/api/state").get("zone") or {}
                    except (ValueError, OSError): playing = {}
                track = playing.get("now_playing") or {}
                cover_key = track.get("image_key") or ""
                elapsed = int(playing.get("seek_position") or 0) if track else None
                signature = json.dumps([state, home, error, cover_key, elapsed], sort_keys=True)
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
                    selected = binding.get("action") == "mode" and binding.get("value") == state.get("last_mode")
                    entity = next((item for item in _home_entities(home) if item.get("entity_id") == binding.get("entity_id")), {})
                    active = selected or entity.get("state") == "on"
                    colour = binding.get("color") or ("#236650" if active else "#11201d")
                    image = Image.new("RGB", (120, 120), colour)
                    if binding.get("action") == "playpause" and cover[1] is not None:
                        # Current album artwork behind the control, dimmed so the icon and time stay readable.
                        image = Image.blend(cover[1], Image.new("RGB", (120, 120), "#000000"), .5)
                    art = binding.get("image")
                    if art:
                        # Only operator-controlled artwork adjacent to listening.json.
                        path = (controls.path.parent / "deck-art" / art).resolve()
                        root = (controls.path.parent / "deck-art").resolve()
                        if path.is_relative_to(root) and path.is_file():
                            with Image.open(path) as custom:
                                overlay = custom.convert("RGBA").resize((120, 120), getattr(Image, "Resampling", Image).LANCZOS)
                                image.paste(overlay, (0, 0), overlay)
                    draw = ImageDraw.Draw(image)
                    if binding.get("action") == "playpause" and elapsed is not None:
                        draw.text((60, 113), clock(elapsed), fill="white", font=load_font(17), anchor="ms", stroke_width=2, stroke_fill="#000000")
                    if active and (binding.get("color") or art): draw.rectangle((0, 0, 119, 119), outline="#6ef0be", width=4)
                    timed = binding.get("action") == "playpause" and elapsed is not None
                    if binding.get("label") and not timed:
                        face, lines, size = fit_lines(draw, str(binding.get("label", ""))[:30], 104, (20, 18, 16, 14, 12), 3)
                        top = 116 - len(lines) * (size + 3)
                        for number, text in enumerate(lines):
                            draw.text((8, top + number * (size + 3)), text, fill="white", font=face, stroke_width=2 if art else 0, stroke_fill="#000000")
                    if binding.get("action") == "mode" and not next((mode.get("available") for mode in state.get("modes", []) if mode["id"] == binding.get("value")), False):
                        draw.text((8, 8), "Unavailable", fill="#f2b991", font=font)
                    data = jpeg(image)
                    if shown.get(key) != data:
                        shown[key] = data; deck.set_key_image(key, data)
                strip = Image.new("RGB", (800, 100), "#11201d"); draw = ImageDraw.Draw(strip)
                for index, binding in enumerate(dials):
                    action = binding.get("action")
                    if binding.get("color"): draw.rectangle((index * 200, 0, index * 200 + 199, 99), fill=binding["color"])
                    if action in {None, "none"}: continue
                    left = index * 200 + 12
                    face, lines, _ = fit_lines(draw, str(binding.get("label", ""))[:20], 176, (20, 18, 16, 14), 1)
                    draw.text((left, 8), lines[0] if lines else "", fill="white", font=face)
                    level, detail = None, ""
                    if action == "home_level":
                        entity = next((item for item in _home_entities(home) if item.get("entity_id") == binding.get("entity_id")), {})
                        if entity: level = entity.get("percentage", round((entity.get("brightness") or 0) / 2.55))
                        else: detail = "Unavailable"
                    elif action == "home_script_dial":
                        centre_x, centre_y, radius = left + 88, 60, 22
                        box = (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius)
                        draw.arc(box, 40, 320, fill="#a4dcc7", width=2)
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
                        draw.text((left, 32), f"{level}%", fill="#a4dcc7", font=load_font(30))
                        draw.rounded_rectangle((left, 80, left + 172, 85), radius=3, fill="#2c4a42")
                        if level: draw.rounded_rectangle((left, 80, left + max(6, round(172 * level / 100)), 85), radius=3, fill="#6ef0be")
                        if detail: draw.text((left + 172, 36), detail, fill="#f2b991", font=load_font(14), anchor="ra")
                    elif detail:
                        face, lines, _ = fit_lines(draw, detail[:22], 176, (22, 18, 14), 1)
                        draw.text((left, 40), lines[0] if lines else "", fill="#a4dcc7", font=face)
                strip_data = jpeg(strip)
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
