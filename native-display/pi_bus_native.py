#!/usr/bin/env python3
"""Native GTK4 touchscreen for RoonDeck."""
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

# Shared appliance page grid; rendered into GTK CSS for older GTK versions too.
PANEL_STROKE = 2
APPLIANCE_PAGE_TOP = 8
LANDSCAPE_PAGE_MARGIN = 28
PORTRAIT_PAGE_MARGIN = 30
PORTRAIT_CONTENT_GAP = 16
CAROUSEL_START_INSET = 10
CAROUSEL_END_SPACE = 30


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


CSS = b"""
window { background: #0b1110; color: #f4f0e6; font-family: Inter, Cantarell, sans-serif; }
button { border: 0; box-shadow: none; background-image: none; outline: none; }
.page { padding: 14px 20px 10px; }.eyebrow { color: #97a39f; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
.clock { font-size: 31px; font-weight: 600; }.stop { font-size: 25px; font-weight: 700; }.stop-code { color: #7f8b87; font-size: 25px; font-weight: 550; }
.header-hotspot { min-height: 42px; padding: 0; border: 0; box-shadow: none; background: transparent; background-image: none; }
.header-hotspot:hover, .header-hotspot:active { background: transparent; box-shadow: none; }
.header-title { padding-left: 0; }.header-clock { padding-right: 0; }
.display-landscape .page { padding-top: 8px; padding-bottom: 4px; }
.display-landscape .page-header, .display-landscape .discover-toolbar { margin-left: -4px; margin-right: -4px; }
.utility { min-width: 92px; min-height: 38px; border-radius: 7px; background: #18211f; color: #d9dedb; font-size: 11px; font-weight: 750; }
.service { background: #131c1a; border: 1px solid #26312e; border-radius: 14px; padding: 5px 16px; }
.service-blue { border-color: #28566e; background: #112027; }.service-green { border-color: #285e43; background: #102219; }
.service-violet { border-color: #554a77; background: #1d1929; }.service-amber { border-color: #75572a; background: #271e11; }
.service-no, .arrival { font-size: 82px; font-weight: 720; font-variant-numeric: tabular-nums; }
.service-no { font-weight: 760; }.service-blue .service-no { color: #55a9d7; }.service-green .service-no { color: #61c68f; }.service-violet .service-no { color: #a998e0; }.service-amber .service-no { color: #d4a85f; }
.service.compact .service-no, .service.compact .arrival { font-size: 59px; }.service.dense .service-no, .service.dense .arrival { font-size: 45px; }.service.compact, .service.dense { padding-top: 2px; padding-bottom: 2px; }
.original-landscape .bus-page .service.original-compact { min-height: 0; padding: 2px 12px; border-radius: 10px; }
.original-landscape .bus-page .service.original-compact .arrival-sub { font-size: 8px; }
.arrival-sub { color: #7f8b87; font-size: 10px; font-weight: 650; }.muted { color: #78837f; font-size: 11px; font-weight: 400; }
.nav { padding-top: 3px; }.nav button { min-width: 0; min-height: 40px; border: 0; border-bottom: 5px solid transparent; border-radius: 0; background: transparent; color: #7f8b87; font-size: 14px; font-weight: 700; }
.nav button.active { border-bottom-color: #6ed9ae; background: transparent; color: #dfe4e1; }.artwork { border-radius: 12px; }.roon-title { font-size: 35px; font-weight: 620; }.roon-artist { color: #b6c0bc; font-size: 18px; }
.artwork-button, .artwork-button viewport, .artwork { border-radius: 12px; }.artwork-button { padding: 0; background: transparent; overflow: hidden; }.detail-takeover { padding: 0; background: #000; }.detail-header { min-height: 76px; padding: 10px 28px 0; background: #000; }.detail-close { min-width: 56px; min-height: 56px; border: 2px solid #6ed9ae; border-radius: 50%; padding: 0; background: transparent; color: #fff; }.detail-sheet-scroll { background: #000; }.detail-panel { padding: 12px 34px 24px; }.detail-entity { padding: 0 12px; background: transparent; }.detail-section-label { margin-top: 10px; color: #6ed9ae; font-size: 15px; font-weight: 800; letter-spacing: 2px; }.detail-artwork-frame, .detail-artwork { border-radius: 12px; background: #242424; }.detail-title { font-size: 35px; font-weight: 680; }.detail-artist { color: #b6c0bc; font-size: 22px; }.detail-subtitle { color: #84908c; font-size: 16px; }.detail-writeup { color: #d3d9d6; font-size: 20px; line-height: 1.5; }.detail-source { color: #78837f; font-size: 13px; font-weight: 500; }.detail-facts { padding: 10px 0 14px; }.detail-fact { color: #858b89; font-size: 15px; font-weight: 500; }.detail-action { min-height: 58px; margin-top: 10px; border-radius: 10px; background: #173a30; color: #6ed9ae; font-size: 19px; font-weight: 750; }.detail-footer { padding: 10px 28px 28px; background: #000; }.detail-footer .detail-primary-action { min-height: 68px; margin: 0; background: #6ed9ae; color: #111; font-size: 26px; font-weight: 800; }.detail-tracks { padding-top: 5px; }.detail-track { min-height: 38px; padding: 5px 6px; }.detail-track-no { color: #6ed9ae; font-size: 13px; }.detail-track-title { color: #f4f0e6; font-size: 16px; }
.roon-subnav { margin-top: 0; }.roon-subnav button { min-height: 29px; padding: 4px 13px 2px; border-radius: 0; border-top: 3px solid transparent; background: transparent; color: #68736f; font-size: 10px; font-weight: 750; letter-spacing: 1px; }.roon-subnav button.active { border-top-color: #5bcbd6; color: #f4f0e6; }
.source-view { padding: 8px; }.source-title { font-size: 25px; font-weight: 700; }.source-volume { font-size: 104px; font-weight: 620; font-variant-numeric: tabular-nums; }.source-step { min-width: 92px; min-height: 92px; border-radius: 46px; background: #18211f; color: #f4f0e6; font-size: 45px; }.source-mute { min-width: 92px; min-height: 38px; border-radius: 8px; background: #18211f; color: #dfe4e1; font-size: 11px; font-weight: 750; }
.queue-scroll { background: transparent; }.queue-scroll scrollbar { opacity: 0; min-width: 0; min-height: 0; }.queue-list { padding: 5px 8px 8px; }.queue-row { min-height: 78px; padding: 7px 11px; border-radius: 8px; background: transparent; color: #f4f0e6; }.queue-row:hover, .queue-row:active, .queue-row.current { background: #121e1c; }.queue-row.previous { opacity: .5; }.queue-art { min-width: 66px; min-height: 66px; border-radius: 6px; background: #18211f; }.queue-art-stack { min-width: 66px; min-height: 66px; }.queue-play-badge { min-width: 34px; min-height: 34px; border-radius: 17px; background: rgba(8,13,12,.82); color: #6ed9ae; }.queue-title { color: #f4f0e6; font-size: 20px; font-weight: 650; }.queue-meta { color: #84908c; font-size: 15px; }.queue-duration { color: #aab4b0; font-size: 18px; font-variant-numeric: tabular-nums; }.queue-empty { color: #78837f; font-size: 15px; padding: 60px 0; }
.browser-view { padding: 2px 4px 10px; }.browser-sidebar { min-width: 132px; padding: 4px 5px 4px 0; }.browser-filter { min-height: 58px; padding: 8px 10px; border-radius: 8px; background: transparent; color: #84908c; font-size: 16px; font-weight: 720; }.browser-filter.active { background: #19302a; color: #f4f0e6; }.browser-main { padding-left: 3px; }.browser-back { min-width: 100px; min-height: 44px; margin: 5px 12px 0 0; padding: 6px 11px; border-radius: 7px; background: #18211f; color: #dfe4e1; font-size: 13px; font-weight: 750; }.browser-message { padding: 3px 8px; color: #7f8b87; font-size: 12px; }.browser-row { min-height: 78px; padding: 7px 12px; border-radius: 10px; background: transparent; color: #f4f0e6; }.browser-row:hover, .browser-row:active { background: #18211f; }.browser-action-icon { min-width: 66px; min-height: 66px; border-radius: 6px; background: #18211f; color: #6ed9ae; }.browser-arrow { min-width: 44px; color: #84908c; font-size: 15px; font-variant-numeric: tabular-nums; }.browser-scrubber { min-width: 64px; padding-left: 3px; }.browser-scrubber scale { min-width: 28px; padding: 8px; }.browser-scrubber trough { min-width: 5px; border: 0; border-radius: 3px; background: #25312e; }.browser-scrubber highlight { background: #25312e; }.browser-scrubber slider { min-width: 18px; min-height: 18px; border: 0; border-radius: 9px; background: #6ed9ae; }.browser-scrub-letter { min-width: 34px; min-height: 34px; background: transparent; color: #6ed9ae; font-size: 16px; font-weight: 800; }.browser-section { padding: 15px 8px 5px; color: #6ed9ae; font-size: 12px; font-weight: 750; letter-spacing: 1px; }
.browser-home-grid, .browser-cover-grid { padding: 3px 3px 18px; }.browser-home-card { min-height: 270px; padding: 22px 14px; border-radius: 14px; background: #131c1a; color: #f4f0e6; }.browser-home-card.compact { min-height: 150px; }.browser-home-card:hover, .browser-home-card:active { background: #19302a; }.browser-home-icon { color: #6ed9ae; font-size: 64px; font-weight: 350; }.browser-home-title { color: #f4f0e6; font-size: 21px; font-weight: 720; }.browser-cover-card { min-height: 202px; padding: 7px; border-radius: 10px; background: transparent; color: #f4f0e6; }.browser-cover-card:hover, .browser-cover-card:active { background: #18211f; }.browser-cover-art { min-width: 172px; min-height: 172px; border-radius: 8px; background: #18211f; }.browser-tile-icon { color: #6ed9ae; font-size: 54px; font-weight: 500; }.browser-cover-title { padding-top: 6px; color: #f4f0e6; font-size: 14px; font-weight: 650; }.browser-cover-title.tile { padding: 14px 8px 9px; background: linear-gradient(transparent, rgba(5,10,9,.94)); color: #f4f0e6; font-size: 18px; font-weight: 760; }.browser-cover-subtitle { color: #87928e; font-size: 11px; }
.transport button { min-width: 50px; min-height: 50px; border-radius: 25px; padding: 0; background: #18211f; color: #e4e7e4; }.transport .play { min-width: 68px; min-height: 68px; border-radius: 34px; background: #285f4d; }
.progress trough, .volume trough { min-height: 7px; border: 0; box-shadow: none; border-radius: 4px; background: #303a37; }.progress highlight, .volume highlight { border: 0; box-shadow: none; background: #6ed9ae; }.time { color: #87928e; font-size: 12px; }
.sleep { background: #000; }.sleep-clock { font-size: 112px; font-weight: 550; }.settings-title { font-size: 32px; font-weight: 500; }
.settings-card { background: #131c1a; border: 1px solid #26312e; border-radius: 14px; padding: 16px; }.settings-action { min-height: 54px; border-radius: 12px; background: #285f4d; color: #f4f0e6; font-weight: 750; }
.settings-select { min-height: 48px; border-radius: 8px; background: #0d1412; color: #f4f0e6; }.settings-row { padding: 7px 0; }.settings-diagnostic { color: #aab4b0; font-size: 12px; }
.settings-controls { padding: 4px 0; }.settings-column { padding: 0 5px; }.setting-line { min-height: 52px; padding: 0 12px; border-radius: 8px; background: #0d1412; }.setting-line label { font-size: 14px; font-weight: 650; }.setting-line checkbutton { font-size: 14px; font-weight: 650; }.setting-line checkbutton label { margin-left: 12px; }.setting-line check { min-width: 22px; min-height: 22px; border-radius: 5px; border: 2px solid #61706b; background: #111a18; }.setting-line check:checked { background: #6ed9ae; border-color: #6ed9ae; color: #082018; }
.brightness-setting { padding-top: 7px; padding-bottom: 7px; }
.stop-row { margin-bottom: 4px; }.home-grid { padding: 5px 0 1px; }.home-tile { min-height: 112px; border-radius: 20px; padding: 7px 9px 11px; background: #131c1a; border: 1px solid #293633; color: #aab4b0; }.home-tile.on { background: #173229; border-color: #35785f; color: #f4f0e6; }.home-tile.activated { background: #173b31; border-color: #6ed9ae; box-shadow: 0 0 18px rgba(110,217,174,.6); }.home-device-button { min-height: 88px; padding: 0; background: transparent; color: #9aaba5; }.home-tile.on .home-device-button, .home-tile.activated .home-device-button { color: #6ed9ae; }.home-icon { opacity: .82; }.home-name { font-size: 15px; font-weight: 700; }.home-state { color: #7f8b87; font-size: 11px; }.home-level { min-width: 28px; min-height: 88px; }.home-level trough { min-width: 7px; border-radius: 4px; background: #303a37; }.home-level highlight { background: #6ed9ae; border-radius: 4px; }.home-level slider { min-width: 20px; min-height: 20px; border-radius: 10px; background: #f4f0e6; }
.high-resolution .page { padding: 21px 30px 15px; }.high-resolution .stop, .high-resolution .stop-code { font-size: 38px; }.high-resolution .clock { font-size: 47px; }.high-resolution .eyebrow { font-size: 17px; }.high-resolution .service { border-radius: 20px; padding: 8px 24px; }.high-resolution .service-no, .high-resolution .arrival { font-size: 123px; }.high-resolution .service.compact .service-no, .high-resolution .service.compact .arrival { font-size: 89px; }.high-resolution .service.dense .service-no, .high-resolution .service.dense .arrival { font-size: 68px; }.high-resolution .arrival-sub { font-size: 15px; }.high-resolution .muted { font-size: 16px; }.high-resolution .artwork { min-width: 420px; min-height: 420px; }.high-resolution .roon-title { font-size: 52px; }.high-resolution .roon-artist { font-size: 27px; }.high-resolution .nav button { min-height: 60px; font-size: 21px; }
.high-resolution .roon-subnav button { min-height: 44px; font-size: 15px; }.high-resolution .transport button { min-width: 75px; min-height: 75px; border-radius: 38px; }.high-resolution .transport .play { min-width: 96px; min-height: 96px; border-radius: 48px; }.high-resolution .queue-row { min-height: 99px; }.high-resolution .queue-art, .high-resolution .browser-action-icon { min-width: 84px; min-height: 84px; }.high-resolution .queue-title { font-size: 24px; }.high-resolution .queue-meta, .high-resolution .queue-duration { font-size: 18px; }.high-resolution .detail-header { min-height: 92px; padding: 14px 52px 0; }.high-resolution .detail-close { min-width: 72px; min-height: 72px; }.high-resolution .detail-panel { padding: 10px 34px 64px; }.high-resolution .detail-entity { padding: 0 18px; }.high-resolution .detail-section-label { font-size: 18px; }.high-resolution .detail-title { font-size: 45px; }.high-resolution .detail-artist { font-size: 28px; }.high-resolution .detail-writeup { font-size: 24px; }.high-resolution .detail-source { font-size: 15px; }.high-resolution .detail-fact { font-size: 18px; }.high-resolution .detail-action { min-height: 74px; font-size: 23px; }.high-resolution .detail-footer .detail-primary-action { min-height: 82px; font-size: 30px; }.high-resolution .detail-track-title { font-size: 20px; }
.touch-landscape .page { padding: 18px 28px 14px; }.touch-landscape .service-no, .touch-landscape .arrival { font-size: 138px; }.touch-landscape .service-no { min-width: 205px; }.touch-landscape .arrival-sub { font-size: 17px; }.touch-landscape .stop, .touch-landscape .stop-code { font-size: 42px; }.touch-landscape .clock { font-size: 50px; }.touch-landscape .nav button { min-height: 58px; font-size: 22px; }.touch-landscape .roon-subnav button { min-height: 54px; padding: 8px 18px 5px; font-size: 18px; }.touch-landscape .artwork { min-width: 320px; min-height: 320px; }.touch-landscape .roon-title { font-size: 46px; }.touch-landscape .roon-artist { font-size: 25px; }.touch-landscape .transport button { min-width: 70px; min-height: 70px; border-radius: 35px; }.touch-landscape .transport .play { min-width: 88px; min-height: 88px; border-radius: 44px; }.touch-landscape .settings-title { font-size: 43px; }.touch-landscape .settings-card { padding: 24px 28px; }.touch-landscape .settings-card .muted, .touch-landscape .settings-diagnostic { font-size: 17px; }.touch-landscape .settings-select { min-height: 70px; font-size: 19px; }.touch-landscape .setting-line { min-height: 78px; padding: 0 18px; }.touch-landscape .setting-line label, .touch-landscape .setting-line checkbutton { font-size: 19px; }.touch-landscape .setting-line check { min-width: 30px; min-height: 30px; }.touch-landscape .settings-action { min-height: 74px; font-size: 20px; }.touch-landscape .settings-controls { padding: 12px 0; }.touch-landscape .utility { min-width: 118px; min-height: 52px; font-size: 16px; }
.boot-splash { background: #000; }.boot-wordmark, .settings-wordmark { min-width: 0; min-height: 0; }
.touch-landscape .header-title { transform: translateY(-5px); }
.touch-landscape .bus-number-choice { padding-left: 0; padding-right: 0; font-size: 14px; }
.touch-landscape .stop, .touch-landscape .stop-code { font-size: 34px; }
.touch-landscape .stop-row { margin-bottom: 14px; }
.touch-landscape .service { border-width: 2px; padding-top: 11px; padding-bottom: 11px; }
.touch-landscape .home-tile { border-width: 2px; }
.touch-landscape .bus-page { padding-top: 10px; }.touch-landscape .bus-footer .muted { color: #68736f; }.touch-landscape .service-no { opacity: .82; }
.touch-landscape .home-name { font-size: 24px; }.touch-landscape .home-state { font-size: 17px; }
.home-device-button.scene-action.activated { color: #6ed9ae; }
.touch-landscape .home-page { padding-top: 10px; }
.touch-landscape .roon-page { padding-top: 8px; }
.touch-landscape .roon-subnav button { min-height: 42px; padding: 2px 14px 4px; }
.touch-landscape .source-volume { font-size: 220px; font-weight: 450; }.touch-landscape .source-step { min-width: 112px; min-height: 112px; border-radius: 56px; font-size: 58px; }.touch-landscape .source-mute { min-width: 160px; min-height: 62px; font-size: 20px; }
.touch-landscape .time { font-size: 20px; }.touch-landscape .volume-number { font-size: 26px; }
.touch-landscape .browser-back { min-width: 104px; min-height: 48px; font-size: 15px; }.touch-landscape .browser-filter { min-height: 62px; font-size: 17px; }.touch-landscape .browser-row { min-height: 88px; }.touch-landscape .browser-home-card { min-height: 290px; }.touch-landscape .browser-home-icon { font-size: 78px; }.touch-landscape .browser-home-title { font-size: 26px; }.touch-landscape .browser-cover-art { min-width: 172px; min-height: 172px; }.touch-landscape .browser-cover-title { font-size: 16px; }.touch-landscape .browser-cover-title.tile { font-size: 21px; }.touch-landscape .browser-scrub-letter { font-size: 18px; }
.touch-landscape .settings-page { padding-top: 18px; padding-bottom: 18px; }.touch-landscape .settings-page button { padding: 8px 20px; }
.touch-landscape .settings-page .settings-card { padding: 8px 10px; border: 0; background: transparent; }
.touch-landscape .settings-page .setting-line { min-height: 72px; padding: 5px 18px; }.touch-landscape .settings-page .setting-line checkbutton label { margin-left: 16px; }
.touch-landscape .settings-page .brightness-setting { padding-top: 6px; padding-bottom: 6px; }
.touch-landscape .settings-page .settings-select { min-height: 62px; padding: 5px 18px; }
.touch-landscape .settings-page .settings-diagnostic { line-height: 1.25; }
.touch-landscape .settings-page .settings-action { min-height: 62px; }
"""


CSS += b"""
.clock { font-weight: 300; color: #b4bfba; }
.stop { color: #f5f1e8; }.stop-code { color: #777; }
.browser-filter, .touch-landscape .browser-filter { min-height: 44px; padding: 5px 0; border-radius: 0; border: 0; background: transparent; }
.browser-filter.active, .touch-landscape .browser-filter.active { background: transparent; border: 0; color: #6ed9ae; }
.browser-back, .touch-landscape .browser-back { min-width: 90px; min-height: 42px; margin: 12px 0 0; padding: 5px 12px; background: #242b28; border: 1px solid #4a514e; border-radius: 10px; color: #d5dcd8; }
.theme-roon, .theme-roon .page { background: #151515; color: #f5f5f5; }
.theme-roon .page { background: linear-gradient(120deg, #1d1c2d, #121212 62%, #1b1519); }
.theme-roon .browser-filter.active, .theme-roon .touch-landscape .browser-filter.active { color: #9868F9; }
.theme-roon .browser-filter, .theme-roon .browser-filter.active { background: transparent; border: 0; }
.theme-roon .artwork, .theme-roon .queue-art, .theme-roon .browser-cover-art, .theme-roon .browser-action-icon, .theme-roon .surprise-action, .theme-roon .artist-hero-frame { background: #202020; color: #9868F9; }
.theme-roon .nav button.active, .theme-roon .roon-subnav button.active { border-color: #9868F9; }
.theme-roon .transport .play, .theme-roon scale highlight { background: #9868F9; color: #fff; }
.theme-roon .eyebrow, .theme-roon .details-tag { color: #9868F9; }
.theme-roon .browser-back { background: #292929; border-color: #555; color: #ddd; }
.queue-scroll overshoot.left, .queue-scroll overshoot.right { background: transparent; box-shadow: none; }
.bus-page, .touch-landscape .bus-page { padding-top: 8px; padding-left: 20px; padding-right: 20px; }
.bus-page .service { min-height: 0; padding-top: 6px; padding-bottom: 6px; }
.bus-page .service.compact .arrival, .bus-page .service.compact .service-no { font-size: 76px; }
.touch-landscape .bus-page .service.compact .arrival, .touch-landscape .bus-page .service.compact .service-no { font-size: 99px; }
.bus-page .header-title { transform: none; }
.surprise-title { font-size: 30px; font-weight: 750; }.surprise-artist { font-size: 23px; color: #b6c0bc; }.surprise-caption { font-size: 17px; color: #b6c0bc; }
.touch-landscape .surprise-title { font-size: 34px; }.touch-landscape .surprise-artist { font-size: 25px; }
.artist-profile { padding: 12px 22px 8px 12px; }.artist-name { font-size: 27px; font-weight: 750; }.artist-bio { color: #b6c0bc; font-size: 17px; }.artist-source { color: #78837f; font-size: 11px; }
.browser-sidebar { padding-top: 12px; }
.browser-back { margin-top: 12px; margin-right: 0; }
.browser-cover-title.tile { background: transparent; }
.browser-action-icon, .queue-art { padding: 0; }
.browser-cover-art { min-width: 0; min-height: 0; }
.touch-landscape .browser-cover-art { min-width: 0; min-height: 0; }
.browser-cover-card { min-height: 0; padding: 3px; }
.browser-cover-card:hover, .browser-cover-card:active, .browser-home-card:hover, .browser-row:hover, .browser-row:active { background: transparent; box-shadow: none; outline: none; transform: none; transition: none; }
.browser-search-entry, .browser-search-entry:focus, .browser-search-entry:focus-within, .browser-search-entry text:focus { outline: none; box-shadow: none; border: 0; }
.browser-key.browser-search-submit { background: #6ed9ae; color: #111; font-weight: 750; }
.theme-roon .browser-key.browser-search-submit { background: #9868F9; color: #111; }
.browser-section { font-size: 17px; padding-bottom: 12px; }
.search-column { padding: 0 10px; }
.theme-roon .browser-row:active, .theme-roon .browser-row:hover { background: transparent; }
.browser-scrubber { padding: 0; }
.browser-surprise { font-size: 14px; }
.surprise-action { min-width: 72px; min-height: 72px; padding: 8px; border-radius: 50%; background: #18211f; color: #6ed9ae; }
.browser-search-panel { padding: 2px 0 10px; margin: 0; }
.touch-landscape .browser-search-panel { margin: 0; }
.portrait .browser-search-panel { margin-left: 0; margin-right: 0; }
.browser-search-entry { min-height: 60px; font-size: 28px; padding: 8px 14px; background: #18211f; color: #f4f0e6; border-radius: 8px; }
.browser-key { min-height: 44px; min-width: 40px; padding: 6px; background: #18211f; color: #f4f0e6; font-size: 20px; border-radius: 7px; }
.queue-duration, .high-resolution .queue-duration { font-size: 26px; min-width: 72px; padding-right: 16px; }
.queue-play-badge { min-width: 52px; min-height: 52px; border-radius: 26px; }
.browser-view { padding-left: 0; }
.browser-back, .touch-landscape .browser-back { min-width: 70px; min-height: 40px; padding: 4px 10px; margin-top: 8px; border: 0; border-radius: 7px; background: #303030; color: #fff; }
.queue-play-badge { background: transparent; border-radius: 0; color: #6ed9ae; }
.theme-roon .browser-back { background: #303030; border: 0; color: #fff; }
.theme-choice { min-height: 36px; padding: 4px 12px; background: #303030; color: #fff; border-radius: 6px; }
.theme-choice.active { background: #6ed9ae; color: #101714; }
.theme-roon .theme-choice.active { background: #9868F9; color: #fff; }
.settings-select label { color: #fff; }
.settings-select popover contents { background: #29292d; color: #f2f0f4; border: 1px solid #55525d; border-radius: 8px; }
.settings-select popover listview { background: transparent; color: #f2f0f4; }
.settings-select popover listview row { min-height: 46px; padding: 5px 12px; color: #f2f0f4; }
.settings-select popover listview row label { color: #f2f0f4; }
.settings-select popover listview row:selected { background: #403c55; color: #f2f0f4; }
.settings-select popover listview row:selected label { color: #f2f0f4; }
.artist-play { margin-top: 12px; padding: 12px 30px 12px 20px; border: 0; border-radius: 999px; background: #6ed9ae; color: #111; font-size: 20px; font-weight: 800; }
.artist-play:hover, .artist-play:active, .artist-play:focus { background: #83e6bd; color: #111; }
.theme-roon .artist-play { background: #9868F9; }
.theme-roon .artist-play:hover, .theme-roon .artist-play:active, .theme-roon .artist-play:focus { background: #a77cff; }
.queue-pill, .theme-roon .queue-pill { min-height: 52px; padding: 10px 22px; border: 2px solid #55515d; border-radius: 999px; background: transparent; color: #ddd; font-size: 18px; font-weight: 700; }
.queue-pill:hover, .queue-pill:active, .queue-pill:focus, .theme-roon .queue-pill:hover, .theme-roon .queue-pill:active, .theme-roon .queue-pill:focus { border-color: #77717f; background: #222; color: #fff; }
.artist-albums-heading { font-size: 16px; font-weight: 750; }
.artist-album-title { font-size: 24px; }
.theme-roon .queue-play-badge { background: transparent; color: #9868F9; }
.theme-roon .queue-row.current, .theme-roon .queue-row:hover, .theme-roon .queue-row:active { background: #292733; }
.theme-roon .utility, .theme-roon .source-step, .theme-roon .source-mute, .theme-roon .transport button, .theme-roon .browser-key, .theme-roon .browser-search-entry { background: #292929; color: #ddd; }
.theme-roon .transport .play, .theme-roon .settings-action { background: #9868F9; color: #fff; }
.theme-roon .settings-card, .theme-roon .home-tile { background: #232228; border-color: #44414c; }
.theme-roon .setting-line, .theme-roon .settings-select { background: #202025; color: #eee; }
.theme-roon check { background: #242329; border-color: #77727e; }
.theme-roon check:checked { background: #9868F9; color: #151515; border-color: #9868F9; }
.theme-roon .progress trough, .theme-roon .volume trough, .theme-roon .home-level trough { background: #45424b; }
.theme-roon .progress highlight, .theme-roon .volume highlight, .theme-roon .home-level highlight { background: #9868F9; }
.theme-roon .home-tile.on { background: #302b44; border-color: #9868F9; }
.theme-roon .home-tile.activated { background: #3b3063; border-color: #9868F9; box-shadow: 0 0 18px rgba(152,104,249,.7); }
.theme-roon .home-tile.activated .home-device-button { color: #9868F9; }
.theme-roon .home-tile.on button, .theme-roon .boot-logo, .theme-roon .surprise-action { color: #9868F9; }
.theme-roon .home-device-button.scene-action.activated { color: #9868F9; }
.theme-roon .surprise-action, .theme-roon .queue-art { background: #202020; }
.theme-roon .clock { color: #bbb; }
.theme-roon .browser-tile-icon, .theme-roon .browser-home-icon, .theme-roon .browser-section { color: #9868F9; }
.theme-roon .browser-home-card { background: #232228; }
.theme-roon .roon-artist, .theme-roon .detail-artist, .theme-roon .surprise-artist, .theme-roon .surprise-caption, .theme-roon .queue-meta, .theme-roon .queue-duration, .theme-roon .muted, .theme-roon .home-state, .theme-roon .settings-diagnostic, .theme-roon .time, .theme-roon .browser-filter { color: #aaa; }
.theme-roon .browser-filter.active { color: #9868F9; }
.theme-roon .detail-takeover { background: rgba(21,21,21,.96); }
.theme-roon .detail-close, .theme-roon .detail-close-glyph { border-color: #9868F9; }
.theme-roon .detail-section-label, .theme-roon .detail-track-no, .theme-roon .recommendation-heading,
.theme-roon .discover-utility, .theme-roon .browser-sort, .theme-roon .volume-step,
.theme-roon .track-menu-action { color: #9868F9; }
.theme-roon .detail-action { background: #2d2943; color: #9868F9; }
.theme-roon .detail-footer .detail-primary-action,
.theme-roon .track-menu-action.primary-play { background: #9868F9; color: #111; }
.theme-roon .track-menu-action.primary-play:disabled { background: #9868F9; color: #111; opacity: .72; }
.theme-roon popover.sort-menu .track-menu-action:hover,
.theme-roon popover.sort-menu .track-menu-action:focus { background: #292929; }
.theme-roon popover.sort-menu .track-menu-action.active,
.theme-roon popover.sort-menu .track-menu-action.active:hover,
.theme-roon popover.sort-menu .track-menu-action.active:focus { background: #9868F9; color: #111; box-shadow: none; }
.discovery-card, .discovery-card:hover, .discovery-card:active { padding: 4px; background: transparent; background-image: none; box-shadow: none; }
.discovery-card .queue-title { font-size: 18px; }.discovery-card .queue-subtitle { font-size: 14px; color: #aaa; }
.daily-card .queue-title { font-size: 20px; }.daily-card .queue-subtitle { font-size: 16px; }
.discovery-scroll scrollbar, .daily-scroll scrollbar { opacity: 0; min-width: 0; min-height: 0; }
.discovery-scroll overshoot.top, .discovery-scroll overshoot.bottom, .daily-scroll overshoot.left, .daily-scroll overshoot.right { background: transparent; box-shadow: none; }
.daily-track { padding: 0 0 4px 10px; }
.daily-track .queue-title { margin-top: 5px; }
.daily-heading { margin: 2px 7px 0 7px; }
.recommendation-heading { margin: 12px 7px -8px 17px; color: #6ed9ae; font-size: 14px; font-weight: 780; letter-spacing: 1px; }
.confirm-shade { background: rgba(5,5,7,.82); }
.confirm-card { min-width: 390px; padding: 28px; border-radius: 14px; background: #242329; border: 1px solid #4a4752; }
.confirm-title { font-size: 28px; font-weight: 760; color: #fff; }
.confirm-copy { font-size: 17px; color: #bbb; }
.confirm-cancel, .confirm-reboot { min-height: 54px; padding: 8px 22px; border-radius: 8px; font-size: 17px; font-weight: 700; }
.confirm-cancel { background: #343338; color: #fff; }.confirm-reboot { background: #6ed9ae; color: #101714; }
.loading-notice { font-size: 14px; font-weight: normal; color: #aaa; background: transparent; padding: 4px 0; }
.touch-landscape .roon-page { padding-right: 0; }
.touch-landscape .roon-header, .touch-landscape .roon-page .nav, .touch-landscape .now-playing-content, .touch-landscape .queue-scroll, .touch-landscape .source-view { margin-right: 28px; }
.touch-landscape .roon-page .browser-view { padding-right: 0; }
.touch2-7-landscape .search-main { margin-top: 26px; margin-right: 28px; }
.touch2-7-landscape .mix-controls button { min-height: 52px; padding: 8px 18px; }
.touch2-7-landscape .mix-controls .artist-play { margin-top: 0; }
.portrait .page { padding: 22px 24px 16px; }
.portrait .roon-page { padding-right: 24px; }
.portrait .roon-header, .portrait .roon-page .nav, .portrait .now-playing-content, .portrait .queue-scroll, .portrait .source-view { margin-right: 0; }
.portrait .now-playing-content { margin: 32px 0 8px 0; }
.portrait.compact-portrait .now-playing-content { margin-top: 24px; }
.portrait.large-portrait .artwork-button { margin-bottom: 18px; }
.portrait.large-portrait .roon-artist { margin-bottom: 12px; }
.portrait .browser-view { padding-right: 0; }
.portrait .artwork { min-width: 0; min-height: 0; }
.portrait .roon-title { font-size: 40px; }
.portrait .roon-artist { font-size: 24px; }
.portrait .transport button { min-width: 64px; min-height: 64px; border-radius: 32px; }
.portrait .transport .play { min-width: 82px; min-height: 82px; border-radius: 41px; }
.portrait .nav button { min-height: 58px; font-size: 18px; }
.portrait .roon-subnav button { min-height: 48px; padding: 6px 12px; font-size: 15px; }
.portrait .browser-sidebar { padding: 0 0 8px; }
.portrait .browser-filter { min-height: 48px; padding: 6px 10px; }
.portrait .browser-back { margin: 0; }
.portrait .queue-row { min-height: 92px; }
.portrait .settings-card { padding: 20px; }
.portrait .settings-controls { padding: 0; }
.portrait .settings-column { padding: 4px 0; }
.portrait .settings-select, .portrait .setting-line { min-height: 58px; }
.portrait.compact-portrait .page { padding: 12px 14px 10px; }
.portrait.compact-portrait .roon-title { font-size: 28px; }
.portrait.compact-portrait .roon-artist { font-size: 19px; }
.portrait.compact-portrait .nav button { min-height: 48px; padding: 4px; font-size: 14px; }
.settings-page .settings-card { padding: 0; border: 0; background: transparent; }
.settings-page .settings-column { padding: 0; }
.settings-page .settings-controls { padding: 12px 0 0; }
.settings-brand { color: #6ed9ae; }
.settings-theme-choice { min-height: 48px; font-size: 16px; }
.settings-appearance { margin-top: 6px; }
.settings-option-title { color: #f2f0f4; font-size: 15px; font-weight: 700; }
.settings-appearance .theme-choice { min-height: 48px; font-size: 16px; }
.touch-landscape .settings-theme-choice { min-height: 56px; font-size: 19px; }
.theme-roon .settings-brand { color: #8275ef; }
.settings-version { font-size: 12px; color: #a4aaa7; }
.settings-page .settings-diagnostic { font-size: 13px; color: #747974; }
.settings-divider { background: #232228; min-height: 3px; margin-top: 2px; margin-bottom: 2px; }
.settings-page .setting-line, .settings-page .settings-select { min-height: 46px; padding: 7px 14px; }
.settings-page .brightness-setting { padding-top: 6px; }
.settings-page .brightness-control { padding: 0; }
.settings-page .brightness-control scale { min-height: 44px; padding: 8px 0; }
.settings-page .brightness-value { min-width: 54px; color: #b6bbb8; font-size: 17px; font-weight: 600; }
.touch-landscape .settings-page { padding: 26px 28px; }
.touch-landscape .settings-page .settings-card { padding: 0; }
.touch-landscape .settings-page .settings-version { font-size: 17px; }
.touch-landscape .settings-page .settings-diagnostic { font-size: 17px; }
.touch-landscape .settings-page .settings-title { font-size: 43px; }
.touch-landscape .settings-page .settings-controls { padding: 8px 0 0; }
.touch-landscape .settings-page .setting-line, .touch-landscape .settings-page .settings-select { min-height: 62px; padding: 5px 18px; }
.touch-landscape .settings-page .brightness-setting { padding: 5px 0; }
.touch-landscape .settings-page .brightness-value { min-width: 64px; font-size: 20px; }
.touch-landscape .settings-page .settings-action { min-height: 62px; }
.portrait .settings-page .settings-title { font-size: 26px; }
.portrait.compact-portrait .settings-page .settings-title { font-size: 22px; }
.portrait .roon-page { padding-top: 6px; }
.portrait .roon-subnav button { border-top: 0; border-bottom: 3px solid transparent; min-height: 32px; padding: 2px 2px; letter-spacing: .6px; font-size: 16px; }
.portrait .browser-view .queue-scroll { margin-right: 0; }
.portrait .daily-track { padding-left: 0; }
.bus-footer .muted { color: #888; }
.portrait .recommendation-heading { margin-left: 4px; }
.portrait .stop, .portrait .stop-code { font-size: 26px; }
.portrait.compact-portrait .stop, .portrait.compact-portrait .stop-code { font-size: 22px; }
.portrait .service { padding: 18px 12px; }
.portrait .bus-route-badge { border-radius: 60px; padding: 6px 24px; background: rgba(255,255,255,.045); }
.portrait .bus-route-word { color: #f4f4f4; font-weight: 500; }
.portrait .bus-next { font-weight: 700; color: #f4f4f4; }
.portrait .bus-next-unit { color: #66716e; font-weight: 400; }
.portrait .bus-rule { min-height: 1px; background: rgba(220,230,230,.35); }
.portrait .bus-then { color: #596562; font-weight: 500; }
.portrait .bus-route-badge .service-no { font-weight: 600; }
.portrait .bus-following { color: #f4f4f4; font-weight: 600; }
.portrait .bus-following-unit { color: #66716e; font-weight: 500; }
.portrait .service.compact, .portrait .service.dense { padding: 12px; }
.portrait .roon-subnav button.active { border-bottom-color: #5bcbd6; }
.portrait.theme-roon .roon-subnav button.active { border-bottom-color: #9868F9; }
.portrait .browser-sidebar { min-width: 0; }
.portrait .service-no { min-width: 0; font-size: 108px; }
.portrait .arrival { font-size: 96px; }
.portrait .service.compact .service-no, .portrait .service.dense .service-no { font-size: 58px; }
.portrait .service.compact .arrival, .portrait .service.dense .arrival { font-size: 58px; }
.portrait .home-level { min-height: 24px; min-width: 0; }
.portrait .home-level trough { min-height: 7px; min-width: 0; }
.portrait .home-name { font-size: 21px; }
.portrait .home-state { font-size: 14px; }
.portrait.compact-portrait .roon-subnav button { font-size: 12px; min-height: 32px; letter-spacing: .4px; }
.portrait.compact-portrait .browser-filter { font-size: 12px; min-height: 40px; padding: 4px 6px; }
.portrait .discover-toolbar { padding: 4px 0 0; }
.discover-utility { background: transparent; border: 0; padding: 0; min-width: 36px; min-height: 42px; color: #6ed9ae; }
.discover-sleep { color: #888; }
.display-landscape .discover-toolbar { padding-top: 0; }
.display-landscape .discover-toolbar .roon-subnav button { border-top: 0; border-bottom: 3px solid transparent; padding-bottom: 0; }
.display-landscape .discover-toolbar .roon-subnav button.active { border-bottom-color: #5bcbd6; }
.display-landscape.theme-roon .discover-toolbar .roon-subnav button.active { border-bottom-color: #9868F9; }
.display-landscape .bus-page, .display-landscape .home-page { padding-top: 8px; padding-left: 28px; padding-right: 28px; }
.recommendation-album { color: #fff; font-size: 18px; }
.display-landscape .recommendation-heading, .display-landscape .recommendation-album { margin-left: 10px; margin-right: 0; }
.display-landscape .discovery-card, .display-landscape .discovery-card:hover, .display-landscape .discovery-card:active { padding: 0; }
.portrait .discover-toolbar .roon-subnav button { font-weight: 500; letter-spacing: 0; padding: 4px 0; min-height: 38px; }
.portrait .discover-toolbar .roon-subnav button.active { color: #fff; }
.portrait .browser-sidebar { padding: 0 0 14px; }
.portrait .browser-filter { font-weight: 500; font-size: 16px; padding: 4px 6px; min-height: 38px; }
.portrait .browser-cover-card { min-height: 0; padding: 0; }
.portrait .browser-cover-art { min-width: 0; min-height: 0; }
.portrait .browser-cover-grid { padding: 0 8px 12px; }
.portrait .queue-list { padding: 0; }
.portrait .nav button { font-weight: 500; }
.portrait.compact-portrait .discover-toolbar .roon-subnav button { font-size: 11px; }
.portrait.compact-portrait .browser-filter { font-size: 12px; }
.loading-notice { font-size: 19px; color: #aaa; }
.loading-dots { color: #6ed9ae; font-size: 34px; }
.theme-roon .loading-dots { color: #9868F9; }
.portrait.large-portrait .roon-page { padding-left: 38px; padding-right: 38px; padding-top: 24px; }
.portrait.large-portrait .discover-toolbar .roon-subnav button { font-size: 24px; min-height: 52px; }
.portrait .discover-toolbar .roon-subnav button { min-height: 30px; padding-bottom: 1px; }
.portrait .browser-view { padding-left: 0; padding-right: 0; }
.portrait .browser-main { padding-left: 0; }
.portrait .browser-cover-grid { padding: 0 0 18px; }
.portrait.large-portrait .browser-cover-grid { padding-left: 0; }
.portrait .browser-search-panel { padding: 2px 0 10px; }
.portrait .artist-profile { padding: 8px 0 24px; }
.portrait .recommendation-album { color: #fff; font-size: 18px; }
.portrait .page, .portrait .roon-page, .portrait.compact-portrait .page,
.portrait.large-portrait .roon-page { padding-left: 30px; padding-right: 30px; }
.portrait .discover-toolbar .roon-subnav button { padding-bottom: 0; }
.portrait .discovery-card { padding: 0; }
.portrait .recommendation-heading { margin-left: 0; margin-right: 0; }
.portrait .browser-section, .portrait .browser-row, .portrait .browser-filter,
.portrait.compact-portrait .browser-filter { padding-left: 0; padding-right: 0; }
.portrait.compact-portrait .browser-key { min-width: 0; min-height: 32px; padding: 4px; font-size: 14px; }
.portrait.compact-portrait .browser-search-entry { min-width: 0; min-height: 44px; font-size: 20px; }
.portrait.large-portrait .browser-filter { font-size: 24px; min-height: 52px; }
.portrait.large-portrait .browser-cover-grid { padding-left: 0; }
.portrait.large-portrait .nav button { font-size: 26px; min-height: 72px; }
.portrait .roon-page { padding-top: 9px; }
.portrait .settings-page { padding-top: 17px; }
.portrait .settings-page .settings-title { font-size: 30px; }
.portrait .settings-page .settings-version { font-size: 15px; }
.portrait .settings-page .settings-diagnostic { font-size: 15px; }
.portrait .settings-header .settings-utilities button { min-height: 52px; font-size: 13px; }
.portrait.compact-portrait .settings-page .settings-title { font-size: 24px; }
.portrait.compact-portrait .settings-page .settings-version { font-size: 13px; }
.portrait.compact-portrait .settings-page .settings-diagnostic { font-size: 14px; }
.portrait.compact-portrait .settings-header .settings-utilities button { min-height: 44px; }
.settings-page .settings-action.reboot-action, .confirm-reboot { background: #8a5b24; color: #fff1d2; }
.settings-page .settings-action.reboot-action:hover, .confirm-reboot:hover { background: #a76f2b; }
"""


CSS += ("""
.settings-icon { color: #6ed9ae; }
.theme-roon .settings-icon { color: #9868F9; }
.bus-page, .home-page { padding-top: %dpx; }
.display-landscape .bus-page, .display-landscape .home-page { padding-left: %dpx; padding-right: %dpx; }
.portrait .bus-page, .portrait .home-page { padding-left: %dpx; padding-right: %dpx; }
.service, .home-tile { border-width: %dpx; }
.home-grid { padding-top: 0; }
.daily-track { padding-left: %dpx; }
scrolledwindow overshoot, scrolledwindow undershoot { background: transparent; background-image: none; box-shadow: none; border: 0; }
@keyframes library-pulse {
  from { box-shadow: 0 0 0 1px alpha(#6ed9ae, .25), 0 0 3px alpha(#6ed9ae, .10); }
  to { box-shadow: 0 0 0 3px alpha(#6ed9ae, .8), 0 0 10px alpha(#6ed9ae, .35); }
}
@keyframes library-pulse-roon {
  from { box-shadow: 0 0 0 1px alpha(#9868F9, .25), 0 0 3px alpha(#9868F9, .10); }
  to { box-shadow: 0 0 0 3px alpha(#9868F9, .8), 0 0 10px alpha(#9868F9, .35); }
}
.transport button.library-action.library-busy:disabled { opacity: 1; color: #6ed9ae; animation: library-pulse 900ms ease-in-out infinite alternate; }
.theme-roon .transport button.library-action.library-busy:disabled { color: #9868F9; animation-name: library-pulse-roon; }
.large-display .transport button { min-width: 120px; min-height: 120px; border-radius: 60px; }
.large-display .transport .play { min-width: 150px; min-height: 150px; border-radius: 75px; }
.large-display .utility, .large-display .browser-back { min-width: 150px; min-height: 72px; font-size: 21px; padding: 12px 24px; }
.large-display .transport button.library-action { min-width: 120px; min-height: 120px; padding: 0; border-radius: 60px; }
.large-display .settings-page .settings-version, .large-display .settings-page .settings-diagnostic { font-size: 23px; }
.large-display .settings-header .settings-utilities button { font-size: 23px; }
.large-display .settings-page .setting-line label, .large-display .settings-page .setting-line checkbutton { font-size: 23px; }
.large-display .settings-page .settings-theme-choice { font-size: 24px; min-height: 72px; }
.large-display .settings-page scale value { font-size: 21px; }
.large-display.portrait .discover-toolbar .roon-subnav button { padding-left: 5px; padding-right: 5px; }
.large-display .source-volume { font-size: 400px; font-weight: 300; }
.large-display .source-mute { min-width: 240px; min-height: 82px; font-size: 26px; }
.source-step, .theme-roon .source-step { color: #fff; padding: 0; border-radius: 999px; }
.large-display .browser-back { min-width: 132px; min-height: 64px; padding: 10px 20px; }
.portrait .browser-back { min-height: 38px; padding: 4px 16px; }
.portrait.large-portrait .browser-back { min-height: 52px; }
.browser-sort { min-height: 48px; padding: 8px 12px; border-radius: 8px; background: #282828; color: #6ed9ae; }
.browser-sort:hover { background: #303033; }
.large-display .home-name { font-size: 34px; }
.large-display .home-state { font-size: 24px; }
.large-display .browser-home-title { font-size: 24px; }
.portrait .browser-home-card, .portrait .browser-home-card.compact { min-height: 0; padding: 12px; }
.large-display .artist-albums-heading { font-size: 24px; }
.large-display .artist-album-title { font-size: 30px; }
.large-display .recommendation-heading { font-size: 21px; margin-top: 18px; margin-bottom: 0; }
.large-display .recommendation-album { font-size: 25px; }
.album-profile { padding: 12px 0 24px; }
.album-artist { background: transparent; padding: 0; color: #aaa; font-size: 22px; }
.large-display .album-artist { font-size: 28px; }
.large-display .service-no { font-weight: 300; }
.large-display.portrait .now-volume-row { margin-top: 30px; }
.large-display.portrait .now-mute { margin-top: 36px; }
.portrait.large-portrait .roon-page { padding-top: 15px; }
.large-display.display-landscape .roon-page { padding-top: 5px; }
.compact-portrait .source-step { min-width: 64px; min-height: 64px; border-radius: 32px; }
.compact-portrait .source-volume { font-size: 84px; }
.compact-portrait .browser-filter { padding-left: 2px; padding-right: 2px; }
.compact-portrait .browser-back { min-width: 56px; padding-left: 8px; padding-right: 8px; }
.large-display .settings-select, .large-display .setting-line { min-height: 72px; font-size: 22px; }
.large-display .settings-action { min-height: 82px; font-size: 22px; }
.large-display .discovery-card .queue-title { font-size: 27px; }
.large-display .discovery-card .queue-subtitle { font-size: 22px; }
.large-display .queue-row { min-height: 138px; }
.queue-row:hover, .queue-row:active, .queue-row:focus, .theme-roon .queue-row:hover, .theme-roon .queue-row:active, .theme-roon .queue-row:focus { background: transparent; box-shadow: none; }
.queue-row.current, .queue-row.current:hover, .queue-row.current:active, .queue-row.current:focus { background: #121e1c; }
.theme-roon .queue-row.current, .theme-roon .queue-row.current:hover, .theme-roon .queue-row.current:active, .theme-roon .queue-row.current:focus { background: #292733; }
.queue-play-badge, .theme-roon .queue-play-badge { background: transparent; color: #fff; }
.queue-play-badge.light-art, .theme-roon .queue-play-badge.light-art { color: #392772; }
.large-display .queue-title { font-size: 30px; }
.large-display .queue-meta, .large-display .queue-duration { font-size: 23px; }
.large-display .browser-cover-title, .large-display .browser-cover-title.tile { font-size: 26px; }
.large-display .browser-cover-subtitle { font-size: 21px; }
.large-display .queue-art, .large-display .browser-action-icon { min-width: 116px; min-height: 116px; }
.large-display .artist-name { font-size: 38px; }
.large-display .artist-play, .large-display .queue-pill { min-height: 76px; font-size: 27px; }
.large-display .surprise-title { font-size: 42px; }
.large-display .surprise-artist { font-size: 30px; }
.large-display .surprise-action { min-width: 108px; min-height: 108px; }
.large-display .surprise-caption { font-size: 24px; }
.large-display .time { font-size: 23px; }
.large-display .roon-artist { font-size: 32px; }
""" % (APPLIANCE_PAGE_TOP, LANDSCAPE_PAGE_MARGIN, LANDSCAPE_PAGE_MARGIN,
       PORTRAIT_PAGE_MARGIN, PORTRAIT_PAGE_MARGIN, PANEL_STROKE, CAROUSEL_START_INSET)).encode()

CSS += b"""
popover.track-menu > contents { background: #171717; color: #eceaef; border: 1px solid #45434e; border-radius: 12px; padding: 12px; box-shadow: 0 12px 48px rgba(0,0,0,.55); }
.browser-sort, .browser-sort:hover { background: transparent; }
.detail-header { min-height: 92px; padding-top: 14px; padding-bottom: 14px; }
.detail-heading { color: #f4f0e6; font-size: 28px; font-weight: 700; }
.high-resolution .detail-header { min-height: 112px; padding: 18px 52px; }
.high-resolution .detail-heading { font-size: 36px; }
.high-resolution.portrait .detail-title { font-size: 49px; }
.high-resolution.portrait .detail-section-label { font-size: 22px; letter-spacing: 2.2px; }
.high-resolution.portrait .detail-artist { font-size: 30px; }
.high-resolution.portrait .detail-subtitle { margin-top: 2px; color: #96919a; font-size: 21px; }
.high-resolution.portrait .detail-writeup { font-size: 24px; line-height: 1.34; }
.high-resolution.portrait .detail-close { min-width: 88px; min-height: 88px; }
.high-resolution.portrait .detail-close-glyph { min-width: 60px; min-height: 60px; }
.compact-detail .detail-heading { font-size: 24px; }
.detail-close { border: 0; background: transparent; color: #fff; }
.detail-close-glyph { border: 2px solid #6ed9ae; border-radius: 50%; background: transparent; color: #fff; }
.compact-detail .detail-header { min-height: 68px; padding-top: 10px; padding-bottom: 10px; }
.compact-detail .detail-close-glyph { min-width: 40px; min-height: 40px; }
.detail-source { margin-top: 4px; margin-bottom: 14px; }
.detail-facts { padding-top: 0; }
.primary-play { background: #6ed9ae; color: #111; font-weight: 800; }
.primary-play:hover, .primary-play:active, .primary-play:focus { background: #83e6bd; color: #111; }
.theme-roon .primary-play { background: #9868F9; color: #111; }
.theme-roon .primary-play:hover, .theme-roon .primary-play:active, .theme-roon .primary-play:focus { background: #a77cff; color: #111; }
.surprise-action.primary-play, .theme-roon .surprise-action.primary-play { border-radius: 50%; }
.volume-step { min-width: 48px; min-height: 48px; padding: 0; border-radius: 24px; background: transparent; color: #6ed9ae; }
.large-display .volume-step { min-width: 68px; min-height: 68px; border-radius: 34px; }
.track-menu-action { min-height: 52px; padding: 10px 16px; border-radius: 8px; background: #18211f; color: #6ed9ae; font-size: 18px; }
.track-menu-action:hover { background: #34323a; }
.track-menu-action:active, .track-menu-action:focus { background: #292929; box-shadow: none; }
.track-menu-action.primary-play, .track-menu-action.primary-play:hover, .track-menu-action.primary-play:active, .track-menu-action.primary-play:focus { border-radius: 8px; background: #6ed9ae; color: #111; }
.track-menu-action.primary-play:disabled { background: #6ed9ae; color: #111; opacity: .72; }
.mix-track-row { min-height: 72px; padding-top: 3px; padding-bottom: 3px; }
.volume-number.fixed-volume-label { min-width: 150px; margin-top: 34px; color: #3d3b40; font-size: 16px; font-weight: 350; letter-spacing: 2px; }
.artist-overlay-info { padding: 62px 16px 12px; background: transparent; }
.artist-hero-frame, .artist-hero-frame viewport, .artist-hero-image,
.theme-roon .artist-hero-frame, .theme-roon .artist-hero-frame viewport, .theme-roon .artist-hero-image { border-top-left-radius: 8px; border-top-right-radius: 8px; background: transparent; background-image: none; }
.artist-overlay-info .artist-name { color: #fff; text-shadow: 0 2px 8px rgba(0,0,0,.9); }
.artist-overlay-play { box-shadow: 0 6px 22px rgba(0,0,0,.55); }
.touch2-7-landscape .artist-profile .artist-name { font-size: 31px; }
.touch2-7-landscape .artist-profile .artist-bio { font-size: 21px; line-height: 1.34; }
.original-landscape .artist-overlay-info { padding: 34px 12px 9px; }
.original-landscape .artist-overlay-info .artist-name { font-size: 22px; }
.original-landscape .artist-overlay-play { min-height: 38px; padding: 4px 12px; }
.original-landscape .artist-profile .artist-bio { font-size: 15px; line-height: 1.25; }
.artist-profile-summary { padding: 8px 16px 0; }
.artist-albums-heading { padding-top: 3px; }
popover.sort-menu .track-menu-action:hover,
popover.sort-menu .track-menu-action:focus { background: #18211f; box-shadow: none; }
popover.sort-menu .track-menu-action.active,
popover.sort-menu .track-menu-action.active:hover,
popover.sort-menu .track-menu-action.active:focus { background: #6ed9ae; color: #111; box-shadow: none; }
.large-display .track-menu-action { min-height: 64px; font-size: 24px; }
.compact-landscape popover.track-menu > contents { padding: 7px; border-radius: 10px; }
.compact-landscape .track-menu-action { min-height: 42px; padding: 5px 12px; font-size: 16px; }
.compact-landscape .page { padding: 10px 12px 8px; }
.compact-landscape .browser-sidebar { min-width: 112px; padding-right: 2px; }
.compact-landscape .browser-filter { min-height: 44px; padding: 6px; font-size: 14px; }
.compact-landscape .browser-scrubber { min-width: 44px; }
.compact-landscape .browser-search-entry { min-height: 42px; padding: 4px 10px; font-size: 18px; }
.compact-landscape .browser-key { min-width: 0; min-height: 32px; padding: 3px; font-size: 14px; }
.compact-landscape .clock { font-size: 24px; }
.compact-landscape .settings-page { padding: 8px 12px; }
.compact-landscape .settings-page .settings-title { font-size: 26px; }
.compact-landscape .settings-page .settings-version, .compact-landscape .settings-page .settings-diagnostic { font-size: 11px; }
.compact-landscape .settings-header .settings-utilities button { min-height: 38px; padding: 4px 12px; }
.compact-landscape .settings-page .setting-line, .compact-landscape .settings-page .settings-select { min-height: 40px; padding: 3px 10px; }
.compact-landscape .settings-page .settings-action { min-height: 46px; padding: 4px 10px; }
.compact-landscape .settings-page .settings-theme-choice { min-height: 40px; font-size: 14px; }
.compact-landscape .settings-page .settings-controls { padding-top: 2px; }
.compact-detail .detail-header { min-height: 61px; padding: 7px 20px 2px; }
.compact-detail .detail-close { min-width: 52px; min-height: 52px; padding: 0; }
.compact-detail .detail-panel { padding: 8px 20px 14px; }
.compact-detail .detail-entity { padding: 0; }
.compact-detail .detail-section-label { margin-top: 3px; font-size: 14px; letter-spacing: 1.6px; }
.compact-detail .detail-title { font-size: 30px; }
.compact-detail .detail-artist { font-size: 21px; }
.compact-detail .detail-subtitle { font-size: 15px; }.compact-detail .detail-writeup { font-size: 17px; line-height: 1.32; }
.compact-detail .detail-fact, .compact-detail .detail-track-title { color: #858b89; font-size: 13px; font-weight: 500; }
.compact-detail .detail-action { min-height: 43px; padding: 6px 12px; font-size: 14px; }
.compact-detail .detail-rule { margin: 7px 0; }
.compact-detail .detail-footer { padding: 10px 20px 20px; }
.compact-detail .detail-footer .detail-primary-action { min-height: 56px; font-size: 21px; }
.album-focus-detail .detail-panel { padding: 10px 20px 13px; }
.album-focus-detail .detail-entity { padding: 0; }
.album-focus-detail .detail-album-card { padding: 0; }
.album-focus-detail .detail-artwork-frame { margin: 0; }
.album-focus-detail .detail-section-label { margin-top: 0; font-size: 18px; letter-spacing: 1.9px; }
.album-focus-detail .detail-title { font-size: 36px; }
.album-focus-detail .detail-artist { font-size: 25px; }
.album-focus-detail .detail-writeup { font-size: 19px; line-height: 1.38; }
.touch2-7-landscape .album-focus-detail .detail-action,
.touch2-7-landscape.theme-roon .album-focus-detail .detail-action { min-height: 54px; margin-top: 14px; padding: 8px 22px; border-radius: 10px; background: #9868F9; color: #111; font-size: 18px; font-weight: 800; }

/* The original 800x480 DSI panel has its own density profile.  Keep these
   rules out of the 1024x600 and larger landscape layouts. */
.original-landscape .page { padding: 5px 12px 5px; }
.original-landscape .discover-toolbar { min-height: 44px; margin-bottom: 5px; padding-top: 0; }
.original-landscape .roon-page.now-layout .discover-toolbar { min-height: 40px; }
.original-landscape .discover-utility { min-width: 34px; min-height: 34px; padding: 0; }
.original-landscape .roon-subnav button { min-height: 34px; padding: 3px 8px 0; font-size: 14px; letter-spacing: .2px; }
.original-landscape .discover-toolbar .roon-subnav button { border-bottom-width: 2px; }
.original-landscape .browser-sidebar { min-width: 116px; padding: 4px 6px 2px 0; }
.original-landscape .browser-sidebar.library-sidebar { margin-top: -12px; }
.original-landscape .browser-sidebar.discovery-sidebar { margin-top: -12px; }
.original-landscape .browser-filter { min-height: 39px; padding: 3px 6px; font-size: 14px; letter-spacing: .2px; }
.original-landscape .browser-back { min-height: 38px; margin-top: 6px; }
.original-landscape .browser-main { margin-top: -16px; margin-bottom: -10px; padding-left: 0; }
.original-landscape .browser-cover-grid { padding: 1px 12px 10px 1px; }
.original-landscape .browser-cover-card { padding: 2px; }
.original-landscape .browser-cover-title { padding-top: 4px; font-size: 13px; }
.original-landscape .browser-cover-title.tile { padding: 5px 4px 6px; font-size: 15px; line-height: 1.05; }
.original-landscape .browser-cover-subtitle { font-size: 10px; }
.original-landscape .artist-album-title { font-size: 20px; }
.original-landscape .browser-scrubber scale { padding: 5px; }
.original-landscape .browser-scrub-letter { min-width: 28px; min-height: 28px; font-size: 14px; }
.original-landscape .discovery-scroll { margin-bottom: 2px; }
.original-landscape .discovery-card .queue-title { font-size: 17px; line-height: 1.05; }
.original-landscape .discovery-card .queue-subtitle { font-size: 13px; line-height: 1.05; }
.original-landscape .daily-card .queue-title { font-size: 18px; }
.original-landscape .daily-card .queue-subtitle { font-size: 14px; }
.original-landscape .daily-track { padding-left: 6px; padding-right: 0; }
.original-landscape .daily-scroll { margin-right: -4px; }
.original-landscape .roon-page.daily-edge { padding-right: 0; }
.original-landscape .roon-page.daily-edge .discovery-scroll { margin-right: -16px; }
.original-landscape .roon-page.daily-edge .discover-toolbar,
.original-landscape .roon-page.daily-edge > .nav { margin-right: 12px; }
.original-landscape .recommendation-heading { margin-top: 8px; }
.original-landscape .loading-dots { font-size: 24px; }
.original-landscape .loading-notice { font-size: 15px; }
.original-landscape .surprise-action { min-width: 62px; min-height: 62px; padding: 5px; }
.original-landscape .surprise-caption { font-size: 14px; }
.original-landscape .surprise-title { font-size: 24px; line-height: 1.05; }
.original-landscape .surprise-artist { font-size: 17px; }
.original-landscape .now-playing-content { margin-top: 0; margin-bottom: 0; }
.original-landscape .artwork, .original-landscape .artwork-button { border-radius: 6px; }
.original-landscape .roon-title { font-size: 34px; }
.original-landscape .now-mute { min-width: 54px; padding-left: 8px; padding-right: 8px; }
.original-landscape .volume-step { min-width: 36px; min-height: 36px; border-radius: 18px; }
.original-landscape .source-title { font-size: 22px; font-weight: 600; }
.original-landscape .source-step { min-width: 72px; min-height: 72px; border-radius: 36px; font-size: 38px; }
.original-landscape .source-volume { font-size: 112px; font-weight: 400; }
.original-landscape .settings-page { padding: 10px 12px 6px; }
.original-landscape .settings-card { padding: 7px 8px; border: 0; background: transparent; }
.original-landscape .settings-controls { padding: 0; }
.original-landscape .settings-column { padding: 0 3px; }
.original-landscape .settings-page .setting-line,
.original-landscape .settings-page .settings-select { min-height: 34px; padding: 2px 8px; }
.original-landscape .settings-page .settings-theme-choice { min-height: 31px; padding-top: 2px; padding-bottom: 2px; }
.original-landscape .settings-page .settings-action { min-height: 41px; }
.original-landscape .settings-header .settings-utilities button { min-height: 34px; }
.original-landscape .brightness-setting { padding: 2px 0; }
.original-landscape .artist-profile { padding: 3px 10px 4px 0; }
.original-landscape .artist-name { font-size: 25px; }
.original-landscape .artist-play { min-height: 38px; margin-top: 3px; padding: 4px 17px 4px 12px; font-size: 16px; }
.original-landscape .queue-pill { min-height: 38px; padding: 4px 14px; font-size: 15px; }
.original-landscape.compact-detail .detail-header { min-height: 46px; padding: 1px 20px 0; }
.original-landscape.compact-detail .detail-close { min-width: 37px; min-height: 37px; }
.original-landscape.compact-detail .detail-close-glyph { min-width: 31px; min-height: 31px; }
.original-landscape.compact-detail .detail-panel { padding-top: 3px; padding-bottom: 6px; }
.original-landscape.compact-detail .detail-album-content { margin: 0; }
.original-landscape.compact-detail .detail-writeup { font-size: 16px; line-height: 1.25; }
.original-landscape.compact-detail .detail-footer { padding-top: 6px; padding-bottom: 12px; }
.original-landscape.compact-detail .detail-footer .detail-primary-action { min-height: 48px; font-size: 18px; }
.original-landscape .compact-detail .detail-album-card .detail-action { min-height: 38px; margin-top: 3px; padding: 4px 12px; background: #6ed9ae; color: #111; font-size: 14px; font-weight: 800; }
.original-landscape.theme-roon .compact-detail .detail-album-card .detail-action { background: #9868F9; color: #111; }
.original-landscape .album-focus-detail .detail-section-label { font-size: 14px; letter-spacing: 1.5px; }
.original-landscape .album-focus-detail .detail-title { font-size: 28px; line-height: 1.08; }
.original-landscape .album-focus-detail .detail-artist { font-size: 19px; }
.original-landscape .album-focus-detail .detail-writeup { font-size: 16px; line-height: 1.28; }
.touch2-7-landscape .album-focus-detail .detail-section-label { font-size: 17px; letter-spacing: 1.7px; }
.touch2-7-landscape .album-focus-detail .detail-title { font-size: 36px; line-height: 1.08; }
.touch2-7-landscape .album-focus-detail .detail-artist { font-size: 25px; }
.touch2-7-landscape .album-focus-detail .detail-writeup { font-size: 21px; line-height: 1.36; }
.touch2-7-landscape .album-focus-detail .detail-action { margin-top: 8px; }
.touch2-7-landscape .transport button { min-width: 76px; min-height: 76px; border-radius: 38px; }
.touch2-7-landscape .transport .play { min-width: 96px; min-height: 96px; border-radius: 48px; }
.interface-smaller .transport button { min-width: 43px; min-height: 43px; border-radius: 22px; }
.interface-smaller .transport .play { min-width: 58px; min-height: 58px; border-radius: 29px; }
.interface-larger .transport button { min-width: 60px; min-height: 60px; border-radius: 30px; }
.interface-larger .transport .play { min-width: 82px; min-height: 82px; border-radius: 41px; }
.touch-landscape.interface-smaller .transport button { min-width: 60px; min-height: 60px; border-radius: 30px; }
.touch-landscape.interface-smaller .transport .play { min-width: 75px; min-height: 75px; border-radius: 38px; }
.touch-landscape.interface-larger .transport button { min-width: 84px; min-height: 84px; border-radius: 42px; }
.touch-landscape.interface-larger .transport .play { min-width: 106px; min-height: 106px; border-radius: 53px; }
/* Do not let the generic larger rule collapse the 10-inch hierarchy. */
.large-display.interface-larger .transport button,
.large-display.interface-larger .transport button.library-action { min-width: 120px; min-height: 120px; border-radius: 60px; }
.large-display.interface-larger .transport .play { min-width: 150px; min-height: 150px; border-radius: 75px; }
.interface-smaller .nav button { min-height: 36px; }
.interface-larger .nav button { min-height: 48px; }
.touch-landscape.interface-smaller .nav button { min-height: 52px; }
.touch-landscape.interface-larger .nav button { min-height: 70px; }
.interface-smaller .detail-action { min-height: 49px; padding-top: 5px; padding-bottom: 5px; }
.interface-larger .detail-action { min-height: 70px; padding-top: 10px; padding-bottom: 10px; }
.touch-landscape.interface-smaller .detail-action { min-height: 46px; }
.touch-landscape.interface-larger .detail-action { min-height: 65px; }
/* Shared semantic heading tier. Display profiles change geometry, not rank. */
.page-title, .stop, .settings-title, .detail-heading { font-size: 25px; font-weight: 700; }
.stop-code { font-size: 18px; font-weight: 550; }
.high-resolution .page-title, .high-resolution .stop,
.high-resolution .settings-title, .high-resolution .detail-heading { font-size: 34px; }
.high-resolution .stop-code { font-size: 22px; }
.touch-landscape .page-title, .touch-landscape .stop,
.touch-landscape .settings-title, .touch-landscape .detail-heading { font-size: 31px; }
.touch-landscape .stop-code { font-size: 21px; }
.original-landscape .page-title, .original-landscape .stop,
.original-landscape .settings-title, .original-landscape .detail-heading { font-size: 23px; }
.original-landscape .stop-code { font-size: 16px; }
/* Interface-size variants must affect every shared control family. */
.interface-larger .browser-back { min-width: 96px; min-height: 52px; padding: 8px 15px; font-size: 16px; }
.touch-landscape.interface-larger .browser-back { min-width: 112px; min-height: 58px; font-size: 18px; }
.interface-larger .album-profile .artist-name { font-size: 34px; }
.interface-larger .album-profile .album-artist { font-size: 26px; }
.interface-larger .album-profile .queue-meta { font-size: 21px; line-height: 1.35; }
.interface-larger .settings-select { font-size: 23px; }
.interface-smaller .settings-select { font-size: 16px; }
.album-play-split { margin-top: 2px; }
.album-play-split .artist-play { border-top-right-radius: 0; border-bottom-right-radius: 0; margin: 0; }
.album-play-menu { min-width: 36px; padding: 0 5px 0 3px; border-left: 2px solid rgba(21,21,21,.72); border-top-left-radius: 0; border-bottom-left-radius: 0; border-top-right-radius: 999px; border-bottom-right-radius: 999px; background: #6ed9ae; color: #111; }
.theme-roon .album-play-menu { background: #9868F9; color: #111; }
.interface-larger .album-play-menu { min-width: 40px; padding-left: 4px; padding-right: 6px; }
.touch-landscape.seven-inch-settings .settings-page { padding: 18px 28px; }
.touch-landscape.seven-inch-settings .settings-controls { padding-top: 4px; }
.touch-landscape.seven-inch-settings .settings-select { min-height: 56px; }
.touch-landscape.seven-inch-settings .settings-action { min-height: 58px; }
/* The shared seven-inch header frame sits slightly below the physical bezel.
   Keep this single inset for Now Playing, Discover, Bus Times and Home. */
.touch2-7-landscape .page { padding-top: 10px; }
.touch2-7-landscape .settings-page { padding-top: 10px; }
.original-landscape .page { padding-top: 7px; }
.original-landscape .settings-page { padding-top: 7px; }
.display-landscape .page-header .discover-utility { margin-top: 7px; }
.display-landscape .discover-toolbar > .discover-utility { margin-top: 7px; }
.touch2-7-landscape .browser-sidebar { min-width: 144px; }
.touch2-7-landscape .browser-main { padding-left: 9px; }
.touch2-7-landscape.interface-larger .browser-main { padding-left: 0; margin-left: -9px; }
.touch2-7-landscape .browser-scrubber { min-width: 42px; padding-left: 0; }
.touch2-7-landscape .bus-page,
.touch2-7-landscape .home-page { padding-top: 0; }
.detail-takeover.inline-detail { background: transparent; }
.inline-detail .detail-sheet-scroll,
.inline-detail .detail-panel,
.inline-detail .detail-entity { background: transparent; }
.inline-detail .detail-panel { padding: 0; }
.inline-detail .detail-section-label { margin-top: 0; }
.inline-detail .detail-action { margin-top: 12px; }
.touch2-7-landscape.interface-larger .inline-detail .detail-title { font-size: 34px; line-height: 1.05; }
.touch2-7-landscape.interface-larger .inline-detail .detail-artist { font-size: 23px; }
.touch2-7-landscape.interface-larger .inline-detail .detail-writeup { font-size: 18px; line-height: 1.18; }
.touch2-7-landscape.interface-larger .inline-detail .detail-action { min-height: 56px; margin-top: 8px; padding-top: 7px; padding-bottom: 7px; }
.touch2-7-landscape.interface-larger .artist-overlay-info .artist-name { font-size: 34px; line-height: 1.05; }
"""
# Small static texture: no animation, full-screen image download or per-frame work.
CSS += ('.theme-roon .page { background-image: url("%s"), linear-gradient(120deg, #1d1c2d, #121212 62%%, #1b1519); background-repeat: repeat, no-repeat; background-size: 128px 128px, cover; }' %
        (Path(__file__).resolve().parent / 'icons/gradient-dither.svg').as_uri()).encode()
CSS += b"""
window.background-black, window.background-black .page,
window.background-black .roon-page, window.background-black .home-page,
window.background-black .settings-page, window.background-black .sleep {
    background-color: #000; background-image: none;
}

/* Beta 64: one shared frame and density system for physical displays. */
window.theme-roon .detail-takeover,
window.theme-roon .detail-header,
window.theme-roon .detail-sheet-scroll,
window.theme-roon .detail-footer { background: transparent; }
window.background-black .detail-takeover,
window.background-black .detail-header,
window.background-black .detail-sheet-scroll,
window.background-black .detail-footer { background: #000; }
.detail-footer .detail-primary-action { font-size: 22px; }
.high-resolution .detail-footer .detail-primary-action { font-size: 25px; }

/* Only the installation-profile picker receives the larger menu treatment. */
.touch-profile-select { font-size: 22px; }
.touch-profile-select popover listview row { min-height: 60px; padding: 9px 16px; }
.touch-profile-select popover listview row label { font-size: 22px; }
.portrait .touch-profile-select,
.portrait .touch-profile-select popover listview row label { font-size: 27px; }
.portrait .touch-profile-select popover listview row { min-height: 72px; }

.settings-close { min-width: 58px; min-height: 58px; padding: 0; border: 2px solid #6ed9ae; border-radius: 50%; background: transparent; color: #fff; }
.theme-roon .settings-close { border-color: #9868F9; }
.settings-sleep { min-width: 128px; min-height: 58px; padding: 0 24px; border-radius: 8px; background: #303030; color: #f4f0e6; font-size: 16px; font-weight: 750; }
.settings-page .settings-title { font-size: 34px; }
.settings-page .settings-diagnostic { font-size: 11px; }
popover listview row { min-height: 48px; padding: 8px 14px; }
popover listview row label { font-size: 19px; }
.interface-larger popover listview row { min-height: 58px; }
.interface-larger popover listview row label { font-size: 22px; }
.settings-action-stack { padding-top: 4px; padding-bottom: 6px; }
.portrait .settings-page { padding-top: 24px; padding-bottom: 12px; }
.portrait .settings-header { min-height: 84px; }
.portrait .settings-title { font-size: 38px; font-weight: 600; }
.portrait .settings-version { font-size: 17px; }
.portrait .settings-diagnostic { font-size: 17px; }
.portrait .settings-card { padding-bottom: 10px; }
.portrait .settings-action-stack { padding-top: 18px; padding-bottom: 0; }
.portrait .settings-primary-actions { margin-bottom: 22px; }
.portrait .settings-action { min-height: 72px; }

/* The same page-edge geometry drives all four primary pages. */
.touch-landscape .page-header,
.touch-landscape .discover-toolbar { margin-left: -8px; margin-right: -8px; }
.touch-landscape .page-header .discover-utility,
.touch-landscape .discover-toolbar > .discover-utility { margin-top: 11px; }
.touch-landscape .header-clock,
.touch-landscape .discover-sleep { margin-top: 8px; }

/* One physical anchor for the utility controls on every 10-inch page.
   Keep this after device-specific rules so the shared position wins. */
.large-display .page-header,
.large-display .discover-toolbar { min-height: 64px; }
.large-display .page-header .discover-utility,
.large-display .discover-toolbar > .discover-utility,
.large-display .header-clock,
.large-display .discover-sleep { margin-top: 0; margin-bottom: 0; }
.large-display .page-header > button,
.large-display .discover-toolbar > button { min-height: 56px; margin-top: 4px; margin-bottom: 4px; }
.touch2-7-landscape .nav { min-height: 60px; padding-top: 0; margin-top: 0; margin-bottom: 0; }
.touch2-7-landscape .nav button { min-height: 58px; }
.touch2-7-landscape .bus-page .service.compact { padding-top: 2px; padding-bottom: 2px; }
.touch2-7-landscape .bus-page .service.compact .service-no,
.touch2-7-landscape .bus-page .service.compact .arrival { font-size: 66px; }
.touch2-7-landscape .bus-page .stop-row { margin-bottom: 4px; }
.touch2-7-landscape .bus-page .bus-footer { min-height: 18px; }

.large-display.portrait .bus-page .service.compact,
.large-display.portrait .bus-page .service.dense { padding-top: 3px; padding-bottom: 3px; }
.large-display.portrait .bus-page .bus-route-badge { margin-top: 4px; }
.large-display.portrait .bus-page .bus-next-unit { margin-top: -4px; }
"""


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


class Display(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.pihome.Native")
        self.polling = False
        self.state = None
        self.settings_open = False
        self.last_mode = "bus"
        self.pending_mode = None
        self.pending_mode_started_at = 0.0
        self.settings_data = {}
        self.image_key = None
        self.image_misses = 0
        self.volume_updating = False
        self.seek_updating = False
        self.seek_timeout = None
        self.screen_powered = None
        self.system_data = {}
        self.last_config_fetch = 0.0
        self.last_system_fetch = 0.0
        self.bus_signature = None
        self.display_controls_loaded = False
        self.touch_controls = {}
        self.home_signature = None
        self.home_nav_buttons = []
        self.roon_nav_buttons = []
        self.bus_nav_buttons = []
        self.discover_nav_buttons = []
        self.discovery_active = False
        self.discovery_section = "recent"
        self.discovery_mix = ""
        self.discovery_request = 0
        self.discovery_signature = None
        self.discovery_pictures = {}
        self.discovery_recent_mode = "added"
        self.discovery_picks = False
        self.discovery_cards = []
        self.discovery_browser_origin = False
        self.home_value_timeouts = {}
        self.brightness_updating = False
        self.brightness_timeout = None
        self.brightness_applied = False
        self.update_in_progress = False
        self.update_status_seen = False
        self.views_prewarmed = False
        self.started_at = time.monotonic()
        self.refresh_count = 0
        self.queue_signature = None
        self.queue_thumbnail_jobs = Queue()
        self.queue_thumbnail_pending = set()
        self.queue_thumbnail_cache = {}
        self.queue_thumbnail_source = {}
        self.queue_thumbnail_order = []
        self.artist_hero_cache = {}
        self.artist_hero_keys = set()
        self.preview_artwork_cache = {}
        self.queue_pictures = {}
        self.queue_artwork_keys = []
        self.browser_state = None
        self.browser_loading = False
        self.browser_rendering = False
        self.browser_pictures = {}
        self.browser_artwork_keys = []
        self.browser_scroll_restore = None
        self.browser_section_scrolls = {}
        self.last_interaction = time.monotonic()
        self.browse_last_interaction = self.last_interaction
        self.inactivity_sleeping = False
        self.sleep_entered_at = 0.0
        self.manual_sleep_pending = False
        self.manual_sleep_started_at = 0.0
        self.requested_audio_view = "now"
        self.last_active_input = ""
        self.detail_album_image_key = None
        self.detail_artist_image_key = None
        self.detail_artist_profile_name = None
        self.detail_artist_profile = {}
        self.detail_artist_profile_fetched_at = 0.0
        self.detail_artist_profile_loading = None
        self.detail_signature = None
        self.bluos_source_buttons = {}
        self.last_display_view_id = None

    def label(self, text="", css=None, x=0):
        widget = Gtk.Label(label=text, xalign=x)
        if css:
            for name in css.split(): widget.add_css_class(name)
        self.scale_text_label(widget)
        return widget

    def button(self, text, callback, css="utility"):
        widget = Gtk.Button(label=text)
        if css:
            for name in css.split(): widget.add_css_class(name)
        widget.connect("clicked", callback)
        if isinstance(widget.get_child(), Gtk.Label): self.scale_text_label(widget.get_child())
        return widget

    def scale_text_label(self, widget):
        """Multiply CSS typography without discarding each label's design size."""
        if not hasattr(widget, "roondeck_base_attributes"):
            current = widget.get_attributes()
            widget.roondeck_base_attributes = current.copy() if current else Pango.AttrList()
        attributes = widget.roondeck_base_attributes.copy()
        size = (self.settings_data or {}).get("interface_size", "standard")
        factor = {"smaller": .86, "larger": 1.2}.get(size, 1.0)
        # Route and arrival numerals are intentionally the largest information
        # on their page already. They still respond, but at half the global
        # delta; headings and clocks retain the same scale as every other page.
        has_class = getattr(widget, "has_css_class", lambda _name: False)
        # The wordmark and Settings heading are one lock-up. Scaling only the
        # label creates a large false gap and makes the heading look heavier.
        if has_class("settings-title"):
            factor = 1.0
        if has_class("service-no") or has_class("arrival"):
            factor = 1.0 + (factor - 1.0) * .5
        attributes.insert(Pango.attr_scale_new(factor))
        widget.set_attributes(attributes)

    def apply_interface_size(self, value):
        value = value if value in {"smaller", "standard", "larger"} else "standard"
        self.settings_data["interface_size"] = value
        for name in ("interface-smaller", "interface-larger"): self.window.remove_css_class(name)
        if value != "standard": self.window.add_css_class("interface-" + value)
        pending = [self.window]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Gtk.Label): self.scale_text_label(widget)
            child = widget.get_first_child()
            while child:
                pending.append(child); child = child.get_next_sibling()
        factor = {"smaller": .86, "larger": 1.2}.get(value, 1.0)
        for icon in getattr(self, "utility_icons", []):
            base = getattr(icon, "roondeck_base_size", None)
            if base:
                scaled = round(base * factor)
                if hasattr(icon, "set_pixel_size"): icon.set_pixel_size(scaled)
                icon.set_size_request(scaled, scaled)
        for control, base in getattr(self, "interface_transport_icon_sizes", {}).items():
            control.get_child().set_pixel_size(round(base * factor))
        if hasattr(self, "interface_detail_close_sizes"):
            close_size, glyph_size, icon_size = self.interface_detail_close_sizes
            self.detail_close.set_size_request(round(close_size * factor), round(close_size * factor))
            self.detail_close_glyph.set_size_request(round(glyph_size * factor), round(glyph_size * factor))
            self.detail_close_icon.set_pixel_size(round(icon_size * factor))

    def icon_button(self, icon, callback, css=""):
        widget = Gtk.Button()
        if css:
            for name in css.split(): widget.add_css_class(name)
        large = min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000
        original = getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        image = FamilyIcon(icon, (64 if large else 34 if original else 42) if "surprise-action" in css else 44 if original and "source-step" in css else 46 if "source-step" in css else 34, filled=icon in {"play", "media-playback-start-symbolic"} and "primary-play" in css); widget.set_child(image)
        caption = {"previous": "Previous track", "next": "Next track", "play": "Play", "pause": "Pause", "refresh": "Refresh", "remove": "Volume down", "add": "Add"}.get(image.icon_name, image.icon_name.title())
        widget.set_tooltip_text(caption)
        widget.update_property([Gtk.AccessibleProperty.LABEL], [caption])
        widget.connect("clicked", callback)
        return widget

    def labelled_icon_button(self, name, text, callback, css="utility"):
        widget = self.button(text, callback, css)
        row = Gtk.Box(spacing=8); row.set_halign(Gtk.Align.CENTER)
        large = min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000
        primary_play = name == "play" and "primary-play" in css
        row.append(FamilyIcon(name, (42 if large else 30) if primary_play else (36 if large else 24), filled=primary_play)); row.append(self.label(text))
        widget.set_child(row)
        widget.set_tooltip_text(text)
        widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
        return widget

    def loading_notice(self):
        """Animate only while mapped; remove the timer when this view leaves."""
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.set_halign(Gtk.Align.CENTER); panel.set_valign(Gtk.Align.CENTER)
        panel.set_hexpand(True); panel.set_vexpand(True)
        original = getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        panel.set_margin_top(18 if original else 48); panel.set_margin_bottom(18 if original else 48)
        dots = Gtk.Box(spacing=12); dots.set_halign(Gtk.Align.CENTER)
        labels = [self.label("●", "loading-dots") for _ in range(3)]
        for label in labels: dots.append(label)
        panel.append(dots)
        timer = [None]; started = [0.0]
        def pulse():
            elapsed = time.monotonic() - started[0]
            for index, label in enumerate(labels):
                label.set_opacity(.25 + .75 * (1 + math.sin(elapsed * 5 - index * 1.1)) / 2)
            return True
        def start(*_):
            if timer[0] is None:
                started[0] = time.monotonic(); pulse(); timer[0] = GLib.timeout_add(80, pulse)
        def stop(*_):
            if timer[0] is not None: GLib.source_remove(timer[0]); timer[0] = None
        panel.connect("map", start); panel.connect("unmap", stop)
        return panel

    def discover_utility_icon(self, clock=False):
        compact = getattr(self, "viewport_width", 800) < 1000 and getattr(self, "viewport_height", 480) <= 600
        # The hand-drawn clock has a circular outline that reads larger than the
        # settings glyph at the same allocation. Give it its final compact size
        # immediately; the first responsive pass can run before this header is
        # constructed on the original 800x480 display.
        size = 20 if clock and compact else 30 if compact else 38
        if not clock:
            icon = FamilyIcon("settings", size)
            icon.roondeck_base_size = size
            icon.add_css_class("settings-icon")
            self.utility_icons = getattr(self, "utility_icons", []) + [icon]
            return icon
        # Draw outlines directly: symbolic theme recolouring can fill SVG holes.
        icon = Gtk.DrawingArea(); icon.set_size_request(size, size); icon.roondeck_base_size = size
        self.utility_icons = getattr(self, "utility_icons", []) + [icon]
        def draw(_area, cr, width, height):
            original_clock = clock and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
            cr.save(); cr.translate(width / 2, height / 2); scale = (1.008 if original_clock else 1.12) * min(width, height) / 38; cr.scale(scale, scale)
            colour = (.53, .55, .56) if clock else ((.506, .478, .922) if self.settings_data.get("display_theme") == "roon" else (.431, .851, .682))
            cr.set_source_rgb(*colour); cr.set_line_width(2); cr.set_line_join(1); cr.set_line_cap(1)
            if clock:
                cr.arc(0, 0, 12.5, 0, math.tau); cr.stroke()
                current = datetime.now(TZ)
                for angle, length in ((math.tau * current.minute / 60 - math.pi / 2, 9), (math.tau * ((current.hour % 12) + current.minute / 60) / 12 - math.pi / 2, 6)):
                    cr.move_to(0, 0); cr.line_to(math.cos(angle) * length, math.sin(angle) * length); cr.stroke()
            else:
                for point in range(32):
                    angle = math.tau * point / 32
                    radius = 14 if point % 4 in (0, 1) else 10.5
                    x, y = math.cos(angle) * radius, math.sin(angle) * radius
                    if point: cr.line_to(x, y)
                    else: cr.move_to(x, y)
                cr.close_path(); cr.stroke(); cr.arc(0, 0, 5, 0, math.tau); cr.stroke()
            cr.restore()
        icon.set_draw_func(draw)
        if clock: self.music_clock_icon = icon
        return icon

    def do_activate(self):
        provider = Gtk.CssProvider(); provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.home_color_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.home_color_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = create_display_window(application=self); self.window.set_decorated(False); self.window.set_default_size(800, 480); self.window.fullscreen()
        # Apply saved theme before the first frame, not after an API poll.
        try:
            initial_config = tomllib.loads(Path("/etc/pi-home/config.toml").read_text())
            if initial_config.get("display_theme") == "roon": self.window.add_css_class("theme-roon")
        except (OSError, ValueError): pass
        self.window.set_cursor_from_name("none")
        activity = Gtk.EventControllerLegacy(); activity.set_propagation_phase(Gtk.PropagationPhase.CAPTURE); activity.connect("event", self.note_activity); self.window.add_controller(activity)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, transition_duration=0)
        self.stack.set_hhomogeneous(False); self.stack.set_vhomogeneous(False)
        self.boot_started_at = time.monotonic(); self.boot_transition_timer = None; self.pending_boot_mode = None
        self.stack.add_named(self.build_boot_splash(), "boot"); self.stack.add_named(self.build_bus(), "bus"); self.stack.add_named(self.build_roon(), "roon"); self.stack.add_named(self.build_home(), "home"); self.stack.add_named(self.build_settings(), "settings"); self.stack.add_named(self.build_sleep(), "sleep")
        self.root_overlay = Gtk.Overlay(); self.root_overlay.set_child(self.stack)
        self.window.set_child(self.root_overlay); self.window.present()
        GLib.timeout_add_seconds(1, self.log_renderer)
        GLib.timeout_add_seconds(1, self.hide_touch_cursor)
        for _ in range(3): threading.Thread(target=self.thumbnail_worker, daemon=True).start()
        threading.Thread(target=self.touchscreen_wake_worker, daemon=True).start()
        GLib.idle_add(self.adapt_display)
        self.window.connect("notify::width", lambda *_: self.adapt_display())
        self.window.connect("notify::height", lambda *_: self.adapt_display())
        GLib.timeout_add_seconds(1, self.tick); GLib.timeout_add_seconds(2, self.start_poll); self.tick(); self.start_poll()

    def adapt_display(self):
        width, height = self.window.get_width(), self.window.get_height()
        monitors = Gdk.Display.get_default().get_monitors(); monitor = monitors.get_item(0) if monitors.get_n_items() else None
        if monitor and width > 1 and height > 1:
            geometry = monitor.get_geometry(); width, height = min(width, geometry.width), min(height, geometry.height)
        if width < 2 or height < 2:
            monitors = Gdk.Display.get_default().get_monitors(); monitor = monitors.get_item(0) if monitors.get_n_items() else None
            if not monitor: return False
            geometry = monitor.get_geometry(); width, height = geometry.width, geometry.height
        portrait = height > width
        previous = getattr(self, "responsive_portrait", None)
        self.responsive_portrait = portrait
        self.viewport_width, self.viewport_height = width, height
        original_landscape = not portrait and width <= 820 and height <= 500
        for control in (self.source_down, self.source_up):
            source_size = 64 if portrait and width < 600 else 72 if original_landscape else 112
            control.set_size_request(source_size, source_size)
        self.source_volume.set_size_request(180 if portrait and width < 600 else 190 if original_landscape else 230, -1)
        large_display = min(width, height) >= 1000
        (self.window.add_css_class if large_display else self.window.remove_css_class)("large-display")
        (self.window.add_css_class if portrait and width >= 1000 else self.window.remove_css_class)("large-portrait")
        compact_landscape = not portrait and (height <= 600 or width < 1000)
        touch2_7_landscape = not portrait and 1200 <= width < 1500 and 650 <= height < 850
        for css_class, enabled in (("portrait", portrait), ("display-landscape", not portrait), ("compact-landscape", compact_landscape), ("original-landscape", original_landscape), ("compact-portrait", portrait and width < 600), ("high-resolution", max(width, height) >= 1200), ("touch-landscape", width >= 1200 and not portrait), ("touch2-7-landscape", touch2_7_landscape)):
            (self.window.add_css_class if enabled else self.window.remove_css_class)(css_class)
        utility_size = 26 if original_landscape else 30 if compact_landscape else 38
        for icon in getattr(self, "utility_icons", []):
            clock_icon = icon is getattr(self, "music_clock_icon", None)
            icon_size = 20 if original_landscape and clock_icon else 42 if large_display and clock_icon else utility_size
            icon.roondeck_base_size = icon_size
            if hasattr(icon, "set_pixel_size"): icon.set_pixel_size(icon_size)
            else: icon.set_size_request(icon_size, icon_size)
        self.now_playing_content.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.now_playing_content.set_spacing(24 if portrait else 20 if original_landscape else 26)
        self.now_playing_content.set_margin_top(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)
        self.now_playing_content.set_margin_bottom(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)
        self.now_playing_centre.set_valign(Gtk.Align.START if portrait else Gtk.Align.CENTER)
        if hasattr(self, "volume_row"):
            mute_parent = self.mute.get_parent()
            target = self.now_playing_centre if large_display and portrait else self.volume_row
            if mute_parent is not target:
                mute_parent.remove(self.mute)
                if target is self.volume_row: target.prepend(self.mute)
                else: target.append(self.mute)
            self.mute.set_halign(Gtk.Align.CENTER if large_display and portrait else Gtk.Align.FILL)
            self.controls.set_spacing(26 if large_display else 14)
            for control in (self.library_add, self.prev, self.play, self.next):
                control.get_child().set_pixel_size((80 if control is self.play else 64) if large_display else 42 if control is self.play else 34)
            self.interface_transport_icon_sizes = {control: ((80 if control is self.play else 64) if large_display else 42 if control is self.play else 34) for control in (self.library_add, self.prev, self.play, self.next)}
        self.zone.set_valign(Gtk.Align.START if portrait else Gtk.Align.CENTER)
        self.zone.set_margin_top(8 if portrait else 0)
        self.roon_clock.set_valign(Gtk.Align.START if portrait else Gtk.Align.CENTER)
        if hasattr(self, "settings_controls"):
            self.configure_settings_layout(width, height)
        self.browser_body.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.browser_search_panel.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.search_main.set_spacing(6 if compact_landscape else 12)
        self.browser_sidebar.set_orientation(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL)
        self.browser_discovery_sidebar.set_orientation(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL)
        self.browser_sidebar_spacer.set_hexpand(portrait); self.browser_sidebar_spacer.set_vexpand(not portrait)
        self.search_nav.set_orientation(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL)
        for sidebar in (self.browser_sidebar, self.browser_discovery_sidebar, self.discovery_sidebar, self.search_nav):
            sidebar.set_vexpand(not portrait); sidebar.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
            sidebar.set_spacing(4 if portrait and width < 600 else round(width * .036) if portrait else 0 if original_landscape else 2)
        # Portrait tabs are a real second row, not an overlay on the clock.
        for tabs in (self.roon_subnav, self.discover_subnav):
            parent = tabs.get_parent()
            target = self.discover_toolbar_tabs
            if parent is not target:
                if parent is self.music_header_overlay: parent.remove_overlay(tabs)
                else: parent.remove(tabs)
                target.append(tabs)
            tabs.set_halign(Gtk.Align.FILL if portrait else Gtk.Align.CENTER)
            # Equal cells multiply the longest label's minimum width by five.
            # Share the spare space instead, keeping every full label readable.
            tabs.set_homogeneous(False); tabs.set_spacing(24 if width >= 1000 else 4 if original_landscape else 8)
            child = tabs.get_first_child()
            while child:
                child.set_hexpand(portrait); child = child.get_next_sibling()
        exploring = self.discovery_active and self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
        self.discover_toolbar.set_visible(True)
        self.discover_toolbar.set_margin_end(28 if not portrait and width >= 1200 else 0)
        self.discover_toolbar.set_spacing(8 if portrait and width < 600 else 8 if original_landscape else 12)
        self.music_header_overlay.set_visible(False)
        if hasattr(self, "configure_music_clock"): self.configure_music_clock()
        self.portrait_music_tabs.set_visible(False)
        self.portrait_music_tabs.set_margin_end(24 if portrait else 0)
        self.portrait_music_tabs.set_margin_bottom((16 if width < 600 else 24) if portrait else 0)
        self.browser_body.set_margin_end(0)
        self.browser_content.set_margin_top(0 if original_landscape else 16)
        self.browser_scroll.set_margin_bottom(0 if original_landscape else 10)
        compact_browser_scrubber = portrait or compact_landscape or touch2_7_landscape
        self.browser_scrubber.set_size_request(54 if original_landscape else 42 if touch2_7_landscape else 52 if compact_browser_scrubber else 74, -1)
        self.browser_scrubber.set_margin_end(0 if compact_browser_scrubber else 18)
        self.browser_search_columns.set_orientation(Gtk.Orientation.VERTICAL if portrait and width < 700 else Gtk.Orientation.HORIZONTAL)
        self.discovery_body.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.discovery_sidebar.set_orientation(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL)
        self.detail_panel.set_orientation(Gtk.Orientation.VERTICAL if portrait and width < 1000 else Gtk.Orientation.HORIZONTAL)
        self.detail_panel.set_spacing(16 if compact_landscape else 28)
        # Ask GTK how much height the actual text and controls need. Long
        # titles must shrink the artwork instead of expanding the window.
        reserved = max(560, 120 + sum(widget.measure(Gtk.Orientation.VERTICAL, max(1, width - 64))[0] for widget in (self.discover_toolbar, self.now_playing_centre, self.music_navigation))) if portrait else 0
        artwork_size = now_playing_artwork_size(width, height, portrait, reserved)
        # Larger typography consumes more of the fixed 720px canvas. Keep the
        # whole composition inside it instead of producing a scrollable page.
        if touch2_7_landscape and (self.settings_data or {}).get("interface_size") == "larger":
            artwork_size = min(480, artwork_size)
        self.artwork_button.set_halign(Gtk.Align.CENTER if portrait else Gtk.Align.START)
        self.artwork_button.set_valign(Gtk.Align.END if original_landscape else Gtk.Align.CENTER)
        self.artwork_button.set_margin_bottom(16 if original_landscape else 0)
        self.artwork.set_size_request(artwork_size, artwork_size); self.artwork_button.set_size_request(artwork_size, artwork_size)
        self.volume_row.set_halign(Gtk.Align.CENTER if portrait else Gtk.Align.FILL)
        self.volume_row.set_size_request(round((width - 60) * .88) if portrait else -1, -1)
        # Keep an explicit square allocation around the picture in every
        # orientation. Gtk.Picture otherwise exposes the newly decoded image's
        # intrinsic size and the transport column can jump while a cover loads.
        for axis in ("width", "height"):
            getattr(self.artwork_viewport, "set_min_content_" + axis)(artwork_size)
            getattr(self.artwork_viewport, "set_max_content_" + axis)(artwork_size)
        self.artwork_viewport.set_size_request(artwork_size, artwork_size)
        compact_detail = compact_landscape or (not portrait and height <= 720)
        # Compact landscape prioritises the album. Larger portrait and
        # 10-inch landscape displays retain the two-card presentation.
        album_focus_detail = not portrait and height <= 720
        inline_detail = original_landscape or touch2_7_landscape
        large_detail_portrait = portrait and max(width, height) >= 1200
        self.compact_detail = compact_detail
        (self.detail_takeover.add_css_class if compact_detail else self.detail_takeover.remove_css_class)("compact-detail")
        self.album_focus_detail = album_focus_detail
        self.inline_detail = inline_detail
        (self.detail_takeover.add_css_class if inline_detail else self.detail_takeover.remove_css_class)("inline-detail")
        self.large_detail_portrait = large_detail_portrait
        self.detail_year_only = album_focus_detail or large_detail_portrait
        self.original_landscape = original_landscape
        (self.detail_takeover.add_css_class if album_focus_detail else self.detail_takeover.remove_css_class)("album-focus-detail")
        self.detail_artist_card.set_visible(not album_focus_detail)
        self.detail_panel.set_homogeneous(not album_focus_detail)
        self.detail_album_card.set_orientation(Gtk.Orientation.VERTICAL if inline_detail else Gtk.Orientation.HORIZONTAL if album_focus_detail else Gtk.Orientation.VERTICAL)
        self.detail_album_card.set_spacing(8 if inline_detail else 28 if album_focus_detail else 8)
        self.detail_album_content.set_hexpand(album_focus_detail)
        self.detail_album_content.set_valign(Gtk.Align.START)
        self.detail_album_content.set_spacing(6 if original_landscape else 8)
        self.detail_album_action.set_visible(album_focus_detail)
        self.detail_browse_action.set_visible(not album_focus_detail)
        self.detail_footer.set_visible(not album_focus_detail)
        self.detail_header.set_visible(not inline_detail)
        self.detail_album_artwork_frame.set_visible(not inline_detail)
        if inline_detail:
            page_left = 12 if original_landscape else 28
            self.detail_takeover.set_margin_start(page_left + artwork_size + 26)
            self.detail_takeover.set_margin_end(12 if original_landscape else 28)
            larger_detail = (self.settings_data or {}).get("interface_size") == "larger"
            self.detail_takeover.set_margin_top(52 if original_landscape else 54 if larger_detail else 62)
            self.detail_takeover.set_margin_bottom(54 if original_landscape else 68 if larger_detail else 76)
            self.detail_panel.set_valign(Gtk.Align.CENTER)
            self.detail_album_card.set_valign(Gtk.Align.CENTER)
        else:
            self.detail_takeover.set_margin_start(0); self.detail_takeover.set_margin_end(0)
            self.detail_takeover.set_margin_top(0); self.detail_takeover.set_margin_bottom(0)
            self.detail_panel.set_valign(Gtk.Align.FILL)
        detail_size = max(180, min(round((width - 100) / 2), 500)) if portrait else (380 if original_landscape else max(240, min(round(width * .5), height - 100, 620)) if album_focus_detail else max(220, min(round((width - 260) / 2), height - 300, 460)))
        self.detail_heading_width = detail_size
        self.detail_album_artwork.set_size_request(detail_size, detail_size)
        self.detail_artist_artwork.set_size_request(detail_size, detail_size)
        for viewport in (self.detail_album_artwork_frame, self.detail_artist_artwork_frame):
            viewport.set_min_content_width(detail_size); viewport.set_max_content_width(detail_size)
            viewport.set_min_content_height(detail_size); viewport.set_max_content_height(detail_size)
            viewport.set_size_request(detail_size, detail_size)
            viewport.set_halign(Gtk.Align.START); viewport.set_valign(Gtk.Align.START)
        for label in (self.detail_artist_writeup, self.detail_writeup):
            label.set_lines(3 if original_landscape else 4 if inline_detail and (self.settings_data or {}).get("interface_size") == "larger" else 5 if album_focus_detail else 24 if large_detail_portrait else 3 if compact_detail else -1)
            label.set_ellipsize(Pango.EllipsizeMode.END if compact_detail or large_detail_portrait else Pango.EllipsizeMode.NONE)
        self.detail_sheet.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER if inline_detail else Gtk.PolicyType.AUTOMATIC)
        self.detail_sheet.set_kinetic_scrolling(not inline_detail)
        self.detail_artist_facts.set_visible(not large_detail_portrait)
        self.detail_facts.set_visible(not original_landscape and not large_detail_portrait)
        self.detail_tracks.set_visible(False)
        close_size = 37 if original_landscape else 48 if album_focus_detail else 88 if large_detail_portrait else 72 if min(width, height) >= 1000 else 56
        self.detail_close.set_size_request(close_size, close_size)
        glyph_size = 31 if original_landscape else 60 if large_detail_portrait else 48
        self.detail_close_glyph.set_size_request(glyph_size, glyph_size)
        detail_close_icon_size = 29 if original_landscape else 40 if large_detail_portrait else 34
        self.detail_close_icon.set_pixel_size(detail_close_icon_size)
        self.interface_detail_close_sizes = (close_size, glyph_size, detail_close_icon_size)
        self.detail_close.set_halign(Gtk.Align.CENTER); self.detail_close.set_valign(Gtk.Align.CENTER)
        if previous is not None and previous != portrait:
            self.home_signature = None; self.discovery_signature = None
            if getattr(self, "browser_state", None): self.render_browser(self.browser_state)
        self.now_playing_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait else Gtk.PolicyType.NEVER)
        self.apply_interface_size((self.settings_data or {}).get("interface_size", "standard"))
        return False

    def header(self, centre, clock):
        row = Gtk.Box(spacing=10); row.add_css_class("page-header")
        if isinstance(centre, Gtk.Label): centre.set_xalign(0)
        settings = self.icon_button("emblem-system-symbolic", lambda *_: self.open_settings(), "discover-utility"); settings.set_valign(Gtk.Align.CENTER)
        settings.set_child(self.discover_utility_icon()); settings.set_tooltip_text("Settings"); row.append(settings)
        row.append(centre)
        spacer = Gtk.Box(); spacer.set_hexpand(True); row.append(spacer)
        if isinstance(clock, Gtk.Label): clock.set_valign(Gtk.Align.CENTER)
        clock.set_xalign(1)
        clock_button = Gtk.Button(); clock_button.add_css_class("header-hotspot"); clock_button.add_css_class("header-clock"); clock_button.set_valign(Gtk.Align.CENTER); clock_button.set_child(clock); clock_button.connect("clicked", self.sleep); row.append(clock_button)
        return row

    def navigation(self, active):
        row = Gtk.Box(spacing=8); row.add_css_class("nav")
        row.set_homogeneous(True)
        now = self.button("Now Playing", lambda *_: (self.show_roon_now(), self.set_mode("roon")), ""); now.navigation_page = active; self.roon_nav_buttons.append(now)
        discover = self.button("Discover", lambda *_: self.resume_discover(), ""); discover.navigation_page = active; self.discover_nav_buttons.append(discover)
        bus = self.button("Bus Times", lambda *_: self.set_mode("bus"), "")
        self.bus_nav_buttons.append(bus)
        home = self.button("Home", lambda *_: self.set_mode("home"), ""); self.home_nav_buttons.append(home)
        {"roon": now, "bus": bus, "home": home}.get(active, bus).add_css_class("active")
        for button in (now, discover, bus, home): button.set_hexpand(True); row.append(button)
        return row

    def build_boot_splash(self):
        page = Gtk.Box(); page.add_css_class("boot-splash"); page.set_hexpand(True); page.set_vexpand(True)
        paintable, width = wordmark_paintable(52)
        logo = Gtk.Picture.new_for_paintable(paintable); logo.add_css_class("boot-wordmark"); logo.set_size_request(width, 52); logo.set_can_shrink(True); logo.set_content_fit(Gtk.ContentFit.CONTAIN); logo.set_halign(Gtk.Align.CENTER); logo.set_valign(Gtk.Align.CENTER); page.append(logo)
        return page

    def build_bus(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); page.add_css_class("page"); page.add_css_class("bus-page")
        self.bus_clock = self.label("--:--", "clock", 1); self.stop = self.label("Connecting…", "stop"); self.stop_code = self.label("", "stop-code")
        self.stop.set_ellipsize(Pango.EllipsizeMode.END)
        stop_heading = Gtk.Box(spacing=14); stop_heading.set_baseline_position(Gtk.BaselinePosition.CENTER); self.stop.set_valign(Gtk.Align.BASELINE); self.stop_code.set_valign(Gtk.Align.BASELINE); stop_heading.append(self.stop); stop_heading.append(self.stop_code); page.append(self.header(stop_heading, self.bus_clock))
        self.services = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14); self.services.set_vexpand(True)
        self.bus_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); self.bus_content.append(self.services)
        self.bus_scroll = Gtk.ScrolledWindow(); self.bus_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.bus_scroll.set_kinetic_scrolling(True); self.bus_scroll.set_overlay_scrolling(True); self.bus_scroll.set_propagate_natural_height(False); self.bus_scroll.set_propagate_natural_width(False); self.bus_scroll.set_min_content_height(1); self.bus_scroll.set_size_request(-1, 1); self.bus_scroll.set_vexpand(True); self.bus_scroll.set_child(self.bus_content); page.append(self.bus_scroll)
        elastic_vertical_scroll(self.bus_scroll)
        footer = Gtk.Box(); footer.add_css_class("bus-footer"); self.bus_status = self.label("Starting", "muted"); self.updated = self.label("", "muted", 1); self.updated.set_hexpand(True); footer.append(self.bus_status); footer.append(self.updated); self.bus_content.append(footer)
        page.append(self.navigation("bus")); return page

    def build_roon(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); page.add_css_class("page"); page.add_css_class("roon-page"); self.roon_page = page
        self.zone = self.label("ROON NOW PLAYING", "eyebrow"); self.roon_clock = self.label("--:--", "clock", 1)
        header_overlay = Gtk.Overlay(); header_overlay.add_css_class("roon-header"); header_overlay.set_child(self.header(self.zone, self.roon_clock)); self.music_header_overlay = header_overlay
        subnav = Gtk.Box(spacing=12); subnav.add_css_class("roon-subnav"); subnav.set_halign(Gtk.Align.CENTER); subnav.set_valign(Gtk.Align.START); self.roon_subnav = subnav
        self.now_playing_tab = self.button("NOW PLAYING", self.show_roon_now, ""); self.now_playing_tab.add_css_class("active")
        self.queue_tab = self.button("QUEUE", lambda *_: self.set_roon_view("queue"), "")
        self.browser_tab = self.button("BROWSE", self.show_browser, ""); subnav.append(self.now_playing_tab); subnav.append(self.queue_tab); subnav.append(self.browser_tab)
        header_overlay.add_overlay(subnav); page.append(header_overlay)
        self.discover_subnav = Gtk.Box(spacing=8); self.discover_subnav.add_css_class("roon-subnav"); self.discover_subnav.set_halign(Gtk.Align.CENTER); self.discover_subnav.set_valign(Gtk.Align.START)
        self.discover_tabs = {}
        for section, title in (("recent", "RECENT"), ("browse", "BROWSE"), ("daily", "DAILY"), ("releases", "NEW RELEASES"), ("surprise", "SURPRISE ME")):
            button = self.button(title, lambda _button, value=section: self.open_discover(value), "")
            self.discover_tabs[section] = button; self.discover_subnav.append(button)
        header_overlay.add_overlay(self.discover_subnav); self.discover_subnav.set_visible(False); self.browser_tab.set_visible(False)
        self.portrait_music_tabs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.portrait_music_tabs.set_visible(False); page.append(self.portrait_music_tabs)
        self.discover_toolbar = Gtk.Box(spacing=12); self.discover_toolbar.add_css_class("discover-toolbar")
        self.discover_toolbar.set_margin_end(0); self.discover_toolbar.set_margin_bottom(14)
        settings = self.icon_button("emblem-system-symbolic", lambda *_: self.open_settings(), "discover-utility")
        settings.set_child(self.discover_utility_icon())
        settings.set_tooltip_text("Settings"); settings.set_valign(Gtk.Align.CENTER); self.discover_toolbar.append(settings)
        self.discover_toolbar_tabs = Gtk.Box(); self.discover_toolbar_tabs.set_hexpand(True)
        self.discover_toolbar_tabs.set_halign(Gtk.Align.CENTER)
        self.discover_toolbar.append(self.discover_toolbar_tabs)
        sleep = self.icon_button("preferences-system-time-symbolic", lambda *_: self.sleep(), "discover-utility discover-sleep")
        sleep.set_child(self.discover_utility_icon(clock=True))
        sleep.set_valign(Gtk.Align.CENTER)
        self.music_settings_button = settings; self.music_clock_button = sleep
        self.music_full_clock = self.label("--:--", "clock", 1)
        sleep.set_tooltip_text("Sleep"); self.discover_toolbar.append(sleep)
        self.discover_toolbar.set_visible(False); page.append(self.discover_toolbar)
        self.roon_views = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, transition_duration=0)
        # Hidden pages (especially the on-screen search keyboard) must not set
        # the minimum size of compact landscape views after navigation.
        self.roon_views.set_hhomogeneous(False); self.roon_views.set_vhomogeneous(False); self.roon_views.set_vexpand(True)
        self.roon_views.set_hhomogeneous(False); self.roon_views.set_vhomogeneous(False)
        self.discovery_list = ElasticVerticalTrack(spacing=18); self.discovery_list.set_vexpand(True)
        self.discovery_scroll = Gtk.ScrolledWindow(); self.discovery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.discovery_scroll.set_kinetic_scrolling(True); self.discovery_scroll.set_overlay_scrolling(True); self.discovery_scroll.set_propagate_natural_height(False); self.discovery_scroll.set_min_content_height(1); self.discovery_scroll.set_size_request(-1, 1); self.discovery_scroll.set_vexpand(True); self.discovery_scroll.set_hexpand(True); self.discovery_scroll.set_child(self.discovery_list)
        self.discovery_scroll.add_css_class("discovery-scroll")
        self.discovery_scroll.set_margin_bottom(10)
        self.discovery_list.connect_scroll(self.discovery_scroll)
        self.discovery_scroll.get_vadjustment().connect("value-changed", self.note_browse_scroll)
        self.discovery_scroll.get_vadjustment().connect("value-changed", self.discovery_scrolled)
        self.discovery_body = Gtk.Box(spacing=0); self.discovery_body.set_vexpand(True); self.discovery_body.set_hexpand(True)
        self.discovery_sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); self.discovery_sidebar.add_css_class("browser-sidebar"); self.discovery_sidebar.add_css_class("discovery-sidebar"); self.discovery_sidebar.set_vexpand(True)
        self.discovery_body.append(self.discovery_sidebar); self.discovery_body.append(self.discovery_scroll)
        self.roon_views.add_named(self.discovery_body, "discover")
        content = Gtk.Box(spacing=26); content.add_css_class("now-playing-content"); content.set_vexpand(True); content.set_margin_start(0); content.set_margin_end(8); content.set_margin_top(12); content.set_margin_bottom(8); self.now_playing_content = content
        self.artwork = Gtk.Picture(); self.artwork.add_css_class("artwork"); self.artwork.set_size_request(280, 280); self.artwork.set_halign(Gtk.Align.FILL); self.artwork.set_valign(Gtk.Align.FILL); self.artwork.set_can_shrink(True); self.artwork.set_content_fit(Gtk.ContentFit.COVER); self.set_browser_placeholder(self.artwork)
        self.artwork_viewport = Gtk.ScrolledWindow(); self.artwork_viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); self.artwork_viewport.set_propagate_natural_width(False); self.artwork_viewport.set_propagate_natural_height(False); self.artwork_viewport.set_child(self.artwork)
        artwork_button = Gtk.Button(); artwork_button.add_css_class("artwork-button"); artwork_button.set_halign(Gtk.Align.START); artwork_button.set_valign(Gtk.Align.CENTER); artwork_button.set_hexpand(False); artwork_button.set_child(self.artwork_viewport); artwork_button.connect("clicked", self.toggle_now_playing_details); content.append(artwork_button); self.artwork_button = artwork_button
        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); centre.set_valign(Gtk.Align.CENTER); centre.set_hexpand(True); self.now_playing_centre = centre
        self.title = self.label("Waiting for Roon…", "roon-title", .5); self.title.set_hexpand(True); self.title.set_halign(Gtk.Align.FILL); self.title.set_wrap(True); self.title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); self.title.set_lines(2); self.title.set_ellipsize(Pango.EllipsizeMode.END); self.title.set_justify(Gtk.Justification.CENTER)
        self.artist = self.label("Enable RoonDeck in Roon", "roon-artist", .5); self.artist.set_hexpand(True); self.artist.set_halign(Gtk.Align.FILL); self.artist.set_wrap(True); self.artist.set_justify(Gtk.Justification.CENTER); centre.append(self.title); centre.append(self.artist)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1); self.progress.add_css_class("progress"); self.progress.set_draw_value(False); self.progress.set_sensitive(False); self.progress.connect("value-changed", self.change_seek); centre.append(self.progress)
        times = Gtk.Box(); self.elapsed = self.label("0:00", "time"); self.remaining = self.label("−0:00", "time", 1); self.remaining.set_hexpand(True); times.append(self.elapsed); times.append(self.remaining); centre.append(times); self.roon_times = times
        self.controls = Gtk.Box(spacing=14); self.controls.set_halign(Gtk.Align.CENTER); self.controls.add_css_class("transport")
        self.controls.set_margin_top(6); self.controls.set_margin_bottom(16)
        self.library_add = self.button("", self.add_current_album); self.library_add.add_css_class("library-action"); self.library_add.set_tooltip_text("Add album to library"); self.library_add.set_visible(False)
        self.library_add.set_valign(Gtk.Align.CENTER); self.library_add.set_halign(Gtk.Align.CENTER); self.library_add.set_size_request(50, 50)
        self.library_pending = False; self.library_album_id = None; self.library_favorite = None
        self.library_status = "unknown"; self.set_library_icon(False)
        self.prev = self.icon_button("media-skip-backward-symbolic", lambda *_: self.control("previous")); self.play = self.icon_button("media-playback-start-symbolic", lambda *_: self.control("playpause"), "play"); self.play.get_child().set_pixel_size(42); self.next = self.icon_button("media-skip-forward-symbolic", lambda *_: self.control("next"))
        self.prev.set_size_request(50, 50); self.prev.set_valign(Gtk.Align.CENTER); self.play.set_size_request(68, 68); self.play.set_valign(Gtk.Align.CENTER); self.next.set_size_request(50, 50); self.next.set_valign(Gtk.Align.CENTER)
        self.controls.append(self.library_add); self.controls.append(self.prev); self.controls.append(self.play); self.controls.append(self.next); centre.append(self.controls)
        self.library_message = self.label("", "browser-message", .5); self.library_message.set_wrap(True); self.library_message.set_visible(False); centre.append(self.library_message)
        volume_row = Gtk.Box(spacing=10); volume_row.add_css_class("now-volume-row"); self.volume_row = volume_row; self.mute = self.button("MUTE", self.toggle_audio_mute, "utility"); self.mute.add_css_class("now-mute"); self.mute.set_size_request(62, 38); volume_row.append(self.mute)
        self.volume_down = self.icon_button("remove", lambda *_: self.step_volume(-1), "volume-step"); self.volume_down.set_tooltip_text("Volume down 1%"); volume_row.append(self.volume_down)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); self.volume.add_css_class("volume"); self.volume.set_hexpand(True); self.volume.set_draw_value(False); self.volume.connect("value-changed", self.change_volume); volume_row.append(self.volume)
        self.volume_up = self.icon_button("add", lambda *_: self.step_volume(1), "volume-step"); self.volume_up.set_tooltip_text("Volume up 1%"); volume_row.append(self.volume_up)
        self.volume_value = self.label("—", "time", 1); self.volume_value.add_css_class("volume-number"); volume_row.append(self.volume_value); centre.append(volume_row)
        content.append(centre)
        now_scroll = Gtk.ScrolledWindow(); now_scroll.add_css_class("now-playing-scroll"); now_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); now_scroll.set_kinetic_scrolling(True); now_scroll.set_overlay_scrolling(True); now_scroll.set_propagate_natural_height(False); now_scroll.set_min_content_height(1); now_scroll.set_size_request(-1, 1); now_scroll.set_vexpand(True); now_scroll.set_child(content); elastic_vertical_scroll(now_scroll); self.now_playing_scroll = now_scroll; self.roon_views.add_named(now_scroll, "now")
        source = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); source.add_css_class("source-view"); source.set_halign(Gtk.Align.CENTER); source.set_valign(Gtk.Align.CENTER); source.set_hexpand(True); source.set_vexpand(True)
        self.source_title = self.label("EXTERNAL INPUT", "source-title", .5); source.append(self.source_title)
        source_volume = Gtk.Box(spacing=28); source_volume.set_halign(Gtk.Align.CENTER); source_volume.set_valign(Gtk.Align.CENTER)
        source_down = self.icon_button("remove", lambda *_: self.step_bluos_volume(-1), "source-step"); self.source_down = source_down; source_down.set_tooltip_text("Volume down"); source_down.set_size_request(112, 112); source_down.set_halign(Gtk.Align.CENTER); source_down.set_valign(Gtk.Align.CENTER); source_volume.append(source_down)
        self.source_volume = self.label("—", "source-volume", .5); self.source_volume.set_size_request(230, -1); source_volume.append(self.source_volume)
        source_up = self.icon_button("add", lambda *_: self.step_bluos_volume(1), "source-step"); self.source_up = source_up; source_up.set_tooltip_text("Volume up"); source_up.set_size_request(112, 112); source_up.set_halign(Gtk.Align.CENTER); source_up.set_valign(Gtk.Align.CENTER); source_volume.append(source_up); source.append(source_volume)
        self.source_mute = self.button("MUTE", self.toggle_audio_mute, "source-mute"); self.source_mute.set_halign(Gtk.Align.CENTER); source.append(self.source_mute)
        source_scroll = Gtk.ScrolledWindow(); source_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); source_scroll.set_kinetic_scrolling(True); source_scroll.set_overlay_scrolling(True); source_scroll.set_propagate_natural_height(False); source_scroll.set_min_content_height(1); source_scroll.set_size_request(-1, 1); source_scroll.set_vexpand(True); source_scroll.set_child(source); elastic_vertical_scroll(source_scroll); self.source_scroll = source_scroll; self.roon_views.add_named(source_scroll, "source")
        self.queue_list = ElasticVerticalTrack(spacing=2); self.queue_list.add_css_class("queue-list")
        queue_scroll = Gtk.ScrolledWindow(); queue_scroll.add_css_class("queue-scroll"); queue_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); queue_scroll.set_kinetic_scrolling(True); queue_scroll.set_overlay_scrolling(True); queue_scroll.set_propagate_natural_height(False); queue_scroll.set_propagate_natural_width(False); queue_scroll.set_min_content_height(1); queue_scroll.set_size_request(-1, 1); queue_scroll.set_vexpand(True); queue_scroll.set_hexpand(True); queue_scroll.set_child(self.queue_list); self.queue_scroll = queue_scroll
        queue_scroll.get_vadjustment().connect("value-changed", self.load_visible_queue_artwork)
        self.queue_list.connect_scroll(queue_scroll)
        self.roon_views.add_named(queue_scroll, "queue")
        browser = Gtk.Overlay(); browser.add_css_class("browser-view"); browser.set_vexpand(True); browser.set_hexpand(True)
        browser_body = Gtk.Box(spacing=0); browser_body.set_vexpand(True); browser_body.set_hexpand(True); browser.set_child(browser_body); self.browser_body = browser_body
        self.browser_section_buttons = {}; sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); sidebar.add_css_class("browser-sidebar"); sidebar.add_css_class("library-sidebar")
        for section in ("albums", "artists", "genres", "playlists"):
            button = self.button(section.upper(), lambda _button, value=section: self.request_browser("section", section=value), "browser-filter"); button.get_child().set_xalign(0); self.browser_section_buttons[section] = button; sidebar.append(button)
        self.browser_search_button = self.button("SEARCH", self.show_browser_search, "browser-filter"); self.browser_search_button.get_child().set_xalign(0); sidebar.append(self.browser_search_button)
        # Surprise is a top-level Discover destination.  Keep no sixth rail
        # item that can leak back into album/artist navigation after reparenting.
        self.browser_surprise_button = self.button("SURPRISE!", lambda *_: self.request_browser("surprise"), "browser-filter"); self.browser_surprise_button.set_visible(False)
        self.browser_back = self.button("BACK", self.browser_back_action, "browser-back"); self.browser_back.set_visible(False); self.browser_back.set_halign(Gtk.Align.START); self.browser_back.set_valign(Gtk.Align.END)
        self.browser_sort_order = "title"
        self.browser_sort = self.button("Sort: Title, A to Z", self.show_browser_sort, "browser-filter browser-sort")
        self.browser_sort.set_visible(False)
        self.browser_sidebar = sidebar; browser_body.append(sidebar)
        self.browser_discovery_sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); self.browser_discovery_sidebar.add_css_class("browser-sidebar"); self.browser_discovery_sidebar.add_css_class("discovery-sidebar"); self.browser_discovery_sidebar.set_vexpand(True); self.browser_discovery_sidebar.set_visible(False); browser_body.append(self.browser_discovery_sidebar)
        browser_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); browser_main.add_css_class("browser-main"); browser_main.set_vexpand(True); browser_main.set_hexpand(True)
        sidebar.set_vexpand(True); spacer = Gtk.Box(); spacer.set_vexpand(True); self.browser_sidebar_spacer = spacer; sidebar.append(spacer); sidebar.append(self.browser_sort); sidebar.append(self.browser_back)
        self.browser_message = self.label("", "browser-message"); self.browser_message.set_ellipsize(Pango.EllipsizeMode.END); self.browser_message.set_visible(False); browser_main.append(self.browser_message)
        self.browser_list = ElasticVerticalTrack(spacing=2); self.browser_list.set_vexpand(True); self.browser_list.add_css_class("queue-list")
        browser_scroll = Gtk.ScrolledWindow(); browser_scroll.add_css_class("queue-scroll"); browser_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); browser_scroll.set_kinetic_scrolling(True); browser_scroll.set_overlay_scrolling(True); browser_scroll.set_propagate_natural_height(False); browser_scroll.set_propagate_natural_width(False); browser_scroll.set_min_content_height(1); browser_scroll.set_size_request(-1, 1); browser_scroll.set_vexpand(True); browser_scroll.set_hexpand(True); browser_scroll.set_child(self.browser_list); self.browser_scroll = browser_scroll
        browser_scroll.get_vadjustment().connect("value-changed", self.note_browse_scroll)
        browser_scroll.get_vadjustment().connect("value-changed", self.browser_scrolled)
        self.browser_list.connect_scroll(browser_scroll)
        browser_scroll.set_margin_bottom(10)
        previous_scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        previous_scroll.connect("scroll", self.browser_previous_scroll); browser_scroll.add_controller(previous_scroll)
        previous_drag = Gtk.GestureDrag.new(); previous_drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE); previous_drag.connect("drag-update", lambda _gesture, x, y: self.browser_previous_scroll(None, 0, -1) if y > 30 and y > abs(x) * 2 else None); previous_drag.connect("drag-end", self.browser_swipe_back); browser_scroll.add_controller(previous_drag)
        content = Gtk.Box(spacing=2); content.set_vexpand(True); content.set_hexpand(True); self.browser_content = content
        content.set_margin_top(16)
        self.browser_artist_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.browser_artist_panel.add_css_class("artist-profile"); self.browser_artist_panel.set_visible(False)
        self.browser_artist_inline_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.browser_artist_inline_panel.add_css_class("artist-profile"); self.browser_artist_inline_panel.set_visible(False)
        self.browser_artist_scroll = Gtk.ScrolledWindow(); self.browser_artist_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.browser_artist_scroll.set_propagate_natural_height(False); self.browser_artist_scroll.set_min_content_height(1); self.browser_artist_scroll.set_size_request(-1, 1); self.browser_artist_scroll.set_child(self.browser_artist_panel); self.browser_artist_scroll.set_visible(False); content.append(self.browser_artist_scroll); content.append(browser_scroll)
        # Independent result scrollers must not be nested in the ordinary
        # browser viewport: that viewport measures them at minimum height.
        self.browser_search_columns = Gtk.Box(spacing=18); self.browser_search_columns.set_homogeneous(True); self.browser_search_columns.set_hexpand(True); self.browser_search_columns.set_vexpand(True); self.browser_search_columns.set_visible(False); content.append(self.browser_search_columns)
        self.browser_scrubber = Gtk.DrawingArea(); self.browser_scrubber.add_css_class("browser-scrubber"); self.browser_scrubber.set_size_request(74, -1); self.browser_scrubber.set_margin_end(18); self.browser_scrubber.set_vexpand(True); self.browser_scrubber.set_visible(False); self.browser_scrubber.set_draw_func(self.draw_browser_scrubber)
        self.browser_scrub_scale = Gtk.Adjustment(value=0, lower=0, upper=25, step_increment=1); self.browser_scrub_scale.connect("value-changed", self.browser_scrub_changed)
        scrub_gesture = Gtk.GestureDrag.new(); scrub_gesture.connect("drag-begin", self.browser_scrub_begin); scrub_gesture.connect("drag-update", self.browser_scrub_drag); scrub_gesture.connect("drag-end", self.browser_scrub_end); self.browser_scrubber.add_controller(scrub_gesture)
        content.append(self.browser_scrubber); browser_main.append(content); browser_body.append(browser_main)
        self.roon_views.add_named(browser, "browse")
        search_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); search_panel.add_css_class("browser-search-panel"); self.browser_search_panel = search_panel
        search_nav = Gtk.Box(spacing=2); search_nav.add_css_class("browser-sidebar"); search_nav.add_css_class("library-sidebar"); self.search_nav = search_nav
        for section in ("albums", "artists", "genres", "playlists"):
            button = self.button(section.upper(), lambda _button, value=section: (self.set_roon_view("browse"), self.request_browser("section", section=value)), "browser-filter"); button.get_child().set_xalign(0); search_nav.append(button)
        search_active = self.button("SEARCH", lambda *_: None, "browser-filter"); search_active.add_css_class("active"); search_active.get_child().set_xalign(0); search_nav.append(search_active); search_panel.append(search_nav)
        search_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); search_main.add_css_class("search-main"); search_main.set_hexpand(True); search_main.set_vexpand(True); self.search_main = search_main
        self.search_results_scroll = Gtk.ScrolledWindow(); self.search_results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.search_results_scroll.set_vexpand(True); self.search_results_scroll.set_hexpand(True); self.search_results_scroll.set_propagate_natural_width(False); self.search_results_scroll.set_propagate_natural_height(False); self.search_results_scroll.set_min_content_height(1); self.search_results_scroll.set_visible(False); search_main.append(self.search_results_scroll)
        self.browser_search_timer = None
        elastic_vertical_scroll(self.browser_artist_scroll)
        self.search_results_scroll.get_vadjustment().connect("value-changed", lambda *_: self.load_visible_browser_artwork())
        self.browser_list.attach_touch_pull(self.search_results_scroll, vertical=True)
        search_header = Gtk.Box(spacing=12); self.browser_search_entry = Gtk.Entry(); self.browser_search_entry.add_css_class("browser-search-entry"); self.browser_search_entry.set_placeholder_text("Search Roon"); self.browser_search_entry.set_hexpand(True); self.browser_search_entry.connect("activate", self.submit_browser_search); search_header.append(self.browser_search_entry); search_header.append(self.button("CANCEL", lambda *_: self.set_roon_view("browse"), "browser-key")); search_main.append(search_header)
        for keys in ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM", "1234567890"):
            key_row = Gtk.Box(spacing=7); key_row.set_homogeneous(True)
            for key in keys: key_row.append(self.button(key, lambda _button, value=key: self.browser_keyboard_key(value), "browser-key"))
            search_main.append(key_row)
        keyboard_actions = Gtk.Box(spacing=10); keyboard_actions.set_homogeneous(True)
        for title, value in (("SPACE", " "), ("Backspace", "BACKSPACE"), ("CLEAR", "CLEAR")):
            callback = lambda _button, value=value: self.browser_keyboard_key(value)
            key = self.icon_button("erase", callback, "browser-key") if value == "BACKSPACE" else self.button(title, callback, "browser-key")
            key.set_tooltip_text(title); keyboard_actions.append(key)
        search_submit = self.button("SEARCH", self.submit_browser_search, "browser-key"); search_submit.add_css_class("browser-search-submit"); keyboard_actions.append(search_submit); search_main.append(keyboard_actions); search_panel.append(search_main); self.roon_views.add_named(search_panel, "search")
        detail_panel = Gtk.Box(spacing=24); detail_panel.add_css_class("detail-panel"); detail_panel.set_hexpand(True); detail_panel.set_vexpand(True); detail_panel.set_homogeneous(True); self.detail_panel = detail_panel
        self.browser_search_entry.connect("changed", self.schedule_browser_search)
        self.browser_search_entry.set_width_chars(1)
        artist_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); artist_card.add_css_class("detail-entity"); artist_card.add_css_class("detail-artist-card"); artist_card.set_hexpand(True); artist_card.set_valign(Gtk.Align.START); self.detail_artist_card = artist_card
        self.detail_artist_artwork = Gtk.Picture(); self.detail_artist_artwork.add_css_class("detail-artwork"); self.detail_artist_artwork.set_size_request(420, 420); self.detail_artist_artwork.set_content_fit(Gtk.ContentFit.COVER); self.detail_artist_artwork.set_can_shrink(True)
        self.detail_artist_artwork_frame = Gtk.ScrolledWindow(); self.detail_artist_artwork_frame.add_css_class("detail-artwork-frame"); self.detail_artist_artwork_frame.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); self.detail_artist_artwork_frame.set_halign(Gtk.Align.CENTER); self.detail_artist_artwork_frame.set_child(self.detail_artist_artwork); artist_card.append(self.detail_artist_artwork_frame)
        artist_card.append(self.label("ARTIST", "detail-section-label"))
        self.detail_artist_name = self.label("Unknown artist", "detail-title"); self.detail_artist_name.set_wrap(True); artist_card.append(self.detail_artist_name)
        self.detail_artist_writeup = self.label("", "detail-writeup"); self.detail_artist_writeup.set_wrap(True); artist_card.append(self.detail_artist_writeup)
        self.detail_artist_source = self.label("", "detail-source"); artist_card.append(self.detail_artist_source)
        self.detail_artist_facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); self.detail_artist_facts.add_css_class("detail-facts"); artist_card.append(self.detail_artist_facts)
        artist_rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); artist_rule.add_css_class("detail-rule"); artist_rule.set_visible(False); artist_card.append(artist_rule)
        self.detail_artist_action = self.button("BROWSE ARTIST", self.browse_detail_artist, "detail-action"); self.detail_artist_action.set_visible(False); artist_card.append(self.detail_artist_action); detail_panel.append(artist_card)
        album_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); album_card.add_css_class("detail-entity"); album_card.add_css_class("detail-album-card"); album_card.set_hexpand(True); album_card.set_valign(Gtk.Align.START); self.detail_album_card = album_card
        self.detail_album_artwork = Gtk.Picture(); self.detail_album_artwork.add_css_class("detail-artwork"); self.detail_album_artwork.set_size_request(420, 420); self.detail_album_artwork.set_content_fit(Gtk.ContentFit.COVER); self.detail_album_artwork.set_can_shrink(True)
        self.detail_album_artwork_frame = Gtk.ScrolledWindow(); self.detail_album_artwork_frame.add_css_class("detail-artwork-frame"); self.detail_album_artwork_frame.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); self.detail_album_artwork_frame.set_halign(Gtk.Align.CENTER); self.detail_album_artwork_frame.set_child(self.detail_album_artwork); album_card.append(self.detail_album_artwork_frame)
        for artwork_frame in (self.detail_artist_artwork_frame, self.detail_album_artwork_frame):
            close_artwork = Gtk.GestureClick(); close_artwork.connect("released", lambda *_: self.set_roon_view("now")); artwork_frame.add_controller(close_artwork)
        detail_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); detail_content.add_css_class("detail-album-content"); self.detail_album_content = detail_content
        self.detail_album_section_label = self.label("ALBUM", "detail-section-label"); detail_content.append(self.detail_album_section_label)
        self.detail_title = self.label("Nothing playing", "detail-title"); self.detail_title.set_wrap(True); self.detail_title.set_lines(2); self.detail_title.set_ellipsize(Pango.EllipsizeMode.END); detail_content.append(self.detail_title)
        self.detail_artist = self.label("", "detail-artist"); self.detail_artist.set_wrap(True); detail_content.append(self.detail_artist)
        self.detail_subtitle = self.label("", "detail-subtitle"); self.detail_subtitle.set_wrap(True); detail_content.append(self.detail_subtitle)
        self.detail_writeup = self.label("", "detail-writeup"); self.detail_writeup.set_wrap(True); detail_content.append(self.detail_writeup)
        self.detail_album_action = self.button("BROWSE ARTIST ALBUMS", self.browse_detail_artist, "detail-action"); self.detail_album_action.set_visible(False); self.detail_album_action.set_halign(Gtk.Align.START); detail_content.append(self.detail_album_action)
        self.detail_source = self.label("", "detail-source"); detail_content.append(self.detail_source)
        self.detail_facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); self.detail_facts.add_css_class("detail-facts"); detail_content.append(self.detail_facts)
        album_rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); album_rule.add_css_class("detail-rule"); album_rule.set_visible(False); detail_content.append(album_rule)
        self.detail_tracks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.detail_tracks.add_css_class("detail-tracks")
        detail_scroll = Gtk.ScrolledWindow(); detail_scroll.add_css_class("queue-scroll"); detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); detail_scroll.set_kinetic_scrolling(True); detail_scroll.set_overlay_scrolling(True); detail_scroll.set_propagate_natural_height(True); detail_scroll.set_max_content_height(210); detail_scroll.set_child(self.detail_tracks); detail_content.append(detail_scroll)
        elastic_vertical_scroll(detail_scroll)
        album_card.append(detail_content); detail_panel.append(album_card); page.append(self.roon_views); self.music_navigation = self.navigation("roon"); page.append(self.music_navigation)
        takeover = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); takeover.add_css_class("detail-takeover"); takeover.set_hexpand(True); takeover.set_vexpand(True); takeover.set_halign(Gtk.Align.FILL); takeover.set_valign(Gtk.Align.FILL)
        detail_header = Gtk.Box(spacing=12); detail_header.add_css_class("detail-header"); self.detail_header = detail_header
        self.detail_heading = self.label("Album & Artist", "detail-heading"); self.detail_heading.set_valign(Gtk.Align.CENTER); detail_header.append(self.detail_heading)
        spacer = Gtk.Box(); spacer.set_hexpand(True); detail_header.append(spacer)
        close = Gtk.Button(); close.add_css_class("detail-close"); close.set_size_request(72, 72); close.set_halign(Gtk.Align.CENTER); close.set_valign(Gtk.Align.CENTER)
        close_glyph = Gtk.CenterBox(); close_glyph.add_css_class("detail-close-glyph"); close_glyph.set_size_request(48, 48); close_glyph.set_halign(Gtk.Align.CENTER); close_glyph.set_valign(Gtk.Align.CENTER); close_icon = FamilyIcon("close", 34, stroke_width=3); close_glyph.set_center_widget(close_icon); close.set_child(close_glyph); self.detail_close_glyph = close_glyph; self.detail_close_icon = close_icon
        close.connect("clicked", lambda *_: self.set_roon_view("now")); close.set_tooltip_text("Close album and artist information"); close.update_property([Gtk.AccessibleProperty.LABEL], ["Close album and artist information"]); self.detail_close = close; detail_header.append(close); takeover.append(detail_header)
        detail_sheet = Gtk.ScrolledWindow(); self.detail_sheet = detail_sheet; detail_sheet.add_css_class("detail-sheet-scroll"); detail_sheet.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); detail_sheet.set_kinetic_scrolling(True); detail_sheet.set_overlay_scrolling(True); detail_sheet.set_propagate_natural_height(False); detail_sheet.set_min_content_height(1); detail_sheet.set_size_request(-1, 1); detail_sheet.set_vexpand(True); detail_sheet.set_child(detail_panel); elastic_vertical_scroll(detail_sheet); takeover.append(detail_sheet)
        detail_footer = Gtk.Box(); detail_footer.add_css_class("detail-footer"); self.detail_footer = detail_footer; self.detail_browse_action = self.button("BROWSE ARTIST ALBUMS", self.browse_detail_artist, "detail-action detail-primary-action"); self.detail_browse_action.set_hexpand(True); self.detail_browse_action.get_child().set_width_chars(1); self.detail_browse_action.get_child().set_ellipsize(Pango.EllipsizeMode.END); detail_footer.append(self.detail_browse_action); takeover.append(detail_footer); takeover.set_visible(False); self.detail_takeover = takeover
        root = Gtk.Overlay(); root.set_child(page); root.add_overlay(takeover); return root

    def build_home(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); page.add_css_class("page"); page.add_css_class("home-page")
        self.home_title = self.label("Home Controls", "page-title"); self.home_clock = self.label("--:--", "clock", 1); page.append(self.header(self.home_title, self.home_clock))
        self.home_status = self.label("Connecting to Home Assistant…", "muted", .5); page.append(self.home_status)
        self.home_grid = Gtk.Grid(column_spacing=18, row_spacing=18); self.home_grid.add_css_class("home-grid"); self.home_grid.set_column_homogeneous(True); self.home_grid.set_row_homogeneous(True); self.home_grid.set_vexpand(True)
        self.home_scroll = Gtk.ScrolledWindow(); self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.home_scroll.set_propagate_natural_height(False); self.home_scroll.set_min_content_height(1); self.home_scroll.set_vexpand(True); self.home_scroll.set_child(self.home_grid); page.append(self.home_scroll)
        elastic_vertical_scroll(self.home_scroll)
        page.append(self.navigation("home")); return page

    def configure_settings_layout(self, width, height):
        portrait = height > width
        compact = not portrait and (height <= 600 or width < 1000)
        original = not portrait and width <= 820 and height <= 500
        self.resize_settings_wordmark(width, height)
        self.settings_controls.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.settings_daily.set_size_request(-1 if portrait else round((width - 56) * .343), -1)
        self.settings_daily.set_hexpand(portrait)
        self.settings_controls.set_spacing(20 if portrait else 18 if compact else round(width * .052))
        if hasattr(self, "settings_appearance"):
            self.settings_appearance.set_spacing(8 if original else 12)
            self.settings_daily.set_spacing(10 if original else 16)
            self.settings_display_column.set_spacing(10 if original else 16)
        # Keep the identity and utilities on one deliberate header line. The
        # portrait display has ample width; stacking the controls created the
        # large dead band seen on the physical 10-inch panel.
        self.settings_header.set_orientation(Gtk.Orientation.HORIZONTAL)
        if hasattr(self, "touch_bus_pair"):
            self.touch_bus_pair.set_orientation(Gtk.Orientation.VERTICAL if width < 1000 else Gtk.Orientation.HORIZONTAL)
            self.touch_bus_heading.set_visible(portrait or width > 1280)
        seven_inch = original or (not portrait and 1000 <= width < 1500 and height <= 850)
        (self.window.add_css_class if seven_inch else self.window.remove_css_class)("seven-inch-settings")
        # Profile, mounting and orientation are installation controls. On the
        # two seven-inch panels they consume most of the daily Settings view,
        # despite normally being used only once during setup.
        for control in (self.touch_profile, self.touch_orientation, self.touch_mounting, self.apply_display_button):
            control.set_visible(not seven_inch)

    def resize_settings_wordmark(self, width, height):
        """Match the wordmark to the adjacent Settings title at every profile."""
        if height > width:
            target_height = 34 if width >= 900 else 28
        elif max(width, height) >= 1600:
            target_height = 44
        elif width >= 1200 and width > height:
            target_height = 43
        else:
            target_height = 26 if width < 1000 else 32
        accent = "#9868F9" if self.settings_data.get("display_theme") == "roon" else "#6ED9AE"
        paintable, target_width = wordmark_paintable_tinted(target_height, accent)
        self.settings_wordmark.set_paintable(paintable)
        self.settings_wordmark.set_size_request(target_width, target_height)
        self.settings_wordmark_frame.set_size_request(target_width, target_height)
        # The supplied wordmark is drawn to its baseline at the bottom of the
        # SVG. Lift that edge by the adjacent title font's descent so its
        # visible baseline matches GTK labels rather than their bounding box.
        baseline_lift = 10 if max(width, height) >= 1600 or (width >= 1200 and width > height) else 7 if height > width else 6 if width < 1000 else 8
        self.settings_wordmark_frame.set_margin_bottom(baseline_lift)
        if hasattr(self, "touch_diagnostics"):
            diagnostics_gap = 5 if max(width, height) >= 1600 else 2
            self.touch_diagnostics.set_margin_top(diagnostics_gap)

    def build_settings(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); page.add_css_class("page"); page.add_css_class("settings-page")
        top = Gtk.Box(spacing=20); top.add_css_class("settings-header"); self.settings_header = top
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); heading.set_hexpand(True)
        title_row = Gtk.Box(spacing=8); title_row.set_valign(Gtk.Align.START); title_row.set_baseline_position(Gtk.BaselinePosition.CENTER); self.settings_title_row = title_row
        wordmark = Gtk.Picture(); wordmark.add_css_class("settings-wordmark"); wordmark.set_can_shrink(True); wordmark.set_content_fit(Gtk.ContentFit.CONTAIN); wordmark.set_hexpand(False); wordmark.set_halign(Gtk.Align.START); wordmark.set_valign(Gtk.Align.END); self.settings_wordmark = wordmark
        wordmark_frame = Gtk.Box(); wordmark_frame.set_hexpand(False); wordmark_frame.set_halign(Gtk.Align.START); wordmark_frame.set_valign(Gtk.Align.END); wordmark_frame.append(wordmark); self.settings_wordmark_frame = wordmark_frame; title_row.append(wordmark_frame); self.resize_settings_wordmark(800, 480)
        settings_title = self.label("Settings", "settings-title"); settings_title.set_valign(Gtk.Align.BASELINE); self.settings_title_label = settings_title; title_row.append(settings_title)
        self.device_status = self.label("", "settings-version"); self.device_status.set_valign(Gtk.Align.BASELINE); self.device_status.set_max_width_chars(32); self.device_status.set_ellipsize(Pango.EllipsizeMode.END); title_row.append(self.device_status); heading.append(title_row)
        self.touch_diagnostics = self.label("Loading diagnostics…", "settings-diagnostic"); self.touch_diagnostics.set_wrap(True); self.touch_diagnostics.set_margin_top(2); heading.append(self.touch_diagnostics); top.append(heading)
        utilities = Gtk.Box(spacing=12); utilities.add_css_class("settings-utilities"); utilities.set_valign(Gtk.Align.START)
        sleep_button = self.button("SLEEP", self.sleep, "settings-sleep"); utilities.append(sleep_button)
        close = Gtk.Button(); close.add_css_class("settings-close"); close.set_size_request(58, 58); close.set_hexpand(False); close.set_vexpand(False); close.set_halign(Gtk.Align.CENTER); close.set_valign(Gtk.Align.CENTER); close.set_tooltip_text("Close settings"); close.set_child(FamilyIcon("close", 32, stroke_width=3)); close.connect("clicked", self.close_settings); utilities.append(close)
        top.append(utilities); page.append(top)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); separator.add_css_class("settings-divider"); self.settings_divider = separator; page.append(separator)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14); card.add_css_class("settings-card"); card.set_vexpand(True)
        self.settings_row_sizes = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.VERTICAL)
        appearance = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); appearance.add_css_class("settings-appearance"); self.settings_appearance = appearance; appearance.append(self.label("DISPLAY THEME", "eyebrow"))
        self.touch_theme_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.touch_theme_buttons = {}
        theme_choices = Gtk.Box(spacing=16); theme_choices.set_homogeneous(True); self.touch_theme_row.append(theme_choices)
        for value, title in (("fresh-mint", "Mint"), ("roon", "Roon")):
            button = self.button(title, lambda _button, theme=value: self.change_theme(theme), "theme-choice")
            button.set_hexpand(True); button.add_css_class("settings-theme-choice"); self.touch_theme_buttons[value] = button; theme_choices.append(button)
        appearance.append(self.touch_theme_row)
        appearance.append(self.label("DISPLAY BACKGROUND", "eyebrow"))
        self.touch_background_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.touch_background_buttons = {}
        background_choices = Gtk.Box(spacing=16); background_choices.set_homogeneous(True); self.touch_background_row.append(background_choices)
        for value, title in (("current", "Gradient"), ("black", "Black")):
            choice = self.button(title, lambda _button, selected=value: self.change_background(selected), "theme-choice"); choice.add_css_class("settings-theme-choice"); choice.set_hexpand(True); self.touch_background_buttons[value] = choice; background_choices.append(choice)
        appearance.append(self.touch_background_row)
        controls = Gtk.Box(spacing=28); controls.add_css_class("settings-controls"); controls.set_vexpand(True); controls.set_valign(Gtk.Align.START); self.settings_controls = controls
        daily = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); daily.add_css_class("settings-column"); daily.set_size_request(400, -1); daily.append(self.label("NETWORK CONTROLS", "eyebrow")); self.touch_daily = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); daily.append(self.touch_daily)
        self.touch_bus_heading = self.label("BUS TIMES", "eyebrow"); daily.append(self.touch_bus_heading); bus_pair = Gtk.Box(spacing=12); self.touch_bus_pair = bus_pair; bus_visibility = Gtk.Box(spacing=8); bus_visibility.add_css_class("setting-line"); self.touch_bus_enabled = Gtk.CheckButton(label="Bus Times"); self.touch_bus_enabled.set_active(True); self.touch_bus_enabled.connect("toggled", self.toggle_bus_visibility); bus_visibility.append(self.touch_bus_enabled); bus_pair.append(bus_visibility); self.touch_bus_services = Gtk.Box(spacing=8); self.touch_bus_services.add_css_class("setting-line"); self.touch_bus_services.set_hexpand(True); bus_pair.append(self.touch_bus_services); daily.append(bus_pair); self.touch_bus_visibility_row = bus_visibility
        daily.append(self.label("INTERFACE SCALING", "eyebrow"))
        self.touch_interface_size = Gtk.DropDown.new_from_strings(["Smaller", "Standard", "Larger"]); self.touch_interface_size.add_css_class("settings-select"); self.touch_interface_size.connect("notify::selected", self.change_interface_size); daily.append(self.touch_interface_size)
        self.settings_daily = daily; controls.append(daily)
        display_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); display_column.add_css_class("settings-column"); self.settings_display_column = display_column; display_column.set_hexpand(True)
        display_column.append(appearance)
        self.display_settings_heading = self.label("DISPLAY SETTINGS", "eyebrow"); display_column.append(self.display_settings_heading)
        self.touch_profile = Gtk.DropDown.new_from_strings(["Profile · Original 800×480", "Profile · Touch 2 5-inch", "Profile · Touch 2 7-inch", "Profile · Touch 2 10-inch"]); self.touch_profile.add_css_class("settings-select"); self.touch_profile.add_css_class("touch-profile-select"); display_column.append(self.touch_profile)
        self.touch_orientation = Gtk.DropDown.new_from_strings(["Orientation · Landscape", "Orientation · Portrait"]); self.touch_orientation.add_css_class("settings-select"); display_column.append(self.touch_orientation); controls.append(display_column)
        scroll = Gtk.ScrolledWindow(); self.settings_scroll = scroll; scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_vexpand(True); scroll.set_child(controls); card.append(scroll)
        self.touch_mounting = Gtk.DropDown.new_from_strings(["Rotation · Standard", "Rotation · 180°"]); self.touch_mounting.add_css_class("settings-select"); display_column.append(self.touch_mounting)
        elastic_vertical_scroll(scroll)
        brightness_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); brightness_row.add_css_class("brightness-setting"); brightness_row.set_margin_top(8); brightness_row.append(self.label("DISPLAY BRIGHTNESS", "eyebrow")); brightness_control = Gtk.Box(spacing=12); brightness_control.add_css_class("brightness-control"); self.touch_brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 1); self.touch_brightness.set_draw_value(False); self.touch_brightness.set_hexpand(True); self.touch_brightness_value = self.label("100%", "brightness-value", 1); self.touch_brightness.connect("value-changed", self.change_brightness); brightness_control.append(self.touch_brightness); brightness_control.append(self.touch_brightness_value); brightness_row.append(brightness_control); display_column.append(brightness_row)
        # Appearance first, then the everyday brightness control, followed by
        # the rarely-used installation fields as one clearly labelled group.
        display_column.reorder_child_after(brightness_row, appearance)
        display_column.reorder_child_after(self.display_settings_heading, brightness_row)
        display_column.reorder_child_after(self.touch_profile, self.display_settings_heading)
        display_column.reorder_child_after(self.touch_orientation, self.touch_profile)
        display_column.reorder_child_after(self.touch_mounting, self.touch_orientation)
        for row in (self.touch_profile, self.touch_orientation, self.touch_mounting, self.touch_bus_visibility_row): self.settings_row_sizes.add_widget(row)
        action_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); action_stack.add_css_class("settings-action-stack"); action_stack.set_valign(Gtk.Align.END)
        actions = Gtk.Box(spacing=18); actions.add_css_class("settings-primary-actions"); actions.set_homogeneous(True); self.settings_actions = actions; self.apply_display_button = self.button("APPLY DISPLAY", self.request_display_settings, "settings-action"); self.apply_display_button.set_hexpand(True); self.update_button = self.button("INSTALL UPDATE", self.request_update, "settings-action"); self.update_button.set_hexpand(True); actions.append(self.update_button); actions.append(self.apply_display_button); action_stack.append(actions)
        reboot = self.button("REBOOT", self.confirm_reboot, "settings-action"); reboot.add_css_class("reboot-action"); reboot.set_hexpand(True); action_stack.append(reboot); card.append(action_stack); page.append(card)
        return page

    def build_sleep(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); box.add_css_class("sleep"); box.set_halign(Gtk.Align.FILL); box.set_valign(Gtk.Align.FILL); box.set_hexpand(True); box.set_vexpand(True)
        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); centre.set_halign(Gtk.Align.CENTER); centre.set_valign(Gtk.Align.CENTER); centre.set_hexpand(True); centre.set_vexpand(True)
        self.sleep_clock = self.label("--:--", "sleep-clock", .5); centre.append(self.sleep_clock); self.sleep_hint = self.label("TAP ANYWHERE TO WAKE", "eyebrow", .5); centre.append(self.sleep_hint); box.append(centre)
        wake_gesture = Gtk.GestureClick(); wake_gesture.set_button(0); wake_gesture.connect("pressed", self.sleep_gesture_pressed); box.add_controller(wake_gesture)
        return box

    def apply_theme(self, theme):
        theme = "roon" if theme == "roon" else "fresh-mint"
        self.settings_data["display_theme"] = theme
        if theme == "roon": self.window.add_css_class("theme-roon")
        else: self.window.remove_css_class("theme-roon")
        if hasattr(self, "settings_wordmark"):
            self.resize_settings_wordmark(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480))
        self.theme_updating = True
        for value, button in self.touch_theme_buttons.items():
            if value == theme: button.add_css_class("active")
            else: button.remove_css_class("active")
        self.theme_updating = False
        if hasattr(self, "library_add"): self.set_library_icon(getattr(self, "library_favorite", None) is True)
        self.browser_scrubber.queue_draw()
        for pictures in self.discovery_pictures.values():
            for picture in pictures: picture.queue_draw()

    def apply_home_colors(self, config):
        defaults = {"light": "#f4c95d", "fan": "#5bcbd6", "switch": "#6ed9ae", "scene": "#6ed9ae"}
        def colour(domain):
            key = "home_assistant_single_color" if config.get("home_assistant_color_mode") == "single" else f"home_assistant_{domain}_color"
            value = str(config.get(key, defaults[domain]))
            return value if len(value) == 7 and value.startswith("#") and all(character in "0123456789abcdefABCDEF" for character in value[1:]) else defaults[domain]
        def blend(foreground, background, amount):
            front = tuple(int(foreground[index:index + 2], 16) for index in (1, 3, 5)); back = tuple(int(background[index:index + 2], 16) for index in (1, 3, 5))
            return "#" + "".join(f"{round(base + (accent - base) * amount):02x}" for accent, base in zip(front, back))
        rules = []
        for domain in defaults:
            accent = colour(domain); idle = blend(accent, "#232228", .18); active = blend(accent, "#232228", .34); border = blend(accent, "#44414c", .58)
            rules.append(f".home-tile.home-domain-{domain} {{ background: {idle}; border-color: {border}; }}")
            rules.append(f".home-tile.home-domain-{domain}.on {{ background: {active}; border-color: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain} .home-icon, .home-tile.home-domain-{domain}.on .home-device-button {{ color: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain} .home-level highlight {{ background: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain}.activated {{ background: {active}; border-color: {accent}; box-shadow: 0 0 18px {accent}; }}")
        self.home_color_provider.load_from_data("\n".join(rules))

    def change_theme(self, selected):
        if getattr(self, "theme_updating", False): return
        if selected == self.settings_data.get("display_theme"): return
        self.touch_theme_row.set_sensitive(False)
        def save():
            result = post_json(f"{BUS}/api/admin/config", {"section": "appearance", "display_theme": selected}, timeout=3)
            GLib.idle_add(finish, result)
        def finish(result):
            self.touch_theme_row.set_sensitive(True)
            if result and not result.get("error"):
                self.apply_theme(selected); self.last_config_fetch = 0
            else:
                self.apply_theme(self.settings_data.get("display_theme")); self.device_status.set_text("Could not save theme. Please try again.")
            return False
        threading.Thread(target=save, daemon=True).start()

    def sleep_gesture_pressed(self, _gesture, _count, _x, _y):
        if time.monotonic() - self.sleep_entered_at >= .45: self.wake("sleep gesture")

    def touchscreen_devices(self):
        devices = []
        for event_path in sorted(Path("/sys/class/input").glob("event*")):
            try: name = (event_path / "device/name").read_text(encoding="utf-8").strip().lower()
            except OSError: continue
            if any(token in name for token in ("touchscreen", "touch display", "raspberrypi-ts", "dsi touch", "ft5406", "edt-ft", "goodix")):
                device = Path("/dev/input") / event_path.name
                if device.exists(): devices.append((device, name))
        return devices

    def touchscreen_wake_worker(self):
        event_struct = struct.Struct("llHHI")
        while True:
            handles = []
            try:
                for device, name in self.touchscreen_devices():
                    try:
                        handle = os.open(device, os.O_RDONLY | os.O_NONBLOCK); handles.append((handle, name))
                    except OSError: continue
                if not handles:
                    time.sleep(5); continue
                print("RoonDeck low-level wake listening on " + ", ".join(name for _, name in handles), flush=True)
                while True:
                    readable, _, _ = select.select([handle for handle, _ in handles], [], [], 30)
                    for handle in readable:
                        try: packet = os.read(handle, event_struct.size * 32)
                        except OSError: continue
                        for offset in range(0, len(packet) - event_struct.size + 1, event_struct.size):
                            _sec, _usec, event_type, code, value = event_struct.unpack_from(packet, offset)
                            # Goodix panels can announce a new contact as
                            # BTN_TOUCH or as an MT tracking id. Accept either
                            # real contact start, but ignore coordinate motion.
                            button_touch = event_type == 1 and code == 330 and value == 1
                            tracking_start = event_type == 3 and code == 57 and value != 0xFFFFFFFF
                            if button_touch or tracking_start:
                                event_at = _sec + (_usec / 1_000_000)
                                now = time.monotonic()
                                # input_event normally uses CLOCK_MONOTONIC. If
                                # a driver reports wall time instead, use the
                                # observation time rather than comparing unlike
                                # clocks.
                                contact_at = event_at if abs(event_at - now) < 3600 else now
                                GLib.idle_add(self.low_level_touch_wake, contact_at)
            finally:
                for handle, _name in handles:
                    try: os.close(handle)
                    except OSError: pass
            time.sleep(1)

    def low_level_touch_wake(self, contact_at=None):
        # Raw contact starts are the most reliable activity signal on DSI
        # panels: GTK may turn a drag into scrolling without emitting a button
        # press. Record every contact so inactivity is measured from the last
        # touch, not from the time the panel originally woke.
        self.last_interaction = max(self.last_interaction, contact_at or time.monotonic())
        if (hasattr(self, "stack") and self.stack.get_visible_child_name() == "roon"
                and (self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
                     or (hasattr(self, "detail_takeover") and self.detail_takeover.get_visible()))):
            self.browse_last_interaction = self.last_interaction
        # The low-level event from the gesture which pressed Sleep may reach
        # GTK after the screen has already gone dark. It is not a wake gesture.
        # Compare when contact actually began, not when this idle callback ran.
        if contact_at is not None and contact_at <= self.sleep_entered_at:
            return False
        if self.inactivity_sleeping or (self.stack.get_visible_child_name() == "sleep" and time.monotonic() - self.sleep_entered_at >= .45): self.wake("Linux touchscreen event")
        return False

    def tick(self):
        current = datetime.now(TZ)
        now = current.strftime("%H:%M") if current.year >= 2024 else "--:--"
        self.bus_clock.set_text(now); self.roon_clock.set_text(now); self.home_clock.set_text(now); self.sleep_clock.set_text(now)
        if hasattr(self, "music_full_clock"): self.music_full_clock.set_text(now)
        if now != getattr(self, "last_clock_time", None):
            self.last_clock_time = now
            if icon := getattr(self, "music_clock_icon", None): icon.queue_draw()
        browse_timeout = int(getattr(self, "settings_data", {}).get("browse_idle_return_seconds", 60))
        if (browse_timeout > 0 and hasattr(self, "stack") and self.stack.get_visible_child_name() == "roon"
                and (self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
                     or (hasattr(self, "detail_takeover") and self.detail_takeover.get_visible()))
                and time.monotonic() - self.browse_last_interaction >= browse_timeout):
            self.show_roon_now()
        return True

    def log_renderer(self):
        renderer = self.window.get_renderer()
        print(f"RoonDeck GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()} renderer={type(renderer).__name__}", flush=True)
        return False

    def start_poll(self):
        if not self.polling:
            self.polling = True; threading.Thread(target=self.poll, daemon=True).start()
        return True

    def load_detail_artist_profile_async(self, name):
        if not name or self.detail_artist_profile_loading == name:
            return
        self.detail_artist_profile_loading = name
        self.detail_artist_profile_fetched_at = time.monotonic()
        def load():
            profile = get_json(f"{ROON}/api/artist?name={quote(name, safe='')}") or {}
            def apply_profile():
                if self.detail_artist_profile_name == name:
                    self.detail_artist_profile = profile
                    self.detail_signature = None
                if self.detail_artist_profile_loading == name:
                    self.detail_artist_profile_loading = None
                return False
            GLib.idle_add(apply_profile)
        threading.Thread(target=load, daemon=True).start()

    def poll(self):
        started = time.monotonic()
        target_response = get_json(BUS + "/api/display-target"); status = get_json(BUS + "/api/status"); roon = get_json(ROON + "/api/state"); device = get_json(BUS + "/api/device/controls") or {}
        capture_id = device.get("capture_request")
        view_request = device.get("display_view_request") or {}
        view_id = view_request.get("id")
        if view_id and view_id != self.last_display_view_id:
            self.last_display_view_id = view_id
            GLib.idle_add(self.apply_display_view_request, dict(view_request))
        now = time.monotonic(); config = None; system = None
        if not self.settings_data or now - self.last_config_fetch >= 60:
            fetched_config = get_json(BUS + "/api/admin/config")
            if isinstance(fetched_config, dict) and fetched_config:
                config = fetched_config; self.last_config_fetch = now
            else:
                # The API and display start independently at boot. Never apply
                # defaults because one early request lost that race; keep the
                # last good settings and retry on the next two-second poll.
                self.last_config_fetch = 0
        if self.settings_open and (not self.system_data or self.update_in_progress or now - self.last_system_fetch >= 15):
            system = get_json(BUS + "/api/admin/system?diagnostics=1") or {}; self.last_system_fetch = now
        zone = (roon or {}).get("zone") or {}; key = (zone.get("now_playing") or {}).get("image_key")
        details = (roon or {}).get("details") or {}; album_detail_key = details.get("album_image_key") or details.get("image_key"); artist_detail_key = details.get("artist_image_key")
        detail_artist = details.get("artist") or ""
        profile_missing = not (self.detail_artist_profile.get("full_writeup") or self.detail_artist_profile.get("writeup"))
        if detail_artist and (detail_artist != self.detail_artist_profile_name or (profile_missing and now - self.detail_artist_profile_fetched_at >= 15)):
            if detail_artist != self.detail_artist_profile_name:
                self.detail_artist_profile_name = detail_artist
                self.detail_artist_profile = {}
                self.detail_signature = None
            self.load_detail_artist_profile_async(detail_artist)
        target = target_response.get("target") if isinstance(target_response, dict) else None
        GLib.idle_add(self.apply, target, status, roon, config, system, device, key, None)
        if capture_id and capture_id != getattr(self, "last_capture_id", None):
            self.last_capture_id = capture_id
            # Apply the latest navigation/state first, then allow GTK and the
            # panel a frame to settle. Capturing before apply() races wake and
            # can snapshot the intentionally black sleep surface.
            GLib.timeout_add(350, self.capture_display, capture_id, 0)
        self.polling = False
        image = get_bytes(f"{ROON}/api/image?key={quote(key, safe='')}") if key and key != self.image_key else None
        if image:
            GLib.idle_add(self.apply_artwork, key, image)
        album_detail_image = get_bytes(f"{ROON}/api/image?key={quote(album_detail_key, safe='')}&size=600") if album_detail_key and album_detail_key != self.detail_album_image_key else None
        if album_detail_image: GLib.idle_add(self.apply_detail_artwork, "album", album_detail_key, album_detail_image)
        artist_detail_image = get_bytes(f"{ROON}/api/image?key={quote(artist_detail_key, safe='')}&size=600") if artist_detail_key and artist_detail_key != self.detail_artist_image_key else None
        if artist_detail_image: GLib.idle_add(self.apply_detail_artwork, "artist", artist_detail_key, artist_detail_image)
        elapsed = time.monotonic() - started; self.refresh_count += 1
        if self.refresh_count <= 5 and elapsed > .25:
            print(f"RoonDeck core refresh completed in {elapsed:.3f}s", flush=True)

    def capture_display(self, capture_id, retry=0):
        data = {"id": capture_id}
        try:
            # Snapshot the actual live GTK tree.  This captures precisely what
            # RoonDeck rendered (including fetched artwork) and remains reliable
            # when Cage/wlroots uses direct scan-out, where grim can otherwise
            # return an all-black but syntactically valid PNG.
            stack = getattr(self, "stack", None)
            visible_page = stack.get_visible_child_name() if stack is not None else None
            if retry == 0 and (getattr(self, "inactivity_sleeping", False) or visible_page == "sleep"):
                self.wake("screen preview")
                GLib.timeout_add(700, self.capture_display, capture_id, retry + 1)
                return False
            if hasattr(self, "set_screen_power"):
                self.set_screen_power(True)
            self.window.queue_draw()
            width, height = self.window.get_width(), self.window.get_height()
            if width <= 0 or height <= 0:
                raise ValueError("Display has no drawable size")
            # Snapshot the visible client page, not the native window surface.
            # A fullscreen Wayland window can expose only its black backing
            # surface to WidgetPaintable while the child contains the live UI.
            target = self.window.get_child()
            if target is None:
                raise ValueError("Display has no visible page")
            def visible_png(texture):
                pixels = Gdk.pixbuf_get_from_texture(texture)
                if pixels is None:
                    raise ValueError("Screenshot pixels are unavailable")
                raw = pixels.get_pixels()
                channels, stride = pixels.get_n_channels(), pixels.get_rowstride()
                visible = any(raw[y * stride + x * channels + c] > 8
                              and (channels != 4 or raw[y * stride + x * channels + 3] > 8)
                              for y in range(0, pixels.get_height(), 8)
                              for x in range(0, pixels.get_width(), 8)
                              for c in range(3))
                if not visible:
                    raise ValueError("Display capture contains no visible content")
                return bytes(texture.save_to_png_bytes().get_data())

            def render_snapshot(snapshot):
                node = snapshot.to_node()
                if node is None:
                    raise ValueError("Display produced no render node")
                errors = []
                # Render into independent memory first. Asking the active
                # fullscreen KMS/Wayland renderer to read its own scan-out
                # buffer can stall or return no pixels on Raspberry Pi.
                try:
                    bounds = node.get_bounds()
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                    context = cairo.Context(surface)
                    context.translate(-bounds.get_x(), -bounds.get_y())
                    node.draw(context)
                    surface.flush()
                    raw = surface.get_data()
                    if not any(raw[index] > 8 or raw[index + 1] > 8 or raw[index + 2] > 8
                               for index in range(0, len(raw) - 3, 128)):
                        raise ValueError("software render contains no visible content")
                    output = io.BytesIO()
                    surface.write_to_png(output)
                    image = output.getvalue()
                    if image.startswith(b"\x89PNG\r\n\x1a\n"):
                        return image
                    raise ValueError("software renderer returned an invalid image")
                except (cairo.Error, AttributeError, RuntimeError, TypeError, ValueError) as error:
                    errors.append(f"software renderer: {error}")
                live = self.window.get_renderer()
                if live is not None:
                    try:
                        return visible_png(live.render_texture(node, None))
                    except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                        errors.append(f"live renderer: {error}")
                # Some KMS/Wayland drivers display the live node correctly but
                # cannot read it back through the active renderer.  The Cairo
                # renderer is slower, but it is a reliable capture-only path.
                cairo_renderer = Gsk.CairoRenderer.new()
                try:
                    if not cairo_renderer.realize_for_display(self.window.get_display()):
                        raise RuntimeError("Cairo renderer could not be initialized")
                    return visible_png(cairo_renderer.render_texture(node, None))
                except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                    errors.append(f"Cairo renderer: {error}")
                finally:
                    if cairo_renderer.is_realized(): cairo_renderer.unrealize()
                raise ValueError("; ".join(errors))

            def add_popovers(snapshot):
                for popup in (getattr(self, "browser_action_popover", None), getattr(self, "browser_sort_popover", None)):
                    if popup is not None and popup.get_mapped():
                        valid, bounds = popup.compute_bounds(target)
                        if valid:
                            snapshot.save()
                            point = Graphene.Point(); point.init(bounds.get_x(), bounds.get_y())
                            snapshot.translate(point)
                            Gtk.WidgetPaintable.new(popup).snapshot(snapshot, float(popup.get_width()), float(popup.get_height()))
                            snapshot.restore()

            attempts = []
            # Prefer the current frame in the parent widget tree.  If a GTK or
            # driver combination refuses that readback, fall back to a fresh
            # WidgetPaintable snapshot of the same visible page.
            for strategy in ("parent", "paintable"):
                try:
                    snapshot = Gtk.Snapshot()
                    if strategy == "parent":
                        self.window.snapshot_child(target, snapshot)
                    else:
                        Gtk.WidgetPaintable.new(target).snapshot(
                            snapshot, float(target.get_width() or width), float(target.get_height() or height))
                    add_popovers(snapshot)
                    image = render_snapshot(snapshot)
                    break
                except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                    attempts.append(f"{strategy}: {error}")
            else:
                raise ValueError(" | ".join(attempts))
            if len(image) > 8_388_608 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid screenshot")
            data["image"] = base64.b64encode(image).decode("ascii")
        except Exception as error:
            transient = any(text in str(error).lower() for text in (
                "no visible content", "no drawable size", "no visible page",
                "no render node", "pixels are unavailable",
            ))
            if transient and retry < 4:
                self.window.queue_draw()
                GLib.timeout_add(250 * (retry + 1), self.capture_display, capture_id, retry + 1)
                return False
            print(f"RoonDeck display capture failed: {error}", flush=True)
            detail = str(error).strip()[:240]
            data["error"] = f"Display capture failed: {detail}. The previous preview is unchanged."
        if post_json(BUS + "/api/device/display-capture", data, timeout=15) is None:
            print("RoonDeck display capture delivery failed", flush=True)
        return False

    def apply_display_view_request(self, request):
        self.preview_navigation_id = request.get("id")
        if self.preview_navigation_id:
            GLib.timeout_add(150, self.finish_preview_navigation, request, time.monotonic() + 40)
        view = str(request.get("view", ""))
        action = request.get("browse_action")
        if action in {"open", "back", "current", "section"}:
            if popup := getattr(self, "browser_action_popover", None):
                self.browser_action_selected["value"] = True
                popup.popdown()
            self.set_mode("roon"); self.set_roon_view("browse")
            self.browser_action_anchor = None
            child = self.browser_list.get_first_child()
            while child:
                if getattr(child, "browse_item_key", None) == request.get("item_key"):
                    self.browser_action_anchor = child; break
                child = child.get_next_sibling()
            payload = {"item_key": request.get("item_key", "")} if action == "open" else {"section": request.get("section", "albums")} if action == "section" else {}
            self.request_browser(action, **payload)
            return False
        if view == "now":
            self.show_roon_now()
            self.set_mode("roon")
        elif view == "details":
            self.set_mode("roon"); self.set_roon_view("details")
        elif view == "settings":
            self.open_settings()
        elif view == "search":
            self.discovery_browser_origin = False
            self.discovery_active = True; self.discovery_section = "browse"
            self.set_mode("roon"); self.set_roon_view("search")
        elif view in {"recent", "daily", "releases", "browse", "surprise"}:
            self.discovery_signature = None
            self.open_discover(view)
        elif view in {"bus", "home"}:
            self.set_mode(view)
        return False

    def finish_preview_navigation(self, request, deadline):
        if request.get("id") != getattr(self, "preview_navigation_id", None): return False
        requested = request.get("view")
        if requested in {"bus", "home", "settings", "details"}: view = requested
        else: view = self.roon_views.get_visible_child_name()
        browser = view in {"browse", "search"}
        loading = (getattr(self, "browser_loading", False) or getattr(self, "browser_rendering", False)) if browser else view == "discover" and (not self.discovery_signature or (getattr(self, "discovery_data", {}) or {}).get("status") == "loading")
        if loading and time.monotonic() < deadline: return True
        data = (self.browser_state or {}) if browser else (getattr(self, "discovery_data", {}) or {}) if view == "discover" else {}
        error = "The display did not finish opening this view." if loading else str(data.get("message") or "Could not open this view") if data.get("error") or data.get("status") in {"error", "unavailable"} else ""
        result = {"id": request["id"], "error": error, "title": data.get("title") or request.get("view", "Display"), "can_back": data.get("can_back", False), "items": data.get("items", []) if browser else []}
        threading.Thread(target=post_json, args=(BUS + "/api/device/preview", result), kwargs={"timeout": 5}, daemon=True).start()
        return False

    def apply(self, target, status, roon, config, system, device, image_key, image):
        effective_config = config if isinstance(config, dict) and config else self.settings_data
        background = (effective_config or status or {}).get("display_background")
        if background is not None:
            if background == "black": self.window.add_css_class("background-black")
            else: self.window.remove_css_class("background-black")
        if status and "display_theme" in status and config is None: self.apply_theme(status["display_theme"])
        if isinstance(config, dict) and config:
            grid_changed = self.settings_data.get("portrait_discovery_columns", 2) != config.get("portrait_discovery_columns", 2)
            self.settings_data = config
            self.apply_interface_size(config.get("interface_size", "standard"))
            if grid_changed and getattr(self, "responsive_portrait", False) and hasattr(self, "discovery_data"):
                self.discovery_signature = None
                self.render_discover(self.discovery_request, self.discovery_data)
            self.apply_theme(config.get("display_theme"))
            self.apply_home_colors(config)
            for value, button in getattr(self, "touch_background_buttons", {}).items():
                (button.add_css_class if value == config.get("display_background", "current") else button.remove_css_class)("active")
            for button in self.bus_nav_buttons: button.set_visible(config.get("bus_enabled", True))
            if hasattr(self, "touch_bus_enabled") and self.touch_bus_enabled.get_active() != config.get("bus_enabled", True):
                self.bus_visibility_updating = True; self.touch_bus_enabled.set_active(config.get("bus_enabled", True)); self.bus_visibility_updating = False
            requested_interface_size = {"smaller": 0, "standard": 1, "larger": 2}.get(config.get("interface_size"), 1)
            if self.touch_interface_size.get_selected() != requested_interface_size:
                self.interface_size_updating = True; self.touch_interface_size.set_selected(requested_interface_size); self.interface_size_updating = False
            for button in self.roon_nav_buttons: button.set_label("Now Playing")
            self.now_playing_tab.set_label((config.get("roon_now_playing_name") or "Now Playing").upper())
            self.queue_tab.set_label((config.get("roon_queue_name") or "Queue").upper())
            self.controls.set_visible(config.get("roon_show_controls", True)); self.roon_clock.set_visible(config.get("roon_show_clock", True))
            self.sync_music_navigation(); self.queue_tab.set_visible(config.get("roon_show_queue", True))
            if not config.get("roon_show_queue", True) and self.roon_views.get_visible_child_name() == "queue": self.set_roon_view("now")
            self.browser_tab.set_visible(False)
            self.refresh_music_subnav_layout()
            if not config.get("roon_show_browser", True) and self.roon_views.get_visible_child_name() in {"browse", "search"}: self.set_roon_view("now")
            show_sleep_clock = config.get("sleep_show_clock", False); self.sleep_clock.set_visible(show_sleep_clock); self.sleep_hint.set_visible(show_sleep_clock)
            home_title = str(config.get("home_assistant_title", "Home Controls")); self.home_title.set_text(home_title); self.home_title.set_visible(bool(home_title))
            for button in self.home_nav_buttons: button.set_visible(bool(config.get("home_assistant_enabled") and config.get("home_assistant_entities")))
        if system is not None:
            self.system_data = system
            update_status = str(system.get("update_status", "Ready"))
            visible_update = update_status.startswith(("Update ·", "Failed:"))
            waiting_for_update = self.update_in_progress and not self.update_status_seen and update_status == "Ready"
            if not waiting_for_update: self.device_status.set_text(update_status if visible_update else f"v{system.get('app_version', '—')}")
            self.device_status.set_tooltip_text(update_status)
            if update_status.startswith("Update ·"):
                self.update_status_seen = True
            elif self.update_in_progress and self.update_status_seen:
                self.update_in_progress = False
                self.update_button.set_sensitive(True)
            if update_status.startswith("Failed:"):
                self.update_button.set_sensitive(True)
            diagnostics = system.get("diagnostics") or {}; memory = diagnostics.get("memory") or {}; processes = diagnostics.get("processes") or []
            states = {item.get("label"): item.get("active", bool(item.get("pids"))) for item in processes}
            temperature = diagnostics.get("temperature_c"); load = diagnostics.get("load") or [0]
            health = f"Memory {memory.get('used_percent', 0):g}%  ·  Load {float(load[0]):.2f}"
            if temperature is not None: health += f"  ·  {temperature:g}°C"
            health += f"  ·  Controller {'ready' if states.get('Roon controller') else 'offline'}  ·  Bridge {'ready' if states.get('Roon Bridge') else 'offline'}"
            self.touch_diagnostics.set_text(health)
            if not self.display_controls_loaded:
                profiles = {"original": 0, "touch2-5": 1, "touch2-7": 2, "touch2-5-7": 2, "touch2-10": 3}; orientations = {"landscape": 0, "portrait": 1}; mountings = {"standard": 0, "inverted": 1}
                self.touch_profile.set_selected(profiles.get(system.get("display_profile"), 0)); self.touch_orientation.set_selected(orientations.get(system.get("display_orientation"), 0)); self.touch_mounting.set_selected(mountings.get(system.get("display_mounting"), 0)); self.display_controls_loaded = True
        self.render_touch_controls(device, self.system_data)
        self.render_home((device or {}).get("home") or {})
        brightness = int((device or {}).get("display_brightness", 100))
        if not self.brightness_updating and round(self.touch_brightness.get_value()) != brightness:
            self.brightness_updating = True; self.touch_brightness.set_value(brightness); self.brightness_updating = False
        if not self.brightness_applied:
            self.brightness_applied = True
            threading.Thread(target=post_json, args=(BUS + "/api/device/brightness", {"brightness": brightness}), daemon=True).start()
        config = self.settings_data; system = self.system_data
        bus_signature = json.dumps(status, sort_keys=True, separators=(",", ":"), default=str)
        if bus_signature != self.bus_signature:
            self.render_bus(status); self.bus_signature = bus_signature
        # The artwork viewport already reserves the final square before a cover
        # exists. Keep its current paintable while a replacement downloads and
        # decode the new cover off-screen; apply_artwork() then swaps it in as a
        # single GTK update. Clearing here used to expose the placeholder for a
        # frame when returning from a BluOS input and made the whole player look
        # as though it had reflowed. A genuinely empty zone still converges on
        # the fixed-size placeholder via note_missing_artwork().
        self.render_roon(roon)
        if not self.views_prewarmed:
            self.views_prewarmed = True; GLib.idle_add(self.prewarm_views)
        if self.manual_sleep_pending:
            if target == "/sleep.html":
                self.manual_sleep_pending = False
                print("RoonDeck manual sleep confirmed by controller", flush=True)
            elif time.monotonic() - self.manual_sleep_started_at < 6:
                # The local panel changes immediately, but the mode request is
                # asynchronous. Do not let a poll of the previous mode turn
                # the backlight on while the controller catches up.
                target = "/sleep.html"
            else:
                self.manual_sleep_pending = False
                print("RoonDeck manual sleep confirmation timed out", flush=True)
        scheduled_wake = bool(
            target is not None
            and target != "/sleep.html"
            and self.stack.get_visible_child_name() == "sleep"
            and not self.inactivity_sleeping
        )
        if scheduled_wake:
            # Overnight time must not count towards daytime inactivity. Without
            # this reset, the wake boundary and inactivity sleep happen in the
            # same refresh and the panel appears never to wake.
            self.last_interaction = time.monotonic()
            print("RoonDeck resuming at the scheduled wake boundary", flush=True)
        inactivity_seconds = max(0, int(effective_config.get("daytime_inactivity_seconds", 0) or 0))
        playing = ((roon or {}).get("zone") or {}).get("state") == "playing"
        if playing and target != "/sleep.html":
            # Playback is activity: keep the panel lit and start a fresh idle
            # countdown when music stops. Do not override an explicit Sleep.
            was_sleeping = self.inactivity_sleeping or self.stack.get_visible_child_name() == "sleep"
            self.inactivity_sleeping = False
            self.last_interaction = time.monotonic()
            if target and ":8766/" in target and (was_sleeping or not getattr(self, "playback_was_active", False)) and not self.settings_open:
                self.set_roon_view("now")
        self.playback_was_active = playing
        inactivity_due = bool(not playing and inactivity_seconds and time.monotonic() - self.last_interaction >= inactivity_seconds and target != "/sleep.html")
        if inactivity_due and not self.inactivity_sleeping:
            self.inactivity_sleeping = True
            self.prepare_sleep_wake()
            print(f"RoonDeck sleeping after {inactivity_seconds}s without a touch", flush=True)
        if self.settings_open and target != "/sleep.html" and not self.inactivity_sleeping:
            return False
        if target is None and not self.inactivity_sleeping:
            # A transient backend timeout must not wake a sleeping panel or force Bus Times.
            return False
        if target == "/sleep.html":
            self.settings_open = False; self.inactivity_sleeping = False; desired = "sleep"
            if self.stack.get_visible_child_name() != "sleep": self.prepare_sleep_wake()
            self.set_screen_power(bool(effective_config.get("sleep_show_clock", False)))
        elif self.inactivity_sleeping: self.settings_open = False; desired = "sleep"; self.set_screen_power(False)
        elif target == "/home": desired = "home"; self.set_screen_power(True); self.last_mode = "home"
        elif target == "/" or target.endswith(":8765/"): desired = "bus"; self.set_screen_power(True); self.last_mode = "bus"
        else: desired = "roon"; self.set_screen_power(True); self.last_mode = "roon"
        if self.pending_mode:
            if desired == self.pending_mode:
                self.pending_mode = None; self.pending_mode_started_at = 0.0
            elif time.monotonic() - self.pending_mode_started_at < 3:
                # A bottom-nav tap updates locally before the asynchronous
                # controller request is reflected by the next poll. Keep the
                # chosen page visible instead of flashing back to the stale
                # backend page for one frame.
                desired = self.pending_mode
            else:
                self.pending_mode = None; self.pending_mode_started_at = 0.0
        if self.stack.get_visible_child_name() != desired:
            if self.stack.get_visible_child_name() == "boot" and time.monotonic() - self.boot_started_at < 2.5:
                self.pending_boot_mode = desired
                if self.boot_transition_timer is None:
                    remaining = max(1, round((2.5 - (time.monotonic() - self.boot_started_at)) * 1000))
                    self.boot_transition_timer = GLib.timeout_add(remaining, self.finish_boot_splash)
            else: self.stack.set_visible_child_name(desired)
        return False

    def finish_boot_splash(self):
        self.boot_transition_timer = None
        if self.stack.get_visible_child_name() == "boot" and self.pending_boot_mode:
            self.stack.set_visible_child_name(self.pending_boot_mode)
        self.pending_boot_mode = None
        return False

    def apply_artwork(self, image_key, image):
        try:
            self.artwork.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))); self.image_key = image_key; self.image_misses = 0
        except GLib.Error:
            pass
        return False

    def apply_detail_artwork(self, kind, image_key, image):
        try:
            picture = self.detail_artist_artwork if kind == "artist" else self.detail_album_artwork
            picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(image)))
            if kind == "artist": self.detail_artist_image_key = image_key
            else: self.detail_album_image_key = image_key
        except GLib.Error:
            pass
        return False

    def prewarm_views(self):
        started = time.monotonic()
        for name in ("roon", "home"):
            child = self.stack.get_child_by_name(name)
            child.measure(Gtk.Orientation.HORIZONTAL, 800)
            child.measure(Gtk.Orientation.VERTICAL, 480)
        print(f"RoonDeck views pre-measured in {(time.monotonic() - started) * 1000:.1f}ms", flush=True)
        return False

    def render_touch_controls(self, device, system):
        signature = json.dumps({"services": device.get("services", []), "bridge": (system or {}).get("roon_bridge"), "netdata": (system or {}).get("netdata"), "background": self.settings_data.get("display_background")}, sort_keys=True)
        if signature == getattr(self, "touch_controls_signature", None): return
        self.touch_controls_signature = signature
        while child := self.touch_daily.get_last_child():
            if child.has_css_class("setting-line"): self.settings_row_sizes.remove_widget(child)
            self.touch_daily.remove(child)
        bridge_state = (system or {}).get("roon_bridge")
        service_pair = Gtk.Box(spacing=12); service_pair.set_homogeneous(True)
        if bridge_state in {"active", "running", "inactive", "stopped"}:
            bridge = Gtk.Box(spacing=8); bridge.add_css_class("setting-line"); bridge_check = Gtk.CheckButton(label="Roon Bridge"); bridge_check.set_active(bridge_state in {"active", "running"}); bridge_check.connect("toggled", self.toggle_bridge); bridge.append(bridge_check); service_pair.append(bridge)
        netdata_state = (system or {}).get("netdata")
        if netdata_state in {"active", "running", "inactive", "stopped"}:
            netdata = Gtk.Box(spacing=8); netdata.add_css_class("setting-line"); netdata_check = Gtk.CheckButton(label="Netdata"); netdata_check.set_active(netdata_state in {"active", "running"}); netdata_check.connect("toggled", self.toggle_netdata); netdata.append(netdata_check); service_pair.append(netdata)
        if service_pair.get_first_child(): self.touch_daily.append(service_pair)
        for value, choice in self.touch_background_buttons.items():
            if value == self.settings_data.get("display_background", "current"): choice.add_css_class("active")
            else: choice.remove_css_class("active")
        while child := self.touch_bus_services.get_first_child(): self.touch_bus_services.remove(child)
        services = self.touch_bus_services
        for item in device.get("services", []):
            button = Gtk.CheckButton(label=item.get("name", "")); button.add_css_class("bus-number-choice"); button.set_active(bool(item.get("enabled"))); button.connect("toggled", self.toggle_service, item.get("name", "")); services.append(button)
        self.settings_row_sizes.add_widget(services)

    def render_home(self, home):
        portrait = self.window.has_css_class("portrait")
        self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait else Gtk.PolicyType.NEVER)
        signature = json.dumps({"status": home.get("status"), "entities": home.get("entities", []), "theme": self.settings_data.get("display_theme"), "portrait": portrait}, sort_keys=True, default=str)
        if signature == self.home_signature: return
        self.home_signature = signature
        while child := self.home_grid.get_first_child(): self.home_grid.remove(child)
        entities = home.get("entities", [])[:8]
        self.home_status.set_text("Home Assistant offline" if home.get("status") == "offline" else ("Choose Home Assistant devices in web settings" if not entities else ""))
        self.home_status.set_visible(bool(self.home_status.get_text()))
        self.home_grid.set_margin_top(PORTRAIT_CONTENT_GAP if portrait else 0)
        for index, entity in enumerate(entities):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL, spacing=18 if portrait else 4); box.add_css_class("home-tile"); box.set_vexpand(True)
            state = str(entity.get("state", "unknown")); detail = state.upper()
            if entity.get("percentage") is not None: detail += f" · {entity['percentage']}%"
            if state in {"on", "open", "playing"}: box.add_css_class("on")
            control_row = Gtk.Box(spacing=5); control_row.set_vexpand(True)
            domain = entity.get("domain", "switch")
            box.add_css_class("home-domain-switch" if domain == "input_boolean" else f"home-domain-{domain}")
            scene = domain == "scene"
            if scene: detail = "TAP TO ACTIVATE" if entity.get("available", True) else "UNAVAILABLE"
            icon_size = 108 if self.window.has_css_class("high-resolution") else 82
            if portrait: icon_size = max(64, min(240, round((self.window.get_height() - 190) / max(4, len(entities)) * .7)))
            icon_slot = icon_size; icon_size = round(icon_size * .75)
            icon = FamilyIcon("check" if scene else domain if domain in {"fan", "light"} else "switchon" if state == "on" else "switch", icon_size); icon.set_size_request(icon_slot, icon_slot); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.add_css_class("home-icon")
            button = Gtk.Button(); button.add_css_class("home-device-button"); button.set_hexpand(not portrait); button.set_vexpand(True); button.set_child(icon)
            if scene:
                button.add_css_class("scene-action"); button.scene_tile = box; button.set_sensitive(bool(entity.get("available", True))); button.connect("clicked", self.activate_home_scene, entity.get("entity_id", ""))
            else: button.connect("clicked", self.toggle_home, entity.get("entity_id", ""))
            control_row.append(button)
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); details.set_hexpand(True); details.set_valign(Gtk.Align.CENTER)
            if entity.get("supports_level"):
                level = entity.get("percentage")
                if level is None and entity.get("brightness") is not None: level = round(float(entity["brightness"]) * 100 / 255)
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL, 0, 100, 1); scale.add_css_class("home-level"); scale.set_draw_value(False); scale.set_inverted(not portrait); scale.set_hexpand(portrait); scale.set_value(float(level or 0)); scale.connect("value-changed", self.change_home_value, entity.get("entity_id", "")); (details if portrait else control_row).append(scale)
            if domain in {"switch", "input_boolean"}:
                swipe = Gtk.GestureSwipe(); swipe.connect("swipe", self.swipe_home_switch, entity.get("entity_id", "")); button.add_controller(swipe)
            box.append(control_row)
            name = self.label(entity.get("name", "Device"), "home-name", 0 if portrait else .5); name.set_wrap(True); name.set_lines(2); name.set_justify(Gtk.Justification.LEFT if portrait else Gtk.Justification.CENTER); (details if portrait else box).append(name)
            state_label = self.label(detail, "home-state", 0 if portrait else .5); (details if portrait else box).append(state_label)
            if scene: button.scene_status_label = state_label
            if portrait: box.append(details)
            if not portrait and len(entities) == 6:
                # Two full-height primary controls plus a compact 2x2 group
                # use the complete landscape canvas without empty grid cells.
                if index < 2: self.home_grid.attach(box, index, 0, 1, 2)
                else: self.home_grid.attach(box, 2 + (index - 2) % 2, (index - 2) // 2, 1, 1)
            else:
                self.home_grid.attach(box, 0 if portrait else index % 4, index if portrait else index // 4, 1, 1)

    def render_bus(self, data):
        if not data: self.bus_status.set_text("Bus service unavailable"); return
        self.stop.set_text(data.get('stop_name', 'Bus times')); self.stop_code.set_text(data.get('stop_code', ''))
        while child := self.services.get_first_child(): self.services.remove(child)
        visible = data.get("services", [])[:4]
        portrait = self.window.has_css_class("portrait")
        original_compact = (not portrait and getattr(self, "viewport_width", 800) <= 820
                            and getattr(self, "viewport_height", 480) <= 500 and len(visible) >= 3)
        self.bus_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait else Gtk.PolicyType.NEVER)
        self.services.set_spacing(24 if portrait else 8 if original_compact else 14)
        self.services.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
        self.services.set_vexpand(not portrait and not original_compact)
        self.bus_content.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
        self.services.set_margin_top(PORTRAIT_CONTENT_GAP if portrait else 0)
        for index, service in enumerate(visible):
            row = Gtk.Box(spacing=12); row.add_css_class("service"); row.add_css_class("service-" + (service.get("colour") or {"40": "blue", "42": "green", "401": "violet"}.get(str(service.get("service")), "amber"))); row.set_vexpand(not original_compact)
            if len(visible) == 3: row.add_css_class("compact")
            elif len(visible) >= 4: row.add_css_class("dense")
            if original_compact:
                row.add_css_class("original-compact"); row.set_size_request(-1, 82 if len(visible) == 3 else 62)
            if portrait:
                self.render_portrait_bus_card(row, service, len(visible))
                self.services.append(row)
                continue
            number = self.label(str(service.get("service", "")), "service-no"); number.set_size_request((150 if len(visible) > 2 else 188) if self.window.has_css_class("high-resolution") else (86 if original_compact else 100 if len(visible) > 2 else 125), -1); number.set_valign(Gtk.Align.CENTER)
            arrivals = Gtk.Box(spacing=8); arrivals.set_hexpand(True)
            if portrait:
                number.set_xalign(.5); number.set_size_request(-1, -1); number.set_valign(Gtk.Align.CENTER)
                count = max(1, len(visible))
                card_budget = (getattr(self, "viewport_height", self.window.get_height()) - 240 - (count - 1) * 24) / count
                large = self.window.has_css_class("large-display")
                route_size = min(344 if large else 216, max(40, round((card_budget - 80) / (2.6 if large else 1.85))))
            font_size = (route_size if self.window.has_css_class("large-display") else round(route_size * .8)) if portrait else (123 if self.window.has_css_class("high-resolution") else 82)
            if not portrait and len(visible) > 2:
                font_size = 38 if original_compact and len(visible) >= 4 else 46 if original_compact else round(font_size / (1.8 if len(visible) >= 4 else 1.4))
            attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(font_size * Pango.SCALE)); number.set_attributes(attrs)
            number.add_css_class("solid-route"); row.append(number)
            for arrival in service.get("arrivals", [])[:2 if portrait else 3]:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); col.set_valign(Gtk.Align.CENTER); minutes = arrival.get("minutes"); value = self.label("Due" if minutes == 0 else str(minutes), "arrival", .5)
                if portrait:
                    due_size = min(344 if self.window.has_css_class("large-display") else 112, max(32, round(route_size * 1.1 if self.window.has_css_class("large-display") else route_size * .68)))
                    if self.window.has_css_class("large-display"):
                        text = "Due" if minutes == 0 else str(minutes)
                        due_size = min(due_size, round((getattr(self, "viewport_width", 1200) - 100) / (2 * max(2, len(text)) * .7)))
                    attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(due_size * Pango.SCALE)); value.set_attributes(attrs)
                col.append(value); col.append(self.label("MIN · LIVE" if arrival.get("monitored") else "MIN · AFTER", "arrival-sub", .5)); col.set_hexpand(True); arrivals.append(col)
            row.append(arrivals); self.services.append(row)
        self.bus_status.set_text("Live from LTA DataMall" if data.get("status") == "ok" and not data.get("stale") else "Offline / last known arrivals")
        updated = data.get("updated_at"); self.updated.set_text("Updated " + updated[11:19] if updated else "")

    def render_portrait_bus_card(self, row, service, count):
        count = max(1, count)
        height = getattr(self, "viewport_height", self.window.get_height())
        width = getattr(self, "viewport_width", self.window.get_width())
        # Reserve the real header, footer and bottom navigation. The previous
        # 240px allowance was optimistic and made a third portrait service
        # extend beneath the fixed navigation on the physical display.
        chrome = 390 if count >= 3 else 300
        gap = 14 if count >= 3 else 24
        budget = max(180, (height - chrome - (count - 1) * gap) / count)
        route_size = max(26, min(110, round(budget * .145)))
        primary_size = max(46, min(248, round(budget * .34)))
        secondary_size = max(24, min(86, round(budget * .115)))
        caption_size = max(14, min(42, round(budget * .055)))
        row.set_orientation(Gtk.Orientation.VERTICAL); row.set_vexpand(False)
        row.set_spacing(max(4, min(16, round(budget * .02))))
        # Budget includes CSS padding, so compact screens can scroll rather
        # than forcing the native window beyond its physical dimensions.
        row.set_size_request(-1, round(budget - (36 if count < 3 else 24)))
        def sized(text, css, size):
            label = self.label(text, css, .5)
            attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(size * Pango.SCALE))
            label.set_attributes(attrs)
            return label
        top = Gtk.Box(spacing=max(18, round(width * .06))); top.add_css_class("bus-primary-row")
        top.set_homogeneous(True); top.set_hexpand(True); top.set_vexpand(True)
        top.set_margin_start(round(width * .055)); top.set_margin_end(round(width * .055))
        badge_slot = Gtk.Box(); badge_slot.set_hexpand(True); badge_slot.set_valign(Gtk.Align.CENTER)
        badge = Gtk.Box(spacing=12); badge.add_css_class("bus-route-badge"); badge.set_halign(Gtk.Align.CENTER)
        badge.append(sized("ROUTE", "bus-route-word", caption_size))
        number = sized(str(service.get("service", "")), "service-no", route_size)
        number.add_css_class("solid-route"); badge.append(number); badge_slot.append(badge); top.append(badge_slot)
        arrivals = service.get("arrivals", [])[:3]
        minutes = arrivals[0].get("minutes") if arrivals else None
        text = "Due" if minutes == 0 else "—" if minutes is None else str(minutes)
        primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); primary.set_hexpand(True); primary.set_vexpand(True); primary.set_valign(Gtk.Align.CENTER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0); content.set_valign(Gtk.Align.CENTER)
        primary_size = min(primary_size, round((width - 100) / (max(2, len(text)) * .75)))
        content.append(sized(text, "bus-next", primary_size))
        content.append(sized("arriving now" if minutes == 0 else "minutes" if minutes is not None else "no prediction", "bus-next-unit", caption_size))
        primary.append(content); top.append(primary); row.append(top)
        later = arrivals[1:]
        if later:
            rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); rule.add_css_class("bus-rule")
            rule.set_margin_start(round(width * .055)); rule.set_margin_end(round(width * .055)); row.append(rule)
            row.append(sized("THEN", "bus-then", max(13, round(caption_size * .75))))
            following = Gtk.Box(spacing=12); following.set_homogeneous(True)
            following.set_margin_bottom(max(8, round(budget * .025)))
            for arrival in later:
                value = arrival.get("minutes")
                item = Gtk.Box(spacing=max(4, round(caption_size * .18))); item.set_halign(Gtk.Align.CENTER)
                text = "Due" if value == 0 else str(value)
                size = min(secondary_size, round((width - 110) / (max(1, len(later)) * max(2, len(text)) * .75)))
                item.append(sized(text, "bus-following", max(12, size)))
                if value != 0: item.append(sized("min", "bus-following-unit", max(20, round(secondary_size * .52))))
                following.append(item)
            row.append(following)

    def render_roon(self, data):
        self.state = data; self.render_queue((data or {}).get("queue") or {}); self.render_details((data or {}).get("details") or {}); zone = (data or {}).get("zone")
        amplifier = (data or {}).get("amplifier") or {}; active_input = amplifier.get("active_input")
        active_id = str((active_input or {}).get("id") or "")
        if active_id != self.last_active_input:
            if active_id: self.requested_audio_view = "source"
            elif self.last_active_input and self.requested_audio_view == "source": self.requested_audio_view = "now"
            self.last_active_input = active_id
        self.render_bluos_inputs(amplifier, bool(zone))
        external = bool(amplifier.get("connected") and active_input)
        external_view = external and self.requested_audio_view == "source"
        # Source input has its own stack page.  Keep the hidden Now Playing
        # page fully allocated while that page is shown so returning cannot
        # briefly lay out the transport controls at full width before artwork.
        self.artwork_button.set_visible(True); self.controls.set_visible(self.settings_data.get("roon_show_controls", True)); self.progress.set_visible(True); self.roon_times.set_visible(True); self.roon_subnav.set_sensitive(True); self.queue_tab.set_sensitive(True); self.browser_tab.set_sensitive(True)
        if external_view:
            player = amplifier.get("player") or {}; volume = amplifier.get("volume") or {}; value = volume.get("value")
            self.zone.set_text(player.get("name") or (zone or {}).get("name") or player.get("model") or "Player"); self.source_title.set_text((active_input.get("name") or "External input").upper()); self.source_volume.set_text(str(round(value)) if value is not None else "—"); self.source_mute.set_sensitive(value is not None); self.source_mute.set_label("UNMUTE" if volume.get("muted") else "MUTE")
            self.set_roon_view("source")
            return
        if self.roon_views.get_visible_child_name() == "source": self.set_roon_view(self.requested_audio_view if self.requested_audio_view != "source" else "now")
        if not zone:
            self.zone.set_text(self.settings_data.get("roon_zone_name") or "ROON")
            if data is None:
                self.title.set_text("Controller unavailable"); self.artist.set_text("Check the controller service in web settings")
            elif not data.get("connected"):
                self.title.set_text("Authorise in Roon"); self.artist.set_text("Settings → Extensions → RoonDeck")
            else:
                self.title.set_text("Nothing playing"); self.artist.set_text("No Roon zones are available")
            self.prev.set_sensitive(False); self.play.set_sensitive(False); self.next.set_sensitive(False); self.seek_updating = True; self.progress.set_value(0); self.progress.set_sensitive(False); self.seek_updating = False; self.volume.set_sensitive(False); self.note_missing_artwork(); return
        if zone.get("available") is False:
            self.zone.set_text(zone.get("name") or self.settings_data.get("roon_zone_name") or "ROON")
            self.title.set_text("Nothing playing"); self.artist.set_text("Selected zone is offline")
            self.prev.set_sensitive(False); self.play.set_sensitive(False); self.next.set_sensitive(False)
            self.seek_updating = True; self.progress.set_value(0); self.progress.set_sensitive(False); self.seek_updating = False
            self.volume.set_sensitive(False); self.mute.set_sensitive(False); self.note_missing_artwork(); return
        playing = zone.get("now_playing") or {}; lines = playing.get("three_line") or playing.get("two_line") or playing.get("one_line") or {}
        if not playing.get("image_key"):
            self.note_missing_artwork()
        else:
            self.image_misses = 0
        self.zone.set_text(zone.get("name") or "ROON"); self.title.set_text(lines.get("line1") or "Nothing playing"); self.artist.set_text(playing.get("display_artist") or re.split(r"\s+/\s+|\s*;\s*", lines.get("line2") or "Roon")[0])
        icon_name = "play" if external or zone.get("state") != "playing" else "pause"
        icon_size = 80 if self.window.has_css_class("large-display") else 42
        current_icon = self.play.get_child()
        if not isinstance(current_icon, FamilyIcon) or current_icon.icon_name != icon_name or current_icon.get_pixel_size() != icon_size:
            self.play.set_child(FamilyIcon(icon_name, icon_size))
        self.prev.set_sensitive(not external and bool(zone.get("can_previous"))); self.next.set_sensitive(not external and bool(zone.get("can_next"))); self.play.set_sensitive(bool(zone.get("can_play") or zone.get("can_pause")))
        elapsed = int(zone.get("seek_position") or 0); length = int(playing.get("length") or 0); self.seek_updating = True; self.progress.set_range(0, max(1, length)); self.progress.set_value(min(elapsed, length) if length else 0); self.progress.set_sensitive(bool(zone.get("can_seek") and length)); self.seek_updating = False; self.elapsed.set_text(self.format_time(elapsed)); self.remaining.set_text("−" + self.format_time(max(0, length - elapsed)))
        output = zone.get("output") or {}; volume = output.get("volume") or {}; value = volume.get("value"); fixed_volume = value is None; self.volume_updating = True
        for control in (self.mute, self.volume_down, self.volume, self.volume_up): control.set_visible(not fixed_volume)
        self.volume.set_sensitive(not fixed_volume); self.volume.set_value(float(value or 0)); self.volume_value.set_text("FIXED VOLUME" if fixed_volume else str(value)); self.volume_value.set_hexpand(fixed_volume); self.volume_value.set_xalign(.5 if fixed_volume else 1); (self.volume_value.add_css_class if fixed_volume else self.volume_value.remove_css_class)("fixed-volume-label"); self.mute.set_sensitive(not fixed_volume); self.mute.set_label("UNMUTE" if volume.get("is_muted") else "MUTE"); self.volume_updating = False
        text_layout = (self.title.get_text(), self.artist.get_text())
        if getattr(self, "responsive_portrait", False) and text_layout != getattr(self, "now_text_layout", None):
            self.now_text_layout = text_layout; GLib.idle_add(self.adapt_display)

    def render_bluos_inputs(self, amplifier, have_roon):
        inputs = list(amplifier.get("inputs") or [])
        signature = [(str(item.get("id")), item.get("name") or "Input") for item in inputs]
        if signature != getattr(self, "bluos_input_signature", None):
            self.bluos_input_signature = signature
            while child := self.roon_subnav.get_first_child(): self.roon_subnav.remove(child)
            self.bluos_source_buttons = {}
            for input_id, name in signature:
                button = self.button(name.upper(), lambda _button, value=input_id: self.select_bluos_input(value), "")
                button.set_hexpand(getattr(self, "responsive_portrait", False))
                self.bluos_source_buttons[input_id] = button; self.roon_subnav.append(button)
            self.roon_subnav.append(self.now_playing_tab); self.roon_subnav.append(self.queue_tab); self.roon_subnav.append(self.browser_tab)
            self.refresh_music_subnav_layout()
        active_id = str((amplifier.get("active_input") or {}).get("id") or "")
        for input_id, button in self.bluos_source_buttons.items():
            if self.requested_audio_view == "source" and input_id == active_id: button.add_css_class("active")
            else: button.remove_css_class("active")

    def refresh_music_subnav_layout(self):
        """Discard a stale allocation after optional music tabs change."""
        portrait = getattr(self, "responsive_portrait", False)
        self.roon_subnav.set_halign(Gtk.Align.FILL if portrait else Gtk.Align.CENTER)
        self.roon_subnav.set_hexpand(portrait)
        child = self.roon_subnav.get_first_child()
        while child:
            child.set_hexpand(portrait)
            child = child.get_next_sibling()
        self.roon_subnav.set_size_request(-1, -1)
        self.roon_subnav.queue_resize()

    def select_bluos_input(self, input_id):
        self.requested_audio_view = "source"; self.set_roon_view("source")
        threading.Thread(target=post_json, args=(ROON + "/api/bluos/input", {"input_id": input_id}), daemon=True).start()

    def step_bluos_volume(self, amount):
        value = ((((self.state or {}).get("amplifier") or {}).get("volume")) or {}).get("value")
        if value is not None: threading.Thread(target=post_json, args=(ROON + "/api/bluos/volume", {"value": round(float(value) + amount)}), daemon=True).start()

    def step_volume(self, amount):
        if not self.state: return
        adjustment = self.volume.get_adjustment()
        value = max(adjustment.get_lower(), min(adjustment.get_upper(), round(self.volume.get_value()) + amount))
        self.volume.set_value(value)

    def configure_music_clock(self):
        if not hasattr(self, "music_clock_button"): return
        full = not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) >= 1000 and self.settings_data.get("landscape_music_clock", "icon") == "full"
        child = self.music_full_clock if full else self.music_clock_icon
        if self.music_clock_button.get_child() is not child: self.music_clock_button.set_child(child)
        reserve = 140 if full else 44 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 36
        self.music_settings_button.get_child().set_halign(Gtk.Align.START)
        self.music_settings_button.set_size_request(reserve, -1)
        self.music_clock_button.set_size_request(reserve, -1)

    def sync_music_navigation(self, name=None):
        name = name or self.roon_views.get_visible_child_name()
        exploring = self.discovery_active and name in {"discover", "browse", "search"}
        self.roon_subnav.set_visible(not exploring); self.discover_subnav.set_visible(exploring)
        self.browser_tab.set_visible(False)
        portrait = getattr(self, "responsive_portrait", False)
        self.discover_toolbar.set_visible(True)
        self.music_header_overlay.set_visible(False)
        if hasattr(self, "configure_music_clock"): self.configure_music_clock()
        self.portrait_music_tabs.set_visible(False)

    def set_roon_view(self, name):
        if name in {"discover", "browse", "search", "details"}:
            self.browse_last_interaction = time.monotonic()
        # A delayed search belongs to the keyboard view, never a later Browse
        # or Surprise request. Cancel it before moving the shared results list.
        if name != "search":
            if getattr(self, "browser_search_timer", None):
                GLib.source_remove(self.browser_search_timer); self.browser_search_timer = None
            pending = getattr(self, "browser_pending_request", None)
            if pending and pending[0] == "search": self.browser_pending_request = None
        if hasattr(self, "search_results_scroll"):
            docked = name == "search" and getattr(self, "responsive_portrait", False)
            destination = self.search_results_scroll if docked else self.browser_scroll
            parent = self.browser_list.get_parent()
            if self.browser_list.get_ancestor(Gtk.ScrolledWindow) is not destination:
                if parent: parent.set_child(None)
                destination.set_child(self.browser_list)
                if docked:
                    while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.search_results_scroll.set_visible(docked)
            if docked:
                self.browser_artist_scroll.set_visible(False)
                self.browser_search_columns.set_visible(False)
        if name in {"now", "queue", "browse", "source", "discover"}: self.requested_audio_view = name
        if name in {"now", "queue", "source", "details"}:
            self.discovery_active = False; self.discovery_request += 1
        exploring = self.discovery_active and name in {"discover", "browse", "search"}
        original_landscape = not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        (self.roon_page.add_css_class if original_landscape and name in {"now", "details"} else self.roon_page.remove_css_class)("now-layout")
        self.roon_page.set_spacing(0 if original_landscape and name in {"now", "details"} else 4)
        daily_edge = original_landscape and self.discovery_active and getattr(self, "discovery_section", "") == "daily" and name == "discover"
        (self.roon_page.add_css_class if daily_edge else self.roon_page.remove_css_class)("daily-edge")
        self.discover_toolbar.set_margin_bottom(1 if original_landscape and name == "now" else 14)
        self.sync_music_navigation(name)
        for button in self.roon_nav_buttons:
            if exploring: button.remove_css_class("active")
            elif button.navigation_page == "roon": button.add_css_class("active")
        for button in self.discover_nav_buttons:
            if exploring and button.navigation_page == "roon": button.add_css_class("active")
            else: button.remove_css_class("active")
        inline_details = name == "details" and getattr(self, "inline_detail", False)
        # Preserve the transport column's allocation while details are shown.
        # Removing it makes the remaining cover absorb spare width, so short
        # and long track titles visibly move the artwork between tracks.
        self.now_playing_centre.set_opacity(0 if inline_details else 1)
        self.now_playing_centre.set_can_target(not inline_details)
        self.detail_takeover.set_visible(name == "details")
        if name != "details": self.roon_views.set_visible_child_name(name)
        self.now_playing_tab.remove_css_class("active"); self.queue_tab.remove_css_class("active"); self.browser_tab.remove_css_class("active")
        if name == "queue": self.queue_tab.add_css_class("active")
        elif name in {"browse", "search"}: self.browser_tab.add_css_class("active")
        elif name in {"now", "details"}: self.now_playing_tab.add_css_class("active")
        if name == "queue": GLib.idle_add(self.scroll_queue_to_current)

    def show_roon_now(self, *_):
        self.set_roon_view("now")

    def toggle_now_playing_details(self, *_):
        self.set_roon_view("now" if self.detail_takeover.get_visible() else "details")

    def resume_discover(self, *_):
        section = getattr(self, "discovery_section", "recent") or "recent"
        if section == "browse" and getattr(self, "browser_state", None):
            self.discovery_browser_origin = False; self.discovery_active = True
            for name, button in self.discover_tabs.items():
                if name == section: button.add_css_class("active")
                else: button.remove_css_class("active")
            self.set_roon_view("browse"); self.set_mode("roon"); return
        recent_mode = getattr(self, "discovery_recent_mode", "added") if section == "recent" else None
        self.open_discover(section, getattr(self, "discovery_mix", ""), getattr(self, "discovery_picks", False), recent_mode)

    def show_browser(self, *_):
        self.discovery_browser_origin = False
        self.discovery_active = True; self.discovery_section = "browse"
        self.set_roon_view("browse")
        if self.browser_state is None: self.request_browser("section", section="albums")

    def browse_detail_artist(self, *_):
        artist = (self.detail_artist_profile_name or self.detail_artist.get_text() or "").strip()
        if not artist: return
        # Global Search is only how Roon resolves the catalogue artist. Keep
        # that internal stack out of visible navigation and remember the page
        # beneath the detail sheet as the user's real Back destination.
        departure = self.roon_views.get_visible_child_name() or "now"
        self.browser_departure_view = departure if departure in {"now", "queue", "source", "discover", "browse"} else "now"
        self.discovery_browser_origin = False
        self.discovery_active = True; self.discovery_section = "browse"
        for name, button in self.discover_tabs.items():
            if name == "browse": button.add_css_class("active")
            else: button.remove_css_class("active")
        self.set_roon_view("browse")
        self.request_browser("artist", name=artist)

    def browser_back_action(self, *_):
        departure = getattr(self, "browser_departure_view", None)
        state = self.browser_state or {}
        if departure and state.get("artist_profile") and not state.get("album_profile"):
            self.browser_departure_view = None
            self.set_roon_view(departure)
            return
        self.request_browser("back")

    def open_discover(self, section="recent", mix="", picks=False, recent_mode=None):
        if section == "recent": self.discovery_recent_mode = recent_mode or "added"
        self.discovery_pages = {}
        self.discovery_browser_origin = False
        self.discovery_active = True; self.discovery_section = section; self.discovery_mix = mix
        self.discovery_picks = picks
        self.discovery_opening = False
        self.discovery_request += 1; self.discovery_signature = None
        for name, button in self.discover_tabs.items():
            if name == section: button.add_css_class("active")
            else: button.remove_css_class("active")
        self.set_roon_view("browse" if section in {"browse", "surprise"} else "discover")
        self.set_mode("roon")
        if section == "browse":
            self.request_browser("section", section="albums")
        elif section == "surprise":
            # Do not expose the previous Browse rail/grid while the asynchronous
            # Surprise preview is being prepared.
            self.browser_sidebar.set_visible(False); self.browser_discovery_sidebar.set_visible(False)
            self.browser_artist_scroll.set_visible(False); self.browser_search_columns.set_visible(False)
            self.browser_scroll.set_visible(True); self.browser_message.set_visible(False)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
            self.browser_list.append(self.loading_notice())
            self.request_browser("surprise")
        else:
            self.sync_discovery_sidebar()
            while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
            self.discovery_pictures = {}; self.discovery_cards = []
            self.discovery_list.append(self.loading_notice())
            self.discovery_scroll.get_vadjustment().set_value(0)
            self.request_discovery()

    def request_discovery(self, request=None):
        request = self.discovery_request if request is None else request
        if request != self.discovery_request or not self.discovery_active or self.discovery_section in {"browse", "surprise"}: return False
        section = "mix" if self.discovery_mix else ("daily-home" if self.discovery_section == "daily" else self.discovery_section)
        if section == "recent" and self.discovery_recent_mode == "added": section = "added"
        mix = self.discovery_mix
        threading.Thread(target=self._fetch_discovery, args=(request, section, mix), daemon=True).start()
        return False

    def _fetch_discovery(self, request, section, mix):
        data = get_json(f"{ROON}/api/discovery?section={section}&client=touch&id={quote(mix, safe='')}", timeout=3.0)
        GLib.idle_add(self._apply_discovery_response, request, data)

    def _apply_discovery_response(self, request, data):
        self.render_discover(request, data)
        if request == self.discovery_request and self.discovery_active and (not data or data.get("status") == "loading" or data.get("refreshing")):
            GLib.timeout_add(600 if data and data.get("status") == "loading" else 1200, self.request_discovery, request)
        return False

    def configure_carousel_end(self, scroller, track):
        # Only the trailing margin changes. The leading CSS inset stays intact.
        if not scroller.get_mapped(): return False
        track.set_margin_end(CAROUSEL_END_SPACE)
        return False

    def render_discover(self, request, data):
        if request != self.discovery_request or not self.discovery_active or self.roon_views.get_visible_child_name() != "discover": return False
        data = data or {"status": "unavailable", "message": "Discover is unavailable. Normal Roon controls are unaffected."}
        portrait_grid = getattr(self, "responsive_portrait", False)
        signature = json.dumps([data, portrait_grid, self.settings_data.get("portrait_discovery_columns", 2), getattr(self, "discovery_daily_tab", "mixes")], sort_keys=True)
        if signature == self.discovery_signature: return False
        self.discovery_signature = signature
        self.discovery_data = data
        self.discovery_list.cancel_spring()
        while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
        self.discovery_pictures = {}
        self.discovery_cards = []
        self.discovery_card_scrollers = {}
        self.sync_discovery_sidebar()
        original_daily = not portrait_grid and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500 and getattr(self, "discovery_section", "") == "daily"
        (self.roon_page.add_css_class if original_daily else self.roon_page.remove_css_class)("daily-edge")
        self.discovery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL if original_daily else Gtk.PolicyType.AUTOMATIC)
        self.discovery_body.set_margin_end(0 if portrait_grid or getattr(self, "discovery_section", "") == "daily" else 28 if getattr(self, "viewport_width", 800) >= 1200 else 0)
        gen2_landscape = self.window.has_css_class("touch2-7-landscape")
        offset_discovery = gen2_landscape and getattr(self, "discovery_section", "") in {"recent", "daily", "releases"}
        self.discovery_list.set_margin_top(22 if portrait_grid and self.discovery_section == "releases" else 24 if offset_discovery else 5 if not portrait_grid and getattr(self, "discovery_section", "") in {"recent", "daily", "releases"} else 0)
        if data.get("status") != "ready":
            self.discovery_list.append(self.loading_notice() if data.get("status") == "loading" else self.label(data.get("message", "Discover is unavailable."), "browser-message")); return False
        if self.discovery_mix:
            title = self.label((data.get("mix") or {}).get("title", "Your Daily Mix"), "queue-title")
            self.discovery_list.append(title)
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12); controls.add_css_class("mix-controls"); controls.set_homogeneous(True); controls.set_halign(Gtk.Align.START)
            control_sizes = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.BOTH)
            for action, label in (("play", "PLAY THIS MIX"), ("queue", "QUEUE THIS MIX")):
                control = self.labelled_icon_button("play" if action == "play" else "playlist", label, lambda _button, value=action: self.request_mix_action(value, controls), "artist-play primary-play" if action == "play" else "queue-pill")
                control.set_hexpand(True)
                slot = Gtk.Box(); slot.set_hexpand(False); slot.append(control)
                if gen2_landscape: slot.set_size_request(220, 52)
                control_sizes.add_widget(slot)
                controls.append(slot)
            self.discovery_list.append(controls)
        if self.discovery_section == "daily" and not portrait_grid:
            columns, size = self.browser_grid_metrics(); size = min(212, size)
            if getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500:
                size = max(136, size)
        else:
            columns, size = self.discovery_grid_metrics(self.discovery_section)
        content = self.discovery_list
        self.discovery_daily_sections = {}
        def group(title, items, section_key="", seed=None):
            if title:
                heading = self.label(title, "recommendation-heading" if seed else "browser-section")
                heading.set_wrap(False); heading.set_ellipsize(Pango.EllipsizeMode.END); content.append(heading)
            if self.discovery_mix:
                for item in items: content.append(self.discovery_track_row(item))
                return
            daily = self.discovery_section == "daily"
            if daily and seed:
                context = self.label(seed.get("title", "").upper(), "recommendation-album")
                context.set_wrap(True); context.set_halign(Gtk.Align.FILL)
                context.set_margin_bottom(14); content.append(context)
            visible_items = list(items)
            original = not portrait_grid and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
            column_spacing = 14 if original and self.discovery_section == "releases" else 30 if portrait_grid or self.discovery_section == "releases" else 18 if daily else 24
            grid = Gtk.Grid(column_spacing=column_spacing, row_spacing=14 if original else 18 if daily else 20); grid.set_column_homogeneous(original and self.discovery_section == "releases"); grid.set_halign(Gtk.Align.FILL if original and self.discovery_section == "releases" else Gtk.Align.START); grid.set_hexpand(True); grid.set_valign(Gtk.Align.START); grid.set_vexpand(False)
            track = ElasticCarouselTrack() if daily and not portrait_grid else None
            section_cards = []
            if track: track.add_css_class("daily-track"); track.set_margin_end(0)
            for index, item in enumerate(visible_items):
                card = Gtk.Button(); card.add_css_class("discovery-card"); card.set_hexpand(False); card.set_vexpand(False); card.set_halign(Gtk.Align.CENTER); card.set_valign(Gtk.Align.START)
                if daily: card.add_css_class("daily-card")
                if item.get("_context_seed"): card.add_css_class("recommendation-seed-card")
                body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5); body.set_halign(Gtk.Align.CENTER); body.set_valign(Gtk.Align.START)
                picture = MixPicture(duotone=item.get("kind") == "mix" or item.get("_context_seed", False)); picture.add_css_class("queue-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); self.set_browser_placeholder(picture)
                art = Gtk.ScrolledWindow(); art.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); art.set_propagate_natural_width(False); art.set_propagate_natural_height(False); art.set_min_content_width(size); art.set_max_content_width(size); art.set_min_content_height(size); art.set_max_content_height(size); art.set_size_request(size, size); art.set_halign(Gtk.Align.CENTER); art.set_child(picture); body.append(art)
                large_display = min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000
                title_height = 82 if large_display else 46 if original else 54 if daily else 58
                credit_height = 62 if large_display else 31 if original else 36
                title_label = self.label(item.get("title", ""), "queue-title", .5); title_label.set_wrap(True); title_label.set_max_width_chars(20 if daily else 23); title_label.set_lines(2); title_label.set_ellipsize(Pango.EllipsizeMode.END); title_label.set_size_request(size, title_height); title_label.set_valign(Gtk.Align.START); body.append(title_label)
                title_label.set_justify(Gtk.Justification.CENTER)
                credit = self.label(item.get("artist") or " · ".join(item.get("context") or []), "queue-subtitle", .5); credit.set_wrap(True); credit.set_max_width_chars(25); credit.set_lines(2); credit.set_ellipsize(Pango.EllipsizeMode.END); credit.set_size_request(size, credit_height); credit.set_valign(Gtk.Align.START); body.append(credit)
                credit.set_justify(Gtk.Justification.CENTER)
                card_height = size + title_height + credit_height + 15
                # A GTK size request is only a minimum. Clip the complete card
                # inside a fixed viewport so even very long album names cannot
                # widen a column or push the following covers off-grid.
                shell = Gtk.ScrolledWindow(); shell.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); shell.set_propagate_natural_width(False); shell.set_propagate_natural_height(False); shell.set_min_content_width(size); shell.set_max_content_width(size); shell.set_min_content_height(card_height); shell.set_max_content_height(card_height); shell.set_size_request(size, card_height); shell.set_child(body)
                card.set_child(shell); card.connect("clicked", lambda pressed, value=item: self.open_discover("daily", value.get("id", "")) if value.get("kind") == "mix" else self.open_discovery_item(pressed, value.get("key")))
                card.set_size_request(size, card_height)
                if track is not None:
                    track.append(card)
                else: grid.attach(card, index % columns, index // columns, 1, 1)
                if key := item.get("artwork_key"):
                    key = "discover:" + key; self.discovery_pictures.setdefault(key, []).append(picture)
                    self.discovery_cards.append((card, key))
                    section_cards.append(card)
                    if cached := self.queue_thumbnail_cache.get(key): picture.set_paintable(cached)
            if track is not None:
                scroller = Gtk.ScrolledWindow(); scroller.add_css_class("daily-scroll"); scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER); scroller.set_kinetic_scrolling(True); scroller.set_overlay_scrolling(True); scroller.set_propagate_natural_width(False); scroller.set_hexpand(True); scroller.set_margin_end(0); scroller.set_child(track)
                scroller.get_hadjustment().connect("value-changed", self.load_visible_discovery_artwork)
                track.attach_touch_pull(scroller)
                scroller.connect("map", lambda widget, row=track: GLib.idle_add(self.configure_carousel_end, widget, row))
                for card in section_cards: self.discovery_card_scrollers[id(card)] = scroller
                content.append(scroller)
                if section_key: self.discovery_daily_sections.setdefault(section_key, scroller)
            else:
                content.append(grid)
                if section_key: self.discovery_daily_sections.setdefault(section_key, grid)
        show_mixes = not (portrait_grid and self.discovery_section == "daily" and not self.discovery_mix and getattr(self, "discovery_daily_tab", "mixes") == "recommendations")
        show_recommendations = not (portrait_grid and self.discovery_section == "daily" and not self.discovery_mix and getattr(self, "discovery_daily_tab", "mixes") == "mixes")
        if show_mixes and self.discovery_section == "daily" and not self.discovery_mix and not data.get("items"):
            mixes = data.get("mixes_status", "ready")
            message = "Loading mixes…" if mixes == "loading" else data.get("mixes_message") or "No daily mixes available from Roon."
            notice = self.label(message, "browser-message"); notice.set_wrap(True); content.append(notice)
            self.discovery_daily_sections["mixes"] = notice
        elif show_mixes: group(None, data.get("items", []), "mixes")
        for recommendation in data.get("groups", []) if show_recommendations else []:
            seed = recommendation.get("seed") or {}
            reason = {"recent": "BECAUSE YOU LISTENED TO…", "added": "BECAUSE YOU ADDED…"}.get(recommendation.get("reason"), "INSPIRED BY…")
            group(reason, recommendation.get("items", []), "recommendations", seed if seed.get("title") else None)
        if not data.get("items") and not data.get("groups"): self.discovery_list.append(self.label("Nothing available here yet.", "browser-message"))
        elif not show_mixes and not data.get("groups"):
            self.discovery_list.append(self.label("Loading recommendations…" if data.get("recommendations_status") == "loading" else "No recommendations available yet.", "browser-message"))
        if self.discovery_mix and data.get("total", 0) > len(data.get("items", [])):
            content.append(self.label("Track preview · the mix buttons request the whole mix.", "browser-message"))
        GLib.timeout_add(100, self.load_visible_discovery_artwork)
        return False

    def open_recent(self, mode):
        self.open_discover("recent", recent_mode=mode)

    def discovery_scrolled(self, adjustment):
        self.schedule_scroll_artwork("discovery", self.load_visible_discovery_artwork)
        if getattr(self, "responsive_portrait", False): return
        if self.discovery_section != "daily" or not getattr(self, "discovery_daily_sections", None): return
        marker = self.discovery_daily_sections.get("recommendations")
        active = "recommendations" if marker and adjustment.get_value() >= max(0, marker.get_allocation().y - 30) else "mixes"
        for value, button in getattr(self, "discovery_sidebar_buttons", {}).items():
            if value == active: button.add_css_class("active")
            else: button.remove_css_class("active")

    def note_browse_scroll(self, *_):
        # Kinetic scrolling can consume the underlying touch sequence before
        # the window-level legacy controller sees it. Treat actual viewport
        # movement as browsing activity so the return timer cannot interrupt
        # someone who is actively moving through a list.
        stack = getattr(self, "stack", None)
        roon_views = getattr(self, "roon_views", None)
        if (stack and roon_views and stack.get_visible_child_name() == "roon"
                and roon_views.get_visible_child_name() in {"discover", "browse", "search"}):
            self.browse_last_interaction = time.monotonic()

    def discovery_secondary_navigation(self):
        if self.discovery_section == "recent":
            return (("added", "ADDED"), ("listened", "LISTENED")), self.discovery_recent_mode
        if self.discovery_section == "daily":
            return (("mixes", "MIXES"), ("recommendations", "FOR YOU")), getattr(self, "discovery_daily_tab", "mixes") if getattr(self, "responsive_portrait", False) else "mixes"
        return (), ""

    def select_discovery_secondary(self, value):
        if self.discovery_section == "recent": self.open_recent(value)
        elif getattr(self, "responsive_portrait", False) and value in {"mixes", "recommendations"}:
            self.discovery_daily_tab = value
            if self.discovery_mix:
                self.open_discover("daily")
                return
            self.discovery_signature = None
            self.render_discover(self.discovery_request, getattr(self, "discovery_data", {}))
            self.discovery_scroll.get_vadjustment().set_value(0)
        else:
            marker = getattr(self, "discovery_daily_sections", {}).get(value)
            if marker:
                adjustment = self.discovery_scroll.get_vadjustment()
                adjustment.set_value(max(adjustment.get_lower(), min(adjustment.get_upper() - adjustment.get_page_size(), marker.get_allocation().y)))

    def sync_discovery_sidebar(self, sidebar=None, from_browser=False):
        sidebar = self.discovery_sidebar if sidebar is None else sidebar
        while child := sidebar.get_first_child(): sidebar.remove(child)
        entries, active = self.discovery_secondary_navigation()
        sidebar.set_visible(bool(entries) or from_browser)
        if not from_browser:
            if entries: self.discovery_body.add_css_class("browser-view")
            else: self.discovery_body.remove_css_class("browser-view")
        self.discovery_sidebar_buttons = {}
        for value, label in entries:
            button = self.button(label, lambda _button, choice=value: self.select_discovery_secondary(choice), "browser-filter")
            button.get_child().set_xalign(0)
            if value == active: button.add_css_class("active")
            sidebar.append(button); self.discovery_sidebar_buttons[value] = button
        portrait = getattr(self, "responsive_portrait", False)
        if from_browser and self.discovery_section == "releases" and not portrait:
            back = self.button("BACK", lambda *_: self.open_discover("releases"), "browser-back")
            back.set_halign(Gtk.Align.START); sidebar.prepend(back)
        spacer = Gtk.Box(); spacer.set_vexpand(not portrait); spacer.set_hexpand(portrait); sidebar.append(spacer)
        if self.discovery_mix or (from_browser and (self.discovery_section != "releases" or portrait)):
            back = self.button("BACK", lambda *_: self.open_discover(self.discovery_section, self.discovery_mix, self.discovery_picks) if from_browser else self.open_discover("daily"), "browser-back")
            back.set_halign(Gtk.Align.END if portrait else Gtk.Align.START); back.set_valign(Gtk.Align.END); sidebar.append(back)

    def discovery_track_row(self, item):
        # Match Browse playlist rows, including the fixed thumbnail viewport.
        row = Gtk.Box(spacing=14); row.set_hexpand(True)
        picture = Gtk.Picture(); picture.add_css_class("queue-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); self.set_browser_placeholder(picture)
        art_slot = Gtk.ScrolledWindow(); art_slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); art_slot.set_propagate_natural_width(False); art_slot.set_propagate_natural_height(False); art_slot.set_min_content_width(72); art_slot.set_max_content_width(72); art_slot.set_min_content_height(72); art_slot.set_max_content_height(72); art_slot.set_size_request(72, 72); art_slot.set_halign(Gtk.Align.START); art_slot.set_valign(Gtk.Align.CENTER); art_slot.set_child(picture); row.append(art_slot)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); copy.set_valign(Gtk.Align.CENTER); copy.set_hexpand(True)
        title = self.label(item.get("title") or "Untitled", "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); copy.append(title)
        subtitle = self.label(item.get("artist") or "Roon", "queue-meta"); subtitle.set_ellipsize(Pango.EllipsizeMode.END); copy.append(subtitle); row.append(copy)
        row.append(self.label(item.get("duration") or "", "browser-arrow", 1))
        button = Gtk.Button(); button.add_css_class("browser-row"); button.add_css_class("mix-track-row"); button.set_child(row); button.set_sensitive(bool(item.get("key"))); button.set_vexpand(False); button.set_valign(Gtk.Align.START)
        button.connect("clicked", lambda *_: self.open_discovery_item(button, item.get("key")))
        if key := item.get("artwork_key"):
            key = "discover:" + key; self.discovery_pictures.setdefault(key, []).append(picture); self.discovery_cards.append((button, key))
            if cached := self.queue_thumbnail_cache.get(key): picture.set_paintable(cached)
        return button

    def load_visible_discovery_artwork(self, *_):
        if not self.discovery_active or self.roon_views.get_visible_child_name() != "discover": return False
        adjustment = self.discovery_scroll.get_vadjustment()
        top, bottom = adjustment.get_value() - 160, adjustment.get_value() + adjustment.get_page_size() + 160
        for card, key in self.discovery_cards:
            horizontal = getattr(self, "discovery_card_scrollers", {}).get(id(card))
            if horizontal:
                axis = horizontal.get_hadjustment(); valid, bounds = card.compute_bounds(horizontal.get_child())
                visible = valid and bounds.get_x() + bounds.get_width() >= axis.get_value() - 160 and bounds.get_x() <= axis.get_value() + axis.get_page_size() + 160
            else:
                valid, bounds = card.compute_bounds(self.discovery_list)
                visible = valid and bounds.get_y() + bounds.get_height() >= top and bounds.get_y() <= bottom
            if visible:
                if key not in self.queue_thumbnail_cache and key not in self.queue_thumbnail_pending:
                    self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False

    def request_mix_action(self, action, controls):
        request, mix = self.discovery_request, self.discovery_mix
        self.discovery_opening = True
        child = controls.get_first_child()
        while child:
            child.set_sensitive(False); child = child.get_next_sibling()
        message = self.label("", "browser-message"); loading = self.loading_notice(); self.discovery_list.append(loading)
        def load():
            result = post_json(ROON + "/api/discovery/mix-action", {"id": mix, "action": action, "nonce": str(uuid.uuid4())}, timeout=25.0)
            GLib.idle_add(finish, result)
        def finish(result):
            if request != self.discovery_request or not self.discovery_active: return False
            self.discovery_list.remove(loading); self.discovery_list.append(message)
            message.set_text(f"{'Play requested for' if action == 'play' else 'Queued'} {result.get('count', 0)} mix selections." if result and result.get("accepted") else (result or {}).get("error") or "Roon did not confirm the request. Check its queue before trying again.")
            child = controls.get_first_child()
            while child:
                child.set_sensitive(True); child = child.get_next_sibling()
            # Keep the result visible until navigation; never automatically retry playback.
            return False
        threading.Thread(target=load, daemon=True).start()

    def request_discovery_track_action(self, action):
        key = getattr(self, "discovery_action_key", "")
        if action not in {"play", "queue"} or not key: return
        def load():
            result = post_json(ROON + "/api/discovery/track-action", {"key": key, "action": action, "nonce": str(uuid.uuid4())}, timeout=25.0)
            GLib.idle_add(finish, result)
        def finish(result):
            if result and result.get("accepted"):
                if action == "play": self.set_roon_view("now")
                else:
                    notice = self.label("Queued.", "browser-message"); self.discovery_list.append(notice)
            else:
                notice = self.label((result or {}).get("error") or "Roon did not confirm the track request.", "browser-message"); self.discovery_list.append(notice)
            return False
        threading.Thread(target=load, daemon=True).start()

    def open_discovery_item(self, anchor, key):
        if self.discovery_opening: return
        self.discovery_browser_origin = self.discovery_section in {"recent", "daily", "releases"}
        self.discovery_opening = True
        self.browser_action_anchor = anchor
        self.discovery_action_key = key
        request = self.discovery_request = self.discovery_request + 1
        self.discovery_signature = None
        def load():
            result = post_json(ROON + "/api/discovery/open", {"session": "touch", "key": key}, timeout=20.0)
            GLib.idle_add(self.apply_discovery_item, request, result)
        threading.Thread(target=load, daemon=True).start()

    def apply_discovery_item(self, request, data):
        if request != self.discovery_request or not self.discovery_active: return False
        if not data or data.get("error"):
            while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
            self.discovery_list.append(self.label((data or {}).get("error") or "This item could not be opened. Try again from Discover.", "browser-message")); return False
        self.discovery_opening = False
        if data.get("action_menu"):
            self.render_browser(data)
        else:
            self.set_roon_view("browse"); self.render_browser(data)
        return False

    def browser_swipe_back(self, _gesture, distance_x, distance_y):
        if distance_x > 90 and distance_x > abs(distance_y) * 2 and (self.browser_state or {}).get("can_back"):
            self.browser_back_action()

    def render_artist_profile(self, profile, play_action=None):
        portrait = getattr(self, "responsive_portrait", False)
        original = not portrait and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        seven_landscape = not portrait and getattr(self, "viewport_height", 480) <= 720
        panel = self.browser_artist_panel
        inactive = self.browser_artist_inline_panel
        inactive.set_visible(False)
        while child := panel.get_first_child(): panel.remove(child)
        panel.set_visible(bool(profile))
        self.browser_artist_scroll.set_visible(bool(profile))
        if not profile: return
        # The profile is a fixed companion panel. Only the independently
        # scrolling album column may move on artist pages.
        self.browser_artist_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        viewport_width = getattr(self, "viewport_width", 800)
        picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.add_css_class("artist-hero-image")
        # Keep the hero blank while the full artist image loads. The generic
        # artist glyph reads as part of the composition at this scale and then
        # flashes away when the real artwork arrives.
        name = profile.get("name", "")
        if seven_landscape:
            # Leave real inner space inside each half-width column. The old
            # fixed 330px original-panel image overflowed its 50% allocation
            # and squeezed the album column even though the parent was even.
            hero_width = 304 if original else min(480, round((viewport_width - 280) * .48))
            hero_ratio = .66 if original else .68
            hero_height = round(hero_width * hero_ratio)
            panel.set_size_request(hero_width, -1); panel.set_orientation(Gtk.Orientation.VERTICAL); panel.set_spacing(0); panel.set_halign(Gtk.Align.START)
            self.browser_artist_scroll.set_size_request(hero_width, 1); self.browser_artist_scroll.set_hexpand(False)
            self.browser_artist_scroll.set_vexpand(False); self.browser_artist_scroll.set_valign(Gtk.Align.START); self.browser_artist_scroll.set_propagate_natural_height(True)
            profile_text_height = 72 if original else 94
            self.browser_artist_scroll.set_min_content_height(hero_height + profile_text_height); self.browser_artist_scroll.set_max_content_height(hero_height + profile_text_height)
            artwork = Gtk.ScrolledWindow(); artwork.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); artwork.set_propagate_natural_width(False); artwork.set_propagate_natural_height(False)
            artwork.add_css_class("artist-hero-frame"); artwork.set_overflow(Gtk.Overflow.HIDDEN)
            artwork.set_min_content_width(hero_width); artwork.set_max_content_width(hero_width); artwork.set_min_content_height(hero_height); artwork.set_max_content_height(hero_height); artwork.set_size_request(hero_width, hero_height); artwork.set_halign(Gtk.Align.START); artwork.set_child(picture)
            picture.artist_hero = True
            artwork_area = Gtk.Overlay(); artwork_area.set_child(artwork); artwork_area.set_halign(Gtk.Align.START)
            panel.append(artwork_area)
        else:
            # Keep the established 10-inch composition. The wide, overlaid
            # hero is reserved for the two seven-inch landscape profiles.
            panel.set_size_request(-1 if portrait else 260, -1)
            if portrait:
                panel.set_orientation(Gtk.Orientation.HORIZONTAL); panel.set_spacing(28)
                self.browser_artist_scroll.set_vexpand(False); self.browser_artist_scroll.set_valign(Gtk.Align.START); self.browser_artist_scroll.set_propagate_natural_height(True)
                size = min(460 if viewport_width >= 1000 else 320, round(viewport_width * (.38 if viewport_width >= 1000 else .315)))
                artwork = Gtk.ScrolledWindow(); artwork.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); artwork.set_propagate_natural_width(False); artwork.set_propagate_natural_height(False)
                artwork.set_min_content_width(size); artwork.set_max_content_width(size); artwork.set_min_content_height(size); artwork.set_max_content_height(size); artwork.set_size_request(size, size); artwork.set_valign(Gtk.Align.CENTER)
                self.browser_artist_scroll.set_min_content_height(size + 40); self.browser_artist_scroll.set_max_content_height(size + 40)
            else:
                panel.set_orientation(Gtk.Orientation.VERTICAL)
                self.browser_artist_scroll.set_vexpand(True); self.browser_artist_scroll.set_valign(Gtk.Align.FILL); self.browser_artist_scroll.set_propagate_natural_height(False); self.browser_artist_scroll.set_min_content_height(1)
                artwork = Gtk.AspectFrame(xalign=.5, yalign=.5, ratio=1, obey_child=False); artwork.set_size_request(200, 200)
            artwork.set_halign(Gtk.Align.CENTER); artwork.set_child(picture); panel.append(artwork)
        key = profile.get("image_key")
        if key:
            self.browser_pictures.setdefault(key, []).append(picture); self.browser_artwork_keys.append(key)
            if seven_landscape: self.artist_hero_keys.add(key)
            cached = self.artist_hero_cache.get(key) if seven_landscape else self.queue_thumbnail_cache.get(key)
            if seven_landscape and cached is None and (source := self.queue_thumbnail_source.get(key)):
                cached = self.decode_artist_hero_artwork(source)
                if cached is not None: self.artist_hero_cache[key] = cached
            cached = cached or self.queue_thumbnail_cache.get(key)
            if cached: picture.set_paintable(cached)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6 if seven_landscape else 12)
        details.set_valign(Gtk.Align.START if seven_landscape else Gtk.Align.CENTER); details.set_hexpand(True)
        if seven_landscape:
            details.add_css_class("artist-overlay-info"); details.set_halign(Gtk.Align.FILL); details.set_valign(Gtk.Align.END); details.set_hexpand(True)
            details.set_size_request(hero_width, -1); artwork_area.add_overlay(details)
        else: panel.append(details)
        title = self.label(name, "artist-name", 0 if portrait else .5); title.set_wrap(True); title.set_max_width_chars(20); details.append(title)
        if seven_landscape: title.set_xalign(0)
        if play_action:
            play = self.labelled_icon_button("play", "Play Artist Radio", lambda *_: self.open_browser_item(None, play_action.get("item_key")), "artist-play primary-play")
            play.set_halign(Gtk.Align.START if portrait or seven_landscape else Gtk.Align.CENTER); details.append(play)
        summary_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if seven_landscape:
            summary_slot.add_css_class("artist-profile-summary"); panel.append(summary_slot)
        else: details.append(summary_slot)
        summary_slot.artist_summary_lines = 4 if seven_landscape else 5
        summary_slot.artist_summary_chars = max(28, round((hero_width - (32 if original else 64)) / 9)) if seven_landscape else 52
        self.load_artist_notes(name, summary_slot, profile)

    def load_artist_notes(self, name, slot, seed=None):
        status = self.label("Loading artist summary…", "queue-meta"); status.set_wrap(True); slot.append(status)
        def load():
            profile = seed or {}
            if not (profile.get("full_writeup") or profile.get("writeup")):
                for attempt in range(3):
                    profile = get_json(ROON + "/api/artist?name=" + quote(name, safe=""), timeout=30) or {}
                    if profile.get("full_writeup") or profile.get("writeup"): break
                    if attempt < 2: time.sleep(1.5)
            def apply():
                if slot.get_root() is None: return False
                while child := slot.get_first_child(): slot.remove(child)
                summary = self.label(profile.get("full_writeup") or profile.get("writeup") or "Artist summary is temporarily unavailable.", "queue-meta")
                summary.add_css_class("artist-bio")
                summary.set_wrap(True); summary.set_lines(getattr(slot, "artist_summary_lines", 5)); summary.set_ellipsize(Pango.EllipsizeMode.END); summary.set_max_width_chars(getattr(slot, "artist_summary_chars", 52)); slot.append(summary)
                return False
            GLib.idle_add(apply)
        threading.Thread(target=load, daemon=True).start()

    def show_browser_sort(self, button):
        popover = Gtk.Popover(); popover.add_css_class("track-menu"); popover.add_css_class("sort-menu"); popover.set_parent(button); popover.set_has_arrow(False); popover.set_autohide(True); popover.set_position(Gtk.PositionType.BOTTOM); popover.set_halign(Gtk.Align.START); popover.set_offset(-18, 4)
        choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); choices.set_size_request(max(1, button.get_width()), -1)
        for order, title in (("title", "Title, A to Z"), ("reverse", "Title, Z to A"), ("artist", "Artist, A to Z")):
            def choose(_choice, value=order, menu=popover):
                menu.popdown(); self.browser_sort.set_sensitive(False); self.browser_sort.get_child().set_text("Sorting…"); self.request_browser("sort", order=value)
            choice = self.button(title, choose, "track-menu-action"); choice.set_focusable(False)
            if order == self.browser_sort_order: choice.add_css_class("active")
            choices.append(choice)
        def closed(*_):
            if getattr(self, "browser_sort_popover", None) is popover: self.browser_sort_popover = None
            popover.unparent()
        popover.connect("closed", closed)
        popover.connect("map", lambda widget: GLib.idle_add(self.hide_native_cursor, widget))
        popover.set_child(choices); self.hide_widget_cursor(popover); popover.popup(); self.hide_native_cursor(popover); self.browser_sort_popover = popover

    def request_browser(self, action, **payload):
        if action == "artist":
            self.browser_scroll.set_visible(True)
            self.browser_artist_scroll.set_visible(False); self.browser_search_columns.set_visible(False)
            self.browser_scrubber.set_visible(False); self.browser_message.set_visible(False)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
            self.browser_list.append(self.loading_notice())
        if action == "search":
            self.browser_search_columns.set_visible(False); self.browser_scroll.set_visible(True)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
            self.browser_list.append(self.loading_notice())
            self.browser_artist_scroll.set_visible(False); self.browser_scrubber.set_visible(False)
            self.browser_search_button.add_css_class("active")
            for button in self.browser_section_buttons.values(): button.remove_css_class("active")
        if self.browser_loading:
            if action in {"jump", "section", "search", "surprise", "artist"}: self.browser_pending_request = (action, payload)
            return
        if action == "surprise" and not (self.browser_state or {}).get("surprise_preview"):
            self.browser_section_scrolls[(self.browser_state or {}).get("section", "albums")] = self.browser_scroll.get_vadjustment().get_value()
        if action in {"section", "search"}:
            self.browser_section_scrolls[(self.browser_state or {}).get("section", "albums")] = self.browser_scroll.get_vadjustment().get_value()
            self.browser_scroll_restore = self.browser_section_scrolls.get(payload.get("section", "search"), 0.0) if action == "section" else 0.0
        elif action == "more": self.browser_scroll_restore = self.browser_scroll.get_vadjustment().get_value()
        elif action == "previous":
            self.browser_previous_height = self.browser_scroll.get_vadjustment().get_upper()
            self.browser_scroll_restore = self.browser_scroll.get_vadjustment().get_value()
        elif action == "back" and (self.browser_state or {}).get("surprise_preview"): self.browser_scroll_restore = self.browser_section_scrolls.get(self.browser_state.get("return_section", "albums"), 0.0)
        elif action in {"jump", "open", "back", "surprise"}: self.browser_scroll_restore = 0.0
        self.browser_loading = True; self.browser_message.set_visible(False)
        threading.Thread(target=self._request_browser, args=(action, payload), daemon=True).start()

    def _request_browser(self, action, payload):
        if action == "current": result = get_json(f"{ROON}/api/browse?session=touch", timeout=3.0)
        else: result = post_json(ROON + "/api/browse", {"session": "touch", "action": action, **payload}, timeout=browser_request_timeout(action))
        GLib.idle_add(self.apply_browser_response, result or {"status": "ready", "title": "Browse", "items": [], "message": "Roon Browse did not respond.", "error": True})

    def apply_browser_response(self, data):
        pending = getattr(self, "browser_pending_request", None)
        if pending:
            self.browser_pending_request = None; self.browser_loading = False
            self.request_browser(pending[0], **pending[1])
            return False
        try:
            self.render_browser(data)
        except Exception as error:
            # A rendering exception must not permanently lock navigation.
            self.browser_loading = False; self.browser_rendering = False
            self.browser_scroll_restore = None
            print("RoonDeck Browse render failed: " + type(error).__name__, flush=True)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.append(self.label("This view could not be displayed. Choose a music tab to try again.", "browser-message"))
            return False
        if data.get("navigate") == "now" and not data.get("error"): self.set_roon_view("now")
        return False

    def browser_grid_metrics(self, genres=False, artists=False):
        monitors = Gdk.Display.get_default().get_monitors()
        monitor = monitors.get_item(0) if monitors.get_n_items() else None
        # Never derive minimum tile sizes from content that may have already
        # expanded the window. Reserve the section rail, scrubber and padding.
        monitor_width = monitor.get_geometry().width if monitor else 800
        width = min(monitor_width, getattr(self, "viewport_width", monitor_width))
        profile = (getattr(self, "system_data", {}) or {}).get("display_profile")
        # KMS can briefly expose the source mode (often 1920 wide) before the
        # configured Touch Display 2 canvas settles at 1280. A grid rendered in
        # that interval permanently widens GTK's natural allocation. Use the
        # physical profile as the hard layout budget instead.
        if not getattr(self, "responsive_portrait", False):
            if profile in {"touch2-7", "touch2-5-7"}: width = min(width, 1280)
            elif profile == "original": width = min(width, 800)
        if getattr(self, "responsive_portrait", False):
            width = min(self.window.get_width() or width, width)
            # Includes outer margins, the alphabet rail, queue-list padding
            # and each button's CSS padding; none may depend on image size.
            margin = 30
            available = width - margin * 2 - (80 if not genres and (self.browser_state or {}).get("alpha_scrub") else 0)
            gap = 30
            return 3, max(48, (available - gap * 2) // 3)
        viewport_height = getattr(self, "viewport_height", None)
        original = width <= 820 and viewport_height is not None and viewport_height <= 500
        if original:
            # Measured 800px budget includes page (24), the rail's realised
            # 122px, the full 54px scrubber, scroller chrome and safety gutter.
            available = max(140, width - 252)
            return 4, max(64, (available - 12 * 3) // 4)
        available = max(140, width - (320 if genres else 280))
        larger_seven = profile in {"touch2-7", "touch2-5-7"} and (getattr(self, "settings_data", {}) or {}).get("interface_size") == "larger"
        # The 7-inch Gen 2 has room for four covers at the larger scale when
        # the grid uses its measured page inset and a 22px gutter. Keep the
        # same four-column rhythm for albums, artists and genre results.
        columns = min(4, max(1, available // 140))
        gap = 21 if larger_seven else 24
        cap = 228 if larger_seven else 212
        # Each card contributes 3px padding on both sides in addition to the
        # grid gap. Account for it here rather than allowing the fifth/right
        # edge to be clipped by the alphabet scrubber.
        size = max(64, min(cap, (available - gap * (columns - 1)) // columns - 7))
        return columns, size

    def discovery_grid_metrics(self, section="releases"):
        monitors = Gdk.Display.get_default().get_monitors()
        monitor = monitors.get_item(0) if monitors.get_n_items() else None
        width = monitor.get_geometry().width if monitor else 800
        if getattr(self, "responsive_portrait", False):
            width = min(self.window.get_width() or width, width)
            margin = 30
            available = max(200, width - margin * 2)
            columns = int(self.settings_data.get("portrait_discovery_columns", 2))
            columns = columns if columns in {2, 3} else 2
            gap = 30
            return columns, max(64, (available - gap * (columns - 1)) // columns)
        sidebar = section == "recent"
        available = max(300, width - (198 if sidebar else 56))
        original = width <= 820 and not getattr(self, "responsive_portrait", False)
        columns = 4 if width >= 1000 or (original and section == "releases") else 3
        gap = 14 if original and section == "releases" else 30 if section == "releases" else 24
        # Browse is the visual benchmark. Recent needs substantially more air
        # around its sidebar, while New Releases can remain a little larger.
        cap = 236 if sidebar else 1000
        minimum = 96 if original and section == "releases" else 110 if width < 1000 else 140
        size = max(minimum, min(190 if width < 1000 else cap, (available - gap * (columns - 1)) // columns))
        return columns, size

    def browser_scrub_changed(self, scale):
        if getattr(self, "browser_scrub_sync", False): return
        value = max(0, min(25, round(scale.get_value()))); letter = chr(65 + value); self.position_browser_scrub_letter(letter, value)
        if timer := getattr(self, "browser_scrub_timer", None): GLib.source_remove(timer)
        self.browser_scrub_timer = GLib.timeout_add(220, self.commit_browser_scrub, letter)

    def position_browser_scrub_letter(self, letter, value):
        self.browser_scrubber.queue_draw()

    def draw_browser_scrubber(self, _area, cr, width, height, *_data):
        # One shared centre for the dot and the letter's actual ink bounds.
        value = max(0, min(25, round(self.browser_scrub_scale.get_value())))
        center = 16 + max(1, height - 32) * value / 25
        x = width - 12
        track = (.27, .26, .29) if getattr(self, "settings_data", {}).get("display_theme") == "roon" else (.145, .192, .18)
        cr.set_source_rgb(*track); cr.set_line_width(5); cr.set_line_cap(1); cr.move_to(x, 16); cr.line_to(x, max(16, height - 16)); cr.stroke()
        accent = (.506, .478, .922) if getattr(self, "settings_data", {}).get("display_theme") == "roon" else (.431, .851, .682)
        cr.set_source_rgb(*accent); cr.arc(x, center, 9, 0, 6.283185307); cr.fill()
        cr.select_font_face("Inter", 0, 1)
        large_interface = getattr(self, "settings_data", {}).get("interface_size") == "larger"
        cr.set_font_size(25 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 22 if large_interface else 18)
        letter = chr(65 + value); extents = cr.text_extents(letter)
        cr.move_to(x - 26 - extents[2], center - extents[1] - extents[3] / 2); cr.show_text(letter)

    def browser_scrub_at(self, y):
        height = self.browser_scrubber.get_allocated_height()
        value = max(0, min(25, round((y - 16) * 25 / max(1, height - 32))))
        self.browser_scrub_scale.set_value(value)

    def browser_scrub_begin(self, _gesture, _x, y):
        self.browser_scrub_dragging = True; self.browser_scrub_start_y = y; self.browser_scrub_at(y); self.browser_scrub_changed(self.browser_scrub_scale)

    def browser_scrub_drag(self, _gesture, _x, y):
        self.browser_scrub_at(self.browser_scrub_start_y + y)

    def browser_scrub_end(self, _gesture, _x, y):
        self.browser_scrub_at(self.browser_scrub_start_y + y); self.browser_scrub_dragging = False

    def browser_scrub_pressed(self, *_):
        self.browser_scrub_dragging = True

    def browser_scrub_released(self, *_):
        self.browser_scrub_dragging = False

    def show_browser_search(self, *_):
        self.set_roon_view("search"); self.browser_search_entry.grab_focus()

    def browser_keyboard_key(self, value):
        entry = self.browser_search_entry; text = entry.get_text(); position = entry.get_position()
        bounds = entry.get_selection_bounds()
        selected, start, end = bounds if len(bounds) == 3 else (bool(bounds), *(bounds if len(bounds) == 2 else (0, 0)))
        if selected: text = text[:start] + text[end:]; position = start
        if value == "CLEAR": text = ""; position = 0
        elif value == "BACKSPACE":
            if not selected and position > 0: text = text[:position - 1] + text[position:]; position -= 1
        else: text = text[:position] + value.lower() + text[position:]; position += len(value)
        entry.set_text(text); entry.set_position(position)

    def submit_browser_search(self, *_):
        query = self.browser_search_entry.get_text().strip()
        if query:
            if getattr(self, "browser_search_timer", None):
                GLib.source_remove(self.browser_search_timer); self.browser_search_timer = None
            self.set_roon_view("search" if getattr(self, "responsive_portrait", False) else "browse")
            self.request_browser("search", query=query, source="all")

    def schedule_browser_search(self, *_):
        if getattr(self, "browser_search_timer", None): GLib.source_remove(self.browser_search_timer)
        self.browser_search_timer = None
        if getattr(self, "responsive_portrait", False) and self.roon_views.get_visible_child_name() == "search":
            if len(self.browser_search_entry.get_text().strip()) >= 2:
                self.browser_search_timer = GLib.timeout_add(600, self.run_scheduled_browser_search)
            else:
                while child := self.browser_list.get_first_child(): self.browser_list.remove(child)

    def run_scheduled_browser_search(self):
        self.browser_search_timer = None
        if self.roon_views.get_visible_child_name() == "search": self.submit_browser_search()
        return False

    def commit_browser_scrub(self, letter):
        self.browser_scrub_timer = None; self.request_browser("jump", letter=letter); return False

    def sync_browser_scrubber(self, item=None):
        if not self.browser_state or not getattr(self, "browser_scrubber_active", False) or getattr(self, "browser_scrub_dragging", False) or getattr(self, "browser_scrub_timer", None) or getattr(self, "browser_pending_request", None): return
        if item is None:
            items = [entry for entry in (self.browser_state.get("items") or []) if not entry.get("action") and entry.get("title")]
            item = items[0] if items else None
            value = self.browser_scroll.get_vadjustment().get_value()
            for card, entry in getattr(self, "browser_cards", []):
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() > value:
                    item = entry; break
        field = "subtitle" if self.browser_state.get("sort_order") == "artist" else "title"
        title = str((item or {}).get(field) or "A").strip()
        if title.lower().startswith("the "): title = title[4:]
        first = unicodedata.normalize("NFKD", title)[:1].upper(); value = ord(first) - 65 if "A" <= first <= "Z" else 0
        self.browser_scrub_sync = True; self.browser_scrub_scale.set_value(value); self.browser_scrub_sync = False; self.position_browser_scrub_letter(chr(65 + value), value)

    def open_browser_item(self, _button, item_key):
        if item_key:
            self.browser_action_anchor = _button
            if getattr(self, "responsive_portrait", False) and self.roon_views.get_visible_child_name() == "search": self.set_roon_view("browse")
            self.request_browser("open", item_key=item_key)

    def browser_item_icon(self, title):
        value = (title or "").lower()
        if "library" in value: return "folder-music-symbolic"
        if "playlist" in value: return "view-list-symbolic"
        if "genre" in value: return "audio-x-generic-symbolic"
        if "artist" in value: return "avatar-default-symbolic"
        if "album" in value: return "media-optical-symbolic"
        if "track" in value or "radio" in value: return "audio-x-generic-symbolic"
        return "folder-symbolic"

    def browser_tile_symbol(self, title, kind):
        value = (title or "").lower()
        if kind == "playlists": return "playlist"
        if "jazz" in value: return "jazz"
        if "classical" in value: return "classical"
        if "electronic" in value: return "electronic"
        if "pop" in value or "rock" in value: return "rock"
        if "stage" in value or "screen" in value or "soundtrack" in value: return "stage"
        if "avant" in value: return "avant"
        if "folk" in value: return "folk"
        if "country" in value: return "country"
        if "blues" in value: return "blues"
        if "rap" in value or "hip-hop" in value: return "rap"
        if "r&b" in value or "rhythm" in value: return "rb"
        if "reggae" in value: return "reggae"
        if "latin" in value: return "latin"
        if "world" in value or "international" in value: return "world"
        if "easy listening" in value: return "easy"
        if "vocal" in value: return "vocal"
        if "new age" in value or "ambient" in value: return "ambient"
        if "holiday" in value: return "holiday"
        if "children" in value: return "children"
        if "comedy" in value: return "comedy"
        if "religious" in value or "gospel" in value: return "religious"
        return "music"

    def browser_action_icon(self, title):
        value = (title or "").lower()
        if "add next" in value: return "list-add-symbolic"
        if "queue" in value: return "view-list-symbolic"
        if "shuffle" in value: return "media-playlist-shuffle-symbolic"
        if "from here" in value: return "go-jump-symbolic"
        return "play"

    def browser_svg_icon(self, name, size=54):
        icon = FamilyIcon(name, size, stroke_width=.7)
        icon.set_size_request(size, size)
        icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("browser-tile-icon")
        return icon

    def browser_menu_card(self, item, compact=False):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); content.set_halign(Gtk.Align.CENTER); content.set_valign(Gtk.Align.CENTER)
        portrait = getattr(self, "responsive_portrait", False)
        width = getattr(self, "viewport_width", 800)
        columns = 4 if width >= 1000 else 2
        side = max(64, (width - 60 - (columns - 1) * 12) // columns)
        icon = FamilyIcon(self.browser_item_icon(item.get("title")), round(side * .48) if portrait else 58 if compact else 78, stroke_width=.8); icon.add_css_class("browser-home-icon"); content.append(icon)
        title = self.label(item.get("title") or "Roon", "browser-home-title", .5); title.set_wrap(True); title.set_justify(Gtk.Justification.CENTER); content.append(title)
        button = Gtk.Button(); button.add_css_class("browser-home-card");
        if portrait: button.set_size_request(side, side)
        if compact: button.add_css_class("compact")
        button.set_hexpand(not portrait); button.set_vexpand(not portrait); button.set_child(content); button.set_sensitive(bool(item.get("item_key"))); button.connect("clicked", self.open_browser_item, item.get("item_key")); return button

    def set_browser_placeholder(self, picture, artist=False):
        name = "missing-artist.svg" if artist else "missing-album.svg"
        # Gtk.Picture rasterises SVGs at their intrinsic size before scaling.
        # Keep thumbnails small, but never magnify a 256px disc on Now Playing.
        if not artist and picture is getattr(self, "artwork", None):
            name = "missing-album-large.svg"
        picture.set_filename(str(Path(__file__).with_name("icons") / name))

    def browser_cover_card(self, item, show_labels, tile_kind=None):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); content.set_halign(Gtk.Align.FILL)
        size = getattr(self, "browser_tile_size", 172)
        original_tile = (not getattr(self, "responsive_portrait", False)
                         and getattr(self, "viewport_width", 800) <= 820
                         and getattr(self, "viewport_height", 480) <= 500)
        separated_label_tile = original_tile or (
            not getattr(self, "responsive_portrait", False)
            and getattr(self, "system_data", {}).get("display_profile") in {"touch2-7", "touch2-5-7"})
        artwork = Gtk.Overlay(); picture = Gtk.Picture(); picture.add_css_class("browser-cover-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); artwork.set_child(picture)
        if not tile_kind:
            self.set_browser_placeholder(picture, artist=(self.browser_state or {}).get("section") == "artists")
        # An AspectFrame only requests a minimum; loaded textures can grow it.
        # Bound artwork and text so a real cover cannot widen the GTK window.
        square = Gtk.ScrolledWindow(); square.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); square.set_propagate_natural_width(False); square.set_propagate_natural_height(False); square.set_min_content_width(size); square.set_max_content_width(size); square.set_min_content_height(size); square.set_max_content_height(size); square.set_size_request(size, size); square.set_halign(Gtk.Align.CENTER); square.set_child(artwork); content.append(square)
        key = item.get("image_key"); self.browser_artwork_keys.append(key)
        if key:
            self.browser_pictures.setdefault(key, []).append(picture)
            texture = self.queue_thumbnail_cache.get(key)
            if texture: picture.set_paintable(texture)
        elif tile_kind:
            gen2_genre = tile_kind == "genres" and self.window.has_css_class("touch2-7-landscape")
            icon_scale = .56 if gen2_genre else .58 if tile_kind == "playlists" else .65
            icon = self.browser_svg_icon(self.browser_tile_symbol(item.get("title"), tile_kind), size=max(54, round(size * icon_scale))); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.set_margin_bottom(round(size * (.26 if gen2_genre else .18 if separated_label_tile else .12))); artwork.add_overlay(icon)
        if show_labels:
            title = self.label(item.get("title") or "Untitled", "browser-cover-title", .5); title.set_max_width_chars(22); title.set_ellipsize(Pango.EllipsizeMode.END); content.append(title)
            if tile_kind in {"genres", "playlists"}:
                content.remove(title); title.add_css_class("tile"); title.set_wrap(True); title.set_lines(2); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_xalign(.5); title.set_justify(Gtk.Justification.CENTER); title.set_halign(Gtk.Align.FILL); title.set_valign(Gtk.Align.END); artwork.add_overlay(title)
                title.set_margin_bottom(6 if separated_label_tile else max(12, round(size * .075)))
            if item.get("subtitle") and not tile_kind:
                subtitle = self.label(item.get("subtitle"), "browser-cover-subtitle", .5); subtitle.set_max_width_chars(22); subtitle.set_ellipsize(Pango.EllipsizeMode.END); content.append(subtitle)
        caption_height = 0 if tile_kind in {"genres", "playlists"} else 96 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 60
        shell = Gtk.ScrolledWindow(); shell.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); shell.set_propagate_natural_width(False); shell.set_propagate_natural_height(False); shell.set_min_content_width(size); shell.set_max_content_width(size); shell.set_min_content_height(size + (caption_height if show_labels else 0)); shell.set_max_content_height(size + (caption_height if show_labels else 0)); shell.set_child(content)
        button = Gtk.Button(); button.add_css_class("browser-cover-card")
        if tile_kind: button.add_css_class(f"{tile_kind[:-1]}-tile")
        button.set_child(shell); button.set_sensitive(bool(item.get("item_key"))); button.connect("clicked", self.open_browser_item, item.get("item_key")); return button

    def album_header(self, profile, items):
        width = getattr(self, "viewport_width", 800)
        narrow_portrait = bool(getattr(self, "responsive_portrait", False) and width < 600)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if narrow_portrait else Gtk.Orientation.HORIZONTAL, spacing=16 if narrow_portrait else 24); header.add_css_class("album-profile")
        size = min(380, round(width * .32)) if width >= 1000 else min(240, round(width * .3))
        picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
        self.set_browser_placeholder(picture)
        slot = Gtk.ScrolledWindow(); slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        slot.set_propagate_natural_width(False); slot.set_propagate_natural_height(False)
        slot.set_min_content_width(size); slot.set_max_content_width(size)
        slot.set_min_content_height(size); slot.set_max_content_height(size)
        slot.set_size_request(size, size); slot.set_child(picture); header.append(slot)
        if key := profile.get("image_key"): self.load_preview_artwork(picture, key)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); copy.set_hexpand(True); copy.set_valign(Gtk.Align.START if width <= 820 and getattr(self, "viewport_height", 480) <= 500 else Gtk.Align.CENTER)
        title = self.label(profile.get("name") or "Album", "artist-name"); title.set_wrap(True); title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); title.set_max_width_chars(28); copy.append(title)
        if artist := profile.get("artist"):
            link = self.button(artist, lambda *_: self.request_browser("artist", name=artist), "album-artist")
            link.get_child().set_wrap(True); link.get_child().set_wrap_mode(Pango.WrapMode.WORD_CHAR); link.get_child().set_max_width_chars(23)
            link.set_halign(Gtk.Align.START); link.set_tooltip_text("View artist"); copy.append(link)
        if play := next((item for item in items if item.get("action") and item.get("title", "").lower() == "play album"), None):
            split = Gtk.Box(spacing=0); split.add_css_class("album-play-split"); split.set_halign(Gtk.Align.START)
            button = self.labelled_icon_button("play", "Play Album", lambda *_: self.open_browser_item(None, play.get("item_key")), "artist-play primary-play")
            menu = self.icon_button("chevron-down", lambda arrow, key=play.get("item_key"): self.open_album_play_menu(arrow, key), "album-play-menu")
            menu.get_child().set_pixel_size(22)
            menu.set_tooltip_text("More album play options"); split.append(button); split.append(menu)
            if narrow_portrait:
                play_slot = Gtk.ScrolledWindow(); play_slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
                play_slot.set_propagate_natural_width(False); play_slot.set_propagate_natural_height(True)
                play_width = max(150, width - 64)
                play_slot.set_min_content_width(play_width); play_slot.set_max_content_width(play_width); play_slot.set_size_request(play_width, -1)
                play_slot.set_child(split); copy.append(play_slot)
            else: copy.append(split)
        if review := profile.get("review"):
            summary = self.label(review[:1800], "queue-meta"); summary.set_wrap(True); summary.set_lines(6); summary.set_ellipsize(Pango.EllipsizeMode.END); summary.set_max_width_chars(50); copy.append(summary)
        else:
            summary_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); copy.append(summary_slot)
            self.load_album_notes(profile, summary_slot)
        header.append(copy)
        return header

    def open_album_play_menu(self, anchor, item_key):
        if item_key:
            self.browser_action_anchor = anchor
            self.request_browser("open", item_key=item_key, menu_only=True)

    def load_album_notes(self, profile, slot):
        album, artist = profile.get("name"), profile.get("artist")
        if not album or not artist: return
        status = self.label("Loading album summary…", "queue-meta"); status.set_wrap(True); slot.append(status)
        def load():
            query = urllib.parse.urlencode({"album": album, "artist": artist})
            notes = get_json(ROON + "/api/album-notes?" + query, timeout=30) or {}
            def apply():
                # Navigation may have replaced this album while lookup ran.
                if slot.get_root() is None: return False
                while child := slot.get_first_child(): slot.remove(child)
                summary = self.label(notes.get("writeup") or "No album summary is available.", "queue-meta")
                summary.set_wrap(True); summary.set_lines(6); summary.set_ellipsize(Pango.EllipsizeMode.END); summary.set_max_width_chars(50)
                slot.append(summary)
                return False
            GLib.idle_add(apply)
        threading.Thread(target=load, daemon=True).start()

    def render_browser(self, data):
        self.browser_list.cancel_spring()
        if data.get("action_menu"):
            self.browser_state = data; self.browser_loading = False; self.browser_rendering = False
            anchor = getattr(self, "browser_action_anchor", None) or self.browser_body
            popover = Gtk.Popover(); popover.add_css_class("track-menu"); popover.set_parent(anchor); popover.set_autohide(True)
            popover.set_has_arrow(False); popover.set_position(Gtk.PositionType.RIGHT)
            popover.set_valign(Gtk.Align.START)
            rect = Gdk.Rectangle(); rect.x = max(1, anchor.get_width()) + 8; rect.y = 0; rect.width = 1; rect.height = 1; popover.set_pointing_to(rect)
            self.browser_action_popover = popover
            choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6 if getattr(self, "compact_detail", False) else 10)
            selected = {"value": False}
            self.browser_action_selected = selected
            discovery_actions = bool(data.get("discovery_track_actions"))
            def choose(_button, key):
                selected["value"] = True; popover.popdown()
                if discovery_actions: self.request_discovery_track_action(key)
                else: self.request_browser("open", item_key=key)
            for item in data.get("items", []):
                if item.get("action"):
                    final_play = item.get("title", "").strip().casefold() in {"play now", "play album", "play artist", "play artist radio"}
                    choice = self.labelled_icon_button(self.browser_action_icon(item["title"]), item["title"], lambda button, key=item.get("item_key"): choose(button, key), "track-menu-action primary-play" if final_play else "track-menu-action"); choice.set_focusable(False); choices.append(choice)
            def closed(*_):
                self.browser_action_popover = None
                popover.unparent()
                if not selected["value"] and not discovery_actions: self.request_browser("back")
            popover.connect("closed", closed)
            popover.connect("map", lambda widget: GLib.idle_add(self.hide_native_cursor, widget))
            popover.set_child(choices); self.hide_widget_cursor(popover); popover.popup(); self.hide_native_cursor(popover)
            return False
        self.browser_rendering = True; self.browser_loading = True; self.browser_state = data; self.browser_back.set_visible(bool(data.get("can_back")) and not data.get("surprise_preview")); self.browser_back.set_sensitive(bool(data.get("can_back")))
        self.browser_scrubber_active = bool(data.get("alpha_scrub")) and not data.get("artist_profile") and data.get("layout") in {"covers", "tiles"}
        self.browser_scrubber.set_visible(self.browser_scrubber_active)
        if hasattr(self, "browser_sort"):
            self.browser_sort.set_visible(data.get("section") == "albums" and bool(data.get("section_root")) and getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) >= 1000)
            self.browser_sort.set_sensitive(True)
            self.browser_sort_order = data.get("sort_order", "title")
            self.browser_sort.get_child().set_text({"title":"Sort: Title, A to Z", "reverse":"Sort: Title, Z to A", "artist":"Sort: Artist, A to Z"}.get(self.browser_sort_order, "Sort: Title, A to Z"))
        active_section = "surprise" if data.get("surprise_preview") else (data.get("section") or "albums")
        original_view = not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        self.browser_content.set_margin_top(0 if data.get("surprise_preview") and original_view else 16)
        self.browser_scroll.set_margin_bottom(0 if data.get("surprise_preview") and original_view else 10)
        from_discover = self.discovery_active and self.discovery_browser_origin
        self.browser_sidebar.set_visible(not data.get("surprise_preview") and not from_discover)
        self.browser_discovery_sidebar.set_visible(from_discover)
        if from_discover: self.sync_discovery_sidebar(self.browser_discovery_sidebar, from_browser=True)
        self.browser_surprise_button.set_visible(False); self.browser_surprise_button.set_label("SURPRISE!")
        self.browser_surprise_button.get_child().set_xalign(0)
        if active_section == "surprise": self.browser_surprise_button.add_css_class("active")
        else: self.browser_surprise_button.remove_css_class("active")
        if active_section == "search": self.browser_search_button.add_css_class("active")
        else: self.browser_search_button.remove_css_class("active")
        for section, button in self.browser_section_buttons.items():
            if section == active_section: button.add_css_class("active")
            else: button.remove_css_class("active")
        message = data.get("message") or (data.get("error") if isinstance(data.get("error"), str) else "") or ""; self.browser_message.set_text(message); self.browser_message.set_visible(bool(message))
        self.browser_pictures = {}; self.browser_artwork_keys = []; self.browser_cards = []; self.artist_hero_keys = set()
        while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
        artist_play = next((item for item in data.get("items", []) if item.get("action") and item.get("title", "").strip().lower() in {"play artist", "play artist radio"}), None) if data.get("artist_profile") else None
        self.render_artist_profile(data.get("artist_profile"), artist_play)
        items = data.get("items") or []
        # Merged artist catalogues also carry search_routes so every album can
        # reopen its originating My Catalog or TIDAL session.  They are still
        # artist album lists, not grouped search results.  Treating them as a
        # grouped search hides browser_list on seven-inch landscape displays.
        grouped_results = bool(data.get("search_routes")) and not data.get("artist_profile")
        grouped_search = grouped_results and not getattr(self, "responsive_portrait", False)
        if grouped_results and getattr(self, "responsive_portrait", False) and hasattr(self, "search_results_scroll"):
            self.search_results_scroll.get_vadjustment().set_value(0)
        self.browser_list.set_spacing(12 if data.get("artist_profile") and getattr(self, "responsive_portrait", False) else 2)
        self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
        while child := self.browser_search_columns.get_first_child(): self.browser_search_columns.remove(child)
        self.browser_search_columns.set_visible(grouped_search)
        self.browser_scroll.set_visible(not grouped_search)
        self.browser_list.set_homogeneous(False)
        self.browser_list.set_vexpand(grouped_search)
        self.browser_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER if grouped_search else Gtk.PolicyType.AUTOMATIC)
        album_profile = data.get("album_profile")
        if album_profile:
            self.browser_list.append(self.album_header(album_profile, items))
            items = [item for item in items if not (item.get("action") and item.get("title", "").lower() == "play album")]
        if data.get("artist_profile"):
            heading = self.label("ARTIST ALBUMS", "browser-section"); heading.add_css_class("artist-albums-heading"); self.browser_list.append(heading)
            items = [item for item in items if item is not artist_play]
        self.browser_list.set_valign(Gtk.Align.START if data.get("layout") == "list" else Gtk.Align.FILL)
        browser_content = self.browser_artist_scroll.get_parent()
        browser_content.set_homogeneous(False)
        browser_content.set_orientation(Gtk.Orientation.VERTICAL if data.get("artist_profile") and getattr(self, "responsive_portrait", False) else Gtk.Orientation.HORIZONTAL)
        if not items:
            self.browser_list.append(self.label(message or ("Roon Browse is unavailable." if data.get("status") == "unavailable" else "Nothing is available here."), "queue-empty", .5))
        layout = "list" if data.get("artist_profile") else (data.get("layout") or "list")
        if items and data.get("surprise_preview"):
            album = items[0]
            monitor = Gdk.Display.get_default().get_monitors().get_item(0)
            screen_width = monitor.get_geometry().width if monitor else 800
            portrait = getattr(self, "responsive_portrait", False)
            large_display = min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000
            compact_landscape = not portrait and getattr(self, "viewport_width", 800) < 1000
            original = compact_landscape and screen_width <= 820
            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0 if original else 12); preview.set_halign(Gtk.Align.CENTER); preview.set_hexpand(True)
            preview.set_margin_top(round(getattr(self, "viewport_height", 1280) * .05) if portrait else 18 if original else 12)
            size = max(100, min(760 if large_display else 480, screen_width - (96 if portrait else 350 if original else 360 if compact_landscape else 400), self.browser_scroll.get_allocated_height() - (640 if large_display and portrait else 500 if portrait else 92 if original else 90 if compact_landscape else 135)))
            picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
            square = Gtk.ScrolledWindow(); square.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); square.set_propagate_natural_width(False); square.set_propagate_natural_height(False); square.set_min_content_width(size); square.set_max_content_width(size); square.set_min_content_height(size); square.set_max_content_height(size); square.set_size_request(size, size); square.set_halign(Gtk.Align.CENTER); square.set_child(picture)
            stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL, spacing=38 if portrait else 40); stage.set_halign(Gtk.Align.CENTER); stage.set_valign(Gtk.Align.CENTER)
            play_controls = None
            for caption, icon, action in (("Surprise Again" if portrait else "Surprise Me", "view-refresh-symbolic", "surprise"), ("Play Now", "media-playback-start-symbolic", "surprise_play")):
                controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10 if original else 16); controls.set_size_request(104 if original else 120, -1); controls.set_valign(Gtk.Align.CENTER); controls.set_halign(Gtk.Align.CENTER)
                button = self.icon_button(icon, lambda _button, value=action: self.request_browser(value), "surprise-action primary-play" if action == "surprise_play" else "surprise-action"); button.set_tooltip_text(caption); button.set_halign(Gtk.Align.CENTER)
                controls.append(button); controls.append(self.label(caption, "surprise-caption", .5))
                if portrait and action == "surprise_play": play_controls = controls
                else: stage.append(controls)
                if action == "surprise": stage.append(square)
            preview.append(stage)
            key = album.get("image_key"); self.browser_artwork_keys.append(key)
            if key:
                # Large previews must not share the 256px scrolling-thumbnail cache.
                self.load_preview_artwork(picture, key)
            else: square.set_child(self.browser_svg_icon("music"))
            title = self.label(album.get("title") or "Untitled", "surprise-title", .5); title.set_wrap(True); title.set_lines(2); title.set_max_width_chars(40); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_justify(Gtk.Justification.CENTER); title.set_margin_top(14 if original else 0); preview.append(title)
            artist = self.label(album.get("subtitle") or "", "surprise-artist", .5); artist.set_ellipsize(Pango.EllipsizeMode.END); artist.set_max_width_chars(40); preview.append(artist)
            if play_controls:
                play_controls.set_margin_top(round(getattr(self, "viewport_height", 1280) * .072)); preview.append(play_controls)
            self.browser_list.append(preview)
        elif items and layout in {"home", "menu"}:
            grid = Gtk.Grid(column_spacing=12, row_spacing=12); grid.add_css_class("browser-home-grid"); grid.set_column_homogeneous(True); grid.set_row_homogeneous(True); columns = 4 if not getattr(self, "responsive_portrait", False) or getattr(self, "viewport_width", 800) >= 1000 else 2
            if getattr(self, "responsive_portrait", False): grid.set_valign(Gtk.Align.START); grid.set_vexpand(False)
            for index, item in enumerate(item for item in items if item.get("hint") != "header"): grid.attach(self.browser_menu_card(item, layout == "menu"), index % columns, index // columns, 1, 1)
            self.browser_list.append(grid)
        elif items and layout in {"covers", "tiles"}:
            portrait = getattr(self, "responsive_portrait", False)
            grid = Gtk.Grid(column_spacing=24, row_spacing=24); grid.add_css_class("browser-cover-grid"); grid.set_column_homogeneous(False); grid.set_halign(Gtk.Align.START); grid.set_hexpand(False); columns = 5 if layout == "tiles" and active_section == "genres" else 4
            profile = (getattr(self, "system_data", {}) or {}).get("display_profile")
            larger_seven = (not portrait and profile in {"touch2-7", "touch2-5-7"}
                            and (getattr(self, "settings_data", {}) or {}).get("interface_size") == "larger")
            if larger_seven:
                grid.set_column_spacing(23)
            original = not portrait and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
            if original:
                grid.set_column_spacing(12); grid.set_row_spacing(12)
                grid.set_halign(Gtk.Align.START); grid.set_hexpand(False)
            if portrait:
                grid.set_column_spacing(30)
                grid.set_row_spacing(30)
                grid.set_halign(Gtk.Align.START); grid.set_hexpand(False)
            columns, self.browser_tile_size = self.browser_grid_metrics(
                layout == "tiles" and active_section in {"genres", "playlists"},
                active_section == "artists",
            )
            tile_kind = active_section if layout == "tiles" else None
            for index, item in enumerate(item for item in items if item.get("hint") != "header"):
                card = self.browser_cover_card(item, bool(data.get("show_labels")), tile_kind); self.browser_cards.append((card, item)); grid.attach(card, index % columns, index // columns, 1, 1)
            self.browser_list.append(grid)
        else:
            columns = []
            if grouped_search:
                for _ in range(2):
                    column = ElasticVerticalTrack(spacing=2); column.add_css_class("search-column")
                    scroll = Gtk.ScrolledWindow(); scroll.add_css_class("queue-scroll"); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_kinetic_scrolling(True); scroll.set_hexpand(True); scroll.set_vexpand(True); scroll.set_propagate_natural_width(False); scroll.set_propagate_natural_height(False); scroll.set_min_content_width(1); scroll.set_size_request(1, 1); scroll.set_child(column); scroll.get_vadjustment().connect("value-changed", lambda *_: self.load_visible_browser_artwork()); self.browser_search_columns.append(scroll); columns.append(column)
                    column.connect_scroll(scroll)
            else: self.browser_list.set_homogeneous(False)
            group_index = -1; group_count = 0; group_title = ""; target = self.browser_list
            for item in items:
                if item.get("hint") == "header":
                    group_index += 1; group_count = 0; group_title = item.get("title", "")
                    target = columns[1 if item.get("title") in {"ALBUMS", "TRACKS"} else 0] if columns else self.browser_list
                    target.append(self.label(item.get("title") or "", "browser-section")); continue
                if grouped_results and not item.get("title", "").startswith("View all "):
                    group_count += 1
                    if group_count > (3 if getattr(self, "responsive_portrait", False) and group_title == "ARTISTS" else 4): continue
                if item.get("action") and item.get("title", "").strip().lower() == "play playlist":
                    play_playlist = self.labelled_icon_button("play", "Play Playlist", lambda *_args, key=item.get("item_key"): self.open_browser_item(None, key), "artist-play primary-play browser-primary-action")
                    play_playlist.set_sensitive(bool(item.get("item_key"))); play_playlist.set_halign(Gtk.Align.START); target.append(play_playlist); continue
                row = Gtk.Box(spacing=14); row.set_hexpand(True)
                key = item.get("image_key")
                if item.get("action"):
                    action_icon = FamilyIcon(self.browser_action_icon(item.get("title")), 42)
                    action_frame = Gtk.CenterBox(); action_frame.add_css_class("browser-action-icon"); action_frame.set_size_request(84, 84); action_frame.set_hexpand(False); action_frame.set_halign(Gtk.Align.START); action_frame.set_valign(Gtk.Align.CENTER); action_frame.set_center_widget(action_icon); row.append(action_frame)
                elif album_profile:
                    action_icon = FamilyIcon("play", 60 if self.window.has_css_class("large-display") else 40)
                    action_frame = Gtk.CenterBox(); action_frame.add_css_class("browser-action-icon"); action_frame.set_size_request(84, 84); action_frame.set_valign(Gtk.Align.CENTER); action_frame.set_center_widget(action_icon); row.append(action_frame)
                else:
                    picture = Gtk.Picture(); picture.add_css_class("queue-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
                    self.set_browser_placeholder(picture, item.get("result_type") == "artists")
                    # A fixed viewport prevents the texture's natural dimensions
                    # or the number of rows from enlarging album thumbnails.
                    artist_albums = bool(data.get("artist_profile"))
                    original_artist_albums = artist_albums and not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
                    seven_artist_albums = artist_albums and not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_height", 480) <= 720
                    thumb_size = 84 if original_artist_albums else 112 if seven_artist_albums else (210 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 132) if artist_albums else (116 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 84)
                    art_slot = Gtk.ScrolledWindow(); art_slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); art_slot.set_propagate_natural_width(False); art_slot.set_propagate_natural_height(False); art_slot.set_min_content_width(thumb_size); art_slot.set_max_content_width(thumb_size); art_slot.set_min_content_height(thumb_size); art_slot.set_max_content_height(thumb_size); art_slot.set_size_request(thumb_size, thumb_size); art_slot.set_halign(Gtk.Align.START); art_slot.set_valign(Gtk.Align.CENTER); art_slot.set_child(picture); row.append(art_slot)
                    self.browser_artwork_keys.append(key)
                    if key:
                        self.browser_pictures.setdefault(key, []).append(picture)
                        texture = self.queue_thumbnail_cache.get(key)
                        if texture: picture.set_paintable(texture)
                copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); copy.set_valign(Gtk.Align.CENTER); copy.set_hexpand(True)
                title = self.label(item.get("title") or "Untitled", "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); copy.append(title)
                if data.get("artist_profile"): title.add_css_class("artist-album-title")
                if grouped_results and getattr(self, "responsive_portrait", False):
                    title.set_wrap(True); title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); title.set_lines(2)
                subtitle = self.label(item.get("subtitle") or "Roon", "queue-meta"); subtitle.set_ellipsize(Pango.EllipsizeMode.END); copy.append(subtitle); row.append(copy)
                row.append(self.label(item.get("duration") or "", "browser-arrow", 1))
                button = Gtk.Button(); button.add_css_class("browser-row"); button.set_child(row); button.set_sensitive(bool(item.get("item_key")))
                button.browse_item_key = item.get("item_key")
                button.set_vexpand(False); button.set_valign(Gtk.Align.START)
                if item.get("action"): button.add_css_class("browser-action")
                button.connect("clicked", self.open_browser_item, item.get("item_key")); target.append(button)
        GLib.timeout_add(100, self.load_visible_browser_artwork)
        GLib.timeout_add(60, self.finish_browser_render)
        return False

    def finish_browser_render(self):
        # Restore the old view before dispatching the next section/letter.
        # Otherwise an older restore callback can move a newer page's cursor.
        if self.browser_scroll_restore is not None: self.restore_browser_scroll()
        self.browser_rendering = False; self.browser_loading = False; self.sync_browser_scrubber()
        GLib.timeout_add(120, self.maybe_load_more_browser)
        pending = getattr(self, "browser_pending_request", None)
        if pending:
            self.browser_pending_request = None
            self.request_browser(pending[0], **pending[1])
        return False

    def restore_browser_scroll(self):
        self.browser_rendering = True
        value = self.browser_scroll_restore; self.browser_scroll_restore = None
        previous_height = getattr(self, "browser_previous_height", None)
        if previous_height is not None:
            value = (value or 0) + self.browser_scroll.get_vadjustment().get_upper() - previous_height
            self.browser_previous_height = None
        if value is not None: self.browser_scroll.get_vadjustment().set_value(value)
        self.browser_rendering = False
        self.sync_browser_scrubber()
        return False

    def schedule_scroll_artwork(self, name, callback):
        # Scrolling remains native; bound visibility scans/image jobs instead
        # of walking every card on every touch/kinetic animation frame.
        attribute = "scroll_artwork_" + name
        if getattr(self, attribute, None): return
        def load():
            setattr(self, attribute, None)
            callback()
            return False
        setattr(self, attribute, GLib.timeout_add(80, load))

    def browser_scrolled(self, *_):
        if self.browser_rendering or self.browser_loading or self.browser_scroll_restore is not None or getattr(self, "browser_scrub_timer", None): return
        self.schedule_scroll_artwork("browser", self.load_visible_browser_artwork)
        self.schedule_scroll_artwork("scrubber", self.update_scrolled_scrubber)
        if not self.browser_rendering: self.maybe_load_more_browser()

    def update_scrolled_scrubber(self):
        if self.browser_state and getattr(self, "browser_scrubber_active", False):
            value = self.browser_scroll.get_vadjustment().get_value()
            for card, item in getattr(self, "browser_cards", []):
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() > value:
                    self.sync_browser_scrubber(item); break
            if value < 40 and self.browser_state.get("offset", 0) > 0: self.request_browser("previous")
        return False

    def browser_previous_scroll(self, _controller, _dx, dy):
        if dy < 0 and self.browser_scroll.get_vadjustment().get_value() < 40 and (self.browser_state or {}).get("offset", 0) > 0 and not self.browser_loading:
            self.request_browser("previous")
        return False

    def maybe_load_more_browser(self):
        adjustment = self.browser_scroll.get_vadjustment()
        remaining = adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size()
        if self.browser_state and self.browser_state.get("has_more") and remaining < 220 and not self.browser_loading and not self.browser_rendering:
            self.request_browser("more")
        return False

    def render_details(self, details):
        signature = json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)
        if signature == self.detail_signature: return
        self.detail_signature = signature
        self.detail_title.set_text(details.get("album") or details.get("track") or "Nothing playing")
        detail_artist = details.get("artist") or ""
        self.detail_artist.set_text(detail_artist); self.detail_artist.set_visible(bool(detail_artist) and getattr(self, "album_focus_detail", False))
        self.detail_artist_name.set_text(details.get("artist") or "Unknown artist")
        profile = self.detail_artist_profile if self.detail_artist_profile_name == (details.get("artist") or "") else {}
        self.detail_artist_writeup.set_text(profile.get("full_writeup") or profile.get("writeup") or "Artist information is unavailable.")
        self.detail_artist_source.set_text(""); self.detail_artist_source.set_visible(False)
        while child := self.detail_artist_facts.get_first_child(): self.detail_artist_facts.remove(child)
        artist_facts = []
        if profile.get("type"): artist_facts.append(f"TYPE  {profile['type']}")
        formed = profile.get("formed") or ""
        if formed: artist_facts.append(f"FORMED  {formed}" + (f"  ·  ENDED  {profile['ended']}" if profile.get("ended") else ""))
        place = " · ".join(value for value in (profile.get("area"), profile.get("country")) if value)
        if place: artist_facts.append(f"FROM  {place}")
        if profile.get("genres"): artist_facts.append(f"GENRES  {' · '.join(profile['genres'])}")
        for fact in artist_facts:
            label = self.label(fact, "detail-fact"); label.set_wrap(True); self.detail_artist_facts.append(label)
        self.detail_artist_action.set_sensitive(bool(details.get("artist")))
        self.detail_album_action.set_sensitive(bool(details.get("artist")))
        self.detail_browse_action.set_sensitive(bool(details.get("artist")))
        subtitle = re.sub(r"\[\[\d+\|([^\]]+)\]\]", r"\1", details.get("subtitle") or "")
        if subtitle.strip().casefold() == (details.get("artist") or "").strip().casefold(): subtitle = ""
        detail_subtitle = "" if details.get("status") == "loading" else subtitle
        self.library_status = details.get("library_status") or "unknown"
        if self.library_album_id != details.get("album_id") and not self.library_pending: self.library_message.set_visible(False)
        self.library_album_id = details.get("album_id"); self.library_favorite = details.get("favorite")
        if details.get("library_error") and not self.library_pending:
            self.library_message.set_text(details["library_error"]); self.library_message.set_visible(True)
        has_album = bool(details.get("album")) and details.get("status") != "loading"
        self.library_add.set_visible(has_album)
        self.library_add.set_sensitive(has_album and self.library_status != "unknown" and not self.library_pending and not details.get("library_busy") and (self.library_status != "in_library" or self.library_favorite is not None))
        self.set_library_busy(self.library_pending or bool(details.get("library_busy")))
        self.set_library_icon(self.library_favorite is True)
        metadata = details.get("metadata") or {}
        released = str(metadata.get("release_date") or metadata.get("year") or "")
        year = released[:4] if released else ""
        release_label = release_period_label(released)
        release_type = release_type_label(metadata)
        detail_heading = f"{release_type} · {release_label}" if release_label else release_type
        self.detail_album_section_label.set_text(detail_heading)
        if getattr(self, "detail_year_only", False):
            detail_subtitle = ""
        self.detail_subtitle.set_text(detail_subtitle); self.detail_subtitle.set_visible(bool(detail_subtitle))
        for heading in (self.detail_artist_name, self.detail_title): heading.set_size_request(-1, -1)
        if getattr(self, "large_detail_portrait", False):
            # Measure against the real card width. An unconstrained measure can
            # claim an album title fits on one line, only for GTK to wrap it
            # after allocation and push the album write-up below the artist's.
            heading_width = max(1, getattr(self, "detail_heading_width", 500))
            heading_height = max(heading.measure(Gtk.Orientation.VERTICAL, heading_width)[1] for heading in (self.detail_artist_name, self.detail_title))
            for heading in (self.detail_artist_name, self.detail_title): heading.set_size_request(-1, heading_height)
        writeup = metadata.get("full_writeup") or metadata.get("writeup") or ""; self.detail_writeup.set_text(writeup); self.detail_writeup.set_visible(bool(writeup))
        self.detail_source.set_text(""); self.detail_source.set_visible(False)
        while child := self.detail_facts.get_first_child(): self.detail_facts.remove(child)
        facts = []
        if metadata.get("release_date") or metadata.get("year"): facts.append(f"RELEASED  {metadata.get('release_date') or metadata.get('year')}")
        if metadata.get("genres"): facts.append(f"GENRE  {' · '.join(metadata['genres'])}")
        if metadata.get("type"): facts.append(f"TYPE  {metadata['type']}")
        if metadata.get("label"): facts.append(f"LABEL  {metadata['label']}")
        if metadata.get("format"): facts.append(f"FORMAT  {metadata['format']}")
        summary = []
        if metadata.get("track_count"): summary.append(f"{metadata['track_count']} TRACKS")
        if metadata.get("country"): summary.append(str(metadata["country"]))
        if metadata.get("edition_count", 0) > 1: summary.append(f"{metadata['edition_count']} EDITIONS")
        if summary: facts.append("  ·  ".join(summary))
        for fact in facts:
            label = self.label(fact, "detail-fact"); label.set_wrap(True); self.detail_facts.append(label)
        self.detail_facts.set_visible(
            not getattr(self, "album_focus_detail", False)
            and not getattr(self, "original_landscape", False)
            and not getattr(self, "large_detail_portrait", False)
        )
        while child := self.detail_tracks.get_first_child(): self.detail_tracks.remove(child)
        for index, track in enumerate((details.get("tracks") or [])[:30], 1):
            row = Gtk.Box(spacing=8); row.add_css_class("detail-track"); row.append(self.label(str(index), "detail-track-no")); title = self.label(track.get("title") or "Untitled track", "detail-track-title"); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_hexpand(True); row.append(title); self.detail_tracks.append(row)
        self.detail_tracks.set_visible(False)

    def render_queue(self, queue):
        items = queue.get("items") or []
        signature = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str)
        if signature == self.queue_signature: return
        self.queue_signature = signature; self.queue_pictures = {}; self.queue_artwork_keys = []; self.queue_play_badges = {}
        while child := self.queue_list.get_first_child(): self.queue_list.remove(child)
        if not items:
            if queue.get("status") == "loading":
                self.queue_list.append(self.loading_notice())
            else:
                self.queue_list.append(self.label("Nothing is queued", "queue-empty", .5))
            return
        self.queue_current_index = 0
        for index, item in enumerate(items):
            row = Gtk.Box(spacing=12); row.set_hexpand(True)
            artwork = Gtk.Overlay(); artwork.add_css_class("queue-art-stack"); artwork.set_size_request(66, 66)
            picture = Gtk.Picture(); picture.add_css_class("queue-art"); picture.set_size_request(66, 66); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); artwork.set_child(picture)
            if item.get("is_current"):
                playing = FamilyIcon("play", 76 if getattr(self, "viewport_width", 800) >= 1000 else 48, filled=True); playing.add_css_class("queue-play-badge"); playing.set_halign(Gtk.Align.CENTER); playing.set_valign(Gtk.Align.CENTER); artwork.add_overlay(playing)
                self.queue_play_badges.setdefault(item.get("image_key"), []).append(playing)
                if getattr(self, "queue_artwork_light", {}).get(item.get("image_key"), False): playing.add_css_class("light-art")
            row.append(artwork)
            key = item.get("image_key")
            self.queue_artwork_keys.append(key)
            if key:
                self.queue_pictures.setdefault(key, []).append(picture)
                texture = self.queue_thumbnail_cache.get(key)
                if texture: picture.set_paintable(texture)
            detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); detail.set_valign(Gtk.Align.CENTER); detail.set_hexpand(True)
            title = self.label(item.get("title") or "Untitled track", "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); detail.append(title)
            meta = " · ".join(filter(None, (item.get("artist"), item.get("album"))))
            metadata = self.label(meta or "Roon", "queue-meta"); metadata.set_ellipsize(Pango.EllipsizeMode.END); detail.append(metadata); row.append(detail)
            length = item.get("length"); row.append(self.label(self.format_time(int(length)) if length else "", "queue-duration", 1))
            button = Gtk.Button(); button.add_css_class("queue-row"); button.set_child(row); button.set_focus_on_click(False)
            if item.get("is_current"): button.add_css_class("current"); self.queue_current_index = index
            elif item.get("is_previous"): button.add_css_class("previous"); button.connect("clicked", self.play_queue_item, item.get("queue_item_id"))
            else: button.connect("clicked", self.play_queue_item, item.get("queue_item_id"))
            self.queue_list.append(button)
        GLib.idle_add(self.load_visible_queue_artwork)

    def scroll_queue_to_current(self):
        row_height = 104 if self.window.has_css_class("high-resolution") else 90
        self.queue_scroll.get_vadjustment().set_value(max(0, getattr(self, "queue_current_index", 0) * row_height))
        return False

    def load_visible_queue_artwork(self, *_):
        adjustment = self.queue_scroll.get_vadjustment()
        row_height = 88 if self.window.has_css_class("high-resolution") else 68
        start = max(0, int(adjustment.get_value() / row_height) - 2)
        count = max(8, int(adjustment.get_page_size() / row_height) + 5)
        for key in self.queue_artwork_keys[start:start + count]:
            if key and key not in self.queue_thumbnail_cache and key not in self.queue_thumbnail_pending:
                self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False

    def load_visible_browser_artwork(self, *_):
        adjustment = self.browser_scroll.get_vadjustment()
        if self.browser_state and self.browser_state.get("search_routes"):
            # Grouped previews are bounded (four rows per group). Load all
            # their artwork rather than consulting the hidden single scroller.
            for key in self.browser_artwork_keys:
                if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                    self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
            return False
        cards = getattr(self, "browser_cards", [])
        if cards:
            keys = []
            for card, item in cards:
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() >= adjustment.get_value() - 220 and bounds.get_y() <= adjustment.get_value() + adjustment.get_page_size() + 220: keys.append(item.get("image_key"))
            for key in keys:
                if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                    self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
            return False
        row_height = 100 if self.window.has_css_class("high-resolution") else 68
        start = max(0, int(adjustment.get_value() / row_height) - 2)
        count = max(8, int(adjustment.get_page_size() / row_height) + 5)
        for key in self.browser_artwork_keys[start:start + count]:
            if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False

    def thumbnail_worker(self):
        while True:
            key = self.queue_thumbnail_jobs.get()
            hero_size = 1200 if key in self.artist_hero_keys else 256
            url = f"{ROON}/api/discovery/image?key={quote(key[9:], safe='')}" if key.startswith("discover:") else f"{ROON}/api/image?key={quote(key, safe='')}&size={hero_size}"
            image = get_bytes(url, timeout=6.0 if key in self.artist_hero_keys else 2.5)
            if image:
                if not hasattr(self, "queue_artwork_light"): self.queue_artwork_light = {}
                self.queue_artwork_light[key] = self.artwork_is_light(image)
            artist_hero = self.decode_artist_hero_artwork(image) if key in self.artist_hero_keys else None
            GLib.idle_add(self.apply_queue_thumbnail, key, self.decode_artwork(image), True, artist_hero, image)

    def artwork_is_light(self, image):
        try:
            loader = GdkPixbuf.PixbufLoader.new(); loader.write(image); loader.close()
            pixbuf = loader.get_pixbuf(); pixels = pixbuf.get_pixels()
            width, height, stride, channels = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride(), pixbuf.get_n_channels()
            values = []
            # Sample the central artwork beneath the marker, not its border.
            for fy in (.35, .45, .55, .65):
                for fx in (.35, .45, .55, .65):
                    offset = int(height * fy) * stride + int(width * fx) * channels
                    red, green, blue = pixels[offset:offset + 3]
                    values.append(.2126 * red + .7152 * green + .0722 * blue)
            return sum(values) / len(values) >= 145
        except (GLib.Error, ValueError, TypeError): return False

    def decode_artwork(self, image):
        # Gdk.Texture loading is thread-safe. Keep image decoding out of the
        # touch/animation loop; only widget updates belong on the UI thread.
        if not image: return None
        try: return Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
        except GLib.Error: return None

    def decode_artist_hero_artwork(self, image):
        """Return the top-weighted crop used by the taller seven-inch hero."""
        if not image: return None
        try:
            loader = GdkPixbuf.PixbufLoader.new(); loader.write(image); loader.close()
            source = loader.get_pixbuf()
            width, height = source.get_width(), source.get_height()
            if width <= 0 or height <= 0: return None
            hero_ratio = .66 if getattr(self, "original_landscape", False) else .68
            target_ratio = 1 / hero_ratio
            if width / height > target_ratio:
                crop_height = height; crop_width = max(1, round(height * target_ratio))
                crop_x = max(0, round((width - crop_width) / 2)); crop_y = 0
            else:
                crop_width = width; crop_height = max(1, round(width / target_ratio))
                crop_x = 0
                # Keep faces higher while preserving the exact hero window.
                crop_y = max(0, round((height - crop_height) * .4))
            cropped = source.new_subpixbuf(crop_x, crop_y, crop_width, crop_height)
            scaled_height = round(960 * hero_ratio)
            scaled = cropped.scale_simple(960, scaled_height, GdkPixbuf.InterpType.BILINEAR)
            # Fade the photograph itself to transparent. Painting a black
            # gradient over it only works on the default black theme and
            # exposes a rectangular edge on user-selected backgrounds.
            output, output_stride = fade_rgba_pixels(scaled.get_pixels(), 960, scaled_height, scaled.get_rowstride(), scaled.get_n_channels())
            faded = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(output), GdkPixbuf.Colorspace.RGB, True, 8, 960, scaled_height, output_stride)
            return Gdk.Texture.new_for_pixbuf(faded)
        except (GLib.Error, ValueError, TypeError): return None

    def load_preview_artwork(self, picture, key):
        if cached := self.preview_artwork_cache.get(key):
            picture.set_paintable(cached)
            return
        def apply(texture):
            if texture:
                self.preview_artwork_cache[key] = texture
                if picture.get_root() is not None: picture.set_paintable(texture)
            return False
        def load():
            url = f"{ROON}/api/discovery/image?key={quote(key[9:], safe='')}" if key.startswith("discover:") else f"{ROON}/api/image?key={quote(key, safe='')}&size=900"
            GLib.idle_add(apply, self.decode_artwork(get_bytes(url, timeout=5)))
        threading.Thread(target=load, daemon=True).start()

    def apply_queue_thumbnail(self, key, image, decoded=False, artist_hero=None, source=None):
        self.queue_thumbnail_pending.discard(key)
        if not image:
            failures = getattr(self, "thumbnail_failures", {}); self.thumbnail_failures = failures; failures[key] = failures.get(key, 0) + 1
            if failures[key] <= 3: GLib.timeout_add(1500, self.retry_visible_thumbnail, key)
            return False
        texture = image if decoded else self.decode_artwork(image)
        if texture is None: return False
        self.queue_thumbnail_cache[key] = texture
        if source is not None: self.queue_thumbnail_source[key] = source
        if artist_hero is not None: self.artist_hero_cache[key] = artist_hero
        getattr(self, "thumbnail_failures", {}).pop(key, None)
        if key in self.queue_thumbnail_order: self.queue_thumbnail_order.remove(key)
        self.queue_thumbnail_order.append(key)
        while len(self.queue_thumbnail_order) > 192:
            old = self.queue_thumbnail_order.pop(0); self.queue_thumbnail_cache.pop(old, None); self.artist_hero_cache.pop(old, None); self.queue_thumbnail_source.pop(old, None)
            getattr(self, "queue_artwork_light", {}).pop(old, None)
        for picture in self.queue_pictures.get(key, []): picture.set_paintable(texture)
        for badge in getattr(self, "queue_play_badges", {}).get(key, []):
            if getattr(self, "queue_artwork_light", {}).get(key, False): badge.add_css_class("light-art")
            else: badge.remove_css_class("light-art")
        for picture in self.browser_pictures.get(key, []):
            picture.set_paintable(self.artist_hero_cache.get(key, texture) if getattr(picture, "artist_hero", False) else texture)
        for picture in self.discovery_pictures.get(key, []): picture.set_paintable(texture)
        return False

    def retry_visible_thumbnail(self, key):
        needs_image = key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)
        if (self.browser_pictures.get(key) or self.queue_pictures.get(key) or self.discovery_pictures.get(key)) and needs_image and key not in self.queue_thumbnail_pending:
            self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False

    def play_queue_item(self, _button, queue_item_id):
        if queue_item_id is not None:
            threading.Thread(target=post_json, args=(ROON + "/api/queue/play", {"queue_item_id": queue_item_id}), daemon=True).start()

    def set_mode(self, mode):
        started = time.monotonic(); self.settings_open = False; self.last_mode = mode; self.pending_mode = mode; self.pending_mode_started_at = started; self.stack.set_visible_child_name(mode); print(f"RoonDeck switched to {mode} in {(time.monotonic() - started) * 1000:.1f}ms", flush=True); threading.Thread(target=post_json, args=(BUS + "/api/admin/display-mode", {"mode": mode}), daemon=True).start()

    def note_missing_artwork(self):
        self.image_misses += 1
        if self.image_misses >= 5:
            self.set_browser_placeholder(self.artwork)
            self.image_key = None

    def open_settings(self, *_): self.settings_open = True; self.last_system_fetch = 0; self.stack.set_visible_child_name("settings"); self.start_poll()
    def close_settings(self, *_): self.settings_open = False; self.stack.set_visible_child_name(self.last_mode)
    def note_activity(self, _controller, event):
        if event is None: return False
        # Legacy controllers also receive pointer motion, enter/leave and window
        # events. A powered-down panel can consume the beginning of the first
        # contact, so accept its release as a wake gesture as well.
        event_type = event.get_event_type()
        contact_started = event_type in {Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.KEY_PRESS}
        contact_finished = event_type in {Gdk.EventType.BUTTON_RELEASE, Gdk.EventType.TOUCH_END}
        if not contact_started and not contact_finished:
            return False
        self.last_interaction = time.monotonic()
        if (self.stack.get_visible_child_name() == "roon"
                and (self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
                     or (hasattr(self, "detail_takeover") and self.detail_takeover.get_visible()))):
            self.browse_last_interaction = self.last_interaction
        if self.inactivity_sleeping:
            source = getattr(event_type, "value_nick", str(event_type))
            self.inactivity_sleeping = False; print(f"RoonDeck waking after touchscreen {source}", flush=True); self.set_screen_power(True, force=True); self.stack.set_visible_child_name(self.last_mode or "bus")
        elif self.stack.get_visible_child_name() == "sleep" and time.monotonic() - self.sleep_entered_at >= .45:
            self.wake(getattr(event_type, "value_nick", str(event_type)))
        return False

    def prepare_sleep_wake(self):
        # Ignore only the short tail of the gesture that pressed Sleep. Using a
        # timestamp avoids depending on a delayed GLib arming callback, which
        # could leave manual sleep permanently unable to accept a wake touch.
        self.sleep_entered_at = time.monotonic()

    def sleep(self, *_):
        self.inactivity_sleeping = False; self.settings_open = False
        self.manual_sleep_pending = True; self.manual_sleep_started_at = time.monotonic()
        self.prepare_sleep_wake(); self.stack.set_visible_child_name("sleep")
        self.set_screen_power(bool(self.settings_data.get("sleep_show_clock", False)))
        print("RoonDeck manual sleep requested", flush=True)
        threading.Thread(target=self.request_manual_sleep, daemon=True).start()

    def request_manual_sleep(self):
        for attempt in range(3):
            if post_json(BUS + "/api/admin/display-mode", {"mode": "sleep"}):
                GLib.idle_add(self.start_poll)
                return
            if attempt < 2: time.sleep(.35)
        GLib.idle_add(self.manual_sleep_failed)

    def manual_sleep_failed(self):
        if self.manual_sleep_pending:
            self.manual_sleep_pending = False
            print("RoonDeck manual sleep request failed after three attempts", flush=True)
            self.set_screen_power(True, force=True)
            self.stack.set_visible_child_name(self.last_mode or "bus")
        return False

    def wake(self, *_):
        now = time.monotonic()
        source = _[0] if _ else "input"
        self.manual_sleep_pending = False; self.sleep_entered_at = 0.0; self.last_interaction = now; self.inactivity_sleeping = False; print(f"RoonDeck waking after fresh touchscreen {source}", flush=True); self.set_screen_power(True, force=True); self.stack.set_visible_child_name(self.last_mode or "bus")
        threading.Thread(target=post_json, args=(BUS + "/api/device/wake", {"view": self.last_mode or "bus"}), daemon=True).start()
    def control(self, action):
        if action == "playpause" and (((self.state or {}).get("amplifier") or {}).get("active_input")): action = "resume"
        threading.Thread(target=post_json, args=(ROON + "/api/control", {"action": action}), daemon=True).start()
    def add_current_album(self, *_):
        if self.library_pending or self.library_status == "unknown" or not self.library_album_id: return
        album_id = self.library_album_id
        favorite_action = self.library_status == "in_library"
        if favorite_action and self.library_favorite is None: return
        payload = {"album_id": album_id}
        if favorite_action: payload["favorite"] = not self.library_favorite
        self.library_pending = True; self.library_message.set_visible(False)
        self.set_library_busy(True)
        self.library_add.set_sensitive(False)
        def run():
            try:
                request = urllib.request.Request(ROON + ("/api/library/favorite" if favorite_action else "/api/library/add"), data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=25.0) as response: result = json.load(response)
            except urllib.error.HTTPError as error:
                try: result = json.load(error)
                except Exception: result = {"error": "Roon did not confirm the change. Check Roon before retrying."}
            except Exception: result = {"error": "Roon did not confirm the change. Check Roon before retrying."}
            def finish():
                self.library_pending = False
                self.set_library_busy(False)
                if album_id == self.library_album_id:
                    if result.get("library_status"):
                        self.library_status = result["library_status"]; self.library_favorite = result.get("favorite"); self.set_library_icon(self.library_favorite is True)
                    self.library_message.set_text(result.get("error") or ""); self.library_message.set_visible(bool(result.get("error")))
                else: self.library_message.set_visible(False)
                self.library_add.set_sensitive(self.library_status != "unknown" and (self.library_status != "in_library" or self.library_favorite is not None))
                return False
            GLib.idle_add(finish)
        threading.Thread(target=run, daemon=True).start()

    def set_library_busy(self, busy):
        (self.library_add.add_css_class if busy else self.library_add.remove_css_class)("library-busy")
        self.library_add.update_state([Gtk.AccessibleState.BUSY], [busy])

    def set_library_icon(self, filled):
        size = 64 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 28
        if getattr(self, "library_status", "unknown") != "in_library":
            icon = FamilyIcon("add", size); icon.set_size_request(size, size)
            self.library_add.set_child(icon); self.library_add.set_tooltip_text("Loading library status…" if getattr(self, "library_status", "unknown") == "unknown" else "Add album to library")
            return
        icon = FamilyIcon("heart", size, filled=filled)
        icon.set_pixel_size(size); icon.set_size_request(size, size)
        self.library_add.set_child(icon)
        self.library_add.set_tooltip_text("Unfavourite album" if filled else "Favourite album")
    def toggle_bridge(self, button):
        requested = button.get_active(); button.set_sensitive(False)
        threading.Thread(target=self._toggle_bridge, args=(button, requested), daemon=True).start()
    def _toggle_bridge(self, button, requested):
        result = post_json(BUS + "/api/device/roon-bridge", {"enabled": requested}, timeout=110)
        def finish():
            if not result:
                button.handler_block_by_func(self.toggle_bridge)
                button.set_active(not requested)
                button.handler_unblock_by_func(self.toggle_bridge)
                self.touch_diagnostics.set_text("Could not change Roon Bridge. Check backend Tools for service status.")
            self.touch_controls_signature = None
            self.last_system_fetch = 0
            button.set_sensitive(True)
            return False
        GLib.idle_add(finish)
    def toggle_netdata(self, button):
        requested = button.get_active(); button.set_sensitive(False)
        threading.Thread(target=self._toggle_netdata, args=(button, requested), daemon=True).start()
    def _toggle_netdata(self, button, requested):
        result = post_json(BUS + "/api/device/netdata", {"enabled": requested}, timeout=20)
        def finish():
            if not result:
                button.handler_block_by_func(self.toggle_netdata); button.set_active(not requested); button.handler_unblock_by_func(self.toggle_netdata)
                self.touch_diagnostics.set_text("Could not change Netdata. Check backend Tools for service status.")
            self.touch_controls_signature = None; self.last_system_fetch = 0; button.set_sensitive(True)
            return False
        GLib.idle_add(finish)
    def change_background(self, selected):
        if selected == self.settings_data.get("display_background", "current"): return
        for button in self.touch_background_buttons.values(): button.set_sensitive(False)
        def save():
            result = post_json(f"{BUS}/api/admin/config", {"section": "appearance", "display_background": selected}, timeout=3)
            def finish():
                for button in self.touch_background_buttons.values(): button.set_sensitive(True)
                if not result: self.touch_diagnostics.set_text("Could not save the background. Please try again.")
                self.last_config_fetch = 0
                return False
            GLib.idle_add(finish)
        threading.Thread(target=save, daemon=True).start()
    def change_interface_size(self, dropdown, *_):
        if getattr(self, "interface_size_updating", False): return
        values = ("smaller", "standard", "larger"); value = values[min(dropdown.get_selected(), 2)]
        self.apply_interface_size(value)
        # Several layouts have finite line counts and physical-pixel budgets.
        # Recalculate them immediately when scaling changes instead of waiting
        # for a resize/config poll; otherwise the previous size's allocations
        # can leave the seven-inch page scrollable until it is revisited.
        GLib.idle_add(self.adapt_display)
        threading.Thread(target=post_json, args=(f"{BUS}/api/admin/config", {"section": "appearance", "interface_size": value}), kwargs={"timeout": 3}, daemon=True).start()
    def toggle_service(self, button, service):
        threading.Thread(target=post_json, args=(BUS + "/api/device/service-visibility", {"service": service, "enabled": button.get_active()}), daemon=True).start()
    def toggle_bus_visibility(self, button):
        if getattr(self, "bus_visibility_updating", False): return
        requested = button.get_active(); button.set_sensitive(False)
        for nav_button in self.bus_nav_buttons: nav_button.set_visible(requested)
        def save():
            result = post_json(f"{BUS}/api/admin/config", {"section": "bus", "bus_enabled": requested}, timeout=3)
            def finish():
                button.set_sensitive(True)
                if result and not result.get("error"):
                    self.settings_data["bus_enabled"] = requested; self.last_config_fetch = 0
                else:
                    self.bus_visibility_updating = True; button.set_active(not requested); self.bus_visibility_updating = False
                    for nav_button in self.bus_nav_buttons: nav_button.set_visible(not requested)
                    self.touch_diagnostics.set_text("Could not save Bus Times visibility. Please try again.")
                return False
            GLib.idle_add(finish)
        threading.Thread(target=save, daemon=True).start()
    def toggle_home(self, _button, entity_id):
        if entity_id: threading.Thread(target=post_json, args=(BUS + "/api/device/home-toggle", {"entity_id": entity_id}), daemon=True).start()
    def activate_home_scene(self, button, entity_id):
        if not entity_id: return
        button.add_css_class("activated"); button.scene_tile.add_css_class("activated"); button.set_sensitive(False); button.scene_status_label.set_text("ACTIVATING…")
        def send():
            result = post_json(BUS + "/api/device/home-toggle", {"entity_id": entity_id})
            def finish():
                button.scene_status_label.set_text("ACTIVATED" if result and not result.get("error") else "COULD NOT ACTIVATE")
                GLib.timeout_add(900, self.reset_home_scene, button)
                return False
            GLib.idle_add(finish)
        threading.Thread(target=send, daemon=True).start()
    def reset_home_scene(self, button):
        button.remove_css_class("activated"); button.scene_tile.remove_css_class("activated"); button.set_sensitive(True); button.scene_status_label.set_text("TAP TO ACTIVATE"); return False
    def swipe_home_switch(self, _gesture, velocity_x, _velocity_y, entity_id):
        if entity_id and abs(velocity_x) > 80:
            threading.Thread(target=post_json, args=(BUS + "/api/device/home-state", {"entity_id": entity_id, "enabled": velocity_x > 0}), daemon=True).start()
    def change_home_value(self, scale, entity_id):
        if not entity_id: return
        previous = self.home_value_timeouts.pop(entity_id, None)
        if previous is not None: GLib.source_remove(previous)
        self.home_value_timeouts[entity_id] = GLib.timeout_add(260, self.send_home_value, entity_id, round(scale.get_value()))
    def send_home_value(self, entity_id, value):
        self.home_value_timeouts.pop(entity_id, None)
        threading.Thread(target=post_json, args=(BUS + "/api/device/home-value", {"entity_id": entity_id, "value": value}), daemon=True).start()
        return False
    def change_brightness(self, scale):
        self.touch_brightness_value.set_text(f"{round(scale.get_value())}%")
        if self.brightness_updating: return
        if self.brightness_timeout is not None: GLib.source_remove(self.brightness_timeout)
        self.brightness_timeout = GLib.timeout_add(180, self.send_brightness, round(scale.get_value()))
    def send_brightness(self, value):
        self.brightness_timeout = None
        threading.Thread(target=post_json, args=(BUS + "/api/device/brightness", {"brightness": value}), daemon=True).start()
        return False
    def format_time(self, seconds): return f"{seconds // 60}:{seconds % 60:02d}"
    def change_volume(self, scale):
        if self.volume_updating or not self.state: return
        amplifier = self.state.get("amplifier") or {}
        if amplifier.get("connected"):
            threading.Thread(target=post_json, args=(ROON + "/api/bluos/volume", {"value": round(scale.get_value())}), daemon=True).start(); return
        output = (self.state.get("zone") or {}).get("output") or {}; output_id = output.get("id")
        if output_id: threading.Thread(target=post_json, args=(ROON + "/api/volume", {"output_id": output_id, "value": round(scale.get_value())}), daemon=True).start()

    def toggle_audio_mute(self, *_):
        if not self.state: return
        amplifier = self.state.get("amplifier") or {}
        if amplifier.get("connected"): threading.Thread(target=post_json, args=(ROON + "/api/bluos/mute", {}), daemon=True).start(); return
        output = (self.state.get("zone") or {}).get("output") or {}; output_id = output.get("id")
        if output_id: threading.Thread(target=post_json, args=(ROON + "/api/mute", {"output_id": output_id}), daemon=True).start()

    def change_seek(self, scale):
        if self.seek_updating or not self.state or not (self.state.get("zone") or {}).get("can_seek"):
            return
        if self.seek_timeout is not None:
            GLib.source_remove(self.seek_timeout)
        self.seek_timeout = GLib.timeout_add(220, self.send_seek, round(scale.get_value()))

    def send_seek(self, seconds):
        self.seek_timeout = None
        threading.Thread(target=post_json, args=(ROON + "/api/seek", {"seconds": seconds}), daemon=True).start()
        return False

    def set_screen_power(self, powered, force=False):
        if powered == self.screen_powered and not force:
            return
        self.screen_powered = powered
        threading.Thread(target=post_json, args=(BUS + "/api/device/screen-power", {"powered": powered}), daemon=True).start()
        GLib.timeout_add_seconds(1 if powered else 2, self.confirm_screen_power, powered)

    def confirm_screen_power(self, powered):
        if self.screen_powered is powered:
            threading.Thread(target=post_json, args=(BUS + "/api/device/screen-power", {"powered": powered}), daemon=True).start()
        return False

    def request_update(self, *_):
        self.update_in_progress = True; self.update_status_seen = False; self.update_button.set_sensitive(False); self.device_status.set_text("Update · Requesting installation…")
        threading.Thread(target=self._request_update, daemon=True).start()

    def hide_widget_cursor(self, widget):
        widget.set_cursor_from_name("none")
        child = widget.get_first_child()
        while child:
            self.hide_widget_cursor(child)
            child = child.get_next_sibling()

    def hide_native_cursor(self, widget):
        """Hide the cursor on a newly-mapped popover's separate native surface."""
        self.hide_widget_cursor(widget)
        try:
            native = widget.get_native()
            surface = native.get_surface() if native else None
            if surface: surface.set_cursor(Gdk.Cursor.new_from_name("none", None))
        except (AttributeError, TypeError, GLib.Error):
            pass
        return False

    def hide_touch_cursor(self):
        # Child widgets and newly-created popover surfaces can override the
        # window cursor. Include every current descendant on each pass.
        self.hide_widget_cursor(self.window)
        return True

    def confirm_reboot(self, *_):
        if getattr(self, "reboot_confirmation", None): return
        shade = Gtk.Overlay(); shade.add_css_class("confirm-shade"); shade.set_hexpand(True); shade.set_vexpand(True)
        backdrop = Gtk.Box(); backdrop.set_hexpand(True); backdrop.set_vexpand(True); shade.set_child(backdrop)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); card.add_css_class("confirm-card"); card.set_halign(Gtk.Align.CENTER); card.set_valign(Gtk.Align.CENTER)
        card.set_margin_bottom(round(self.window.get_height() * .08))
        card.append(self.label("Restart RoonDeck?", "confirm-title", .5)); card.append(self.label("The touchscreen will be unavailable for about a minute.", "confirm-copy", .5))
        actions = Gtk.Box(spacing=12); actions.set_halign(Gtk.Align.CENTER)
        def close(*_):
            self.root_overlay.remove_overlay(shade); self.reboot_confirmation = None
        def restart(button):
            button.set_sensitive(False); self.device_status.set_text("Restarting RoonDeck…")
            threading.Thread(target=post_json, args=(BUS + "/api/device/reboot", {}), daemon=True).start()
        actions.append(self.button("CANCEL", close, "confirm-cancel")); actions.append(self.button("RESTART", restart, "confirm-reboot")); card.append(actions); shade.add_overlay(card)
        self.reboot_confirmation = shade; self.root_overlay.add_overlay(shade); shade.set_cursor_from_name("none")

    def _request_update(self):
        result = post_json(BUS + "/api/device/update", {})
        queued = bool(result and result.get("queued", True))
        GLib.idle_add(self.device_status.set_text, "Update · Queued…" if queued else ("Update already running…" if result else "Could not start update"))
        if result:
            # The POST confirms only that the helper was queued. On a slower
            # Pi, an overlapping system poll can still contain the old Ready
            # state. Do not treat progress as observed until apply() receives
            # a real Update · status, or that stale response will end fast
            # polling and replace the queued message with the version label.
            self.last_system_fetch = 0
            GLib.idle_add(self.start_poll)
        else:
            self.update_in_progress = False
            GLib.idle_add(self.update_button.set_sensitive, True)

    def request_display_settings(self, *_):
        profiles = ("original", "touch2-5", "touch2-7", "touch2-10"); orientations = ("landscape", "portrait"); mountings = ("standard", "inverted")
        profile = profiles[min(self.touch_profile.get_selected(), len(profiles) - 1)]; orientation = orientations[min(self.touch_orientation.get_selected(), len(orientations) - 1)]; mounting = mountings[min(self.touch_mounting.get_selected(), len(mountings) - 1)]
        self.apply_display_button.set_sensitive(False); self.device_status.set_text("Applying display settings…")
        threading.Thread(target=self._request_display_settings, args=(profile, orientation, mounting), daemon=True).start()

    def _request_display_settings(self, profile, orientation, mounting):
        result = post_json(BUS + "/api/admin/system-action", {"action": "set_display", "profile": profile, "orientation": orientation, "mounting": mounting}, timeout=15)
        GLib.idle_add(self.device_status.set_text, "Display saved · restarting RoonDeck…" if result else "Could not apply display settings")
        if not result: GLib.idle_add(self.apply_display_button.set_sensitive, True)


if __name__ == "__main__":
    publish_display_source()
    Display().run(None)
