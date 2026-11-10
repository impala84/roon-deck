from __future__ import annotations

import logging
import argparse
import base64
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import urllib.error
from http.cookies import SimpleCookie
from datetime import datetime, time as wall_time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .config import Config, HOME_ASSISTANT_DOMAINS, load_config, load_env
from .domain import normalise, parse_route_colours
from .lta import LTAError, fetch, simulated
from .observability import OpenObserveLogger, openobserve_endpoint
from . import __version__
from .releases import ReleaseChecker
from .performance import PerformanceHistory
from .remote_access import load_json
from .home_layout import load_layout, save_layout, tint_icon, with_layout
from . import remote_backup, backup_server_client, backup_crypto
from .backup import SECRET_KEYS, build_backup, check_backup, restore_backup
from .listening import referenced_entities, ListeningControls, remote_step_allowed
from .kef_ir import input_command as kef_input_command
from .streamdeck import run as run_streamdeck


CONTROL_REQUEST_LOCK = threading.Lock()
DECK_ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,78}\.png")
ALPINE_SYSTEM_ACTIONS = {
    "update", "reboot", "shutdown", "netdata_enable", "netdata_disable", "netdata_claim",
    "netdata_claim_command", "netdata_install", "netdata_official_install", "netdata_disconnect", "netdata_lightweight", "performance_profile",
    "device_credentials", "install_tools", "install_streamdeck", "display_on", "display_off",
    "set_brightness", "set_display", "set_wifi", "set_hostname", "roon_install", "roon_start", "roon_stop", "roon_restart",
    "airplay_install", "airplay_start", "airplay_stop", "airplay_restart", "airplay_configure", "leds_enable", "leds_disable", "set_audio_hat",
}
SYSTEM_ACTIONS = ALPINE_SYSTEM_ACTIONS | {
    "leds_enable", "leds_disable",
    "set_hostname", "set_wifi", "set_rotation", "set_display",
}


def display_version():
    suffix = " Alpine" if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype" else ""
    return __version__ + suffix


def accessory_request(data, *, helper_action="accessories"):
    """Only called after HTTP authentication. Keep keys out of generic actions."""
    if os.getenv("PI_HOME_APPLIANCE_PLATFORM") != "alpine-prototype":
        raise ValueError("Network controls require the Alpine appliance." if helper_action == "network_control" else "Remote Access and Bluetooth Accessories require the Alpine appliance.")
    payload = json.dumps({**data, "action": helper_action}).encode() + b"\n"
    if len(payload) > 32768: raise ValueError("Accessory request is too large.")
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(60)
            client.connect("/run/pi-home-setup.sock")
            client.sendall(payload)
            reply = client.makefile("rb").readline(32769)
        if len(reply) > 32768: raise ValueError("Accessory response is too large.")
        result = json.loads(reply)
    except TimeoutError as exc:
        raise ValueError("The appliance helper took too long to respond. Refresh status to check installation progress.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("The appliance helper is not responding. Check System diagnostics, then retry.") from exc
    if not result.get("ok"): raise ValueError(result.get("error", "Accessory operation failed."))
    return result


class State:
    def mode_remote_allowed(self, value):
        """An infrared step is allowed when it is exactly one saved in a listening-mode tile."""
        try:
            wanted = {key: value.get(key) for key in ("entity_id", "device", "command")}
            for tile in load_layout(self.state_dir / "home-layout.json").get("tiles", {}).values():
                for step in tile.get("steps") or []:
                    if step.get("do") == "ir" and all(step.get(key) == wanted[key] for key in wanted): return True
        except Exception: pass
        return False

    def home_entity_ids(self):
        """Entities RoonDeck may control: those shared on Home plus any a Stream Deck design uses."""
        try: extra = referenced_entities(self.listening.settings())
        except Exception: extra = set()
        try:   # and the devices, scripts and remotes a listening-mode tile's steps use, so a mode works without each also being shared on Home
            for key, tile in load_layout(self.state_dir / "home-layout.json").get("tiles", {}).items():
                for step in tile.get("steps") or []:
                    if step.get("entity_id"): extra.add(step["entity_id"])
        except Exception: pass
        return (*self.config.home_assistant_entities, *self.config.home_assistant_deck_entities, *sorted(extra))

    def __init__(self, config: Config, state_dir: Path | None = None):
        self.config = config
        self.performance = PerformanceHistory()
        self.lock = threading.Lock()
        self.display_capture = None
        self.display_view_request = None
        self.preview_result = None
        self.preview_capture = None
        self.data: dict = {"status": "starting", "services": []}
        self.last_success: datetime | None = None
        self.last_roon_playing = 0.0
        self.awake_until = 0.0
        self.awake_view = "bus"
        self.screen_powered: bool | None = None   # the touchscreen's own report: lets the Stream Deck follow its idle sleep
        self.manual_mode_signature: tuple[int, str] | None = None
        self.manual_mode_period: str | None = None
        self.state_dir = state_dir or Path(".state")
        try:
            self.display_brightness = max(10, min(100, int((self.state_dir / "display-brightness").read_text(encoding="ascii"))))
        except (OSError, ValueError):
            self.display_brightness = 100
        try:
            saved_services = set(json.loads((self.state_dir / "enabled-services.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            saved_services = set(config.services)
        self.enabled_services: set[str] = saved_services.intersection(config.services)
        self.home_data: dict = {"status": "disabled", "entities": []}
        self.listening = ListeningControls(self.state_dir / "listening.json", ir_sender=self.send_kef_input)

    def snapshot(self) -> dict:
        with self.lock:
            result = dict(self.data)
        now = datetime.now(ZoneInfo(self.config.timezone))
        result.update({
            "now": now.isoformat(), "stop_name": self.config.bus_stop_name,
            "stop_code": self.config.bus_stop_code, "walking_minutes": self.config.walking_minutes,
            "window_active": within_window(self.config, now),
            "roon_display_url": self.config.roon_display_url,
            "roon_display_name": self.config.roon_display_name,
            "display_theme": self.config.display_theme,
            "display_background": self.config.display_background,
            "interface_size": self.config.interface_size,
            "settings_layout": self.config.settings_layout,
            "bus_enabled": self.config.bus_enabled,
            "route_tint": self.config.route_tint,
            "stale": bool(self.last_success and (now - self.last_success).total_seconds() > self.config.stale_after_seconds),
        })
        if self.config.services:
            result["services"] = [item for item in result.get("services", []) if item.get("service") in self.enabled_services]
        return result

    def send_kef_input(self, remote, source):
        if not self.config.home_assistant_enabled: raise ValueError("Enable Home Assistant before using the KEF infrared remote")
        home_assistant_request(self.config, "/api/services/remote/send_command",
            {"entity_id": remote, "command": kef_input_command(source), "num_repeats": 1})

    def controls_snapshot(self) -> dict:
        with self.lock:
            capture_id = self.display_capture["id"] if self.display_capture else None
            view_request = dict(self.display_view_request) if self.display_view_request else None
        return {
            "services": [{"name": service, "enabled": service in self.enabled_services} for service in self.config.services],
            "accessory_features": {name: load_json(self.state_dir / "accessory-features.json", {}).get(name) is True for name in ("vpn", "dial")},
            "home": with_layout(self.home_data, load_layout(self.state_dir / "home-layout.json")),
            "listening": self.listening.snapshot(),
            "display_brightness": self.display_brightness,
            "capture_request": capture_id,
            "display_view_request": view_request,
        }

    def request_display_view(self, view: str, browse_action: str = "", item_key: str = "", section: str = "", settings_page: str = "") -> dict:
        request = {"id": secrets.token_urlsafe(12), "view": view}
        if settings_page:
            request["settings_page"] = settings_page
        if browse_action:
            request.update(browse_action=browse_action, item_key=item_key, section=section)
        with self.lock:
            self.display_view_request = request
            self.preview_result = None
        return dict(request)

    def complete_preview(self, data: dict) -> None:
        with self.lock:
            if not self.display_view_request or data.get("id") != self.display_view_request["id"]:
                raise ValueError("Stale preview acknowledgement")
            self.preview_result = {"id": data["id"], "error": str(data.get("error") or "")[:500],
                "title": str(data.get("title") or "")[:500], "can_back": bool(data.get("can_back")),
                "items": [{key: item.get(key) for key in ("title", "subtitle", "item_key", "action", "hint")} for item in data.get("items", [])[:500] if isinstance(item, dict)]}

    def start_preview_capture(self) -> str:
        with self.lock:
            if self.preview_capture and self.preview_capture["status"] == "loading":
                raise RuntimeError("A screenshot is already being captured")
            ticket = {"id": secrets.token_urlsafe(12), "status": "loading", "image": None, "error": ""}
            self.preview_capture = ticket
        def work():
            try:
                ticket["image"] = self.capture_display()
                ticket["status"] = "ready"
            except Exception as error:
                ticket["error"] = str(error); ticket["status"] = "error"
        threading.Thread(target=work, daemon=True).start()
        return ticket["id"]

    def capture_display(self, timeout: float = 35) -> bytes:
        request = {"id": secrets.token_urlsafe(24), "event": threading.Event(), "image": None, "error": None}
        with self.lock:
            if self.display_capture is not None:
                raise RuntimeError("A display capture is already in progress. Please try again shortly.")
            self.display_capture = request
        try:
            if not request["event"].wait(timeout):
                raise RuntimeError("The touchscreen did not respond. Check that the display service is running.")
            if request["error"]:
                raise RuntimeError(request["error"])
            return request["image"]
        finally:
            with self.lock:
                if self.display_capture is request:
                    self.display_capture = None

    def complete_display_capture(self, data: dict) -> None:
        with self.lock:
            request = self.display_capture
            if request is None or not hmac.compare_digest(str(data.get("id", "")), request["id"]) or request["event"].is_set():
                raise ValueError("No matching display capture request")
            error = str(data.get("error") or "")[:300]
            image = None
            if not error:
                image = base64.b64decode(data.get("image", ""), validate=True)
                if len(image) > 8_388_608 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Invalid display image")
            request["image"] = image
            request["error"] = error
            request["event"].set()

    def save_enabled_services(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_dir / "enabled-services.tmp"
        temporary.write_text(json.dumps(sorted(self.enabled_services)), encoding="utf-8")
        temporary.replace(self.state_dir / "enabled-services.json")

    def save_display_brightness(self, value: int) -> None:
        self.display_brightness = max(10, min(100, int(value)))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_dir / "display-brightness.tmp"
        temporary.write_text(f"{self.display_brightness}\n", encoding="ascii")
        temporary.replace(self.state_dir / "display-brightness")


def within_window(config: Config, now: datetime) -> bool:
    start = wall_time.fromisoformat(config.morning_start)
    end = wall_time.fromisoformat(config.morning_end)
    return start <= now.timetz().replace(tzinfo=None) < end


def automatic_display_wake_ready(config: Config, now: datetime) -> bool:
    """Whether the configured morning wake has occurred on this local day."""
    weekend = now.weekday() >= 5
    if not config.scheduled_wake_enabled or (weekend and not config.weekend_wake_enabled):
        return False
    start = wall_time.fromisoformat(config.weekend_wake_time if weekend else config.sleep_end)
    return now.timetz().replace(tzinfo=None) >= start


def within_sleep_window(config: Config, now: datetime) -> bool:
    current = now.timetz().replace(tzinfo=None)
    start = wall_time.fromisoformat(config.sleep_start)
    end = wall_time.fromisoformat(config.sleep_end)
    return start <= current < end if start < end else current >= start or current < end


def scheduled_period(config: Config, now: datetime) -> str:
    """Name the current scheduled period so a manual override expires at its next boundary."""
    if within_sleep_window(config, now):
        return "sleep"
    if within_window(config, now):
        return "morning"
    return "day"


def poll(state: State, stop: threading.Event, events: OpenObserveLogger | None = None) -> None:
    last_status: str | None = None
    while not stop.is_set():
        config = state.config
        if not config.bus_enabled:
            stop.wait(2)
            continue
        timezone = ZoneInfo(config.timezone)
        now = datetime.now(timezone)
        try:
            payload = simulated(now, config.services) if config.simulate else fetch(os.getenv("LTA_ACCOUNT_KEY", ""), config.bus_stop_code)
            services = normalise(payload, now, config.services, config.walking_minutes, parse_route_colours(config.service_colours))
            with state.lock:
                state.data = {"status": "ok", "services": services, "updated_at": now.isoformat(), "error": None}
                state.last_success = now
            status = "ok"
        except LTAError as exc:
            with state.lock:
                state.data = {**state.data, "status": "offline", "error": str(exc)}
            status = "offline"

        if status != last_status and events:
            events.emit("bus.source.status", level="error" if status == "offline" else "info", status=status)
        last_status = status

        stop.wait(config.poll_seconds)


def home_assistant_request(config: Config, path: str, payload: dict | None = None) -> object:
    base = config.home_assistant_url.rstrip("/")
    token = os.getenv("HOME_ASSISTANT_TOKEN", "")
    if not base or not token:
        raise ValueError("Home Assistant URL or token is missing")
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base + path, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=2.5) as response:
        return json.load(response)


def home_assistant_set_value(config: Config, entity_id: str, value: int) -> object:
    domain = entity_id.split(".", 1)[0]
    value = max(0, min(100, int(value)))
    if domain == "fan":
        return home_assistant_request(config, "/api/services/fan/set_percentage", {"entity_id": entity_id, "percentage": value})
    if domain == "light":
        return home_assistant_request(config, "/api/services/light/turn_on", {"entity_id": entity_id, "brightness_pct": value})
    if domain == "climate":
        attributes = (home_assistant_request(config, "/api/states/" + entity_id) or {}).get("attributes") or {}
        return home_assistant_request(config, "/api/services/climate/set_temperature", {"entity_id": entity_id, "temperature": climate_target(attributes, value)})
    raise ValueError("This device has no adjustable level")


def climate_range(attributes):
    low, high = attributes.get("min_temp"), attributes.get("max_temp")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and high > low: return float(low), float(high)
    return None


def climate_target(attributes, percent):
    """The temperature a 0-100 slider position stands for, rounded to the unit's own step."""
    span = climate_range(attributes)
    if span is None: raise ValueError("This air conditioner has no temperature range")
    step = attributes.get("target_temp_step") or 1
    step = float(step) if isinstance(step, (int, float)) and step > 0 else 1.0
    value = span[0] + (span[1] - span[0]) * max(0, min(100, percent)) / 100
    return round(min(span[1], max(span[0], round(value / step) * step)), 2)


def climate_percent(attributes):
    span, temperature = climate_range(attributes), attributes.get("temperature")
    if span is None or not isinstance(temperature, (int, float)): return None
    return round(100 * (min(span[1], max(span[0], temperature)) - span[0]) / (span[1] - span[0]))


def home_assistant_set_state(config: Config, entity_id: str, enabled: bool) -> object:
    domain = entity_id.split(".", 1)[0]
    if domain not in {"fan", "light", "switch", "input_boolean", "climate"}:
        raise ValueError("This entity type cannot be controlled")
    service = "turn_on" if enabled else "turn_off"
    return home_assistant_request(config, f"/api/services/{domain}/{service}", {"entity_id": entity_id})


def home_assistant_group(state: "State", entity_id: str) -> list[str]:
    """The device plus any others its tile switches with it (e.g. two Pi-holes behind one toggle)."""
    try: tile = load_layout(state.state_dir / "home-layout.json")["tiles"].get(entity_id) or {}
    except Exception: tile = {}
    return [entity_id, *[item for item in tile.get("also", []) if item != entity_id]]


def home_assistant_switch_group(state: "State", entity_id: str, enabled: bool | None = None) -> bool:
    """Switch a tile's linked devices together. Returns False when the tile has none, so the caller does the normal single-device action."""
    group = home_assistant_group(state, entity_id)
    if len(group) < 2: return False
    if enabled is None:
        current = next((item for item in state.home_data.get("entities", []) if item.get("entity_id") == entity_id), {})
        enabled = not current.get("on")   # everything on switches off; off or mixed switches everything on
    for item in group: home_assistant_set_state(state.config, item, enabled)
    return True


def home_assistant_activate(config: Config, entity_id: str) -> object:
    domain = entity_id.split(".", 1)[0]
    if domain not in {"scene", "script"}:
        raise ValueError("This entity is not a scene or script")
    return home_assistant_request(config, f"/api/services/{domain}/turn_on", {"entity_id": entity_id})


def home_assistant_entity_available(domain: str, entity_state: object) -> bool:
    # A scene has no persistent on/off state. Home Assistant commonly reports
    # an unactivated scene as unknown until it has been run for the first time.
    # Only its explicit unavailable state should disable the action button.
    if domain in {"scene", "script"}:
        return entity_state != "unavailable"
    return entity_state not in {"unavailable", "unknown"}


def play_trigger_watch(state: State, stop: threading.Event) -> None:
    """When Roon starts playing, run a Home Assistant script (e.g. select the DAC's optical input) unless a helper says it is already set."""
    previous = None
    while not stop.is_set():
        stop.wait(2)
        roon = roon_status()
        playing = ((roon or {}).get("zone") or {}).get("state") == "playing" if roon else None
        if playing is None:
            continue
        started = playing and previous is False
        previous = playing
        if not started:
            continue
        try:
            trigger = state.listening.settings().get("on_play") or {}
            if not trigger.get("script") or not state.config.home_assistant_enabled:
                continue
            if trigger.get("helper") and trigger.get("value"):
                current = home_assistant_request(state.config, "/api/states/" + trigger["helper"])
                if isinstance(current, dict) and str(current.get("state", "")).lower() == trigger["value"].lower():
                    continue
            home_assistant_activate(state.config, trigger["script"])
        except Exception as error:
            LOG.warning("Play trigger failed: %s", error)


def home_assistant_poll(state: State, stop: threading.Event, events: OpenObserveLogger | None = None) -> None:
    last_status: str | None = None
    while not stop.is_set():
        config = state.config
        if not config.home_assistant_enabled or not (config.home_assistant_entities or config.home_assistant_deck_entities or referenced_entities(state.listening.settings())):
            state.home_data = {"status": "disabled", "entities": [], "deck_entities": []}
            if last_status != "disabled" and events:
                events.emit("home_assistant.status", status="disabled")
            last_status = "disabled"
            stop.wait(5)
            continue
        try:
            raw = home_assistant_request(config, "/api/states")
            layout_tiles = load_layout(state.state_dir / "home-layout.json").get("tiles", {})
            linked = {entity_id: tile.get("also", []) for entity_id, tile in layout_tiles.items() if tile.get("also") and entity_id in config.home_assistant_entities}
            also_ids = {item for group in linked.values() for item in group}
            shown = set(config.home_assistant_entities) | set(config.home_assistant_deck_entities) | referenced_entities(state.listening.settings())
            selected = shown | also_ids
            by_id = {str(item.get("entity_id", "")): item for item in raw if isinstance(item, dict)} if isinstance(raw, list) else {}
            entities = []
            for item in raw if isinstance(raw, list) else []:
                entity_id = str(item.get("entity_id", ""))
                if entity_id not in selected:
                    continue
                domain = entity_id.split(".", 1)[0]
                attributes = item.get("attributes") or {}
                raw_state = item.get("state", "unknown")
                entry = {
                    "entity_id": entity_id, "domain": domain, "state": raw_state,
                    "name": attributes.get("friendly_name") or entity_id.split(".", 1)[-1].replace("_", " ").title(),
                    "percentage": attributes.get("percentage"), "percentage_step": attributes.get("percentage_step"), "brightness": attributes.get("brightness"),
                    "action": domain in {"scene", "script"}, "available": home_assistant_entity_available(domain, raw_state),
                    "supports_level": bool(
                        (domain == "fan" and (attributes.get("percentage") is not None or attributes.get("percentage_step") is not None))
                        or (domain == "light" and attributes.get("supported_color_modes") not in (None, [], ["onoff"]))
                        or (domain == "climate" and climate_percent(attributes) is not None)
                    ),
                    "on": raw_state in {"on", "open", "playing"} or (domain == "climate" and raw_state not in {"off", "unavailable", "unknown"}),
                }
                if domain == "climate":
                    entry["percentage"] = climate_percent(attributes)
                    temperature = attributes.get("temperature")
                    if isinstance(temperature, (int, float)): entry["detail"] = f"{temperature:g} °C"
                if entity_id in linked:
                    states = [raw_state] + [str((by_id.get(other) or {}).get("state", "unknown")) for other in linked[entity_id]]
                    on_count = sum(1 for value in states if value == "on")
                    entry["state"] = "on" if on_count == len(states) else "off" if on_count == 0 else "mixed"
                    entry["on"] = on_count == len(states)
                    entry["linked_total"], entry["linked_on"] = len(states), on_count
                    entry["available"] = all(value not in {"unavailable", "unknown"} for value in states)
                entities.append(entry)
            order = {entity_id: index for index, entity_id in enumerate(config.home_assistant_entities)}
            deck_only = [item for item in entities if item["entity_id"] not in order and item["entity_id"] in shown]
            entities = sorted((item for item in entities if item["entity_id"] in order), key=lambda item: order[item["entity_id"]])
            state.home_data = {"status": "ok", "entities": entities, "deck_entities": deck_only, "updated_at": datetime.now(ZoneInfo(config.timezone)).isoformat()}
            status = "ok"
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            state.home_data = {"status": "offline", "entities": [], "error": str(exc)}
            status = "offline"
        if status != last_status and events:
            events.emit("home_assistant.status", level="error" if status == "offline" else "info", status=status)
        last_status = status
        stop.wait(3)


def write_config(path: Path, config: Config) -> None:
    services = ", ".join(json.dumps(item) for item in config.services)
    content = "\n".join((
        f"release_channel = {json.dumps(config.release_channel)}",
        f"auto_update_enabled = {str(config.auto_update_enabled).lower()}",
        f"auto_update_time = {json.dumps(config.auto_update_time)}",
        f"bus_stop_code = {json.dumps(config.bus_stop_code)}",
        f"bus_stop_name = {json.dumps(config.bus_stop_name)}",
        f"services = [{services}]",
        f"service_colours = {json.dumps(config.service_colours)}",
        f"route_tint = {config.route_tint}",
        f"walking_minutes = {config.walking_minutes}",
        f"poll_seconds = {config.poll_seconds}",
        f"stale_after_seconds = {config.stale_after_seconds}",
        f"morning_start = {json.dumps(config.morning_start)}",
        f"morning_end = {json.dumps(config.morning_end)}",
        f"scheduled_wake_enabled = {str(config.scheduled_wake_enabled).lower()}",
        f"weekend_wake_enabled = {str(config.weekend_wake_enabled).lower()}",
        f"weekend_wake_time = {json.dumps(config.weekend_wake_time)}",
        f"sleep_start = {json.dumps(config.sleep_start)}",
        f"sleep_end = {json.dumps(config.sleep_end)}",
        f"timezone = {json.dumps(config.timezone)}",
        f"roon_display_url = {json.dumps(config.roon_display_url)}",
        f"roon_zone_name = {json.dumps(config.roon_zone_name)}",
        f"roon_core_host = {json.dumps(config.roon_core_host)}",
        f"roon_display_name = {json.dumps(config.roon_display_name)}",
        f"display_theme = {json.dumps(config.display_theme)}",
        f"display_background = {json.dumps(config.display_background)}",
        f"interface_size = {json.dumps(config.interface_size)}",
        f"settings_layout = {json.dumps(config.settings_layout)}",
        f"touch_roon_bridge = {str(config.touch_roon_bridge).lower()}",
        f"touch_airplay = {str(config.touch_airplay).lower()}",
        f"touch_netdata = {str(config.touch_netdata).lower()}",
        f"portrait_discovery_columns = {config.portrait_discovery_columns}",
        f"landscape_music_clock = {json.dumps(config.landscape_music_clock)}",
        f"bus_enabled = {str(config.bus_enabled).lower()}",
        f"roon_now_playing_name = {json.dumps(config.roon_now_playing_name)}",
        f"roon_queue_name = {json.dumps(config.roon_queue_name)}",
        f"sleep_when_roon_idle = {str(config.sleep_when_roon_idle).lower()}",
        f"roon_show_controls = {str(config.roon_show_controls).lower()}",
        f"roon_show_clock = {str(config.roon_show_clock).lower()}",
        f"roon_show_queue = {str(config.roon_show_queue).lower()}",
        f"roon_show_browser = {str(config.roon_show_browser).lower()}",
        f"bluos_enabled = {str(config.bluos_enabled).lower()}",
        f"bluos_player_address = {json.dumps(config.bluos_player_address)}",
        "bluos_visible_inputs = [" + ", ".join(json.dumps(item) for item in config.bluos_visible_inputs) + "]",
        "bluos_input_names = [" + ", ".join(json.dumps(item) for item in config.bluos_input_names) + "]",
        f"sleep_show_clock = {str(config.sleep_show_clock).lower()}",
        f"auto_switch_to_roon = {str(config.auto_switch_to_roon).lower()}",
        f"roon_idle_return_seconds = {config.roon_idle_return_seconds}",
        f"browse_idle_return_seconds = {config.browse_idle_return_seconds}",
        f"outside_hours_wake_seconds = {config.outside_hours_wake_seconds}",
        f"remote_wake_seconds = {config.remote_wake_seconds}",
        f"daytime_inactivity_seconds = {config.daytime_inactivity_seconds}",
        f"home_assistant_enabled = {str(config.home_assistant_enabled).lower()}",
        f"home_assistant_title = {json.dumps(config.home_assistant_title)}",
        f"home_assistant_url = {json.dumps(config.home_assistant_url)}",
        "home_assistant_entities = [" + ", ".join(json.dumps(item) for item in config.home_assistant_entities) + "]",
        "home_assistant_deck_entities = [" + ", ".join(json.dumps(item) for item in config.home_assistant_deck_entities) + "]",
        f"home_assistant_color_mode = {json.dumps(config.home_assistant_color_mode)}",
        f"home_assistant_single_color = {json.dumps(config.home_assistant_single_color)}",
        f"home_assistant_light_color = {json.dumps(config.home_assistant_light_color)}",
        f"home_assistant_fan_color = {json.dumps(config.home_assistant_fan_color)}",
        f"home_assistant_switch_color = {json.dumps(config.home_assistant_switch_color)}",
        f"home_assistant_scene_color = {json.dumps(config.home_assistant_scene_color)}",
        f"openobserve_enabled = {str(config.openobserve_enabled).lower()}",
        f"openobserve_url = {json.dumps(config.openobserve_url)}",
        f"openobserve_org = {json.dumps(config.openobserve_org)}",
        f"openobserve_stream = {json.dumps(config.openobserve_stream)}",
        f"openobserve_username = {json.dumps(config.openobserve_username)}",
        f"end_action = {json.dumps(config.end_action)}",
        "",
    ))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o640)
    temporary.replace(path)


def update_secret(path: Path, key: str, value: str) -> None:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, current = line.split("=", 1)
                values[name.strip()] = current.strip()
    values[key] = value
    temporary = path.with_suffix(".tmp")
    temporary.write_text("".join(f"{name}={current}\n" for name, current in values.items()), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.environ[key] = value


def read_display_mode(path: Path) -> str:
    try:
        mode = path.read_text(encoding="utf-8").strip()
        return mode if mode in {"auto", "bus", "roon", "home", "sleep"} else "auto"
    except OSError:
        return "auto"


def set_display_mode(state: State, path: Path, mode: str) -> None:
    if mode not in {"auto", "bus", "roon", "home", "sleep"}:
        raise ValueError("Display mode must be auto, bus, roon, home or sleep")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode + "\n", encoding="utf-8")
    if mode == "sleep":
        # An earlier tap-to-wake grants a temporary awake period. An explicit
        # Sleep command must supersede it, otherwise the next target poll
        # immediately wakes the panel again.
        state.awake_until = 0.0


def clear_sleep_mode_on_start(path: Path) -> None:
    """Never carry an explicit black-screen override across a service restart."""
    if read_display_mode(path) != "sleep":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("auto\n", encoding="utf-8")
    temporary.replace(path)


LOG = logging.getLogger(__name__)

def roon_status() -> dict | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/api/state", timeout=0.35) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


_CHECK_ROON = object()


def display_target(
    config: Config,
    mode_path: Path,
    roon: dict | None | object = _CHECK_ROON,
    now: datetime | None = None,
) -> str:
    mode = read_display_mode(mode_path)
    if mode == "sleep":
        return "/sleep.html"
    if mode == "home":
        return "/home"
    if not config.bus_enabled and mode == "bus":
        if roon is _CHECK_ROON: roon = roon_status()
        return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"
    if mode in {"roon", "auto"} and roon is _CHECK_ROON:
        roon = roon_status()
    if mode == "roon":
        return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"
    if mode == "auto":
        now = now or datetime.now(ZoneInfo(config.timezone))
        if within_sleep_window(config, now):
            return "/sleep.html"
        if not config.bus_enabled:
            if config.sleep_when_roon_idle and ((roon or {}).get("zone") or {}).get("state") != "playing": return "/sleep.html"
            return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"
        if not within_window(config, now):
            if roon is None:
                return "/roon-unavailable.html"
            if config.sleep_when_roon_idle and isinstance(roon, dict) and roon.get("zone", {}).get("state") != "playing":
                return "/sleep.html"
            return "http://127.0.0.1:8766/"
    return "/"


def automatic_display_target(state: State, mode_path: Path, roon: dict | None, now: datetime | None = None) -> str:
    """Resolve Automatic mode with playback grace and temporary touch wake."""
    mode = read_display_mode(mode_path)
    now = now or datetime.now(ZoneInfo(state.config.timezone))
    monotonic = time.monotonic()
    if mode != "auto":
        try:
            signature = (mode_path.stat().st_mtime_ns, mode)
        except OSError:
            signature = (0, mode)
        if signature != state.manual_mode_signature:
            state.manual_mode_signature = signature
            try:
                set_at = datetime.fromtimestamp(mode_path.stat().st_mtime, ZoneInfo(state.config.timezone))
            except OSError:
                set_at = now
            state.manual_mode_period = scheduled_period(state.config, set_at)
        if scheduled_period(state.config, now) == state.manual_mode_period:
            if mode == "sleep" and monotonic < state.awake_until:
                return "http://127.0.0.1:8766/" if (state.awake_view == "roon" or not state.config.bus_enabled) and roon is not None else "/" if state.config.bus_enabled else "/roon-unavailable.html"
            return display_target(state.config, mode_path, roon, now)
        mode_path.write_text("auto\n", encoding="utf-8")
        state.manual_mode_signature = None
        state.manual_mode_period = None
        mode = "auto"
    else:
        state.manual_mode_signature = None
        state.manual_mode_period = None
    zone_state = ((roon or {}).get("zone") or {}).get("state")
    if zone_state == "playing":
        state.last_roon_playing = monotonic
    playback_recent = bool(
        state.last_roon_playing
        and monotonic - state.last_roon_playing <= state.config.roon_idle_return_seconds
    )
    if zone_state == "playing" or (state.config.auto_switch_to_roon and playback_recent):
        return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"
    if monotonic < state.awake_until:
        return "http://127.0.0.1:8766/" if (state.awake_view == "roon" or not state.config.bus_enabled) and roon is not None else "/" if state.config.bus_enabled else "/roon-unavailable.html"
    if within_sleep_window(state.config, now):
        return "/sleep.html"
    if not state.config.bus_enabled:
        if state.config.sleep_when_roon_idle: return "/sleep.html"
        return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"
    if not automatic_display_wake_ready(state.config, now):
        return "/sleep.html"
    if state.config.auto_switch_to_roon:
        return "/"
    if within_window(state.config, now):
        return "/"
    if state.config.sleep_when_roon_idle:
        return "/sleep.html"
    return "http://127.0.0.1:8766/" if roon is not None else "/roon-unavailable.html"


def command_output(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=2, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def diagnostics_snapshot(config: Config | None = None) -> dict:
    memory: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, value = line.split(":", 1)
            memory[name] = int(value.strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", memory.get("MemFree", 0))
    swap_total = memory.get("SwapTotal", 0)
    swap_free = memory.get("SwapFree", 0)
    groups = {
        "display": {"label": "GTK display + Cage", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
        "api": {"label": "Bus data service", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
        "controller": {"label": "Roon controller", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
        "bridge": {"label": "Roon Bridge", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
        "airplay": {"label": "AirPlay · Shairport Sync", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
        "netdata": {"label": "Netdata", "rss_kb": 0, "cpu_percent": 0.0, "pids": [], "active": False},
    }
    for line in command_output(["ps", "-eo", "pid=,rss=,pcpu=,args="]).splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) != 4:
            continue
        pid, rss, cpu, args = parts
        lowered = args.lower()
        executable = lowered.split()[0]
        group = None
        if "roondeck_native.py" in lowered or "/cage" in lowered:
            group = "display"
        elif "roon-controller/server.js" in lowered:
            group = "controller"
        elif "roonbridge" in lowered or "roon bridge" in lowered:
            group = "bridge"
        elif "shairport-sync" in lowered:
            group = "airplay"
        elif Path(executable).name == "netdata" or executable.startswith(("/opt/netdata/usr/libexec/netdata/", "/usr/libexec/netdata/", "/usr/lib/netdata/")):
            group = "netdata"
        elif ("pi-bus-time-display" in lowered or "/pi-home " in lowered) and "native" not in lowered:
            group = "api"
        if group:
            try:
                groups[group]["rss_kb"] += int(rss)
                groups[group]["cpu_percent"] += float(cpu)
                groups[group]["pids"].append(int(pid))
                groups[group]["active"] = True
            except ValueError:
                pass
    alpine = os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype"
    services = {"controller": "pi-home-roon", "api": "pi-home-api", "display": "pi-home-display", "bridge": "roonbridge", "airplay": "shairport-sync"} if alpine else {"controller": "pi-bus-roon-controller.service", "api": "pi-bus-time-display.service", "display": "pi-bus-native.service", "bridge": "roonbridge.service", "airplay": "shairport-sync.service"}
    for group, service in services.items():
        groups[group]["active"] = service_state(service) == "running" or groups[group]["active"]
    if not alpine:
        groups["bridge"]["active"] = service_state("RoonBridge.service") == "running" or groups["bridge"]["active"]
    visible = set(groups)
    if config is not None:
        if not config.roon_zone_name.strip():
            visible.discard("controller")
        if not config.bus_enabled:
            groups["api"]["label"] = "RoonDeck backend"
        # Optional tools are shown when running, or enabled at boot so failures
        # remain diagnosable. A deliberately stopped endpoint is not an idle row.
        bridge_enabled = Path("/etc/runlevels/default/roonbridge").exists() if alpine else command_output(["systemctl", "is-enabled", "roonbridge.service"]) == "enabled" or command_output(["systemctl", "is-enabled", "RoonBridge.service"]) == "enabled"
        if not groups["bridge"]["active"] and not bridge_enabled:
            visible.discard("bridge")
        airplay_enabled = Path("/etc/runlevels/default/shairport-sync").exists() if alpine else command_output(["systemctl", "is-enabled", "shairport-sync.service"]) == "enabled"
        if not groups["airplay"]["active"] and not airplay_enabled:
            visible.discard("airplay")
    try:
        uptime = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        uptime = 0
    try:
        load = list(os.getloadavg())
    except OSError:
        load = [0, 0, 0]
    try:
        temperature = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="ascii")) / 1000, 1)
    except (OSError, ValueError):
        temperature = None
    throttled = command_output(["vcgencmd", "get_throttled"])
    return {
        "memory": {
            "total_kb": total, "available_kb": available,
            "used_kb": max(0, total - available),
            "used_percent": round((total - available) * 100 / total, 1) if total else 0,
        },
        "swap": {"total_kb": swap_total, "used_kb": max(0, swap_total - swap_free)},
        "load": load, "cpu_count": os.cpu_count() or 1, "uptime_seconds": round(uptime),
        "temperature_c": temperature,
        "throttled": throttled.split("=", 1)[-1] if "=" in throttled else "unknown",
        "processes": [value for key, value in groups.items() if key in visible and (key != "netdata" or value["active"])],
    }


def active_wifi_ssid() -> str:
    connections = command_output(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    profile = next((line.rsplit(":", 1)[0] for line in connections.splitlines() if line.rsplit(":", 1)[-1] in {"802-11-wireless", "wifi"}), "")
    if not profile:
        return ""
    ssid = command_output(["nmcli", "--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show", profile])
    return ssid or profile


def connected_network_snapshot() -> dict:
    """Return useful, non-sensitive details for the active network link."""
    rows = command_output(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    # Only a physical link counts: a WireGuard, bridge or loopback entry stays "connected" with the cable unplugged.
    active = next((fields for fields in (line.split(":", 3) for line in rows.splitlines() if ":connected:" in line) if len(fields) == 4 and fields[1] in {"ethernet", "wifi", "802-11-wireless"}), [])
    if len(active) != 4:
        return {"name": active_wifi_ssid(), "interface": "", "type": "", "address": "", "signal": "", "speed": ""}
    interface, link_type, _, connection = active
    name = active_wifi_ssid() if link_type in {"wifi", "802-11-wireless"} else connection
    address_output = command_output(["ip", "-4", "-o", "addr", "show", "dev", interface])
    address_match = re.search(r"\binet\s+([^\s]+)", address_output)
    signal = ""
    speed = ""
    if link_type in {"wifi", "802-11-wireless"}:
        # NetworkManager is part of every RoonDeck image, whereas `iw` is not.
        # Ask it for the active access point so the web UI works on both the
        # original and current Alpine images without another package install.
        access_points = command_output(["nmcli", "--escape", "no", "-t", "-f", "IN-USE,SIGNAL,RATE", "device", "wifi", "list", "ifname", interface])
        active_access_point = next((line.split(":", 2) for line in access_points.splitlines() if line.startswith(("yes:", "*:"))), [])
        if len(active_access_point) == 3:
            signal = f"{active_access_point[1]}%" if active_access_point[1].isdigit() else active_access_point[1]
            speed = active_access_point[2]
        if not signal or not speed:
            link = command_output(["iw", "dev", interface, "link"])
            signal_match = re.search(r"signal:\s*(-?\d+)\s*dBm", link, re.I)
            speed_match = re.search(r"(?:rx|tx) bitrate:\s*([\d.]+\s*\w+/s)", link, re.I)
            signal = signal or (f"{signal_match.group(1)} dBm" if signal_match else "")
            speed = speed or (speed_match.group(1) if speed_match else "")
    else:
        raw_speed = command_output(["cat", f"/sys/class/net/{interface}/speed"])
        speed = f"{raw_speed} Mb/s" if raw_speed.isdigit() else ""
    return {"name": name, "interface": interface, "type": "Wi-Fi" if link_type in {"wifi", "802-11-wireless"} else "Ethernet" if link_type == "ethernet" else link_type, "address": address_match.group(1) if address_match else "", "signal": signal, "speed": speed}


def service_state(name: str) -> str:
    """Return a small, truthful systemd state without keeping a preference."""
    if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype":
        service = name.removesuffix(".service")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", service) or not Path("/etc/init.d", service).is_file():
            return "not_installed"
        result = command_output(["rc-service", service, "status"])
        return "running" if "started" in result.lower() else "stopped"
    if command_output(["systemctl", "show", name, "--property=LoadState", "--value"]) != "loaded":
        return "not_installed"
    return "running" if command_output(["systemctl", "is-active", name]) == "active" else "stopped"


def display_orientation(profile: str, rotation: str) -> str:
    native_portrait = profile.startswith("touch2-")
    portrait = rotation in ({"normal", "180"} if native_portrait else {"90", "270"})
    return "portrait" if portrait else "landscape"


def display_mounting(rotation: str) -> str:
    return "inverted" if rotation in {"180", "270"} else "standard"


def display_config_dir() -> Path:
    return Path("/etc/pi-home" if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype" else "/etc/pi-bus-time-display")


def pi_led_state(state_dir: Path) -> str:
    names = {item.name.lower() for item in Path("/sys/class/leds").glob("*")}
    if not names.intersection({"act", "pwr", "led0", "led1"}):
        return "not_installed"
    try:
        enabled = (state_dir / "leds-enabled").read_text(encoding="ascii").strip() == "true"
    except OSError:
        enabled = False
    return "enabled" if enabled else "disabled"


def current_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return ""


def netdata_snapshot() -> dict:
    service = service_state("netdata.service")
    static_agent = Path("/opt/netdata/bin/netdata")
    installed = service != "not_installed" or static_agent.is_file()
    details = {"service": service if installed else "not_installed", "installed": installed, "version": "", "cloud_status": "unclaimed", "claim_id": ""}
    if not details["installed"]:
        return details
    if details["service"] == "not_installed": details["service"] = "stopped"
    version = command_output([str(static_agent) if static_agent.is_file() else "netdata", "-v"])
    details["version"] = version.replace("netdata ", "", 1).strip() if version and version != "unknown" else "Installed"
    try:
        with urllib.request.urlopen("http://127.0.0.1:19999/api/v1/aclk", timeout=.8) as response:
            aclk_json = json.load(response)
        details["service"] = "running"
        claimed = bool(aclk_json.get("agent-claimed")); online = bool(aclk_json.get("online"))
        details["cloud_status"] = "online" if claimed and online else "offline" if claimed else "unclaimed"
        details["claim_id"] = str(aclk_json.get("claimed-id") or "")
        details["cloud_available"] = bool(aclk_json.get("aclk-available"))
    except (OSError, ValueError, json.JSONDecodeError):
        static_cli = Path("/opt/netdata/bin/netdatacli")
        aclk = command_output([str(static_cli) if static_cli.is_file() else "netdatacli", "aclk-state"])
        if aclk and aclk != "unknown":
            fields = {key.strip().lower(): value.strip() for line in aclk.splitlines() if ":" in line for key, value in [line.split(":", 1)]}
            claimed = fields.get("claimed", "").lower() in {"yes", "true", "1"}
            online = fields.get("online", "").lower() in {"yes", "true", "1"}
            details["cloud_status"] = "online" if claimed and online else "offline" if claimed else "unclaimed"
            details["claim_id"] = fields.get("claimed id", "")
    return details


def system_snapshot(state_dir: Path, include_diagnostics: bool = False, config: Config | None = None) -> dict:
    if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype":
        roon_service = service_state("roonbridge")
        if roon_service == "not_installed" and Path("/opt/RoonBridge/start.sh").is_file():
            roon_service = "stopped"
    else:
        roon_service = "unknown"
        for name in ("roonbridge.service", "RoonBridge.service"):
            status = command_output(["systemctl", "is-active", name])
            if status and status != "unknown":
                roon_service = status
                break
    network = connected_network_snapshot()
    active_wifi = network["name"] if network["type"] == "Wi-Fi" else active_wifi_ssid()
    airplay_service = service_state("shairport-sync.service")
    try:
        update_status = (state_dir / "update-status").read_text(encoding="utf-8").strip()
    except OSError:
        update_status = "Ready"
    display_config = display_config_dir()
    try:
        display_rotation = (display_config / "display-transform").read_text(encoding="utf-8").strip()
    except OSError:
        display_rotation = "normal"
    try:
        display_profile = (display_config / "display-profile").read_text(encoding="utf-8").strip()
    except OSError:
        display_profile = "original"
    try:
        viewport_orientation = (display_config / "display-orientation").read_text(encoding="utf-8").strip()
        if viewport_orientation not in {"landscape", "portrait"}: raise ValueError
    except (OSError, ValueError):
        viewport_orientation = display_orientation(display_profile, display_rotation)
    try:
        mounting = (display_config / "display-mounting").read_text(encoding="utf-8").strip()
        if mounting not in {"standard", "inverted"}: raise ValueError
    except (OSError, ValueError):
        mounting = display_mounting(display_rotation)
    try:
        changed_boot_id = (state_dir / "reboot-required-boot-id").read_text(encoding="ascii").strip()
        reboot_required = bool(changed_boot_id and changed_boot_id == current_boot_id())
    except OSError:
        reboot_required = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/api/state", timeout=.5) as response:
            controller = json.load(response)
        if controller.get("connected"):
            zone = controller.get("zone") or {}
            roon_controller = f"Connected · {zone.get('name')}" if zone.get("name") else "Connected · no zones"
        else:
            roon_controller = "Waiting for authorisation"
    except (OSError, ValueError, json.JSONDecodeError):
        roon_controller = "Unavailable"
    netdata = netdata_snapshot()
    try:
        setup = json.loads((state_dir.parent / "pi-home-setup/progress.json").read_text(encoding="utf-8"))
        device_username = setup.get("username", "admin")
    except (OSError, ValueError, json.JSONDecodeError):
        device_username = "admin"
    snapshot = {
        "hostname": socket.gethostname(),
        "wifi_ssid": active_wifi,
        "network": network,
        "roon_bridge": roon_service,
        # Chosen in web Settings → Display. The touchscreen shows a switch for each one that is on and installed.
        "network_controls": {"roon_bridge": config.touch_roon_bridge if config else True,
                             "airplay": config.touch_airplay if config else False,
                             "netdata": config.touch_netdata if config else True},
        "roon_bridge_operation_status": (state_dir / "roonbridge-install-status").read_text().strip() if (state_dir / "roonbridge-install-status").is_file() else "",
        "airplay": airplay_service,
        "airplay_name": (state_dir / "airplay-name").read_text().strip() if (state_dir / "airplay-name").is_file() else "RoonDeck",
        "airplay_operation_status": (state_dir / "airplay-install-status").read_text().strip() if (state_dir / "airplay-install-status").is_file() else "",
        "roon_controller": roon_controller,
        "netdata": netdata["service"],
        "netdata_details": netdata,
        "netdata_lightweight": (state_dir / "netdata-lightweight").is_file() and (state_dir / "netdata-lightweight").read_text().strip() == "yes",
        "performance_profile": load_performance_profile(state_dir),
        "device_username": device_username,
        "pi_leds": pi_led_state(state_dir),
        "audio_hat": audio_hat_state(),
        "update_status": update_status,
        "display_rotation": display_rotation,
        "display_orientation": viewport_orientation,
        "display_mounting": mounting,
        "display_profile": display_profile,
        "reboot_required": reboot_required,
        "app_version": display_version(),
        "alpine_tools": os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype",
        "tools_status": (state_dir / "tools-status").read_text().strip() if (state_dir / "tools-status").is_file() else "",
        "streamdeck_install_status": (state_dir / "streamdeck-install-status").read_text().strip() if (state_dir / "streamdeck-install-status").is_file() else "",
        "storage_status": (state_dir / "storage-status").read_text().strip() if (state_dir / "storage-status").is_file() else "Not yet checked",
        "netdata_operation_status": (state_dir / "netdata-operation-status").read_text().strip() if (state_dir / "netdata-operation-status").is_file() else "",
    }
    if include_diagnostics:
        snapshot["diagnostics"] = diagnostics_snapshot(config) if config is not None else diagnostics_snapshot()
    return snapshot


def audio_hat_state() -> str:
    """The saved audio HAT choice (none when unset)."""
    try: value = (Path(display_config_dir()) / "audio-hat").read_text(encoding="utf-8").strip()
    except OSError: return "none"
    return value or "none"


def load_performance_profile(state_dir):
    try: value = (Path(state_dir) / "performance-profile").read_text().strip()
    except OSError: return "playback"
    return value if value in {"playback", "dashboard"} else "playback"


def write_control_request(state_dir: Path, request: dict) -> bool:
    """Atomically enqueue a privileged action and wake the systemd path unit.

    A single shared request file loses actions when two HTTP worker threads
    write before the privileged one-shot has consumed the first request.  Use
    one immutable file per action so ordering is preserved across bursts such
    as display-off immediately followed by display-on.
    """
    if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype":
        if request.get("action") in ALPINE_SYSTEM_ACTIONS:
            payload = {"action": request["action"]}
            if request["action"] == "set_wifi":
                payload.update(ssid=str(request.get("ssid", "")), password=str(request.get("password", "")))
            if request["action"] == "set_hostname":
                payload.update(hostname=str(request.get("hostname", "")))
            if request["action"] in {"display_on", "set_brightness"}:
                brightness = int(request.get("brightness", 100))
                if not 10 <= brightness <= 100: raise ValueError("Brightness must be between 10 and 100")
                payload["brightness"] = brightness
            if request["action"] == "netdata_claim":
                payload.update(token=str(request.get("token", "")), rooms=str(request.get("rooms", "")))
            if request["action"] in {"netdata_claim_command", "netdata_official_install"}:
                payload["command"] = str(request.get("command", ""))
            if request["action"] == "performance_profile":
                if request.get("profile") not in ("playback", "dashboard"): raise ValueError("Choose playback or dashboard priority.")
                payload["profile"] = request["profile"]
            if request["action"] == "netdata_lightweight":
                if type(request.get("enabled")) is not bool: raise ValueError("Choose a supported Netdata monitoring mode.")
                payload["enabled"] = request["enabled"]
            if request["action"] == "airplay_configure":
                payload["name"] = str(request.get("name", ""))
            if request["action"] == "set_audio_hat":
                payload["hat"] = str(request.get("hat", ""))
            if request["action"] == "device_credentials":
                payload.update(username=str(request.get("username", "")), password=str(request.get("password", "")), confirmation=str(request.get("confirmation", "")))
            if request["action"] == "set_display":
                payload.update(profile=str(request.get("profile", "")), orientation=str(request.get("orientation", "")), mounting=str(request.get("mounting", "standard")))
            try:
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(105 if request["action"] in {"netdata_claim", "netdata_claim_command", "netdata_lightweight", "roon_start", "roon_stop", "roon_restart", "airplay_start", "airplay_stop", "airplay_restart", "airplay_configure"} else 45 if request["action"] == "set_wifi" else 15); client.connect("/run/pi-home-setup.sock")
                    client.sendall((json.dumps(payload) + "\n").encode())
                    result = json.loads(client.makefile("rb").readline(4096))
            except OSError as error: raise ValueError("Alpine system helper is not ready. Please retry.") from error
            if not result.get("ok"): raise ValueError(result.get("error", "Could not start Alpine update"))
            return bool(result.get("queued", result.get("ok")))
        raise ValueError("OS controls are unavailable in Alpine Beta")
    with CONTROL_REQUEST_LOCK:
        state_dir.mkdir(parents=True, exist_ok=True)
        queue_dir = state_dir / "system-action-queue"
        queue_dir.mkdir(mode=0o700, exist_ok=True)
        if request.get("action") == "update":
            candidates = ([state_dir / "system-action-request.json"] if (state_dir / "system-action-request.json").exists() else []) + sorted(queue_dir.glob("*.json"))
            for candidate in candidates:
                try:
                    if json.loads(candidate.read_text(encoding="utf-8")).get("action") == "update":
                        return False
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        request_id = f"{time.time_ns():020d}-{os.getpid()}-{threading.get_ident()}-{secrets.token_hex(4)}"
        temporary = queue_dir / f".{request_id}.tmp"
        target = queue_dir / f"{request_id}.json"
        temporary.write_text(json.dumps(request), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(target)
        if request.get("action") == "update":
            status_temporary = state_dir / ".update-status.tmp"
            status_temporary.write_text("Update · Queued…\n", encoding="utf-8")
            os.chmod(status_temporary, 0o644)
            status_temporary.replace(state_dir / "update-status")
        trigger_temporary = state_dir / f".system-action-trigger-{request_id}.tmp"
        trigger = state_dir / "system-action-trigger"
        trigger_temporary.write_text(request_id + "\n", encoding="ascii")
        os.chmod(trigger_temporary, 0o600)
        trigger_temporary.replace(trigger)
        return True


def make_handler(state: State, config_path: Path, env_path: Path, mode_path: Path, events: OpenObserveLogger | None = None):
    static = Path(__file__).with_name("static")
    sessions: dict[str, float] = {}
    releases = ReleaseChecker()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static), **kwargs)

        def end_headers(self):
            path = self.path.split("?", 1)[0]
            if path in {"/admin.html", "/admin.css", "/admin.js", "/login.html"}:
                self.send_header("Cache-Control", "no-cache, must-revalidate")
            super().end_headers()

        def deck_art_dir(self) -> Path:
            return state.state_dir / "deck-art"

        def do_GET(self):
            if self.path == "/api/admin/listening/art" or self.path.startswith("/api/admin/listening/art/"):
                if not self.authorised(): return
                folder = self.deck_art_dir()
                if self.path == "/api/admin/listening/art":
                    names = sorted(item.name for item in folder.glob("*.png") if item.is_file()) if folder.is_dir() else []
                    self.send_json(200, json.dumps({"art": names}).encode()); return
                name = self.path.rsplit("/", 1)[-1].split("?", 1)[0]
                target = folder / name
                if not DECK_ART_NAME.fullmatch(name) or not target.is_file():
                    self.send_json(404, b'{"error":"Not found"}'); return
                body = target.read_bytes()
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.path == "/api/admin/backup-server":
                if not self.authorised(): return
                try:
                    result = backup_server_client.status(state.state_dir)
                    result["local_status"] = load_json(state.state_dir / "backup-server-status.json", {})
                    self.send_json(200, json.dumps(result).encode())
                except (ValueError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)[:240]}).encode())
                return
            if self.path == "/api/admin/backup-target":
                if not self.authorised(): return
                self.send_json(200, json.dumps({"target": remote_backup.load_target(state.state_dir / "backup-target.json"), "password_set": bool(os.getenv(remote_backup.SECRET)), "google_secret_set": bool(os.getenv(remote_backup.GOOGLE_SECRET)), "google_connected": bool(os.getenv(remote_backup.GOOGLE_TOKEN)), "ssh_key": remote_backup.ssh_key_path(state.state_dir).with_suffix(".pub").read_text().strip() if remote_backup.ssh_key_path(state.state_dir).with_suffix(".pub").is_file() else "",
                    "status": load_json(state.state_dir / "backup-status.json", {})}).encode()); return
            if self.path.split("?", 1)[0] == "/api/admin/backup":
                if not self.authorised(): return
                bundle = build_backup(config_path, state.state_dir, env_path, __version__, include_secrets="secrets=1" in self.path)
                body = json.dumps(bundle, indent=1).encode()
                name = "roondeck-backup-" + time.strftime("%Y-%m-%d") + ".json"
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"'); self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.path == "/api/admin/home-layout":
                if not self.authorised(): return
                self.send_json(200, json.dumps(load_layout(state.state_dir / "home-layout.json")).encode()); return
            if self.path.startswith("/api/device/home-art/"):
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}'); return
                name = self.path.rsplit("/", 1)[-1].split("?", 1)[0]
                target = self.deck_art_dir() / name
                if not DECK_ART_NAME.fullmatch(name) or not target.is_file():
                    self.send_json(404, b'{"error":"Not found"}'); return
                body = target.read_bytes()
                query = parse_qs(self.path.partition("?")[2])
                if query.get("color"): body = tint_icon(body, query["color"][0])
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Cache-Control", "max-age=300")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.path == "/api/admin/listening":
                if not self.authorised(): return
                try:
                    self.send_json(200, json.dumps(state.listening.settings()).encode())
                except (ValueError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path in {"/api/admin/accessories", "/api/admin/network"}:
                if not self.authorised(): return
                try:
                    self.send_json(200, json.dumps(accessory_request({"operation": "status"}, helper_action="network_control" if self.path == "/api/admin/network" else "accessories")).encode())
                except (ValueError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path in {"/", "/index.html"} and not state.config.bus_enabled:
                self.send_response(302); self.send_header("Location", "/roon/"); self.end_headers(); return
            if self.path == "/home":
                self.send_response(302)
                self.send_header("Location", "/home.html")
                self.end_headers()
                return
            if self.path == "/roon":
                self.send_response(302)
                self.send_header("Location", "/roon/")
                self.end_headers()
                return
            if self.path.startswith("/roon/"):
                self.proxy_roon("GET")
                return
            if self.path.startswith("/login.html?"):
                self.path = "/login.html"
            if self.path == "/api/display-target":
                self.send_json(200, json.dumps({"target": automatic_display_target(state, mode_path, roon_status()), "screen_powered": state.screen_powered,
                    "deck_volume_ago": round(time.monotonic() - state.deck_volume_at, 1) if getattr(state, "deck_volume_at", None) else None}).encode())
                return
            if self.path == "/display":
                self.send_response(302)
                self.send_header("Location", automatic_display_target(state, mode_path, roon_status()))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if self.path == "/admin":
                if not self.is_authorised():
                    self.send_response(302)
                    self.send_header("Location", "/login.html")
                    self.end_headers()
                    return
                self.send_response(302)
                self.send_header("Location", "/admin.html")
                self.end_headers()
                return
            if self.path.split("?", 1)[0] in {"/admin.html", "/accessories.html"} and not self.is_authorised():
                self.send_response(302)
                self.send_header("Location", "/login.html")
                self.end_headers()
                return
            if self.path == "/api/admin/config":
                if not self.authorised():
                    return
                config = state.config
                body = json.dumps({
                    "bus_stop_code": config.bus_stop_code, "bus_stop_name": config.bus_stop_name,
                    "services": list(config.services), "service_colours": config.service_colours, "route_tint": config.route_tint, "walking_minutes": config.walking_minutes,
                    "poll_seconds": config.poll_seconds, "morning_start": config.morning_start,
                    "morning_end": config.morning_end, "scheduled_wake_enabled": config.scheduled_wake_enabled,
                    "weekend_wake_enabled": config.weekend_wake_enabled, "weekend_wake_time": config.weekend_wake_time,
                    "sleep_start": config.sleep_start,
                    "sleep_end": config.sleep_end, "roon_display_url": config.roon_display_url,
                    "roon_zone_name": config.roon_zone_name,
                    "roon_core_host": config.roon_core_host,
                    "roon_display_name": config.roon_display_name,
                    "display_theme": config.display_theme,
                    "display_background": config.display_background,
                    "interface_size": config.interface_size,
                    "settings_layout": config.settings_layout,
                    "touch_roon_bridge": config.touch_roon_bridge,
                    "touch_airplay": config.touch_airplay,
                    "touch_netdata": config.touch_netdata,
                    "portrait_discovery_columns": config.portrait_discovery_columns,
                    "landscape_music_clock": config.landscape_music_clock,
                    "bus_enabled": config.bus_enabled,
                    "roon_now_playing_name": config.roon_now_playing_name,
                    "roon_queue_name": config.roon_queue_name,
                    "sleep_when_roon_idle": config.sleep_when_roon_idle,
                    "roon_show_controls": config.roon_show_controls,
                    "roon_show_clock": config.roon_show_clock,
                    "roon_show_queue": config.roon_show_queue,
                    "roon_show_browser": config.roon_show_browser,
                    "bluos_enabled": config.bluos_enabled,
                    "bluos_player_address": config.bluos_player_address,
                    "bluos_visible_inputs": list(config.bluos_visible_inputs),
                    "bluos_input_names": list(config.bluos_input_names),
                    "sleep_show_clock": config.sleep_show_clock,
                    "auto_switch_to_roon": config.auto_switch_to_roon,
                    "roon_idle_return_seconds": config.roon_idle_return_seconds,
                    "browse_idle_return_seconds": config.browse_idle_return_seconds,
                    "outside_hours_wake_seconds": config.outside_hours_wake_seconds,
                    "remote_wake_seconds": config.remote_wake_seconds,
                    "daytime_inactivity_seconds": config.daytime_inactivity_seconds,
                    "home_assistant_enabled": config.home_assistant_enabled,
                    "home_assistant_title": config.home_assistant_title,
                    "home_assistant_url": config.home_assistant_url,
                    "home_assistant_entities": list(config.home_assistant_entities),
                    "home_assistant_deck_entities": list(config.home_assistant_deck_entities),
                    "home_assistant_color_mode": config.home_assistant_color_mode,
                    "home_assistant_single_color": config.home_assistant_single_color,
                    "home_assistant_light_color": config.home_assistant_light_color,
                    "home_assistant_fan_color": config.home_assistant_fan_color,
                    "home_assistant_switch_color": config.home_assistant_switch_color,
                    "home_assistant_scene_color": config.home_assistant_scene_color,
                    "has_home_assistant_token": bool(os.getenv("HOME_ASSISTANT_TOKEN")),
                    "openobserve_enabled": config.openobserve_enabled,
                    "openobserve_url": config.openobserve_url,
                    "openobserve_org": config.openobserve_org,
                    "openobserve_stream": config.openobserve_stream,
                    "openobserve_username": config.openobserve_username,
                    "has_openobserve_password": bool(os.getenv("OPENOBSERVE_PASSWORD")),
                    "app_version": display_version(),
                    "release_channel": config.release_channel,
                    "auto_update_enabled": config.auto_update_enabled,
                    "auto_update_time": config.auto_update_time,
                    "update_timezone": config.timezone,
                    "admin_username": os.getenv("ADMIN_USERNAME", "admin"),
                    "admin_auth_enabled": os.getenv("ADMIN_AUTH_ENABLED", "true").lower() != "false",
                    "display_mode": read_display_mode(mode_path),
                    "has_lta_key": bool(os.getenv("LTA_ACCOUNT_KEY")),
                }).encode()
                self.send_json(200, body)
                return
            if self.path in {"/api/device/releases", "/api/device/releases?refresh=1"}:   # the touchscreen's Update tile asks the same question as the admin page
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                distribution = "alpine" if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype" else "rpi"
                result = releases.check(state.config.release_channel, __version__, refresh=self.path.endswith("refresh=1"), distribution=distribution)
                self.send_json(200, json.dumps(result).encode())
                return
            if self.path in {"/api/admin/releases", "/api/admin/releases?refresh=1"}:
                if not self.authorised():
                    return
                distribution = "alpine" if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype" else "rpi"
                result = releases.check(state.config.release_channel, __version__, refresh=self.path.endswith("refresh=1"), distribution=distribution)
                result["distribution"] = distribution
                self.send_json(200, json.dumps(result).encode())
                return
            if self.path in {"/api/admin/system", "/api/admin/system?diagnostics=1"}:
                if not self.authorised():
                    return
                system = system_snapshot(mode_path.parent, include_diagnostics=self.path.endswith("diagnostics=1"), config=state.config)
                system["display_brightness"] = state.display_brightness
                body = json.dumps(system).encode()
                self.send_json(200, body)
                return
            if self.path == "/api/admin/performance":
                if not self.authorised(): return
                self.send_json(200, json.dumps(state.performance.snapshot()).encode())
                return
            if self.path == "/api/admin/diagnostics":
                if not self.authorised():
                    return
                self.send_json(200, json.dumps(diagnostics_snapshot(state.config)).encode())
                return
            if self.path == "/api/admin/preview":
                if not self.authorised(): return
                with state.lock:
                    capture = state.preview_capture
                    body = {"navigation": state.preview_result, "capture": {key: capture[key] for key in ("id", "status", "error")} if capture else None}
                self.send_json(200, json.dumps(body).encode()); return
            if self.path.startswith("/api/admin/preview-image?"):
                if not self.authorised(): return
                ticket_id = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("id", [""])[0]
                with state.lock:
                    capture = state.preview_capture
                    image = capture["image"] if capture and capture["id"] == ticket_id and capture["status"] == "ready" else None
                if image is None:
                    self.send_json(404, b'{"error":"Screenshot is not ready"}'); return
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(image))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(image); return
            if self.path == "/api/status":
                body = json.dumps(state.snapshot()).encode()
                self.send_json(200, body)
                return
            if self.path == "/api/admin/home-catalog":
                if not state.config.home_assistant_enabled:
                    self.send_json(200, b'{"entities":[]}')
                    return
                try:
                    raw = home_assistant_request(state.config, "/api/states")
                    catalog = sorted(({"entity_id": item["entity_id"], "domain": item["entity_id"].split(".", 1)[0],
                                       "name": (item.get("attributes") or {}).get("friendly_name") or item["entity_id"]}
                                      for item in (raw if isinstance(raw, list) else []) if str(item.get("entity_id", "")).split(".", 1)[0] in HOME_ASSISTANT_DOMAINS),
                                     key=lambda item: item["name"].lower())
                    self.send_json(200, json.dumps({"entities": catalog}).encode())
                except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    self.send_json(502, json.dumps({"error": str(exc)[:160]}).encode())
                return
            if self.path == "/api/admin/home-remotes":
                # Home Assistant remotes (Broadlink and similar) for the KEF infrared setting; the catalog above leaves them out.
                if not state.config.home_assistant_enabled:
                    self.send_json(200, b'{"remotes":[]}')
                    return
                try:
                    raw = home_assistant_request(state.config, "/api/states")
                    remotes = sorted(({"entity_id": item["entity_id"], "name": (item.get("attributes") or {}).get("friendly_name") or item["entity_id"]}
                                      for item in (raw if isinstance(raw, list) else []) if str(item.get("entity_id", "")).startswith("remote.")),
                                     key=lambda item: item["name"].lower())
                    self.send_json(200, json.dumps({"remotes": remotes}).encode())
                except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    self.send_json(502, json.dumps({"error": str(exc)[:160]}).encode())
                return
            if self.path == "/api/listening/status":
                self.send_json(200, json.dumps(state.listening.snapshot()).encode())
                return
            if self.path == "/api/home/status":
                home_single = state.config.home_assistant_single_color if state.config.home_assistant_color_mode == "single" else None
                self.send_json(200, json.dumps({**with_layout(state.home_data, load_layout(state.state_dir / "home-layout.json")), "roon_display_name": state.config.roon_display_name, "display_theme": state.config.display_theme,
                    "tile_colors": {"light": home_single or state.config.home_assistant_light_color, "fan": home_single or state.config.home_assistant_fan_color,
                        "switch": home_single or state.config.home_assistant_switch_color, "input_boolean": home_single or state.config.home_assistant_switch_color,
                        "scene": home_single or state.config.home_assistant_scene_color, "script": home_single or state.config.home_assistant_scene_color}}).encode())
                return
            if self.path == "/api/device/controls":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                controls = state.controls_snapshot()
                if any(self.headers.get(name) for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP")):
                    controls["capture_request"] = None
                self.send_json(200, json.dumps(controls).encode())
                return
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html", "/home.html", "/admin.html", "/preview.html", "/accessories.html"}:
                if path in {"/admin.html", "/preview.html", "/accessories.html"} and not self.authorised(): return
                theme = "roon" if state.config.display_theme == "roon" else "fresh-mint"
                body = (static / ("index.html" if path == "/" else path[1:])).read_text(encoding="utf-8")
                body = body.replace("<body", f'<body data-theme="{theme}"', 1)
                if theme == "roon": body = body.replace("/favicon.svg", "/favicon-roon.svg")
                encoded = body.encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(encoded)
                return
            super().do_GET()

        def do_POST(self):
            if self.path.startswith("/api/admin/listening/art"):
                if not self.authorised(): return
                try:
                    folder = self.deck_art_dir()
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path == "/api/admin/listening/art/delete":
                        if not 0 < length <= 1000: raise ValueError("Invalid request")
                        name = str(json.loads(self.rfile.read(length)).get("name", ""))
                        if not DECK_ART_NAME.fullmatch(name): raise ValueError("Invalid image name")
                        (folder / name).unlink(missing_ok=True)
                        self.send_json(200, b'{"ok":true}'); return
                    name = parse_qs(urlsplit(self.path).query).get("name", [""])[0]
                    if urlsplit(self.path).path != "/api/admin/listening/art" or not DECK_ART_NAME.fullmatch(name):
                        raise ValueError("Use a short image name made of letters, numbers, dashes or dots, ending in .png")
                    if self.headers.get("Content-Type", "").split(";")[0] != "image/png": raise ValueError("PNG image required")
                    if not 0 < length <= 200000: raise ValueError("Image is too large")
                    body = self.rfile.read(length)
                    if not body.startswith(b"\x89PNG\r\n\x1a\n"): raise ValueError("Not a PNG image")
                    folder.mkdir(parents=True, exist_ok=True)
                    if not (folder / name).exists() and len(list(folder.glob("*.png"))) >= 80: raise ValueError("Too many images; delete some first")
                    temporary = folder / f".{name}.tmp"
                    temporary.write_bytes(body); os.replace(temporary, folder / name)
                    self.send_json(200, json.dumps({"ok": True, "name": name}).encode())
                except (ValueError, TypeError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path == "/api/admin/listening":
                if not self.authorised(): return
                try:
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise ValueError("JSON request required")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 80000: raise ValueError("Listening settings are too large")
                    settings = state.listening.save(json.loads(self.rfile.read(length)))
                    self.send_json(200, json.dumps({"ok": True, "settings": settings}).encode())
                    threading.Thread(target=state.listening.refresh, daemon=True).start()
                except (ValueError, TypeError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path in {"/api/admin/backup-server/pair", "/api/admin/backup-server/run", "/api/admin/backup-server/password", "/api/admin/backup-server/restore", "/api/admin/backup-server/disconnect"}:
                if not self.authorised(): return
                try:
                    with backup_server_client.LOCK:
                        if self.headers.get("Content-Type", "").split(";")[0] != "application/json": raise ValueError("JSON request required")
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 8000: raise ValueError("Invalid request")
                        data = json.loads(self.rfile.read(length))
                        if not isinstance(data, dict): raise ValueError("Invalid request")
                        action = self.path.rsplit("/", 1)[-1]
                        if action == "pair":
                            if os.getenv("PI_HOME_APPLIANCE_PLATFORM") == "alpine-prototype":
                                accessory_request({}, helper_action="install_backup_tools")
                            result = backup_server_client.pair(state.state_dir, data.get("url", ""), data.get("code", ""), data.get("name", ""))
                        elif action == "run":
                            result = {"ok": True, "name": backup_server_client.run(state.state_dir, config_path, env_path, __version__)}
                        elif action == "password":
                            backup_server_client.set_password(state.state_dir, data.get("password", "")); result = {"ok": True}
                        elif action == "disconnect":
                            (state.state_dir / "backup-server.json").unlink(missing_ok=True); result = {"ok": True}
                        else:
                            checked = backup_server_client.restore(state.state_dir, data.get("name", ""), data.get("password", ""))
                            # Make a local safety copy before changing settings. Credentials
                            # remain excluded; independent server pairing is never replaced.
                            backup_server_client.write_private(state.state_dir / "before-server-restore.json", build_backup(config_path, state.state_dir, env_path, __version__))
                            restore_backup(checked, config_path, state.state_dir)
                            for key, value in checked["secrets"].items():
                                if key in SECRET_KEYS: update_secret(env_path, key, value)
                            if checked["config"]:
                                state.config = load_config(config_path)
                                state.enabled_services.intersection_update(state.config.services)
                                state.save_enabled_services()
                            result = {"ok": True, "images": len(checked["art"])}
                        self.send_json(200, json.dumps(result).encode())
                except (ValueError, TypeError, KeyError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)[:240]}).encode())
                return
            if self.path in {"/api/admin/backup-target", "/api/admin/backup-run", "/api/admin/backup-google-start", "/api/admin/backup-google-poll", "/api/admin/backup-rsync-key"}:
                if not self.authorised(): return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4000: raise ValueError("Invalid request")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict): raise ValueError("Invalid request")
                    path = state.state_dir / "backup-target.json"
                    if self.path == "/api/admin/backup-target":
                        target = remote_backup.save_target(path, data)
                        for field, key in (("password", remote_backup.SECRET), ("google_secret", remote_backup.GOOGLE_SECRET)):
                            value = str(data.get(field, ""))
                            if value:
                                if "\n" in value or "\r" in value: raise ValueError("A password cannot contain a line break")
                                update_secret(env_path, key, value)
                        self.send_json(200, json.dumps({"ok": True, "target": target}).encode()); return
                    target = remote_backup.load_target(path)
                    if self.path == "/api/admin/backup-rsync-key":
                        self.send_json(200, json.dumps({"public_key": remote_backup.ensure_ssh_key(state.state_dir)}).encode()); return
                    if self.path == "/api/admin/backup-google-start":
                        if not target["google_client_id"] or not os.getenv(remote_backup.GOOGLE_SECRET): raise ValueError("Save the Google client ID and secret first")
                        flow = remote_backup.google_start(target["google_client_id"])
                        state.google_device = flow["device_code"]
                        self.send_json(200, json.dumps({"user_code": flow.get("user_code"), "url": flow.get("verification_url") or flow.get("verification_uri"), "interval": flow.get("interval", 5)}).encode()); return
                    if self.path == "/api/admin/backup-google-poll":
                        code = getattr(state, "google_device", "")
                        if not code: raise ValueError("Start the Google sign-in first")
                        token = remote_backup.google_poll(target["google_client_id"], os.getenv(remote_backup.GOOGLE_SECRET, ""), code)
                        if token:
                            update_secret(env_path, remote_backup.GOOGLE_TOKEN, token); state.google_device = ""
                        self.send_json(200, json.dumps({"connected": bool(token)}).encode()); return
                    which = data.get("which") if data.get("which") in {"synology", "google", "rsync"} else None
                    saved, errors = remote_backup.run_all(remote_backup.validate_target(target), state.state_dir, config_path, env_path, __version__, which)
                    remote_backup.write_status(state.state_dir / "backup-status.json", not errors, "; ".join(saved + errors))
                    if errors: raise ValueError("; ".join(errors))
                    self.send_json(200, json.dumps({"ok": True, "saved": saved}).encode())
                except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
                    self.send_json(400, json.dumps({"error": str(error)[:240]}).encode())
                return
            if self.path == "/api/admin/restore":
                if not self.authorised(): return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 40_000_000: raise ValueError("That backup file is too large")
                    bundle = json.loads(self.rfile.read(length))
                    if isinstance(bundle, dict) and "encrypted" in bundle:
                        bundle = backup_crypto.decrypt(bundle["encrypted"], bundle.get("password", ""))
                    checked = check_backup(bundle)
                    restore_backup(checked, config_path, state.state_dir)
                    for key, value in checked["secrets"].items():
                        if key in SECRET_KEYS: update_secret(env_path, key, value)
                    if checked["config"]:
                        state.config = load_config(config_path)
                        state.enabled_services.intersection_update(state.config.services)
                        state.save_enabled_services()
                    self.send_json(200, json.dumps({"ok": True, "restored_secrets": sorted(checked["secrets"]), "images": len(checked["art"])}).encode())
                except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
                    self.send_json(400, json.dumps({"error": str(error)[:200]}).encode())
                return
            if self.path == "/api/admin/home-layout":
                if not self.authorised(): return
                try:
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise ValueError("JSON request required")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 90000: raise ValueError("Home layout is too large")
                    saved = save_layout(state.state_dir / "home-layout.json", json.loads(self.rfile.read(length)))
                    self.send_json(200, json.dumps({"ok": True, "layout": saved}).encode())
                except (ValueError, TypeError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path in {"/api/admin/accessories", "/api/admin/network"}:
                if not self.authorised(): return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 30000: raise ValueError("Accessory request is too large.")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict): raise ValueError("Invalid accessory request.")
                    self.send_json(200, json.dumps(accessory_request(data, helper_action="network_control" if self.path == "/api/admin/network" else "accessories")).encode())
                except (ValueError, OSError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path == "/api/listening/command":
                if any(self.headers.get(name) for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP")) and self.client_address[0] in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Forwarded local control is forbidden"}'); return
                if not self.authorised(): return
                try:
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise ValueError("JSON request required")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096: raise ValueError("Invalid command size")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict): raise ValueError("Command must be an object")
                    if data.get("action") == "scene":
                        entity = data.get("value")
                        if not state.config.home_assistant_enabled or not isinstance(entity, str) or entity not in state.home_entity_ids() or not entity.startswith(("scene.", "script.")):
                            raise ValueError("Choose a configured Home Assistant scene or script")
                        home_assistant_request(state.config, f"/api/services/{entity.split('.', 1)[0]}/turn_on", {"entity_id": entity})
                        result = {"ok": True}
                    elif data.get("action") == "deck_brightness":
                        value = data.get("value")
                        if type(value) is not int or not 10 <= value <= 100: raise ValueError("Deck brightness must be between 10 and 100")
                        state.listening.brightness_preview = value
                        if data.get("save") is True:
                            saved = state.listening.settings(); saved["streamdeck_brightness"] = value
                            state.listening.save(saved)
                        result = {"ok": True}
                    elif data.get("action") == "deck_volume":
                        # A Stream Deck volume change: the touchscreen should not jump to Now Playing for it, as it does for the remote.
                        state.deck_volume_at = time.monotonic()
                        result = {"ok": True}
                    elif data.get("action") == "remote":
                        value = data.get("value")
                        if not state.config.home_assistant_enabled or not (remote_step_allowed(state.listening.settings(), value) or state.mode_remote_allowed(value)):
                            raise ValueError("Choose a remote step saved on a Stream Deck dial or a listening-mode tile")
                        home_assistant_request(state.config, "/api/services/remote/send_command", {"entity_id": value["entity_id"], "device": value["device"], "command": value["command"]})
                        result = {"ok": True}
                    else:
                        result = state.listening.command(data.get("action"), data.get("value"))
                    self.send_json(200, json.dumps(result).encode())
                except (ValueError, TypeError) as error:
                    self.send_json(400, json.dumps({"error": str(error)}).encode())
                except OSError as error:
                    self.send_json(502, json.dumps({"error": str(error)}).encode())
                return
            if self.path == "/api/admin/preview-capture":
                if not self.authorised(): return
                try: self.send_json(202, json.dumps({"id": state.start_preview_capture()}).encode())
                except RuntimeError as error: self.send_json(409, json.dumps({"error": str(error)}).encode())
                return
            if self.path == "/api/device/preview":
                if self.client_address[0] not in {"127.0.0.1", "::1"} or any(self.headers.get(name) for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP")):
                    self.send_json(403, b'{"error":"Touchscreen only"}'); return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1_048_576: raise ValueError("Invalid acknowledgement size")
                    state.complete_preview(json.loads(self.rfile.read(length)))
                    self.send_json(200, b'{"ok":true}')
                except (ValueError, TypeError) as error: self.send_json(400, json.dumps({"error": str(error)}).encode())
                return
            if self.path == "/api/admin/display-capture":
                if not self.authorised():
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.send_json(400, b'{"error":"JSON request required"}')
                    return
                try:
                    image = state.capture_display()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(image)))
                    self.send_header("Content-Disposition", 'inline; filename="roondeck-display.png"')
                    self.end_headers()
                    self.wfile.write(image)
                except RuntimeError as exc:
                    self.send_json(503, json.dumps({"error": str(exc)}).encode())
                return
            if self.path == "/api/device/display-capture":
                if self.client_address[0] not in {"127.0.0.1", "::1"} or any(self.headers.get(name) for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP")):
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 11_200_000:
                        raise ValueError("Invalid display capture size")
                    state.complete_display_capture(json.loads(self.rfile.read(length)))
                    self.send_json(200, b'{"ok":true}')
                except (ValueError, TypeError) as exc:
                    self.send_json(400, json.dumps({"error": str(exc)}).encode())
                return
            if self.path.startswith("/roon/"):
                self.proxy_roon("POST")
                return
            if self.path == "/login":
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
                username = form.get("username", [""])[0]
                supplied = form.get("password", [""])[0]
                expected = os.getenv("ADMIN_PASSWORD", "")
                expected_username = os.getenv("ADMIN_USERNAME", "admin")
                if hmac.compare_digest(username, expected_username) and expected and hmac.compare_digest(supplied, expected):
                    token = secrets.token_urlsafe(32)
                    sessions[token] = time.time() + 30 * 24 * 60 * 60
                    self.send_response(302)
                    self.send_header("Location", "/admin")
                    self.send_header("Set-Cookie", f"pi_bus_session={token}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict")
                    self.end_headers()
                else:
                    self.send_response(302)
                    self.send_header("Location", "/login.html?error=1")
                    self.end_headers()
                return
            if self.path in {"/api/device/update", "/api/device/reboot", "/api/device/shutdown"}:
                if self.client_address[0] not in {"127.0.0.1", "::1"} or any(self.headers.get(name) for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP")):
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                try: queued = write_control_request(mode_path.parent, {"action": self.path.rsplit("/", 1)[-1]})
                except (OSError, ValueError) as error:
                    self.send_json(503, json.dumps({"error": str(error)}).encode()); return
                self.send_json(202, json.dumps({"ok": True, "queued": queued}).encode())
                return
            if self.path == "/api/device/screen-power":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length) or b"{}")
                state.screen_powered = bool(data.get("powered"))
                if data.get("report_only"):   # the panel's periodic reminder, so a restarted controller relearns the state
                    self.send_json(202, b'{"ok":true}')
                    return
                request = {"action": "display_on" if data.get("powered") else "display_off"}
                if data.get("powered"):
                    request["brightness"] = state.display_brightness
                write_control_request(mode_path.parent, request)
                if events:
                    events.emit("display.power.requested", powered=bool(data.get("powered")))
                self.send_json(202, b'{"ok":true}')
                return
            if self.path == "/api/device/brightness":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                    data = json.loads(self.rfile.read(length) or b"{}")
                    state.save_display_brightness(int(data.get("brightness", 100)))
                    write_control_request(mode_path.parent, {"action": "set_brightness", "brightness": state.display_brightness})
                    self.send_json(200, json.dumps({"ok": True, "brightness": state.display_brightness}).encode())
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    self.send_json(400, json.dumps({"error": str(exc)}).encode())
                return
            if self.path == "/api/device/wake":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length) or b"{}")
                state.awake_view = "roon" if data.get("view") == "roon" else "bus"
                # A Dial or TV-remote volume change wakes the screen only briefly; a touch keeps the full period.
                awake_seconds = state.config.remote_wake_seconds if data.get("source") == "remote" else state.config.outside_hours_wake_seconds
                state.awake_until = time.monotonic() + awake_seconds
                if events:
                    events.emit("display.wake.requested", view=state.awake_view)
                self.send_json(200, json.dumps({"ok": True, "awake_seconds": awake_seconds}).encode())
                return
            if self.path in {"/api/device/service-visibility", "/api/device/roon-bridge", "/api/device/airplay", "/api/device/netdata", "/api/device/home-toggle", "/api/device/home-state", "/api/device/home-value"}:
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json(403, b'{"error":"Touchscreen only"}')
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/device/service-visibility":
                    service = str(data.get("service", ""))
                    if service not in state.config.services:
                        self.send_json(400, b'{"error":"Unknown bus service"}')
                        return
                    if data.get("enabled"): state.enabled_services.add(service)
                    else: state.enabled_services.discard(service)
                    state.save_enabled_services()
                elif self.path == "/api/device/roon-bridge":
                    if type(data.get("enabled")) is not bool:
                        self.send_json(400, b'{"error":"Choose whether Roon Bridge should run"}')
                        return
                    try:
                        write_control_request(mode_path.parent, {"action": "roon_start" if data["enabled"] else "roon_stop"})
                    except (OSError, ValueError) as error:
                        self.send_json(502, json.dumps({"error": str(error)}).encode())
                        return
                elif self.path == "/api/device/airplay":
                    if type(data.get("enabled")) is not bool:
                        self.send_json(400, b'{"error":"Choose whether AirPlay should run"}')
                        return
                    try:
                        write_control_request(mode_path.parent, {"action": "airplay_start" if data["enabled"] else "airplay_stop"})
                    except (OSError, ValueError) as error:
                        self.send_json(502, json.dumps({"error": str(error)}).encode())
                        return
                elif self.path == "/api/device/netdata":
                    if type(data.get("enabled")) is not bool:
                        self.send_json(400, b'{"error":"Choose whether Netdata should run"}')
                        return
                    try:
                        write_control_request(mode_path.parent, {"action": "netdata_enable" if data["enabled"] else "netdata_disable"})
                    except (OSError, ValueError) as error:
                        self.send_json(502, json.dumps({"error": str(error)}).encode())
                        return
                else:
                    entity_id = str(data.get("entity_id", ""))
                    if entity_id not in state.home_entity_ids():
                        self.send_json(400, b'{"error":"Entity is not available on this display"}')
                        return
                    domain = entity_id.split(".", 1)[0]
                    if domain not in HOME_ASSISTANT_DOMAINS:
                        self.send_json(400, b'{"error":"This entity type cannot be toggled"}')
                        return
                    try:
                        if self.path == "/api/device/home-value":
                            home_assistant_set_value(state.config, entity_id, int(data.get("value", 0)))
                        elif self.path == "/api/device/home-state":
                            if not home_assistant_switch_group(state, entity_id, bool(data.get("enabled"))):
                                home_assistant_set_state(state.config, entity_id, bool(data.get("enabled")))
                        elif domain not in {"scene", "script"} and home_assistant_switch_group(state, entity_id):
                            pass
                        elif domain in {"scene", "script"}:
                            home_assistant_activate(state.config, entity_id)
                        else:
                            home_assistant_request(state.config, f"/api/services/{domain}/toggle", {"entity_id": entity_id})
                    except (OSError, ValueError, urllib.error.URLError) as exc:
                        self.send_json(502, json.dumps({"error": str(exc)}).encode())
                        return
                self.send_json(200, b'{"ok":true}')
                return
            if self.path in {"/api/home/toggle", "/api/home/state", "/api/home/value"}:
                if not self.authorised():
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                    data = json.loads(self.rfile.read(length) or b"{}")
                    entity_id = str(data.get("entity_id", ""))
                    if entity_id not in state.home_entity_ids():
                        raise ValueError("Entity is not available on this dashboard")
                    domain = entity_id.split(".", 1)[0]
                    if self.path == "/api/home/value":
                        home_assistant_set_value(state.config, entity_id, int(data.get("value", 0)))
                    elif self.path == "/api/home/state":
                        if not home_assistant_switch_group(state, entity_id, bool(data.get("enabled"))):
                            home_assistant_set_state(state.config, entity_id, bool(data.get("enabled")))
                    elif domain not in {"scene", "script"} and home_assistant_switch_group(state, entity_id):
                        pass
                    elif domain in {"scene", "script"}:
                        home_assistant_activate(state.config, entity_id)
                    else:
                        home_assistant_request(state.config, f"/api/services/{domain}/toggle", {"entity_id": entity_id})
                    self.send_json(200, b'{"ok":true}')
                except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    self.send_json(400, json.dumps({"error": str(exc)}).encode())
                return
            if self.path not in {"/api/admin/config", "/api/admin/display-mode", "/api/admin/system-action", "/api/admin/password", "/api/admin/brightness", "/api/admin/openobserve-test"}:
                self.send_error(404)
                return
            if not self.authorised():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 16_384:
                    raise ValueError("Request is too large")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/admin/openobserve-test":
                    if events is None:
                        raise ValueError("Central logging is unavailable")
                    events.test()
                    self.send_json(200, b'{"ok":true}')
                    return
                if self.path == "/api/admin/password":
                    username = str(data.get("username", "")).strip()
                    password = str(data.get("password", ""))
                    enabled = bool(data.get("enabled", True))
                    if not (3 <= len(username) <= 32) or not all(character.isalnum() or character in "-_" for character in username):
                        raise ValueError("Username must be 3–32 letters, numbers, hyphens or underscores")
                    if password and len(password) < 8:
                        raise ValueError("Password must contain at least 8 characters")
                    if enabled and not password and not os.getenv("ADMIN_PASSWORD", ""):
                        raise ValueError("Set a password before enabling web sign-in")
                    update_secret(env_path, "ADMIN_USERNAME", username)
                    if password:
                        update_secret(env_path, "ADMIN_PASSWORD", password)
                    update_secret(env_path, "ADMIN_AUTH_ENABLED", "true" if enabled else "false")
                    sessions.clear()
                    body = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Set-Cookie", "pi_bus_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/api/admin/brightness":
                    state.save_display_brightness(int(data.get("brightness", 100)))
                    write_control_request(mode_path.parent, {"action": "set_brightness", "brightness": state.display_brightness})
                    self.send_json(200, json.dumps({"ok": True, "brightness": state.display_brightness}).encode())
                    return
                if self.path == "/api/admin/system-action":
                    action = str(data.get("action", ""))
                    if action not in SYSTEM_ACTIONS:
                        raise ValueError("Unknown system action")
                    request = {"action": action}
                    if action == "set_hostname":
                        request["hostname"] = str(data.get("hostname", "")).strip()
                    if action == "set_wifi":
                        request["ssid"] = str(data.get("ssid", "")).strip()
                        request["password"] = str(data.get("password", ""))
                    if action == "netdata_claim":
                        request.update(token=str(data.get("token", "")), rooms=str(data.get("rooms", "")))
                    if action in {"netdata_claim_command", "netdata_official_install"}:
                        request["command"] = str(data.get("command", ""))
                    if action == "performance_profile":
                        if data.get("profile") not in ("playback", "dashboard"): raise ValueError("Choose playback or dashboard priority.")
                        request["profile"] = data["profile"]
                    if action == "netdata_lightweight":
                        if type(data.get("enabled")) is not bool:
                            raise ValueError("Choose a supported Netdata monitoring mode.")
                        request["enabled"] = data["enabled"]
                    if action == "airplay_configure":
                        request["name"] = str(data.get("name", "")).strip()
                    if action == "set_audio_hat":
                        request["hat"] = str(data.get("hat", "")).strip()
                    if action == "device_credentials":
                        request.update(username=str(data.get("username", "")).strip(), password=str(data.get("password", "")), confirmation=str(data.get("confirmation", "")))
                    if action == "set_rotation":
                        request["transform"] = "180" if data.get("rotated") else "normal"
                    if action == "set_display":
                        profile = str(data.get("profile", ""))
                        orientation = str(data.get("orientation", ""))
                        mounting = str(data.get("mounting", "standard"))
                        if profile not in {"original", "touch2-5", "touch2-7", "touch2-5-7", "touch2-10"}:
                            raise ValueError("Unknown display profile")
                        if orientation not in {"landscape", "portrait"}:
                            raise ValueError("Unknown display orientation")
                        if mounting not in {"standard", "inverted"}:
                            raise ValueError("Unknown display rotation")
                        request.update({"profile": profile, "orientation": orientation, "mounting": mounting})
                    queued = write_control_request(mode_path.parent, request)
                    if events:
                        events.emit("system.action.queued", action=action)
                    self.send_json(202, json.dumps({"ok": True, "status": "queued" if queued else "already_running", "queued": queued}).encode())
                    return
                if self.path == "/api/admin/display-mode":
                    mode = str(data.get("mode", ""))
                    set_display_mode(state, mode_path, mode)
                    view = str(data.get("view", "")).strip()
                    preview_request = None
                    if view:
                        if view not in {"now", "details", "recent", "daily", "releases", "browse", "search", "surprise", "tidal", "bus", "home", "settings"}:
                            raise ValueError("Unknown display view")
                        browse_action = str(data.get("browse_action", ""))
                        item_key = str(data.get("item_key", ""))
                        section = str(data.get("section", ""))
                        if browse_action not in {"", "open", "back", "current", "section"} or len(item_key) > 2048:
                            raise ValueError("Unknown preview navigation")
                        if browse_action == "section" and section not in {"albums", "artists", "genres", "playlists"}:
                            raise ValueError("Unknown preview section")
                        settings_page = str(data.get("settings_page", "overview")) if view == "settings" else ""
                        if settings_page and settings_page not in {"overview", "display", "network", "controls", "performance"}:
                            raise ValueError("Unknown touchscreen Settings page")
                        preview_request = state.request_display_view(view, browse_action, item_key, section, settings_page)
                    if events:
                        events.emit("display.mode.changed", mode=mode)
                    self.send_json(200, json.dumps({"ok": True, "display_mode": mode, "display_view": view or None, "request_id": preview_request["id"] if preview_request else None}).encode())
                    return
                current = state.config
                def values(name, fallback):
                    value = data.get(name, fallback)
                    if isinstance(value, (list, tuple)):
                        return tuple(str(item).strip() for item in value if str(item).strip())
                    return tuple(item.strip() for item in str(value).split(",") if item.strip())

                requested_home_entities = values("home_assistant_entities", current.home_assistant_entities)
                if len(requested_home_entities) > 32:
                    raise ValueError("Choose no more than 32 Home Assistant entities")
                requested_deck_entities = values("home_assistant_deck_entities", current.home_assistant_deck_entities)
                if len(requested_deck_entities) > 40:
                    raise ValueError("Choose no more than forty Stream Deck entities")
                unsupported = [item for item in (*requested_home_entities, *requested_deck_entities) if item.split(".", 1)[0] not in HOME_ASSISTANT_DOMAINS]
                if unsupported:
                    raise ValueError("Unsupported Home Assistant entity: " + unsupported[0])
                home_url = str(data.get("home_assistant_url", current.home_assistant_url)).strip()
                if home_url and not home_url.startswith(("http://", "https://")):
                    raise ValueError("Home Assistant address must start with http:// or https://")
                openobserve_url = str(data.get("openobserve_url", current.openobserve_url)).strip().rstrip("/")
                candidate = Config(
                    release_channel=str(data.get("release_channel", current.release_channel)),
                    auto_update_enabled=data.get("auto_update_enabled", current.auto_update_enabled),
                    auto_update_time=str(data.get("auto_update_time", current.auto_update_time)),
                    bus_stop_code=str(data.get("bus_stop_code", current.bus_stop_code)).strip(),
                    bus_stop_name=str(data.get("bus_stop_name", current.bus_stop_name)).strip(),
                    services=values("services", current.services),
                    route_tint=int(data.get("route_tint", current.route_tint)),
                    service_colours=", ".join(f"{route}={name}" for route, name in parse_route_colours(str(data.get("service_colours", current.service_colours))).items()),
                    walking_minutes=int(data.get("walking_minutes", current.walking_minutes)), poll_seconds=int(data.get("poll_seconds", current.poll_seconds)),
                    stale_after_seconds=current.stale_after_seconds,
                    morning_start=str(data.get("morning_start", current.morning_start)), morning_end=str(data.get("morning_end", current.morning_end)),
                    scheduled_wake_enabled=bool(data.get("scheduled_wake_enabled", current.scheduled_wake_enabled)),
                    weekend_wake_enabled=bool(data.get("weekend_wake_enabled", current.weekend_wake_enabled)),
                    weekend_wake_time=str(data.get("weekend_wake_time", current.weekend_wake_time)),
                    sleep_start=str(data.get("sleep_start", current.sleep_start)), sleep_end=str(data.get("sleep_end", current.sleep_end)),
                    timezone=current.timezone, roon_display_url=current.roon_display_url,
                    roon_zone_name=str(data.get("roon_zone_name", current.roon_zone_name)).strip(),
                    roon_core_host=str(data.get("roon_core_host", current.roon_core_host)).strip(),
                    roon_display_name=str(data.get("roon_display_name", current.roon_display_name)).strip() or "Roon",
                    display_theme=str(data.get("display_theme", current.display_theme)),
                    display_background=str(data.get("display_background", current.display_background)),
                    interface_size=str(data.get("interface_size", current.interface_size)),
                    settings_layout=str(data.get("settings_layout", current.settings_layout)),
                    touch_roon_bridge=bool(data.get("touch_roon_bridge", current.touch_roon_bridge)),
                    touch_airplay=bool(data.get("touch_airplay", current.touch_airplay)),
                    touch_netdata=bool(data.get("touch_netdata", current.touch_netdata)),
                    portrait_discovery_columns=int(data.get("portrait_discovery_columns", current.portrait_discovery_columns)),
                    landscape_music_clock=str(data.get("landscape_music_clock", current.landscape_music_clock)),
                    bus_enabled=bool(data.get("bus_enabled", current.bus_enabled)),
                    roon_now_playing_name=str(data.get("roon_now_playing_name", current.roon_now_playing_name)).strip() or "Now Playing",
                    roon_queue_name=str(data.get("roon_queue_name", current.roon_queue_name)).strip() or "Queue",
                    sleep_when_roon_idle=bool(data.get("sleep_when_roon_idle", current.sleep_when_roon_idle)),
                    roon_show_controls=bool(data.get("roon_show_controls", current.roon_show_controls)),
                    roon_show_clock=bool(data.get("roon_show_clock", current.roon_show_clock)),
                    roon_show_queue=bool(data.get("roon_show_queue", current.roon_show_queue)),
                    roon_show_browser=bool(data.get("roon_show_browser", current.roon_show_browser)),
                    bluos_enabled=bool(data.get("bluos_enabled", current.bluos_enabled)),
                    bluos_player_address=str(data.get("bluos_player_address", current.bluos_player_address)).strip(),
                    bluos_visible_inputs=values("bluos_visible_inputs", current.bluos_visible_inputs),
                    bluos_input_names=values("bluos_input_names", current.bluos_input_names),
                    sleep_show_clock=bool(data.get("sleep_show_clock", current.sleep_show_clock)),
                    auto_switch_to_roon=bool(data.get("auto_switch_to_roon", current.auto_switch_to_roon)),
                    roon_idle_return_seconds=int(data.get("roon_idle_return_seconds", current.roon_idle_return_seconds)),
                    browse_idle_return_seconds=int(data.get("browse_idle_return_seconds", current.browse_idle_return_seconds)),
                    outside_hours_wake_seconds=int(data.get("outside_hours_wake_seconds", current.outside_hours_wake_seconds)),
                    remote_wake_seconds=int(data.get("remote_wake_seconds", current.remote_wake_seconds)),
                    daytime_inactivity_seconds=int(data.get("daytime_inactivity_seconds", current.daytime_inactivity_seconds)),
                    home_assistant_enabled=bool(data.get("home_assistant_enabled", current.home_assistant_enabled)),
                    home_assistant_title=str(data.get("home_assistant_title", current.home_assistant_title)).strip(),
                    home_assistant_url=home_url,
                    home_assistant_entities=requested_home_entities,
                    home_assistant_deck_entities=requested_deck_entities,
                    home_assistant_color_mode=str(data.get("home_assistant_color_mode", current.home_assistant_color_mode)),
                    home_assistant_single_color=str(data.get("home_assistant_single_color", current.home_assistant_single_color)),
                    home_assistant_light_color=str(data.get("home_assistant_light_color", current.home_assistant_light_color)),
                    home_assistant_fan_color=str(data.get("home_assistant_fan_color", current.home_assistant_fan_color)),
                    home_assistant_switch_color=str(data.get("home_assistant_switch_color", current.home_assistant_switch_color)),
                    home_assistant_scene_color=str(data.get("home_assistant_scene_color", current.home_assistant_scene_color)),
                    openobserve_enabled=bool(data.get("openobserve_enabled", current.openobserve_enabled)),
                    openobserve_url=openobserve_url,
                    openobserve_org=str(data.get("openobserve_org", current.openobserve_org)).strip(),
                    openobserve_stream=str(data.get("openobserve_stream", current.openobserve_stream)).strip(),
                    openobserve_username=str(data.get("openobserve_username", current.openobserve_username)).strip(),
                    end_action="display", simulate=current.simulate,
                )
                if not candidate.bus_stop_code.isdigit() or len(candidate.bus_stop_code) != 5:
                    raise ValueError("Bus stop code must be five digits")
                if candidate.display_theme not in {"fresh-mint", "roon"}:
                    raise ValueError("Choose Fresh Mint or Roon for the display style")
                if candidate.display_background not in {"current", "black"}:
                    raise ValueError("Choose Purple Gradient or Pure Black")
                if candidate.settings_layout not in {"graph", "simple"}:
                    raise ValueError("Choose Graph or Simple for the Settings layout")
                if candidate.interface_size not in {"smaller", "standard", "larger"}:
                    raise ValueError("Choose Smaller, Standard or Larger for interface size")
                if candidate.portrait_discovery_columns not in {2, 3}:
                    raise ValueError("Choose 2 or 3 portrait Discover columns")
                if candidate.landscape_music_clock not in {"icon", "full"}:
                    raise ValueError("Choose Full clock or Clock icon")
                if type(candidate.auto_update_enabled) is not bool:
                    raise ValueError("Choose whether automatic updates are enabled")
                if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", candidate.auto_update_time):
                    raise ValueError("Choose an automatic update time in HH:MM format")
                if candidate.release_channel not in {"stable", "beta"}:
                    raise ValueError("Choose Stable or Beta for the release channel")
                if len(candidate.roon_display_name) > 16:
                    raise ValueError("Roon display name must be 16 characters or fewer")
                if len(candidate.roon_now_playing_name) > 16 or len(candidate.roon_queue_name) > 16:
                    raise ValueError("Roon view names must be 16 characters or fewer")
                if not 0 <= candidate.route_tint <= 100:
                    raise ValueError("Route colour strength must be between 0 and 100")
                if candidate.walking_minutes < 0 or candidate.walking_minutes > 60:
                    raise ValueError("Walking time must be between 0 and 60 minutes")
                if not (5 <= candidate.poll_seconds <= 300):
                    raise ValueError("Polling must be between 5 and 300 seconds")
                if not (0 <= candidate.roon_idle_return_seconds <= 7200):
                    raise ValueError("Roon return delay must be between 0 and 7200 seconds")
                if not (0 <= candidate.browse_idle_return_seconds <= 7200):
                    raise ValueError("Browse return delay must be between 0 and 7200 seconds")
                if not (30 <= candidate.outside_hours_wake_seconds <= 7200):
                    raise ValueError("Wake timeout must be between 30 and 7200 seconds")
                if not (5 <= candidate.remote_wake_seconds <= 7200):
                    raise ValueError("Dial and remote wake time must be between 5 and 7200 seconds")
                if not (0 <= candidate.daytime_inactivity_seconds <= 7200):
                    raise ValueError("Daytime inactivity timeout must be between 0 and 7200 seconds")
                if candidate.home_assistant_color_mode not in {"single", "multi"}:
                    raise ValueError("Choose Single colour or Multi-colour")
                for value in (candidate.home_assistant_single_color, candidate.home_assistant_light_color, candidate.home_assistant_fan_color, candidate.home_assistant_switch_color, candidate.home_assistant_scene_color):
                    if len(value) != 7 or value[0] != "#" or any(character not in "0123456789abcdefABCDEF" for character in value[1:]):
                        raise ValueError("Home Assistant tile colours must use #RRGGBB")
                wall_time.fromisoformat(candidate.morning_start)
                wall_time.fromisoformat(candidate.morning_end)
                wall_time.fromisoformat(candidate.weekend_wake_time)
                wall_time.fromisoformat(candidate.sleep_start)
                wall_time.fromisoformat(candidate.sleep_end)
                if candidate.openobserve_enabled:
                    openobserve_endpoint(candidate)
                    supplied_openobserve_password = str(data.get("openobserve_password", ""))
                    if not candidate.openobserve_username:
                        raise ValueError("OpenObserve username is required")
                    if not supplied_openobserve_password and not os.getenv("OPENOBSERVE_PASSWORD", ""):
                        raise ValueError("OpenObserve password is required")
                write_config(config_path, candidate)
                account_key = str(data.get("lta_account_key", "")).strip()
                if account_key:
                    update_secret(env_path, "LTA_ACCOUNT_KEY", account_key)
                home_token = str(data.get("home_assistant_token", "")).strip()
                if home_token:
                    update_secret(env_path, "HOME_ASSISTANT_TOKEN", home_token)
                openobserve_password = str(data.get("openobserve_password", ""))
                if openobserve_password:
                    update_secret(env_path, "OPENOBSERVE_PASSWORD", openobserve_password)
                state.enabled_services.intersection_update(candidate.services)
                state.enabled_services.update(service for service in candidate.services if service not in current.services)
                state.save_enabled_services()
                state.config = candidate
                if events:
                    events.emit("settings.saved", section=str(data.get("section", "unknown")))
                self.send_json(200, json.dumps({"ok": True}).encode())
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                self.send_json(400, json.dumps({"error": str(exc)}).encode())

        def is_authorised(self) -> bool:
            if self.client_address[0] in {"127.0.0.1", "::1"}:
                return True
            if os.getenv("ADMIN_AUTH_ENABLED", "true").lower() == "false":
                return True
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("pi_bus_session")
            if token and sessions.get(token.value, 0) > time.time():
                return True
            return False

        def proxy_roon(self, method: str) -> None:
            upstream_path = self.path[len("/roon"):] or "/"
            body = None
            if method == "POST":
                length = min(int(self.headers.get("Content-Length", "0")), 1_048_576)
                body = self.rfile.read(length)
            request = urllib.request.Request(
                "http://127.0.0.1:8766" + upstream_path,
                data=body,
                headers={"Content-Type": self.headers.get("Content-Type", "application/octet-stream")},
                method=method,
            )
            response_started = False
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    self.send_response(response.status)
                    for name in ("Content-Type", "Cache-Control", "X-Accel-Buffering"):
                        value = response.headers.get(name)
                        if value:
                            self.send_header(name, value)
                    self.end_headers()
                    response_started = True
                    while chunk := response.read(64 * 1024):
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except urllib.error.HTTPError as exc:
                self.send_json(exc.code, exc.read())
            except (OSError, urllib.error.URLError):
                # Event streams reconnect normally and clients can close a page at any time.
                if not response_started:
                    self.send_json(502, b'{"error":"Roon controller is unavailable"}')

        def authorised(self) -> bool:
            if self.is_authorised():
                return True
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return False

        def send_json(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return Handler


def initialise_update_channel(config, config_path, state_dir):
    """Existing beta appliances retain beta; fresh images carry a marker."""
    if os.getenv("PI_HOME_APPLIANCE_PLATFORM") != "alpine-prototype":
        return config
    marker = state_dir / "update-channel-initialized"
    if marker.exists():
        return config
    state_dir.mkdir(parents=True, exist_ok=True)
    config = Config(**{**config.__dict__, "release_channel": "beta"})
    write_config(config_path, config)
    marker.touch()
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=Path, default=Path(".state"))
    args = parser.parse_args()
    load_env(args.env)
    config = load_config(args.config)
    config = initialise_update_channel(config, args.config, args.state_dir)
    if args.simulate:
        config = Config(**{**config.__dict__, "simulate": True})
    clear_sleep_mode_on_start(args.state_dir / "display-mode")
    state = State(config, args.state_dir)
    events = OpenObserveLogger(lambda: state.config)
    stop = threading.Event()
    threading.Thread(target=state.performance.run, args=(stop,), daemon=True).start()
    threading.Thread(target=poll, args=(state, stop, events), daemon=True).start()
    threading.Thread(target=backup_server_client.schedule, args=(args.state_dir, args.config, args.env, __version__, stop), daemon=True).start()
    threading.Thread(target=remote_backup.schedule, args=(args.state_dir, args.config, args.env, __version__, stop), daemon=True).start()
    threading.Thread(target=home_assistant_poll, args=(state, stop, events), daemon=True).start()
    threading.Thread(target=state.listening.poll, args=(stop,), daemon=True).start()
    threading.Thread(target=play_trigger_watch, args=(state, stop), daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, args.config, args.env, args.state_dir / "display-mode", events))
    deck_host = "[::1]" if ":" in args.host else "127.0.0.1"
    threading.Thread(target=run_streamdeck, args=(state.listening, f"http://{deck_host}:{server.server_port}", stop), daemon=True).start()
    events.emit("application.started", bind_host=args.host, bind_port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        events.close()
        server.server_close()


if __name__ == "__main__":
    main()
