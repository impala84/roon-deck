"""Optional direct USB Stream Deck + driver; runs without Elgato or a Mac."""
from __future__ import annotations

import io
import json
import logging
import queue
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
        entity = next((item for item in request(base, "/api/device/controls").get("home", {}).get("entities", [])
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
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            font = ImageFont.truetype(font_path, 16) if Path(font_path).exists() else ImageFont.load_default()

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
                signature = json.dumps([state, home, error], sort_keys=True)
                if signature == previous: continue
                previous = signature
                speaker = state.get("kef", {})
                for key in range(8):
                    binding = buttons[key] if key < len(buttons) else {}
                    selected = binding.get("action") == "mode" and binding.get("value") == state.get("last_mode")
                    entity = next((item for item in home.get("entities", []) if item.get("entity_id") == binding.get("entity_id")), {})
                    active = selected or entity.get("state") == "on"
                    colour = binding.get("color") or ("#236650" if active else "#11201d")
                    image = Image.new("RGB", (120, 120), colour)
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
                    if active and (binding.get("color") or art): draw.rectangle((0, 0, 119, 119), outline="#6ef0be", width=4)
                    if binding.get("label"): draw.multiline_text((8, 96 if art else 80), str(binding.get("label", ""))[:30], fill="white", font=font)
                    if binding.get("action") == "mode" and not next((mode.get("available") for mode in state.get("modes", []) if mode["id"] == binding.get("value")), False):
                        draw.text((8, 8), "Unavailable", fill="#f2b991", font=font)
                    deck.set_key_image(key, jpeg(image))
                strip = Image.new("RGB", (800, 100), "#11201d"); draw = ImageDraw.Draw(strip)
                for index, binding in enumerate(dials):
                    detail = error or (f"{speaker.get('volume', '?')}%" if speaker.get("connected") else "Offline")
                    if speaker.get("muted"): detail += " · Muted"
                    if binding.get("action") == "home_level":
                        entity = next((item for item in home.get("entities", []) if item.get("entity_id") == binding.get("entity_id")), {})
                        detail = str(entity.get("percentage", round((entity.get("brightness") or 0) / 2.55))) + "%" if entity else "Unavailable"
                    draw.text((index * 200 + 10, 15), str(binding.get("label", ""))[:20], fill="white", font=font)
                    draw.text((index * 200 + 10, 50), detail[:22], fill="#a4dcc7", font=font)
                deck.set_touchscreen_image(jpeg(strip), 0, 0, 800, 100)
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
