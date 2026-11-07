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
TILE_KEYS = {"size", "label", "icon", "image", "color"}


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
