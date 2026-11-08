from __future__ import annotations

from datetime import datetime
from math import floor

LOAD_LABELS = {"SEA": "Seats", "SDA": "Standing", "LSD": "Crowded", "": "Unknown"}


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def minutes_until(value: str, now: datetime) -> int | None:
    arrival = parse_time(value)
    if arrival is None:
        return None
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return max(0, floor((arrival - now).total_seconds() / 60))


ROUTE_COLOURS = ("blue", "green", "violet", "amber", "rose", "teal")
DEFAULT_ROUTE_COLOURS = {"40": "blue", "42": "green", "401": "violet"}


def parse_route_colours(text: str) -> dict[str, str]:
    """"40=blue, 42=green" as {"40": "blue", "42": "green"}; anything unrecognised is ignored."""
    colours = {}
    for part in str(text or "").split(","):
        route, _, name = part.partition("=")
        route, name = route.strip(), name.strip().lower()
        if route and name in ROUTE_COLOURS: colours[route] = name
    return colours


def normalise(payload: dict, now: datetime, services: tuple[str, ...], walking: int, colours: dict[str, str] | None = None) -> list[dict]:
    wanted = set(services)
    output = []
    for service in payload.get("Services", []):
        number = str(service.get("ServiceNo", ""))
        if wanted and number not in wanted:
            continue
        buses = []
        for key in ("NextBus", "NextBus2", "NextBus3"):
            raw = service.get(key) or {}
            minutes = minutes_until(str(raw.get("EstimatedArrival", "")), now)
            if minutes is None:
                continue
            buses.append({
                "minutes": minutes,
                "load": str(raw.get("Load", "")),
                "load_label": LOAD_LABELS.get(str(raw.get("Load", "")), "Unknown"),
                "monitored": bool(int(raw.get("Monitored", 0) or 0)),
                "wheelchair": raw.get("Feature") == "WAB",
                "type": str(raw.get("Type", "")),
            })
        output.append({
            "service": number,
            "operator": service.get("Operator", ""),
            "colour": (colours or {}).get(number) or DEFAULT_ROUTE_COLOURS.get(number, "amber"),
            "arrivals": buses,
            "leave_in": max(0, buses[0]["minutes"] - walking) if buses else None,
        })
    order = {number: index for index, number in enumerate(("40", "42", "401"))}
    output.sort(key=lambda item: order.get(item["service"], 3))
    return output
