"""Per-tile look of the touchscreen Home page: size, label, icon, image and colour, stored beside the other device settings."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

SIZES = {"auto", "quarter", "half", "full"}
ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,78}\.png")
ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]{1,100}(#[1-3])?")   # "light.lamp#2" is a second copy of that tile, on another page
BASE = re.compile(r"#[1-3]$")
TILE_KEYS = {"size", "rows", "col", "row", "label", "icon", "image", "color", "also", "half", "sub", "show", "art", "scrubber", "volume", "heading", "align", "download", "upload", "zone", "with", "input", "input_alt", "page", "route", "border", "parked", "steps", "note"}
MODES = ("roondeck.mode", "roondeck.mode2", "roondeck.mode3", "roondeck.mode4")   # listening-mode tiles: one tap runs a list of steps in order
STEP_KINDS = ("kef_power", "kef_input", "kef_volume", "ha_on", "ha_off", "ha_run", "ir")
MAX_STEPS = 12
KEF_CARDS = ("roondeck.kef", "roondeck.kef_power", "roondeck.kef_input", "roondeck.kef_volume")
MAX_PAGES = 4
COLUMNS = (2, 3)
PLAYER, BUS = "roondeck.player", "roondeck.bus"   # the player and next-bus cards are tiles on the Home grid too
CPU, NETWORK, MEMORY = "roondeck.cpu", "roondeck.network", "roondeck.memory"
VOLUME = "roondeck.volume"   # a large volume readout with minus and plus
UPDATE = "roondeck.update"   # an action tile: check for and install the latest RoonDeck
GROUPS = ("roondeck.group", "roondeck.group2", "roondeck.group3")   # action tiles: group / ungroup a Roon zone with another   # live tiles the owner can add


def base_id(entity_id):
    """The device or card a tile copy belongs to: light.lamp#2 is a copy of light.lamp."""
    return BASE.sub("", entity_id)


def clean_steps(raw):
    """The steps of a listening-mode tile: each is something to do (KEF power, input or volume; a Home Assistant switch or script; an infrared button) and how long to wait afterwards."""
    if not isinstance(raw, list) or len(raw) > MAX_STEPS: raise ValueError(f"A listening mode can have up to {MAX_STEPS} steps")
    steps = []
    for item in raw:
        if not isinstance(item, dict) or item.get("do") not in STEP_KINDS: raise ValueError("Choose what each step does")
        kind, step = item["do"], {"do": item["do"]}
        if kind == "kef_power":
            if item.get("value") not in ("on", "off"): raise ValueError("A KEF power step is on or off")
            step["value"] = item["value"]
        elif kind == "kef_input":
            if item.get("value") not in ("wifi", "bluetooth", "aux", "optical"): raise ValueError("Choose a KEF input")
            step["value"] = item["value"]
        elif kind == "kef_volume":
            value = item.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100: raise ValueError("KEF volume is 0 to 100")
            step["value"] = value
        elif kind in ("ha_on", "ha_off", "ha_run"):
            entity = item.get("entity_id")
            if not entity: continue   # not chosen yet: left out
            if not isinstance(entity, str) or not re.fullmatch(r"[a-z_]+\.[a-z0-9_]{1,100}", entity): raise ValueError("Choose a Home Assistant device for the step")
            step["entity_id"] = entity
        else:
            if not all(isinstance(item.get(name), str) and item[name].strip() for name in ("entity_id", "device", "command")): continue   # remote, device and button not all filled in: left out
            for name, top in (("entity_id", 100), ("device", 80), ("command", 120)): step[name] = item[name].strip()[:top]
        wait = item.get("wait", 0)
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 60: raise ValueError("Wait between 0 and 60 seconds after a step")
        if wait: step["wait"] = round(float(wait), 1) if wait != int(wait) else int(wait)
        steps.append(step)
    return steps


def validate_layout(data):
    if not isinstance(data, dict) or set(data) - {"tiles", "columns", "pages"}:
        raise ValueError("Invalid Home layout")
    tiles = data.get("tiles", {})
    if not isinstance(tiles, dict) or len(tiles) > 120:
        raise ValueError("Home layout can describe up to 120 tiles")
    columns = data.get("columns")
    if columns is not None and (isinstance(columns, bool) or columns not in COLUMNS): raise ValueError("Home can use 2 or 3 columns")
    pages = data.get("pages")
    if pages is not None and (isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES): raise ValueError(f"Home can have 1 to {MAX_PAGES} pages")
    clean = {}
    for entity_id, tile in tiles.items():
        if not isinstance(entity_id, str) or not ENTITY.fullmatch(entity_id) or not isinstance(tile, dict) or set(tile) - TILE_KEYS:
            extra = ", ".join(sorted(map(str, set(tile) - TILE_KEYS))) if isinstance(tile, dict) else ""
            raise ValueError(f"Invalid Home tile {str(entity_id)[:60]!r}" + (f" (unknown setting: {extra})" if extra else ""))
        out = {}
        if "size" in tile:
            if tile["size"] not in SIZES: raise ValueError("Choose a tile size")
            out["size"] = tile["size"]
        if "rows" in tile:
            if tile["rows"] not in (1, 2, 3) or isinstance(tile["rows"], bool): raise ValueError("Tiles can be one, two or three rows tall")
            # The player is two rows tall unless the owner makes it one; every other tile is one row unless it is two.
            if tile["rows"] in (2, 3) or (tile["rows"] == 1 and entity_id == PLAYER): out["rows"] = tile["rows"]
        if entity_id.split("#")[0] == "roondeck.kef" and out.get("rows", 1) < 2: out["rows"] = 2   # the combined KEF tile needs two rows for its number and buttons
        for name, top in (("col", 3), ("row", 15)):
            if name in tile:
                if isinstance(tile[name], bool) or not isinstance(tile[name], int) or not 0 <= tile[name] <= top: raise ValueError("Tile positions must be on the screen grid")
                out[name] = tile[name]
        if "page" in tile:   # which page of the dashboard the tile is on; the first page is the default
            if isinstance(tile["page"], bool) or not isinstance(tile["page"], int) or not 0 <= tile["page"] < MAX_PAGES: raise ValueError("Choose a page for the tile")
            if tile["page"] > 0: out["page"] = tile["page"]
        if tile.get("half") is True: out["half"] = True   # half a column wide (dashboard only)
        if tile.get("sub") == 1 and not isinstance(tile.get("sub"), bool): out["sub"] = 1   # the right-hand half of its column
        # Now Playing options: artwork as the background (default), a thumbnail or none; a seekable scrubber; the volume row and heading can be hidden.
        if tile.get("art") in ("thumb", "off", "fade"): out["art"] = tile["art"]
        if tile.get("scrubber") is True: out["scrubber"] = True
        if tile.get("volume") is False: out["volume"] = False
        if tile.get("heading") is False: out["heading"] = False
        if tile.get("align") == "left": out["align"] = "left"   # the track text is centred unless asked otherwise
        for name in ("zone", "with"):   # the two Roon zones a group tile works on, by name
            if isinstance(tile.get(name), str) and tile[name].strip(): out[name] = tile[name].strip()[:80]
        for name in ("input", "input_alt"):   # the KEF input tile: the input a tap selects, and an optional second one to toggle with
            if tile.get(name) in ("wifi", "bluetooth", "aux", "optical"): out[name] = tile[name]
        if out.get("input_alt") and out.get("input_alt") == out.get("input"): del out["input_alt"]
        if "input" not in out: out.pop("input_alt", None)
        for name in ("download", "upload"):   # the network tile can show either direction, or both
            if tile.get(name) is False: out[name] = False
        if isinstance(tile.get("note"), str) and tile["note"].strip() and entity_id.split("#")[0] in MODES: out["note"] = tile["note"].strip()[:60]   # a line under a listening mode's title
        if "steps" in tile and entity_id.split("#")[0] in MODES:
            steps = clean_steps(tile["steps"])
            if steps: out["steps"] = steps
        if tile.get("show") is True: out["show"] = True   # a live tile the owner has added
        if tile.get("parked") is True: out["parked"] = True   # set aside in the holding pen: kept, with its options, but not shown on any page
        if tile.get("also"):
            also = tile["also"]
            if not isinstance(also, list) or len(also) > 4 or any(not isinstance(item, str) or not ENTITY.fullmatch(item) or item == entity_id or "#" in item for item in also):
                raise ValueError("A tile can switch up to four other devices with it")
            out["also"] = list(dict.fromkeys(also))
        if tile.get("label"):
            if not isinstance(tile["label"], str) or len(tile["label"]) > 40: raise ValueError("Tile labels must be at most 40 characters")
            out["label"] = tile["label"]
        for name in ("icon", "image"):
            if tile.get(name):
                if not isinstance(tile[name], str) or not ART_NAME.fullmatch(tile[name]): raise ValueError("Artwork must be a PNG filename")
                out[name] = tile[name]
        if tile.get("color"):
            if not isinstance(tile["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", tile["color"]): raise ValueError("Tile colours must look like #fb923c")
            out["color"] = tile["color"]
        if tile.get("border"):   # a border colour for a tile that has no colour of its own
            if not isinstance(tile["border"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", tile["border"]): raise ValueError("Border colours must look like #fb923c")
            out["border"] = tile["border"]
        if tile.get("route"):   # the bus route a Next-bus tile shows first
            if not isinstance(tile["route"], str) or not re.fullmatch(r"[A-Za-z0-9]{1,8}", tile["route"]): raise ValueError("Bus routes are letters and numbers, like 42 or 401")
            out["route"] = tile["route"]
        if out: clean[entity_id] = out
    return {"tiles": clean, **({"columns": columns} if columns is not None else {}), **({"pages": pages} if pages and pages > 1 else {})}


def load_layout(path):
    try:
        return validate_layout(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {"tiles": {}}


def save_layout(path, data):
    data = validate_layout(data)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".home-layout-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return data


def with_layout(home, layout):
    """The Home data the touchscreen draws, with each device's saved tile look attached."""
    tiles = (layout or {}).get("tiles", {})
    if not isinstance(home, dict): return home
    copies = {}
    for key, tile in tiles.items():
        if "#" in key: copies.setdefault(base_id(key), []).append(tile)   # the same device on other pages
    entities = []
    for item in home.get("entities", []):
        entity_id = item.get("entity_id")
        entities.append({**item, "tile": tiles[entity_id]} if entity_id in tiles else item)
        entities.extend({**item, "tile": tile} for tile in copies.get(entity_id, []))
    cards_of = (PLAYER, BUS, CPU, NETWORK, MEMORY, VOLUME, UPDATE, *GROUPS, *MODES, *KEF_CARDS)
    out = {**home, "entities": entities, "cards": {key: tiles[key] for key in tiles if base_id(key) in cards_of}}
    if (layout or {}).get("columns") in COLUMNS: out["columns"] = layout["columns"]
    if isinstance((layout or {}).get("pages"), int) and layout["pages"] > 1: out["pages"] = layout["pages"]
    return out


def tint_icon(data, colour):
    """A white-on-transparent icon redrawn in one colour, so a chosen icon matches the built-in ones. The original bytes come back if it cannot be done."""
    if not isinstance(colour, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour): return data
    try:
        from io import BytesIO
        from PIL import Image
        icon = Image.open(BytesIO(data)).convert("RGBA")
        alpha = icon.getchannel("A"); side = max(icon.size)
        box = alpha.getbbox()
        if box and side >= 64 and max(box[2] - box[0], box[3] - box[1]) < side * .7:
            # Icons saved by earlier versions sit small in the middle of their square: fill it.
            glyph = alpha.crop(box); scale = side * .86 / max(glyph.size)
            glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))), Image.LANCZOS)
            alpha = Image.new("L", icon.size, 0); alpha.paste(glyph, ((icon.width - glyph.width) // 2, (icon.height - glyph.height) // 2))
        out = Image.new("RGBA", icon.size, tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)) + (0,))
        out.putalpha(alpha)
        buffer = BytesIO(); out.save(buffer, "PNG")
        return buffer.getvalue()
    except Exception:
        return data
