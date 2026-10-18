from __future__ import annotations

import os
import tomllib
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
    sleep_start: str = "23:00"
    sleep_end: str = "06:00"
    timezone: str = "Asia/Singapore"
    roon_display_url: str = ""
    roon_zone_name: str = ""
    roon_display_name: str = "Roon"
    display_theme: str = "fresh-mint"
    display_background: str = "current"
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
    home_assistant_url: str = ""
    home_assistant_entities: tuple[str, ...] = ()
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
    if config.bluos_player_address and any(char.isspace() for char in config.bluos_player_address):
        raise ValueError("BluOS player address cannot contain spaces")
    if config.openobserve_url and not config.openobserve_url.startswith(("http://", "https://")):
        raise ValueError("openobserve_url must start with http:// or https://")
    if any(not value.strip() for value in (config.openobserve_org, config.openobserve_stream)):
        raise ValueError("OpenObserve organisation and stream cannot be empty")
    return config
