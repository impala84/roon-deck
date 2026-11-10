"""Landscape Home page: one grid (2 or 3 columns) holding the player card, the next bus and the device cards.

Used on the 7-inch and larger landscape displays. The original 800x480 panel and portrait displays keep the
classic tile grid in home_page.py.
"""
from __future__ import annotations

from native_common import FamilyIcon, BUS, ROON, get_json, post_json
from home_page import tile_colour_rules
import os
import threading
import types
from pathlib import Path
from gi.repository import GLib, Gtk, Pango

GAP = 18                    # the one gap used between every card, column and row on the page
ROUTE_TINTS = ("blue", "green", "violet", "amber", "rose", "teal")
HOME_BUS_ROUTE = "42"       # shown when the stop serves it; otherwise the stop's first route
CLIMATE_COLOUR = "#4fc3d9"
CARD_DOMAINS = {"light": "light", "fan": "fan", "climate": "snow"}
SAMPLES = 45                # readings kept for the live tiles
SAMPLE_SECONDS = 2
GROUP_KEYS = ("roondeck.group", "roondeck.group2", "roondeck.group3")
ACTION_KEYS = ("roondeck.update",) + GROUP_KEYS   # tiles that do something when tapped
SPARK_GREEN, SPARK_BLUE = (0.43, 0.85, 0.68), (0.42, 0.66, 1.0)


class HomeDashboardMixin:
    def home_big_tiles(self):
        """A tall portrait panel has tiles about 270px high: give their icon and text the size the bus tile has."""
        return self.window.has_css_class("portrait") and getattr(self, "viewport_width", 800) >= 700 and getattr(self, "viewport_height", 480) >= 1200

    def home_dashboard_active(self):
        if self.window.has_css_class("original-landscape"): return False
        if self.window.has_css_class("portrait"): return getattr(self, "viewport_width", 800) >= 700 and getattr(self, "viewport_height", 480) >= 1200   # a tall 7/10-inch panel: two columns, more rows
        return getattr(self, "viewport_width", 800) >= 1000

    def home_scale(self):
        return max(1.0, getattr(self, "viewport_width", 1280) / 1280)

    # ---- the player and next-bus cards: built once, then placed on the grid like any other tile ----
    def build_home_side(self):
        side = Gtk.Box(); side.add_css_class("home-side"); side.set_visible(False)   # an empty, hidden holder: the cards live in the grid
        player = Gtk.Overlay(); player.add_css_class("hs-card"); player.set_overflow(Gtk.Overflow.HIDDEN); player.set_hexpand(True); player.set_vexpand(True); self.hs_player = player; self.hs_short = False
        self.hs_art = Gtk.Picture(); self.hs_art.set_content_fit(Gtk.ContentFit.COVER); self.hs_art.set_can_shrink(True); self.hs_art.set_halign(Gtk.Align.FILL); self.hs_art.set_valign(Gtk.Align.FILL)
        player.set_child(self.hs_art)
        fade = Gtk.Box(); fade.add_css_class("hs-fade"); fade.set_can_target(False); player.add_overlay(fade); self.hs_fade = fade; self.hs_opts = {}
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); content.add_css_class("hs-content"); self.hs_content = content
        self.hs_zone = self.label("", "hs-zone"); content.append(self.hs_zone)
        spacer = Gtk.Box(); spacer.set_vexpand(True); content.append(spacer); self.hs_spacer = spacer
        self.hs_title = self.label("", "hs-title"); self.hs_title.set_wrap(True); self.hs_title.set_lines(2); self.hs_title.set_ellipsize(Pango.EllipsizeMode.END); self.hs_title.set_max_width_chars(1)
        self.hs_artist = self.label("", "hs-artist"); self.hs_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.hs_thumb = Gtk.Image(); self.hs_thumb.add_css_class("hs-thumb"); self.hs_thumb.set_overflow(Gtk.Overflow.HIDDEN); self.hs_thumb.set_halign(Gtk.Align.START); self.hs_thumb.set_hexpand(False); self.hs_thumb.set_valign(Gtk.Align.END); self.hs_thumb.set_visible(False)   # an Image keeps the exact size asked for; a Picture grows to the artwork
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); words.set_hexpand(True); words.set_valign(Gtk.Align.END); words.set_margin_bottom(2); words.append(self.hs_title); words.append(self.hs_artist)
        head = Gtk.Box(spacing=16); head.append(self.hs_thumb); head.append(words); content.append(head); self.hs_head = head; self.hs_words = words
        self.hs_progress = Gtk.ProgressBar(); self.hs_progress.add_css_class("hs-progress"); content.append(self.hs_progress)
        self.hs_scrub = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1); self.hs_scrub.add_css_class("home-slider"); self.hs_scrub.add_css_class("hs-scrub"); self.hs_scrub.set_draw_value(False); self.hs_scrub.set_visible(False)
        self.hs_scrub.connect("value-changed", self.change_seek); content.append(self.hs_scrub)
        transport = Gtk.Box(spacing=26); transport.set_halign(Gtk.Align.CENTER)
        self.hs_prev = self.icon_button("previous", lambda *_: self.control("previous"), "hs-transport")
        self.hs_play = self.icon_button("play", lambda *_: self.control("playpause"), "hs-play")
        self.hs_next = self.icon_button("next", lambda *_: self.control("next"), "hs-transport")
        for button in (self.hs_prev, self.hs_play, self.hs_next): transport.append(button)
        content.append(transport); self.hs_transport = transport
        volume = Gtk.Box(spacing=14); volume.add_css_class("hs-volume-row")
        self.hs_volume_label = self.label("VOL", "hs-volume-label")   # kept for the tests, no longer shown: the slider needs no caption
        self.hs_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); self.hs_volume.add_css_class("home-slider"); self.hs_volume.add_css_class("hs-volume")
        self.hs_volume.set_hexpand(True); self.hs_volume.set_draw_value(False); self.hs_volume.set_focusable(False); self.hs_scrub.set_focusable(False);   # touch only: no keyboard focus ring around the sliders
        self.hs_volume.connect("value-changed", self.change_volume); volume.append(self.hs_volume)
        self.hs_volume_row = volume; content.append(volume)
        player.add_overlay(content)
        self.bus_tiles = {}; self.bus_defaults = {}; self.hs_bus_services = []; self.hs_bus = self.bus_tile("roondeck.bus").box
        self.hs_cpu, self.hs_cpu_value, self.hs_cpu_detail, self.hs_cpu_area = self.build_stat_card("CPU", corner=True)
        self.hs_net, self.hs_net_value, self.hs_net_detail, self.hs_net_area = self.build_stat_card("NETWORK"); self.hs_net_value.add_css_class("hs-net-value"); self.hs_net_value.add_css_class("hs-net-small")
        self.hs_mem, self.hs_mem_value, self.hs_mem_detail, self.hs_mem_area = self.build_stat_card("MEMORY", corner=True)
        self.hs_upd, self.hs_upd_value, self.hs_upd_detail = self.build_action_card("SOFTWARE", self.tap_update_tile)
        self.hs_groups = {key: self.build_action_card("ZONES", lambda key=key: self.tap_group_tile(key)) for key in GROUP_KEYS}
        self.upd_info, self.upd_checked, self.upd_checking, self.group_outputs, self.group_polled, self.hs_cfg = None, 0.0, False, [], 0.0, {}
        self.hs_vol = self.build_volume_card()
        self.stat_cpu, self.stat_down, self.stat_up, self.stat_mem = [], [], [], []
        self.hs_cpu_area.set_draw_func(lambda area, cr, width, height, *_: self.draw_spark(cr, width, height, [(self.stat_cpu, SPARK_GREEN)], 100.0))
        self.hs_mem_area.set_draw_func(lambda area, cr, width, height, *_: self.draw_spark(cr, width, height, [(self.stat_mem, SPARK_BLUE)], 100.0))
        self.hs_net_area.set_draw_func(lambda area, cr, width, height, *_: self.draw_spark(cr, width, height, [pair for pair, shown in (((self.stat_up, SPARK_GREEN), self.net_show[1]), ((self.stat_down, SPARK_BLUE), self.net_show[0])) if shown], None))
        self.net_show = (True, True); self.stat_timer = None; self.stat_prev_cpu = None; self.stat_prev_net = None; self.hs_live_shown = set()
        return side

    # ---- live tiles: CPU and network, read straight from the Pi every couple of seconds ----
    def build_stat_card(self, title, corner=False):
        card = Gtk.Overlay(); card.add_css_class("hs-card"); card.add_css_class("hs-stat"); card.set_overflow(Gtk.Overflow.HIDDEN); card.set_hexpand(True); card.set_vexpand(True)
        area = Gtk.DrawingArea(); area.set_vexpand(True); area.set_hexpand(True); card.set_child(area)   # the graph runs edge to edge, behind the text
        value = self.label("—", "hs-stat-value", 0); detail = self.label("", "hs-stat-detail", 0); detail.set_ellipsize(Pango.EllipsizeMode.END); value.set_ellipsize(Pango.EllipsizeMode.END)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); content.add_css_class("hs-stat-content"); content.set_can_target(False)
        head = Gtk.Box(); head.append(self.label(title, "hs-stat-title", 0))
        if corner:   # a short reading (the temperature) sits top right, level with the title
            filler = Gtk.Box(); filler.set_hexpand(True); head.append(filler); head.append(detail)
        content.append(head); content.append(value)
        if not corner:
            filler = Gtk.Box(); filler.set_vexpand(True); content.append(filler); content.append(detail)
        card.add_overlay(content)
        return card, value, detail, area

    def bus_tile(self, key):
        """The next-bus tile for one key ("roondeck.bus", or a copy such as "roondeck.bus#1"). Each has its own widgets and route, so several can sit side by side."""
        if key in self.bus_tiles: return self.bus_tiles[key]
        tile = types.SimpleNamespace(key=key, choice=None, default=None)
        bus = Gtk.Box(spacing=22); bus.add_css_class("hs-card"); bus.add_css_class("hs-bus"); bus.set_hexpand(True); bus.set_vexpand(True); tile.box = bus
        chip = Gtk.Box(); chip.add_css_class("home-icon-chip"); chip.add_css_class("hs-bus-chip"); chip.set_valign(Gtk.Align.CENTER); chip.set_halign(Gtk.Align.CENTER)
        icon = FamilyIcon("bus", 44); icon.add_css_class("hs-bus-glyph"); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.set_hexpand(True); chip.set_hexpand(False); chip.set_halign(Gtk.Align.START); chip.append(icon); bus.append(chip); tile.glyph, tile.size = icon, ""   # the glyph expands inside the chip so it is centred in the circle
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); text.set_hexpand(True); text.set_valign(Gtk.Align.CENTER)
        tile.route = self.label("", "hs-route"); tile.then = self.label("", "hs-then"); text.append(tile.route); text.append(tile.then); bus.append(text)
        arrival = Gtk.Box(spacing=8); arrival.set_valign(Gtk.Align.CENTER)
        tile.minutes = self.label("", "hs-minutes"); tile.unit = self.label("min", "hs-unit"); tile.unit.set_valign(Gtk.Align.BASELINE); tile.minutes.set_valign(Gtk.Align.BASELINE); arrival.set_baseline_position(Gtk.BaselinePosition.CENTER); arrival.append(tile.minutes); arrival.append(tile.unit); bus.append(arrival)
        # The square version, for a half-column, one-row tile: the route number in the circle where the icon would be, the next arrival in the middle, "then" below.
        small = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); small.set_hexpand(True); small.set_vexpand(True); small.set_visible(False)
        numchip = Gtk.Box(); numchip.add_css_class("hs-bus-numchip"); numchip.set_halign(Gtk.Align.START); numchip.set_valign(Gtk.Align.START); numchip.set_size_request(44, 44)
        tile.cnum = self.label("", "hs-bus-num", 0); tile.cnum.set_halign(Gtk.Align.CENTER); tile.cnum.set_valign(Gtk.Align.CENTER); tile.cnum.set_hexpand(True); numchip.append(tile.cnum)
        middle = Gtk.Box(spacing=6); middle.set_halign(Gtk.Align.CENTER); middle.set_valign(Gtk.Align.CENTER); middle.set_vexpand(True); middle.set_baseline_position(Gtk.BaselinePosition.CENTER)
        tile.cmin = self.label("", "hs-bus-cmin", 0); tile.cunit = self.label("min", "hs-unit", 0); tile.cmin.set_valign(Gtk.Align.BASELINE); tile.cunit.set_valign(Gtk.Align.BASELINE); middle.append(tile.cmin); middle.append(tile.cunit)
        tile.cthen = self.label("", "hs-then", 0); tile.cthen.set_halign(Gtk.Align.CENTER); tile.cthen.set_ellipsize(Pango.EllipsizeMode.END)
        small.append(numchip); small.append(middle); small.append(tile.cthen)
        bus.append(small); tile.small, tile.normal, tile.compact = small, [chip, text, arrival], False
        tap = Gtk.GestureClick(); tap.connect("released", lambda *_: self.cycle_bus_route(tile)); bus.add_controller(tap)
        self.bus_tiles[key] = tile
        return tile

    def build_volume_card(self):
        """A large volume number with a minus and a plus: it follows, and changes, the volume of the zone on the Now Playing page."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0); card.add_css_class("hs-card"); card.add_css_class("hs-voltile"); card.set_hexpand(True); card.set_vexpand(True)
        card.append(self.label("VOLUME", "hs-stat-title", 0))
        row = Gtk.Box(spacing=12); row.set_vexpand(True); row.set_valign(Gtk.Align.CENTER)
        minus = Gtk.Button(label="\u2212"); plus = Gtk.Button(label="+")
        for button, step in ((minus, -2), (plus, 2)): button.add_css_class("hs-volstep"); button.set_valign(Gtk.Align.CENTER); button.connect("clicked", lambda *_, step=step: self.home_step_volume(step))
        self.hs_vol_value = self.label("\u2014", "hs-volbig", 0); self.hs_vol_value.set_hexpand(True); self.hs_vol_value.set_halign(Gtk.Align.CENTER)
        row.append(minus); row.append(self.hs_vol_value); row.append(plus); card.append(row); card.minus = minus; card.plus = plus
        return card

    def home_step_volume(self, step):
        scale = self.volume
        if not scale.get_sensitive(): return
        adjustment = scale.get_adjustment(); scale.set_value(max(adjustment.get_lower(), min(adjustment.get_upper(), round(scale.get_value()) + step)))   # the Now Playing handler sends it

    def refresh_volume_tile(self):
        available = self.volume.get_sensitive()
        self.hs_vol_value.set_text(str(round(self.volume.get_value())) if available else "\u2014")
        self.hs_vol.minus.set_sensitive(available); self.hs_vol.plus.set_sensitive(available)

    def build_action_card(self, title, on_tap):
        """A tile you tap to do something: a small title, a big word for what a tap will do, and a line of detail."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); card.add_css_class("hs-card"); card.add_css_class("hs-action"); card.set_hexpand(True); card.set_vexpand(True)
        chip = Gtk.Box(); chip.add_css_class("hs-action-chip"); chip.set_halign(Gtk.Align.START); chip.set_valign(Gtk.Align.START)
        chip.set_size_request(44, 44); card.icon_name = None; card.chip = chip
        value = self.label("—", "hs-action-value", 0); value.set_wrap(True); value.set_wrap_mode(Pango.WrapMode.WORD_CHAR); value.set_lines(2); value.set_ellipsize(Pango.EllipsizeMode.END); value.set_max_width_chars(1); value.set_hexpand(True); value.set_xalign(0); value.set_valign(Gtk.Align.CENTER)   # the title sits beside the icon, leaving the lines below for the detail
        detail = self.label("", "hs-stat-detail", 0); detail.add_css_class("hs-action-detail"); detail.set_wrap(True); detail.set_wrap_mode(Pango.WrapMode.WORD_CHAR); detail.set_lines(3); detail.set_ellipsize(Pango.EllipsizeMode.END); detail.set_max_width_chars(1); detail.set_valign(Gtk.Align.END)
        filler = Gtk.Box(); filler.set_vexpand(True)
        head = Gtk.Box(spacing=10); head.append(chip); head.append(value); card.head = head; card.value_label = value; card.detail_label = detail; card.append(head); card.append(filler); card.append(detail)
        card.set_tooltip_text(title)
        tap = Gtk.GestureClick(); tap.connect("released", lambda *_: on_tap()); card.add_controller(tap)
        return card, value, detail

    def set_action_state(self, card, icon, state):
        """Show an icon in the tile's chip and colour the tile for its state: ok (green), alert (orange), active (purple) or none."""
        if card.icon_name != icon:
            card.icon_name = icon; image = FamilyIcon(icon, 26); image.add_css_class("hs-action-icon"); image.set_halign(Gtk.Align.CENTER); image.set_valign(Gtk.Align.CENTER); image.set_hexpand(True)
            while child := card.chip.get_first_child(): card.chip.remove(child)
            card.chip.append(image)
        for name in ("ok", "alert", "active", "light", "green", "purple", "blue"):
            (card.add_css_class if name == state else card.remove_css_class)("is-" + name)

    # ---- update tile: shows whether a newer RoonDeck is out and installs it on a tap ----
    def check_updates(self, refresh=False):
        if self.upd_checking: return
        self.upd_checking = True
        def run():
            info = get_json(BUS + "/api/device/releases" + ("?refresh=1" if refresh else ""), timeout=20)
            def done():
                self.upd_checking = False; self.upd_checked = GLib.get_monotonic_time() / 1e6
                if info: self.upd_info = info
                return False
            GLib.idle_add(done)
        threading.Thread(target=run, daemon=True).start()

    def tap_update_tile(self):
        if getattr(self, "update_in_progress", False): return
        info = self.upd_info or {}
        if info.get("update_available"): self.request_update(); self.refresh_update_tile()
        else: self.hs_upd_value.set_text("Checking…"); self.check_updates(refresh=True)   # up to date (or never checked): look again now

    def refresh_update_tile(self):
        now = GLib.get_monotonic_time() / 1e6
        if not self.upd_checking and now - self.upd_checked > 1800: self.check_updates()   # a quiet look every half hour; tapping the tile checks at once
        info = self.upd_info or {}; status = self.device_status.get_text() if hasattr(self, "device_status") else ""
        if getattr(self, "update_in_progress", False):
            self.set_action_state(self.hs_upd, "refresh", "active"); self.hs_upd_value.set_text("Updating…"); self.hs_upd_detail.set_text(status if status.startswith(("Update", "Failed")) else "Please wait")
        elif status.startswith(("Could not", "Failed")):
            self.set_action_state(self.hs_upd, "refresh", "alert"); self.hs_upd_value.set_text("Try again"); self.hs_upd_detail.set_text(status)
        elif info.get("status") == "unavailable":   # the check itself failed (GitHub limit, no network): say so rather than "Up to date"
            self.set_action_state(self.hs_upd, "refresh", None); self.hs_upd_value.set_text("Couldn't check"); self.hs_upd_detail.set_text(str(info.get("message") or "Tap to try again"))
        elif info.get("update_available"):
            self.set_action_state(self.hs_upd, "download", "alert"); self.hs_upd_value.set_text("Update"); self.hs_upd_detail.set_text(f"v{info.get('latest_version', '')} is ready. Tap to install")
        elif info:
            self.set_action_state(self.hs_upd, "check", "ok"); self.hs_upd_value.set_text("Up to date"); self.hs_upd_detail.set_text(f"v{info.get('installed_version', '')}. Tap to check")
        elif not self.upd_checking:
            self.set_action_state(self.hs_upd, "refresh", None); self.hs_upd_value.set_text("Check"); self.hs_upd_detail.set_text("Tap to look for updates")

    # ---- zone group tiles: group one Roon zone with another, or ungroup them ----
    def zones_grouped(self, first, second):
        zone_of = {item.get("name"): item.get("zone") for item in self.group_outputs}
        return bool(first in zone_of and second in zone_of and zone_of[first] == zone_of[second])

    def refresh_group_tiles(self, keys):
        now = GLib.get_monotonic_time() / 1e6
        if now - self.group_polled > 4:
            self.group_polled = now
            def run():
                data = get_json(ROON + "/api/accessory/outputs", timeout=3)
                if data: GLib.idle_add(lambda: setattr(self, "group_outputs", data.get("outputs", [])) or False)
            threading.Thread(target=run, daemon=True).start()
        for key in keys:
            card, value, detail = self.hs_groups[key]; cfg = self.hs_cfg.get(key) or {}
            first, second = cfg.get("zone"), cfg.get("with")
            if not first or not second: self.set_action_state(card, "link", None); value.set_text("Set zones"); detail.set_text("Choose them in the builder"); continue
            grouped = self.zones_grouped(first, second)
            self.set_action_state(card, "link", "active" if grouped else None); value.set_text("Ungroup" if grouped else "Group"); detail.set_text(f"{first}\n+ {second}" if not grouped else f"{first}\n+ {second}")

    def tap_group_tile(self, key):
        cfg = self.hs_cfg.get(key) or {}
        if not cfg.get("zone") or not cfg.get("with"): return
        self.hs_groups[key][1].set_text("Working…")
        def run():
            post_json(ROON + "/api/zones/group", {"zone": cfg["zone"], "with": cfg["with"], "action": "toggle"}, timeout=8)
            self.group_polled = 0.0   # look again straight away
        threading.Thread(target=run, daemon=True).start()

    def draw_spark(self, cr, width, height, series, top):
        scale = top or max([1.0] + [max(values) for values, _ in series if values])
        for values, (red, green, blue) in series:
            if len(values) < 2: continue
            step = width / (SAMPLES - 1); first = width - step * (len(values) - 1)
            band_top, band_bottom = height * .52, height - 8   # the line lives in the lower half; the shading runs to the very bottom
            soft = [sum(values[max(0, i - 1):i + 2]) / len(values[max(0, i - 1):i + 2]) for i in range(len(values))]   # a light three-point average takes the jitter off
            points = [(first + index * step, band_bottom - min(value, scale) / scale * (band_bottom - band_top)) for index, value in enumerate(soft)]
            cr.set_line_width(2.5); cr.set_line_join(1); cr.set_source_rgba(red, green, blue, 1)
            cr.move_to(*points[0])
            for index in range(1, len(points)):   # curved between the points (Catmull-Rom as Béziers), kept inside the tile
                before, here, there, after = points[max(0, index - 2)], points[index - 1], points[index], points[min(len(points) - 1, index + 1)]
                low, high = band_top, band_bottom
                c1 = (here[0] + (there[0] - before[0]) / 6, min(high, max(low, here[1] + (there[1] - before[1]) / 6)))
                c2 = (there[0] - (after[0] - here[0]) / 6, min(high, max(low, there[1] - (after[1] - here[1]) / 6)))
                cr.curve_to(*c1, *c2, *there)
            cr.stroke_preserve(); cr.line_to(points[-1][0], height); cr.line_to(points[0][0], height); cr.close_path(); cr.set_source_rgba(red, green, blue, .16); cr.fill()

    def start_system_sampling(self):
        if self.hs_live_shown and self.stat_timer is None:
            self.stat_timer = GLib.timeout_add_seconds(SAMPLE_SECONDS, self.sample_system); self.sample_system()

    def sample_system(self):
        if not self.hs_live_shown:
            self.stat_timer = None; return False
        on_home = getattr(self, "stack", None) is not None and self.stack.get_visible_child_name() == "home"   # off the Home page nothing below is drawn, polled or fetched
        try:
            fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0); total = sum(fields[:8])
            if self.stat_prev_cpu and total > self.stat_prev_cpu[1]:
                busy = 100.0 * (1 - (idle - self.stat_prev_cpu[0]) / (total - self.stat_prev_cpu[1])); self.stat_cpu = (self.stat_cpu + [max(0.0, min(100.0, busy))])[-SAMPLES:]
            self.stat_prev_cpu = (idle, total)
        except (OSError, ValueError, IndexError): pass
        try:
            rx = tx = 0
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
                name, _, rest = line.partition(":"); numbers = rest.split()
                if name.strip() != "lo" and len(numbers) >= 9: rx += int(numbers[0]); tx += int(numbers[8])
            if self.stat_prev_net:
                seconds = max(0.5, (GLib.get_monotonic_time() - self.stat_prev_net[2]) / 1e6)
                self.stat_down = (self.stat_down + [max(0, rx - self.stat_prev_net[0]) * 8 / seconds])[-SAMPLES:]; self.stat_up = (self.stat_up + [max(0, tx - self.stat_prev_net[1]) * 8 / seconds])[-SAMPLES:]
            self.stat_prev_net = (rx, tx, GLib.get_monotonic_time())
        except (OSError, ValueError, IndexError): pass
        try:
            info = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) > 1}
            total_kb = info["MemTotal"]; used_kb = total_kb - info.get("MemAvailable", info.get("MemFree", 0))
            self.stat_mem = (self.stat_mem + [100.0 * used_kb / total_kb])[-SAMPLES:]; self.mem_used_total = (used_kb, total_kb)
        except (OSError, ValueError, KeyError, ZeroDivisionError): pass
        def rate(bits): return f"{bits / 1e6:.1f} Mb/s" if bits >= 1e6 else f"{bits / 1e3:.0f} kb/s"
        def big_rate(bits):   # the number large and its unit small, so it fits the smallest tile on one line
            if getattr(self, "hs_net_wide", False): return rate(bits)   # a wider tile has room for the full-size reading, as on CPU and Memory
            number, unit = rate(bits).split(" ", 1); return f"{number} <small><small>{unit}</small></small>"
        if "roondeck.cpu" in self.hs_live_shown:
            self.hs_cpu_value.set_text(f"{self.stat_cpu[-1]:.0f}%" if self.stat_cpu else "—")
            try: temperature = f"{int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000:.0f} °C"
            except (OSError, ValueError): temperature = ""
            self.hs_cpu_detail.set_text(temperature); self.hs_cpu_area.queue_draw() if on_home else None
        if "roondeck.memory" in self.hs_live_shown:
            used, total = getattr(self, "mem_used_total", (0, 0))
            self.hs_mem_value.set_text(f"{self.stat_mem[-1]:.0f}%" if self.stat_mem else "—"); self.hs_mem_area.queue_draw() if on_home else None
        if on_home and "roondeck.update" in self.hs_live_shown: self.refresh_update_tile()
        shown_groups = [key for key in GROUP_KEYS if key in self.hs_live_shown]
        if on_home and shown_groups: self.refresh_group_tiles(shown_groups)
        if "roondeck.network" in self.hs_live_shown:
            show_down, show_up = self.net_show
            if show_down: self.hs_net_value.set_markup(big_rate(self.stat_down[-1]) if self.stat_down else "—"); self.hs_net_detail.set_text(f"up {rate(self.stat_up[-1])}" if show_up and self.stat_up else "")
            else: self.hs_net_value.set_markup(big_rate(self.stat_up[-1]) if self.stat_up else "—"); self.hs_net_detail.set_text("upload")
            self.hs_net_area.queue_draw() if on_home else None
        return True

    def render_home_side(self, roon, status):
        self.hs_last_side = (roon, status)
        if not self.home_dashboard_active(): return
        scale = self.home_scale()
        # The Now Playing page already works out the zone, track, controls and volume each refresh; mirror its widgets.
        options = self.hs_opts or {}
        self.hs_zone.set_text(str(options.get("label") or self.zone.get_text() or "ROON").upper()); self.hs_title.set_text(self.title.get_text()); self.hs_artist.set_text(self.artist.get_text())
        paintable = self.artwork.get_paintable()
        art = options.get("art") if options.get("art") in ("thumb", "off") else "background"; fade_art = options.get("art") == "fade"
        self.hs_art.set_visible(art == "background"); self.hs_fade.set_visible(art == "background"); self.hs_thumb.set_visible(art == "thumb" and not self.hs_short)
        thumb_mode = art == "thumb" and not self.hs_short
        card_w, card_h = self.hs_player.get_width(), self.hs_player.get_height()
        if card_w > 0 and card_h > 0:
            wide = art == "background" and not self.hs_short and card_h >= 200 and card_w >= card_h * 1.5   # a wide tile: artwork on the left, the details on the right
            self.hs_split_last = (wide, card_w, card_h)
        else:
            # Not measured yet (the grid is being laid out again): keep what was last decided, so the tile does not flick between layouts.
            wide, card_w, card_h = getattr(self, "hs_split_last", (False, 0, 0))
        split = wide and not fade_art      # a framed square of artwork
        fadewide = wide and fade_art       # full-bleed artwork that fades into the details
        roomy = wide                       # either wide layout gets the large type and controls
        (self.hs_player.add_css_class if roomy else self.hs_player.remove_css_class)("hs-split")   # a wide tile is laid out like the 7-inch Now Playing screen: big title, big controls
        if roomy: self.hs_content.set_spacing(20)
        if split:   # a framed square of artwork centred in the left half, with room round it, not full bleed
            # Margins, not a size request: a Picture grows to its image's own size when it is not made to fill, so the margins decide the square.
            pad = 22; side = max(120, card_h - 2 * pad); split_edge = pad + side
            self.hs_art.set_halign(Gtk.Align.FILL); self.hs_art.set_valign(Gtk.Align.FILL); self.hs_art.set_size_request(-1, -1)
            self.hs_art.set_margin_start(pad); self.hs_art.set_margin_end(card_w - split_edge); self.hs_art.set_margin_top(pad); self.hs_art.set_margin_bottom(pad)
        else:
            self.hs_art.set_halign(Gtk.Align.FILL); self.hs_art.set_valign(Gtk.Align.FILL); self.hs_art.set_size_request(-1, -1)
            for margin in ("start", "end", "top", "bottom"): getattr(self.hs_art, "set_margin_" + margin)(0)
        self.hs_art.set_overflow(Gtk.Overflow.HIDDEN); (self.hs_art.add_css_class if split else self.hs_art.remove_css_class)("hs-art-framed")
        self.hs_content.set_margin_start((22 + max(120, card_h - 44) + 12) if split else round(card_w * 0.46) if fadewide else 0); self.hs_fade.set_visible(art == "background" and not split)
        (self.hs_fade.add_css_class if fadewide else self.hs_fade.remove_css_class)("hs-fade-side")
        reserved = 40 + 80 + 14 + (24 if options.get("heading") is not False else 0) + (50 if options.get("volume") is not False else 0) + 10 * 4   # what the rest of the card needs
        side = round(min(card_w * .46, card_h - reserved) if card_w and card_h else 150 * scale)
        self.hs_thumb.set_pixel_size(max(96, side))
        self.hs_spacer.set_vexpand(not (thumb_mode or roomy)); self.hs_head.set_vexpand(thumb_mode or roomy)   # with a thumbnail the track sits up with it, not pushed to the bottom
        self.hs_thumb.set_valign(Gtk.Align.CENTER if thumb_mode else Gtk.Align.END); self.hs_words.set_valign(Gtk.Align.CENTER if thumb_mode or roomy else Gtk.Align.END)
        left = thumb_mode or options.get("align") == "left"
        for words in (self.hs_zone, self.hs_title, self.hs_artist):   # centred by default; left beside a thumbnail or when chosen
            words.set_xalign(0.0 if left else 0.5); words.set_justify(Gtk.Justification.LEFT if left else Gtk.Justification.CENTER)
        if paintable is not self.hs_art.get_paintable(): self.hs_art.set_paintable(paintable)
        if paintable is not self.hs_thumb.get_paintable(): self.hs_thumb.set_from_paintable(paintable)
        adjustment = self.progress.get_adjustment(); upper = adjustment.get_upper()
        self.hs_progress.set_fraction(min(1.0, adjustment.get_value() / upper) if upper > 1 else 0.0)
        scrubber = bool(options.get("scrubber"))
        self.hs_progress.set_visible(not scrubber); self.hs_scrub.set_visible(scrubber)
        if scrubber:
            self.seek_updating = True; self.hs_scrub.set_range(0, max(1.0, upper)); self.hs_scrub.set_value(adjustment.get_value()); self.hs_scrub.set_sensitive(self.progress.get_sensitive()); self.seek_updating = False
        current = self.play.get_child(); icon_name = current.icon_name if isinstance(current, FamilyIcon) else "play"; glyph = round((62 if roomy else 46) * scale)
        for mine in (self.hs_prev, self.hs_next):   # the skip buttons are larger on a wide tile
            wanted_glyph = round((54 if roomy else 34) * scale); held = mine.get_child()
            if isinstance(held, FamilyIcon) and held.get_pixel_size() != wanted_glyph: mine.set_child(FamilyIcon(held.icon_name, wanted_glyph))
        shown = self.hs_play.get_child()
        if not isinstance(shown, FamilyIcon) or shown.icon_name != icon_name or shown.get_pixel_size() != glyph: self.hs_play.set_child(FamilyIcon(icon_name, glyph))
        for mine, theirs in ((self.hs_prev, self.prev), (self.hs_play, self.play), (self.hs_next, self.next)): mine.set_sensitive(theirs.get_sensitive())
        if "roondeck.volume" in self.hs_live_shown: self.refresh_volume_tile()
        self.volume_updating = True
        self.hs_volume.set_value(self.volume.get_value()); self.hs_volume.set_sensitive(self.volume.get_sensitive()); self.hs_volume_row.set_visible(self.volume.get_visible() and not self.hs_short and options.get("volume") is not False)
        self.hs_zone.set_visible(not self.hs_short and options.get("heading") is not False); self.hs_title.set_lines(1 if self.hs_short else 3 if roomy else 2)
        self.volume_updating = False
        services = (status or {}).get("services") or []
        self.hs_bus_services = [str(item.get("service")) for item in services]
        for tile in self.bus_tiles.values():
            default = self.bus_defaults.get(tile.key) or None
            if default != tile.default: tile.default, tile.choice = default, None   # a route chosen in the builder replaces whatever a tap had picked
            wanted = tile.choice or default or HOME_BUS_ROUTE   # a tap picks the next route; until then the route set for the tile, else 42, else the stop's first
            chosen = next((item for item in services if str(item.get("service")) == wanted), services[0] if services else None)
            tile.box.set_visible(chosen is not None)
            height = tile.box.get_height()
            if height > 0 and not tile.compact:   # the bus tile grows with the room it is given: 7-inch, then the big 10-inch panels
                size = "xl" if height >= 330 else "lg" if height >= 230 else ""
                if size != tile.size:
                    for name in ("lg", "xl"): tile.box.remove_css_class("hs-bus-" + name)
                    if size: tile.box.add_css_class("hs-bus-" + size)
                    tile.size = size; tile.box.set_spacing({"": 22, "lg": 30, "xl": 40}[size])
                    pixels = {"": 44, "lg": 60, "xl": 80}[size]; tile.glyph.set_pixel_size(pixels); tile.glyph._refresh(getattr(tile.glyph, "_colour", None))
            if chosen is None: continue
            minutes = [arrival.get("minutes") for arrival in chosen.get("arrivals", []) if arrival.get("minutes") is not None]
            colour = chosen.get("colour") or "amber"
            for name in ROUTE_TINTS: tile.box.remove_css_class("hs-bus-" + name)
            tile.box.add_css_class("hs-bus-" + (colour if colour in ROUTE_TINTS else "amber"))   # the same colour as that route on the Bus Times page
            tile.route.set_text(str(chosen.get("service", "")))
            tile.minutes.set_text("—" if not minutes else "Due" if minutes[0] == 0 else str(minutes[0])); tile.unit.set_visible(bool(minutes) and minutes[0] != 0)
            (tile.minutes.add_css_class if minutes and minutes[0] == 0 else tile.minutes.remove_css_class)("hs-minutes-due")   # the word "Due" is set smaller than a number so it fits the tile
            tile.then.set_text(f"then {minutes[1]} min" if len(minutes) > 1 else ""); tile.then.set_visible(len(minutes) > 1)
            due = bool(minutes) and minutes[0] == 0
            tile.cnum.set_text(str(chosen.get("service", ""))); (tile.cnum.add_css_class if len(str(chosen.get("service", ""))) > 3 else tile.cnum.remove_css_class)("is-long")
            tile.cmin.set_text("—" if not minutes else "Due" if due else str(minutes[0])); (tile.cmin.add_css_class if due else tile.cmin.remove_css_class)("is-due"); tile.cunit.set_visible(bool(minutes) and not due)
            tile.cthen.set_text(f"then {minutes[1]} min" if len(minutes) > 1 else ""); tile.cthen.set_visible(len(minutes) > 1)

    def set_bus_compact(self, tile, compact):
        """A half-column, one-row bus tile uses the square layout; anything wider keeps the wide one."""
        if tile is None or compact == tile.compact: return
        tile.compact = compact
        for part in tile.normal: part.set_visible(not compact)
        tile.small.set_visible(compact)
        (tile.box.add_css_class if compact else tile.box.remove_css_class)("hs-bus-compact")
        if compact: tile.box.set_spacing(0); [tile.box.remove_css_class("hs-bus-" + name) for name in ("lg", "xl")]; tile.size = ""
        else: tile.size = None   # the next refresh picks the size class again

    def cycle_bus_route(self, tile):
        """Tapping a bus tile shows the next route the stop is registered for; each bus tile steps through them on its own."""
        routes = self.hs_bus_services
        if len(routes) < 2: return
        shown = tile.choice or tile.default or HOME_BUS_ROUTE
        current = shown if shown in routes else routes[0]
        tile.choice = routes[(routes.index(current) + 1) % len(routes)]
        if getattr(self, "hs_last_side", None): self.render_home_side(*self.hs_last_side)

    # ---- right: the grid of device cards ----
    def render_home_dashboard(self, home, entities):
        portrait = self.window.has_css_class("portrait")
        columns = 2 if portrait else home.get("columns") if home.get("columns") in (2, 3) else 3   # portrait is always two columns; landscape 3 unless the owner chose 2
        cols = columns * 2                                                      # the grid is counted in half columns
        scale = self.home_scale()
        self.home_grid.set_row_spacing(GAP); self.home_grid.set_column_spacing(GAP); self.home_grid.set_hexpand(True)
        # The player, the next bus and any live tiles are tiles too: placed, sized and moved like the devices.
        cards = home.get("cards") or {}
        def base_of(key): return key.split("#")[0]
        # The same card can be on several pages ("roondeck.cpu#2"): each copy has its own place and options, but they share one widget, which only ever shows on one page at a time.
        widgets = {"roondeck.player": (self.hs_player, 2, (0, 0)), "roondeck.bus": (self.hs_bus, 1, (0, 2)), "roondeck.cpu": (self.hs_cpu, 1, None), "roondeck.memory": (self.hs_mem, 1, None),
                   "roondeck.update": (self.hs_upd, 1, None), "roondeck.network": (self.hs_net, 1, None), "roondeck.volume": (self.hs_vol, 1, None), **{key: (self.hs_groups[key][0], 1, None) for key in GROUP_KEYS}}
        for key in cards:
            if base_of(key) in ("roondeck.kef", "roondeck.kef_power", "roondeck.kef_input", "roondeck.kef_volume"):
                widgets[key] = (self.kef_tile(key), 2 if base_of(key) == "roondeck.kef" else 1, None)
        records = {key: tile for key, tile in cards.items() if base_of(key) in widgets or key in widgets}
        for fixed in ("roondeck.player", "roondeck.bus"):
            if not any(base_of(key) == fixed for key in records): records[fixed] = {}
        untouched = not any(isinstance(tile.get("col"), int) for key, tile in records.items() if key in ("roondeck.player", "roondeck.bus"))
        virtual = []
        for key, record in records.items():
            widget, rows, home_cell = widgets.get(key, widgets.get(base_of(key)))
            if key in self.kef_tiles: self.style_kef_tile(widget, record)
            if base_of(key) == "roondeck.bus":   # every bus tile has its own widgets and its own route
                widget = self.bus_tile(key).box; self.bus_defaults[key] = record.get("route") or None
            if base_of(key) not in ("roondeck.player", "roondeck.bus") and not record.get("show"): continue
            tile = dict(record); tile.setdefault("rows", rows)
            if base_of(key) == "roondeck.kef": tile["rows"] = max(2, tile.get("rows") or 2)   # the combined KEF tile needs two rows
            if home_cell and untouched and tile.get("page", 0) == 0 and not isinstance(tile.get("col"), int): tile["col"], tile["row"] = home_cell   # the player top-left, the bus under it
            virtual.append({"entity_id": key, "domain": "roondeck", "widget": widget, "tile": tile})
        entities = virtual + list(entities)
        entities = [entity for entity in entities if (entity.get("tile") or {}).get("page", 0) == self.hs_page or (self.hs_pages < 2 and self.hs_page == 0)]   # one page at a time
        shown = [entity for entity in entities if entity.get("widget") is not None]
        self.hs_cfg = {key: {} for key in GROUP_KEYS}
        for entity in shown:
            if base_of(entity["entity_id"]) in GROUP_KEYS: self.hs_cfg[base_of(entity["entity_id"])] = entity["tile"]
        self.hs_opts = next((dict(entity["tile"]) for entity in shown if base_of(entity["entity_id"]) == "roondeck.player"), {})
        net = next((entity["tile"] for entity in shown if base_of(entity["entity_id"]) == "roondeck.network"), {})
        self.net_show = (net.get("download") is not False, net.get("upload") is not False)   # either direction can be switched off, never both
        if self.net_show == (False, False): self.net_show = (True, False)
        def mix(front, back, amount):
            top = tuple(int(front[index:index + 2], 16) for index in (1, 3, 5)); base = tuple(int(back[index:index + 2], 16) for index in (1, 3, 5))
            return "#" + "".join(f"{round(low + (high - low) * amount):02x}" for high, low in zip(top, base))
        self.hs_live_shown = {base_of(entity["entity_id"]) for entity in shown if base_of(entity["entity_id"]) in ("roondeck.cpu", "roondeck.network", "roondeck.memory", "roondeck.volume") + ACTION_KEYS}
        rules = []
        for entity in shown:                       # each card can have its own colour; without one it keeps the standard card look
            name = "hs-custom-" + base_of(entity["entity_id"]).replace(".", "-"); colour = entity["tile"].get("color")
            entity["widget"].remove_css_class(name)
            if base_of(entity["entity_id"]) == "roondeck.kef_input": continue   # its colour follows the input the speaker is on; a colour set in the builder must not paint over it
            if isinstance(colour, str) and len(colour) == 7 and colour.startswith("#"):
                entity["widget"].add_css_class(name); rules.append(f".hs-card.{name} {{ background: {mix(colour, '#232228', .34)}; border-color: {colour}; }}")
            elif base_of(entity["entity_id"]) != "roondeck.bus" and isinstance(entity["tile"].get("border"), str) and len(entity["tile"]["border"]) == 7 and entity["tile"]["border"].startswith("#"):
                entity["widget"].add_css_class(name); rules.append(f".hs-card.{name} {{ border-color: {entity['tile']['border']}; }}")   # a border of its own colour on a tile with no colour
        for domain, accent in (getattr(self, "home_domain_colours", None) or {}).items():
            rules.append(f".home-card.home-domain-{domain} .home-switch.on {{ background: {accent}; }}")
        def tile_of(entity): return entity.get("tile") or {}
        def is_scene(entity): return entity.get("domain") in {"scene", "script"}
        def has_place(entity): return isinstance(tile_of(entity).get("col"), int) and isinstance(tile_of(entity).get("row"), int)
        def is_half(entity): return tile_of(entity).get("half") is True
        spans = {"quarter": 2, "half": min(4, cols), "full": cols}
        def size_of(entity): return 1 if is_half(entity) else min(cols, spans.get(tile_of(entity).get("size"), 2)), tile_of(entity).get("rows") if tile_of(entity).get("rows") in (2, 3) else 1
        def start_of(entity): return tile_of(entity)["col"] * 2 + (1 if is_half(entity) and tile_of(entity).get("sub") == 1 else 0)
        taken, placed = set(), {}
        def spots(column, row, width, height): return {(column + dx, row + dy) for dx in range(width) for dy in range(height)}
        def free_slot(width, height, step):
            row = 0
            while True:
                for column in range(0, cols - width + 1, step):
                    if not spots(column, row, width, height) & taken: return column, row
                row += 1
        for number, entity in enumerate(entities):
            width, height = size_of(entity)
            if has_place(entity):
                column, row = start_of(entity), tile_of(entity)["row"]
                if column + width <= cols and not spots(column, row, width, height) & taken:
                    placed[number] = (column, row); taken |= spots(column, row, width, height)
        for number, entity in enumerate(entities):
            if number in placed: continue
            width, height = size_of(entity); column, row = free_slot(width, height, 1 if is_half(entity) else 2); placed[number] = (column, row); taken |= spots(column, row, width, height)
        grid_rows = max(max((row + size_of(entities[number])[1] for number, (_, row) in placed.items()), default=1), 6 if portrait else 3)
        for column in range(cols):
            for row in range(grid_rows):
                if (column, row) not in taken:
                    spacer = Gtk.Box(); spacer.set_hexpand(True); spacer.set_vexpand(True); self.home_grid.attach(spacer, column, row, 1, 1)
        for number, entity in enumerate(entities):
            width, height = size_of(entity); column, row = placed[number]
            if entity.get("widget") is not None:
                widget = entity["widget"]
                if base_of(entity["entity_id"]) == "roondeck.bus": self.set_bus_compact(self.bus_tiles.get(entity["entity_id"]), width == 1 and height == 1)   # half a column wide: the square tile
                if base_of(entity["entity_id"]) == "roondeck.player": self.hs_short = height == 1
                if base_of(entity["entity_id"]) == "roondeck.player":
                    tall = height >= 3   # a full-height player has room to spare, so the slider and controls are given some
                    self.hs_content.set_spacing(8 if tall else 10)   # the title, scrubber and controls stay together at the bottom; the spare height goes to the artwork above
                    for bar in (self.hs_progress, self.hs_scrub): bar.set_margin_top(6 if tall else 0); bar.set_margin_bottom(10 if tall else 0)
                    self.hs_volume_row.set_margin_top(6 if tall else 0)
                    self.hs_transport.set_margin_bottom(18 if tall else 0)   # lift the controls off the bottom edge
                if hasattr(widget, "chip"):   # a wide action tile (Update, Group) gets larger type and icon
                    widget.chip.set_size_request(*((56, 56) if width >= 4 else (44, 44)))
                    widget.detail_label.set_lines(3 if width >= 4 and height >= 2 else 2)   # a small tile has room for two lines, so a long status never pushes past its border
                    # The title sits beside the icon only where there is room for it: on the smallest tile it goes below the icon.
                    beside = width >= 4 or getattr(widget, "kef_kind", None) == "_input"   # the KEF input tile always has the speaker name next to the icon
                    widget.head.set_orientation(Gtk.Orientation.HORIZONTAL if beside else Gtk.Orientation.VERTICAL); widget.head.set_spacing(10 if beside else 8)
                    widget.value_label.set_valign(Gtk.Align.CENTER if beside else Gtk.Align.START)
                    (widget.add_css_class if width >= 4 else widget.remove_css_class)("hs-action-wide")
                if base_of(entity["entity_id"]) == "roondeck.network":
                    self.hs_net_wide = width >= 2
                    self.hs_net_value.remove_css_class("hs-net-small") if self.hs_net_wide else self.hs_net_value.add_css_class("hs-net-small")
            else:
                grown = scale * (1 + 0.2 * (min(height, 3) - 1) + (0.15 if width >= 4 and height >= 2 else 0))   # a taller tile gets a bigger icon and more air, so it is not a small card floating in a large one
                if is_scene(entity): widget = self.home_scene_card(entity, f"{number}-{entity.get('entity_id')}", rules, grown)
                else: widget = self.home_card(entity, number, rules, grown, columns == 3, is_half(entity))
            self.home_grid.attach(self.clip_cell(widget), column, row, width, height)
        self.home_tile_provider.load_from_data("\n".join(rules))
        if getattr(self, "hs_last_side", None): self.render_home_side(*self.hs_last_side)   # fill a bus tile that has just been added
        self.start_system_sampling()

    def home_accent(self, entity, domain):
        tile = entity.get("tile") or {}
        if tile.get("color"): return tile["color"]
        if domain == "climate": return CLIMATE_COLOUR
        return (getattr(self, "home_domain_colours", None) or {}).get("switch" if domain in {"input_boolean", "switch"} else domain, "#6ed9ae")

    def home_card_classes(self, widget, entity, domain, key, rules, on):
        widget.add_css_class("home-tile"); widget.add_css_class("home-card")
        widget.add_css_class("home-domain-switch" if domain in {"input_boolean", "switch"} else "home-domain-fan" if domain == "climate" else f"home-domain-{domain}")
        if on: widget.add_css_class("on")
        tile = entity.get("tile") or {}
        if tile.get("color") or domain == "climate":
            name = f"home-custom-{key}".replace(".", "-"); widget.add_css_class(name)
            colour = self.home_accent(entity, domain)
            rules += tile_colour_rules(("light", "fan", "switch", "scene"), name, colour)
            rules.append(f".home-card.{name} .home-switch.on {{ background: {colour}; }}")

    def home_icon_for(self, entity, domain, on, scale, accent):
        tile = entity.get("tile") or {}
        glyph = round(40 * scale)
        texture = self.home_art(tile["icon"], accent) if tile.get("icon") else None
        if tile.get("icon") and texture is None: self.home_signature = None   # the picture has not arrived yet: try again next refresh
        if texture is not None:
            icon = Gtk.Image.new_from_paintable(texture); icon.set_pixel_size(glyph); icon.set_opacity(1 if on else .75)
        else:
            if domain in {"scene", "script"}: name = "check"
            elif domain in CARD_DOMAINS: name = CARD_DOMAINS[domain]
            elif any(word in entity.get("entity_id", "") for word in ("pihole", "pi_hole", "adguard")): name = "shield"
            else: name = "switchon" if on else "switch"
            icon = FamilyIcon(name, glyph)
        icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.add_css_class("home-icon")
        return icon

    def home_detail(self, entity, on):
        state = str(entity.get("state", "unknown"))
        if entity.get("available", True) is False: return "UNAVAILABLE"
        if state == "mixed": return f"{entity.get('linked_on', 0)} OF {entity.get('linked_total', 0)} ON"
        if entity.get("domain") == "climate": return entity.get("detail", state.upper()) if on else "OFF"
        if entity.get("supports_level"):
            level = entity.get("percentage")
            if level is None and entity.get("brightness") is not None: level = round(float(entity["brightness"]) * 100 / 255)
            return f"{round(level)}%" if on and level is not None else ("ON" if on else "OFF")
        return "ON" if on else "OFF" if state in {"on", "off"} else state.upper()

    def home_card(self, entity, number, rules, scale, compact=False, half=False):
        domain = entity.get("domain", "switch"); state = str(entity.get("state", "unknown"))
        on = bool(entity.get("on", state in {"on", "open", "playing"})); accent = self.home_accent(entity, domain); entity_id = entity.get("entity_id", "")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); card.set_hexpand(True); card.set_vexpand(True)
        self.home_card_classes(card, entity, domain, number, rules, on)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(16 * scale)); inner.set_valign(Gtk.Align.CENTER); inner.set_vexpand(True)
        top = Gtk.Box(spacing=round(20 * scale))
        big = self.home_big_tiles() and not half
        if big: card.add_css_class("home-big")
        icon = self.home_icon_for(entity, domain, on, scale * (1.5 if big else 1), accent)
        chip = 88 if big else round((48 if half else 58) * scale); button = Gtk.Button(); button.add_css_class("home-device-button"); button.add_css_class("home-icon-chip"); button.set_size_request(chip, chip)
        button.set_valign(Gtk.Align.CENTER); button.set_halign(Gtk.Align.START); button.set_child(icon); button.connect("clicked", self.toggle_home, entity_id); top.append(button)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); text.set_hexpand(True); text.set_valign(Gtk.Align.CENTER)
        name = self.label((entity.get("tile") or {}).get("label") or entity.get("name", "Device"), "home-name", 0); name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(1)   # let the card narrow the name instead of the name widening the card
        name.set_wrap(False); name.set_lines(1)   # one line, cut with an ellipsis: a long name must never make its tile (and so the whole grid) taller
        text.append(name); text.append(self.label(self.home_detail(entity, on), "home-state", 0))
        has_level = bool(entity.get("supports_level"))
        switch = None
        if not has_level:
            switch = Gtk.Box(); switch.add_css_class("home-switch"); switch.set_valign(Gtk.Align.CENTER); switch.set_halign(Gtk.Align.END); switch.set_hexpand(False)
            if on: switch.add_css_class("on")
            knob = Gtk.Box(); knob.add_css_class("home-switch-knob"); knob.set_hexpand(True); knob.set_halign(Gtk.Align.END if on else Gtk.Align.START); switch.append(knob)
        if half:
            # Half a column is narrow: icon (and toggle) on top, name and state under them.
            filler = Gtk.Box(); filler.set_hexpand(True); top.append(filler)
            if switch is not None: top.append(switch)
            name.set_wrap(False); inner.set_spacing(round(8 * scale)); top.set_spacing(0)
        else:
            # One row for icon, name and toggle keeps every card short enough for three rows to fit the screen.
            top.append(text)
            if switch is not None: top.append(switch)
        if compact and not half: inner.set_spacing(round(14 * scale)); top.set_spacing(round(16 * scale))
        if big: inner.set_spacing(22); top.set_spacing(22); inner.set_margin_start(14); inner.set_margin_end(10)
        inner.append(top)
        if half: inner.append(text)
        if has_level:
            level = entity.get("percentage")
            if level is None and entity.get("brightness") is not None: level = round(float(entity["brightness"]) * 100 / 255)
            slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); slider.add_css_class("home-level"); slider.add_css_class("home-slider")
            slider.set_draw_value(False); slider.set_hexpand(True); slider.set_value(float(level or 0)); slider.connect("value-changed", self.change_home_value, entity_id); inner.append(slider)
        else:
            tap = Gtk.GestureClick(); tap.connect("released", lambda *_: self.toggle_home(None, entity_id)); card.add_controller(tap)
        card.append(inner)
        return card

    def clip_cell(self, widget):
        """Hold a tile in a frame whose size ignores what is inside it, so nothing a tile shows (a long name, a tall player) can ever change the shape of the screen; the grid decides every tile's size, and anything extra is clipped."""
        frame = Gtk.ScrolledWindow(); frame.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.EXTERNAL)   # neither direction asks the grid for room
        frame.set_propagate_natural_height(False); frame.set_propagate_natural_width(False); frame.set_min_content_height(0); frame.set_min_content_width(0); frame.set_kinetic_scrolling(False); frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_hexpand(True); frame.set_vexpand(True); frame.add_css_class("home-clip"); frame.clip_wrapper = True
        frame.set_child(widget); return frame

    def home_scene_card(self, entity, key, rules, scale):
        domain = "scene"; entity_id = entity.get("entity_id", ""); accent = self.home_accent(entity, domain)
        button = Gtk.Button(); button.set_hexpand(True); button.set_vexpand(True)
        self.home_card_classes(button, entity, domain, key, rules, True); button.add_css_class("home-scene"); button.add_css_class("scene-action")
        big = self.home_big_tiles()
        if big: button.add_css_class("home-big")
        chip = 88 if big else round(44 * scale); holder = Gtk.Box(); holder.add_css_class("home-icon-chip"); holder.set_size_request(chip, chip)
        icon = self.home_icon_for(entity, domain, True, scale * (1.5 if big else 1), accent); icon.set_hexpand(True); holder.append(icon)
        name = self.label((entity.get("tile") or {}).get("label") or entity.get("name", "Scene"), "home-name", 0); name.set_wrap(True); name.set_wrap_mode(Pango.WrapMode.WORD_CHAR); name.set_lines(2); name.set_ellipsize(Pango.EllipsizeMode.END); name.set_max_width_chars(1)   # up to two lines now that the caption line is gone
        available = entity.get("available", True)
        status = self.label("" if available else "UNAVAILABLE", "home-state", 0); status.set_ellipsize(Pango.EllipsizeMode.END); status.set_max_width_chars(1)   # let the tile narrow the text, never the text widen the tile; status.set_visible(bool(status.get_text()))   # an empty caption must not take height: a two-line name needs the room
        if big:
            # Like the bus tile: the icon on the left, centred, with the name and its caption beside it.
            content = Gtk.Box(spacing=22); content.set_valign(Gtk.Align.CENTER); content.set_margin_start(14); content.set_margin_end(10)
            holder.set_valign(Gtk.Align.CENTER); holder.set_halign(Gtk.Align.START); content.append(holder)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); words.set_valign(Gtk.Align.CENTER); words.set_hexpand(True); words.append(name); words.append(status); content.append(words)
        else:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); holder.set_halign(Gtk.Align.START); content.append(holder)
            spacer = Gtk.Box(); spacer.set_vexpand(True); content.append(spacer); content.append(name); content.append(status)
        button.set_child(content); button.set_sensitive(bool(available))
        button.scene_tile = button; button.scene_status_label = status
        button.connect("clicked", self.activate_home_scene, entity_id)
        return button
