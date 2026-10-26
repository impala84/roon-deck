from __future__ import annotations

import os
import tomllib

HOME_ASSISTANT_DOMAINS = {"fan", "light", "scene", "switch", "input_boolean"}
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    release_channel: str = "stable"
    bus_enabled: bool = True
    bus_stop_code: str = "00000"
    bus_stop_name: str = "Bus stop"
    services: tuple[str, ...] = ()
    walking_minutes: int = 7
    poll_seconds: int = 20
    stale_after_seconds: int = 75
    morning_start: str = "06:00"
    morning_end: str = "10:00"
    scheduled_wake_enabled: bool = True
    weekend_wake_enabled: bool = False
    weekend_wake_time: str = "08:00"
    sleep_start: str = "23:00"
    sleep_end: str = "06:00"
    timezone: str = "Asia/Singapore"
    roon_display_url: str = ""
    roon_zone_name: str = ""
    roon_display_name: str = "Roon"
    display_theme: str = "fresh-mint"
    display_background: str = "current"
    interface_size: str = "standard"
    settings_layout: str = "graph"
    # Quick switches shown on the touchscreen Settings page for services that are installed.
    touch_roon_bridge: bool = True
    touch_airplay: bool = False
    touch_netdata: bool = True
    portrait_discovery_columns: int = 2
    landscape_music_clock: str = "icon"
    roon_now_playing_name: str = "Now Playing"
    roon_queue_name: str = "Queue"
    sleep_when_roon_idle: bool = False
    roon_show_controls: bool = True
    roon_show_clock: bool = True
    roon_show_queue: bool = True
    roon_show_browser: bool = True
    bluos_enabled: bool = False
    bluos_player_address: str = ""
    bluos_visible_inputs: tuple[str, ...] = ()
    bluos_input_names: tuple[str, ...] = ()
    sleep_show_clock: bool = False
    auto_switch_to_roon: bool = True
    roon_idle_return_seconds: int = 300
    browse_idle_return_seconds: int = 60
    outside_hours_wake_seconds: int = 600
    daytime_inactivity_seconds: int = 900
    home_assistant_enabled: bool = False
    home_assistant_title: str = "Home Controls"
    home_assistant_url: str = ""
    home_assistant_entities: tuple[str, ...] = ()
    home_assistant_color_mode: str = "multi"
    home_assistant_single_color: str = "#9868f9"
    home_assistant_light_color: str = "#fb923c"
    home_assistant_fan_color: str = "#60a5fa"
    home_assistant_switch_color: str = "#9868f9"
    home_assistant_scene_color: str = "#a3e635"
    openobserve_enabled: bool = False
    openobserve_url: str = ""
    openobserve_org: str = "default"
    openobserve_stream: str = "pi_home"
    openobserve_username: str = ""
    end_action: str = "display"
    simulate: bool = False


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    allowed = set(Config.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown configuration: {', '.join(sorted(unknown))}")
    if "services" in data:
        data["services"] = tuple(str(item) for item in data["services"])
    if "home_assistant_entities" in data:
        data["home_assistant_entities"] = tuple(str(item) for item in data["home_assistant_entities"])
    if "bluos_visible_inputs" in data:
        data["bluos_visible_inputs"] = tuple(str(item) for item in data["bluos_visible_inputs"])
    if "bluos_input_names" in data:
        data["bluos_input_names"] = tuple(str(item) for item in data["bluos_input_names"])
    config = Config(**data)
    if type(config.portrait_discovery_columns) is not int or config.portrait_discovery_columns not in {2, 3}:
        raise ValueError("portrait_discovery_columns must be 2 or 3")
    if config.release_channel not in {"stable", "beta"}:
        raise ValueError("release_channel must be stable or beta")
    if config.landscape_music_clock not in {"icon", "full"}:
        raise ValueError("landscape_music_clock must be icon or full")
    if config.display_background not in {"current", "black"}:
        raise ValueError("display_background must be current or black")
    if config.display_theme not in {"fresh-mint", "roon"}:
        raise ValueError("display_theme must be fresh-mint or roon")
    if config.interface_size not in {"smaller", "standard", "larger"}:
        raise ValueError("interface_size must be smaller, standard or larger")
    if config.settings_layout not in {"graph", "simple"}:
        raise ValueError("settings_layout must be graph or simple")
    for name in ("touch_roon_bridge", "touch_airplay", "touch_netdata"):
        if type(getattr(config, name)) is not bool:
            raise ValueError(f"{name} must be true or false")
    if not (5 <= config.poll_seconds <= 300):
        raise ValueError("poll_seconds must be between 5 and 300")
    if config.end_action not in {"display", "shutdown", "reboot"}:
        raise ValueError("end_action must be display, shutdown or reboot")
    if not (0 <= config.roon_idle_return_seconds <= 7200):
        raise ValueError("roon_idle_return_seconds must be between 0 and 7200")
    if not (0 <= config.browse_idle_return_seconds <= 7200):
        raise ValueError("browse_idle_return_seconds must be between 0 and 7200")
    if not (30 <= config.outside_hours_wake_seconds <= 7200):
        raise ValueError("outside_hours_wake_seconds must be between 30 and 7200")
    if not (0 <= config.daytime_inactivity_seconds <= 7200):
        raise ValueError("daytime_inactivity_seconds must be between 0 and 7200")
    if len(config.home_assistant_entities) > 8:
        raise ValueError("A maximum of eight Home Assistant entities can be shown")
    if len(config.home_assistant_title) > 60:
        raise ValueError("Home Assistant title must be 60 characters or fewer")
    if config.home_assistant_color_mode not in {"single", "multi"}:
        raise ValueError("Home Assistant colour mode must be single or multi")
    for value in (config.home_assistant_single_color, config.home_assistant_light_color, config.home_assistant_fan_color, config.home_assistant_switch_color, config.home_assistant_scene_color):
        if len(value) != 7 or value[0] != "#" or any(character not in "0123456789abcdefABCDEF" for character in value[1:]):
            raise ValueError("Home Assistant tile colours must use #RRGGBB")
    unsupported = [item for item in config.home_assistant_entities if item.split(".", 1)[0] not in HOME_ASSISTANT_DOMAINS]
    if unsupported:
        raise ValueError("Unsupported Home Assistant entity: " + unsupported[0])
    if config.bluos_player_address and any(char.isspace() for char in config.bluos_player_address):
        raise ValueError("BluOS player address cannot contain spaces")
    if config.openobserve_url and not config.openobserve_url.startswith(("http://", "https://")):
        raise ValueError("openobserve_url must start with http:// or https://")
    if any(not value.strip() for value in (config.openobserve_org, config.openobserve_stream)):
        raise ValueError("OpenObserve organisation and stream cannot be empty")
    return config
