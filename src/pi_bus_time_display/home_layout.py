"""Per-tile look of the touchscreen Home page: size, label, icon, image and colour, stored beside the other device settings."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

SIZES = {"auto", "quarter", "half", "full"}
ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,78}\.png")
ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]{1,100}")
TILE_KEYS = {"size", "rows", "col", "row", "label", "icon", "image", "color"}


def validate_layout(data):
    if not isinstance(data, dict) or set(data) - {"tiles"}:
        raise ValueError("Invalid Home layout")
    tiles = data.get("tiles", {})
    if not isinstance(tiles, dict) or len(tiles) > 40:
        raise ValueError("Home layout can describe up to 40 tiles")
    clean = {}
    for entity_id, tile in tiles.items():
        if not isinstance(entity_id, str) or not ENTITY.fullmatch(entity_id) or not isinstance(tile, dict) or set(tile) - TILE_KEYS:
            raise ValueError("Invalid Home tile")
        out = {}
        if "size" in tile:
            if tile["size"] not in SIZES: raise ValueError("Choose a tile size")
            out["size"] = tile["size"]
        if "rows" in tile:
            if tile["rows"] not in (1, 2) or isinstance(tile["rows"], bool): raise ValueError("Tiles can be one or two rows tall")
            if tile["rows"] == 2: out["rows"] = 2
        for name, top in (("col", 3), ("row", 7)):
            if name in tile:
                if isinstance(tile[name], bool) or not isinstance(tile[name], int) or not 0 <= tile[name] <= top: raise ValueError("Tile positions must be on the screen grid")
                out[name] = tile[name]
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
        if out: clean[entity_id] = out
    return {"tiles": clean}


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
    entities = [{**item, "tile": tiles[item["entity_id"]]} if item.get("entity_id") in tiles else item for item in home.get("entities", [])]
    return {**home, "entities": entities}


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
