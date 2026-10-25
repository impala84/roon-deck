#!/usr/bin/env python3
"""Shared imports, constants, helpers and widgets for the native RoonDeck display."""
from __future__ import annotations

import json
import math
import base64
import io
import subprocess
import os
import re
import select
import struct
import threading
import time
import tomllib
import unicodedata
import urllib.request
import urllib.error
import uuid
import sys
from queue import Queue
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_foreign("cairo")
import cairo
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Graphene, Gsk, Gtk, Pango
sys.path.insert(0, str(Path(__file__).resolve().parent))
from icon_family import FamilyIcon
from white_balance import create_display_window
from layout_constants import CAROUSEL_END_SPACE, PORTRAIT_CONTENT_GAP
from styles import load_css

BUS = "http://127.0.0.1:8765"
ROON = "http://127.0.0.1:8766"
TZ = ZoneInfo("Asia/Singapore")
BRAND_ASSETS = Path(__file__).resolve().parent / "assets" / "brand"


def wordmark_paintable_tinted(target_height, accent="#9868F9"):
    """Render the tightly bounded supplied wordmark at an explicit height."""
    source_svg = (BRAND_ASSETS / "roondeck-wordmark.svg").read_text(encoding="utf-8")
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(source_svg.replace("#9868F9", accent).encode("utf-8")); loader.close()
    source = loader.get_pixbuf()
    target_width = round(target_height * source.get_width() / source.get_height())
    scaled = source.scale_simple(target_width, target_height, GdkPixbuf.InterpType.BILINEAR)
    return Gdk.Texture.new_for_pixbuf(scaled), target_width


def wordmark_paintable(target_height):
    return wordmark_paintable_tinted(target_height)

# Shared appliance page grid: native-display/layout_constants.py (also used by the stylesheet).


def fade_rgba_pixels(pixels, width, height, rowstride, channels, fade_start_ratio=.52):
    """Copy RGB(A) pixels and smoothly reduce their bottom edge to alpha 0."""
    output_stride = width * 4; output = bytearray(output_stride * height)
    fade_start = round(height * fade_start_ratio)
    for y in range(height):
        progress = max(0.0, min(1.0, (y - fade_start) / max(1, height - 1 - fade_start)))
        opacity = 1.0 - progress * progress * (3.0 - 2.0 * progress)
        for x in range(width):
            source_offset = y * rowstride + x * channels; output_offset = y * output_stride + x * 4
            output[output_offset:output_offset + 3] = pixels[source_offset:source_offset + 3]
            source_alpha = pixels[source_offset + 3] if channels == 4 else 255
            output[output_offset + 3] = round(source_alpha * opacity)
    return bytes(output), output_stride


class ElasticCarouselTrack(Gtk.Box):
    """Paint-only resisted touch pull; allocations and resting scroll stay intact."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.elastic_offset = 0.0
        self.spring_timer = None
        self.connect("unmap", self.cancel_spring)

    def cancel_spring(self, *_):
        if self.spring_timer is not None:
            self.remove_tick_callback(self.spring_timer); self.spring_timer = None
        self.elastic_offset = 0.0; self.queue_draw()

    def spring_back(self):
        initial = self.elastic_offset
        self.cancel_spring()
        # Hidden pages have no frame clock; leave them at rest immediately.
        if not self.get_mapped(): return
        self.elastic_offset = initial
        started = time.monotonic()
        def frame(_widget, _clock):
            elapsed = time.monotonic() - started
            if elapsed >= .65:
                self.elastic_offset = 0.0; self.spring_timer = None; self.queue_draw(); return False
            self.elastic_offset = initial * math.exp(-7.5 * elapsed) * math.cos(20 * elapsed)
            self.queue_draw(); return True
        self.spring_timer = self.add_tick_callback(frame)

    def attach_touch_pull(self, scroller, vertical=False):
        self.elastic_vertical = vertical
        drag = Gtk.GestureDrag(); drag.set_touch_only(True)
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        state = {"last": 0.0, "pull": 0.0, "claimed": False}
        def begin(*_):
            self.cancel_spring(); state.update(last=0.0, pull=0.0, claimed=False)
        def update(gesture, x, y):
            if vertical and self.get_ancestor(Gtk.ScrolledWindow) is not scroller: return
            if vertical: x, y = y, x
            delta = x - state["last"]; state["last"] = x
            if not state["claimed"] and (abs(x) < 6 or abs(x) <= abs(y)): return
            adjustment = scroller.get_vadjustment() if vertical else scroller.get_hadjustment()
            lower = adjustment.get_lower(); upper = max(lower, adjustment.get_upper() - adjustment.get_page_size())
            value = adjustment.get_value()
            outward = (value <= lower + .5 and delta > 0) or (value >= upper - .5 and delta < 0)
            if not state["claimed"]:
                if not outward or upper <= lower: return
                gesture.set_state(Gtk.EventSequenceState.CLAIMED); state["claimed"] = True
            if outward or state["pull"]:
                previous = state["pull"]; state["pull"] += delta
                if previous and previous * state["pull"] < 0: state["pull"] = 0.0
                pull = state["pull"]
                self.elastic_offset = math.copysign(34 * (1 - math.exp(-abs(pull) / 60)), pull) if pull else 0.0
                self.queue_draw()
            else:
                adjustment.set_value(max(lower, min(upper, value - delta)))
        drag.connect("drag-begin", begin); drag.connect("drag-update", update)
        drag.connect("drag-end", lambda *_: self.spring_back())
        drag.connect("cancel", lambda *_: self.spring_back())
        scroller.add_controller(drag)
        self.touch_pull = drag

    def do_snapshot(self, snapshot):
        snapshot.save()
        # Keep translated spring nodes inside their declared damage bounds.
        # Painting beyond them can leave stale strips on a real GLES display.
        bounds = Graphene.Rect(); bounds.init(0, 0, self.get_width(), self.get_height())
        snapshot.push_clip(bounds)
        point = Graphene.Point(); point.init(0, self.elastic_offset) if getattr(self, "elastic_vertical", False) else point.init(self.elastic_offset, 0)
        snapshot.translate(point); Gtk.Box.do_snapshot(self, snapshot); snapshot.pop(); snapshot.restore()

class ElasticVerticalTrack(ElasticCarouselTrack):
    def __init__(self, spacing=0):
        super().__init__()
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(spacing)

    def connect_scroll(self, scroller):
        self.attach_touch_pull(scroller, vertical=True)
        return self

def elastic_vertical_scroll(scroller):
    """Wrap non-track content without changing its layout or interaction targets."""
    child = scroller.get_child()
    if isinstance(child, Gtk.Viewport):
        viewport = child; child = viewport.get_child(); viewport.set_child(None)
    scroller.set_child(None)
    track = ElasticVerticalTrack()
    track.set_hexpand(True); track.set_vexpand(True)
    track.append(child); scroller.set_child(track); track.connect_scroll(scroller)

def publish_display_source():
    """Identify the source tree actually executing on the physical display."""
    try:
        source = Path(__file__).resolve().parents[1] / ".source-commit"
        revision = source.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", revision):
            marker = Path("/run/pi-home/display-source-commit")
            temporary = marker.with_suffix(".tmp")
            temporary.write_text(revision + "\n", encoding="utf-8")
            temporary.replace(marker)
    except OSError:
        # Diagnostics must never prevent the touchscreen from starting.
        pass

def mix_duotone_matrix():
    """GTK transposes this row-major matrix: luminance maps black to violet."""
    tint = (150 / 255, 144 / 255, 237 / 255)
    values = [weight * channel for weight in (.2126, .7152, .0722) for channel in (*tint, 0)]
    return values + [0, 0, 0, 1]


class MixPicture(Gtk.Box):
    """Presentation-only tint; shared artwork textures stay unmodified."""
    def __init__(self, duotone=True):
        super().__init__()
        self.duotone = duotone
        self.picture = Gtk.Picture(); self.picture.set_hexpand(True); self.picture.set_vexpand(True); self.append(self.picture)

    def set_can_shrink(self, value): self.picture.set_can_shrink(value)
    def set_content_fit(self, value): self.picture.set_content_fit(value)
    def set_filename(self, value): self.picture.set_filename(value)
    def set_paintable(self, value): self.picture.set_paintable(value)

    def do_snapshot(self, snapshot):
        bounds = Graphene.Rect(); bounds.init(0, 0, self.get_width(), self.get_height())
        clip = Gsk.RoundedRect(); clip.init_from_rect(bounds, 8)
        snapshot.push_rounded_clip(clip)
        root = self.get_root()
        tinted = self.duotone and root and root.has_css_class("theme-roon")
        if tinted:
            matrix = Graphene.Matrix(); matrix.init_from_float(mix_duotone_matrix())
            offset = Graphene.Vec4(); offset.init(0, 0, 0, 0)
            snapshot.push_color_matrix(matrix, offset)
        self.snapshot_child(self.picture, snapshot)
        if tinted: snapshot.pop()
        snapshot.pop()


CSS = load_css()


def get_json(url: str, timeout: float = .8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        return None


def post_json(url: str, data: dict, timeout: float = 1.2):
    try:
        request = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Preserve the controller's bounded error message instead of turning
        # a failed browse into an apparently empty music library.
        if not url.rstrip("/").endswith("/api/browse"): return None
        try:
            result = json.load(error)
            if isinstance(result, dict): return result
        except Exception:
            pass
        return None
    except Exception:
        return None


def browser_request_timeout(action: str) -> float:
    """Keep slow browse operations bounded without blocking ordinary taps."""
    if action in {"sort", "jump", "section", "search", "surprise", "artist"}: return 35.0
    if action in {"surprise_play", "open"}: return 15.0
    return 4.0


def release_period_label(value) -> str:
    """Return the release year without inventing missing precision."""
    released = str(value or "")
    return released[:4] if re.match(r"^\d{4}", released) else ""


def release_type_label(metadata) -> str:
    """Use the provider's release kind, with a conservative album fallback."""
    value = str((metadata or {}).get("type") or (metadata or {}).get("format") or "album").strip()
    folded = value.casefold()
    aliases = {
        "full length": "LP", "full-length": "LP", "long play": "LP",
        "ep": "EP", "single": "SINGLE", "promo": "PROMO",
        "compilation": "COMPILATION", "live": "LIVE ALBUM", "album": "ALBUM",
    }
    return aliases.get(folded, value.upper() if value else "ALBUM")


def get_bytes(url: str, timeout: float = 1.2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except Exception:
        return None


def now_playing_artwork_size(width: int, height: int, portrait: bool, reserved: int = 0) -> int:
    if portrait:
        return round(min(width - 64, max(160, height - reserved)) * .8)
    if width >= 1200:
        # The 1280-wide landscape display was designed around a dominant
        # 540px cover. Do not let unrelated detail-view sizing reduce it.
        return min(540, max(480, height - 180))
    if width <= 820 and height <= 500:
        # Grow into the unused space above while the 8px lower inset keeps the
        # existing bottom-left anchor and the 480px window strictly bounded.
        return 335
    # The original 800×480 and intermediate 1024×600 landscape profiles need
    # an explicit floor. The old 280px cap fought the 320px CSS minimum and the
    # fixed viewport clipped the cover, making it visibly shrink after reflow.
    return min(360, max(320, height - 160))
