"""Landscape Home page: one grid (2 or 3 columns) holding the player card, the next bus and the device cards.

Used on the 7-inch and larger landscape displays. The original 800x480 panel and portrait displays keep the
classic tile grid in home_page.py.
"""
from __future__ import annotations

from native_common import FamilyIcon
from home_page import tile_colour_rules
import os
from pathlib import Path
from gi.repository import GLib, Gtk, Pango

GAP = 18                    # the one gap used between every card, column and row on the page
HOME_BUS_ROUTE = "42"       # shown when the stop serves it; otherwise the stop's first route
CLIMATE_COLOUR = "#4fc3d9"
CARD_DOMAINS = {"light": "light", "fan": "fan", "climate": "snow"}
SAMPLES = 45                # readings kept for the live tiles
SAMPLE_SECONDS = 2
SPARK_GREEN, SPARK_BLUE = (0.43, 0.85, 0.68), (0.42, 0.66, 1.0)


class HomeDashboardMixin:
    def home_dashboard_active(self):
        return (not self.window.has_css_class("portrait") and not self.window.has_css_class("original-landscape")
                and getattr(self, "viewport_width", 800) >= 1000)

    def home_scale(self):
        return max(1.0, getattr(self, "viewport_width", 1280) / 1280)

    # ---- the player and next-bus cards: built once, then placed on the grid like any other tile ----
    def build_home_side(self):
        side = Gtk.Box(); side.add_css_class("home-side"); side.set_visible(False)   # an empty, hidden holder: the cards live in the grid
        player = Gtk.Overlay(); player.add_css_class("hs-card"); player.set_overflow(Gtk.Overflow.HIDDEN); player.set_hexpand(True); player.set_vexpand(True); self.hs_player = player; self.hs_short = False
        self.hs_art = Gtk.Picture(); self.hs_art.set_content_fit(Gtk.ContentFit.COVER); self.hs_art.set_can_shrink(True); self.hs_art.set_halign(Gtk.Align.FILL); self.hs_art.set_valign(Gtk.Align.FILL)
        player.set_child(self.hs_art)
        fade = Gtk.Box(); fade.add_css_class("hs-fade"); fade.set_can_target(False); player.add_overlay(fade); self.hs_fade = fade; self.hs_opts = {}
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); content.add_css_class("hs-content")
        self.hs_zone = self.label("", "hs-zone"); content.append(self.hs_zone)
        spacer = Gtk.Box(); spacer.set_vexpand(True); content.append(spacer)
        self.hs_title = self.label("", "hs-title"); self.hs_title.set_wrap(True); self.hs_title.set_lines(2); self.hs_title.set_ellipsize(Pango.EllipsizeMode.END); self.hs_title.set_max_width_chars(1)
        self.hs_artist = self.label("", "hs-artist"); self.hs_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.hs_thumb = Gtk.Picture(); self.hs_thumb.set_content_fit(Gtk.ContentFit.COVER); self.hs_thumb.set_can_shrink(True); self.hs_thumb.add_css_class("hs-thumb"); self.hs_thumb.set_overflow(Gtk.Overflow.HIDDEN); self.hs_thumb.set_valign(Gtk.Align.START); self.hs_thumb.set_visible(False)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); words.set_hexpand(True); words.set_valign(Gtk.Align.END); words.append(self.hs_title); words.append(self.hs_artist)
        head = Gtk.Box(spacing=16); head.append(self.hs_thumb); head.append(words); content.append(head)
        self.hs_progress = Gtk.ProgressBar(); self.hs_progress.add_css_class("hs-progress"); content.append(self.hs_progress)
        self.hs_scrub = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1); self.hs_scrub.add_css_class("home-slider"); self.hs_scrub.add_css_class("hs-scrub"); self.hs_scrub.set_draw_value(False); self.hs_scrub.set_visible(False)
        self.hs_scrub.connect("value-changed", self.change_seek); content.append(self.hs_scrub)
        transport = Gtk.Box(spacing=26); transport.set_halign(Gtk.Align.CENTER)
        self.hs_prev = self.icon_button("previous", lambda *_: self.control("previous"), "hs-transport")
        self.hs_play = self.icon_button("play", lambda *_: self.control("playpause"), "hs-play")
        self.hs_next = self.icon_button("next", lambda *_: self.control("next"), "hs-transport")
        for button in (self.hs_prev, self.hs_play, self.hs_next): transport.append(button)
        content.append(transport)
        volume = Gtk.Box(spacing=14); volume.add_css_class("hs-volume-row")
        self.hs_volume_label = self.label("VOL", "hs-volume-label"); volume.append(self.hs_volume_label)
        self.hs_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); self.hs_volume.add_css_class("home-slider"); self.hs_volume.add_css_class("hs-volume")
        self.hs_volume.set_hexpand(True); self.hs_volume.set_draw_value(False); self.hs_volume.connect("value-changed", self.change_volume); volume.append(self.hs_volume)
        self.hs_volume_row = volume; content.append(volume)
        player.add_overlay(content)
        bus = Gtk.Box(spacing=14); bus.add_css_class("hs-card"); bus.add_css_class("hs-bus"); bus.set_hexpand(True); bus.set_vexpand(True); self.hs_bus = bus
        chip = Gtk.Box(); chip.add_css_class("home-icon-chip"); chip.add_css_class("hs-bus-chip"); chip.set_valign(Gtk.Align.CENTER); chip.set_halign(Gtk.Align.CENTER)
        self.hs_bus_icon = FamilyIcon("bus", 44); self.hs_bus_icon.set_halign(Gtk.Align.CENTER); self.hs_bus_icon.set_valign(Gtk.Align.CENTER); self.hs_bus_icon.set_hexpand(True); chip.append(self.hs_bus_icon); bus.append(chip)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); text.set_hexpand(True); text.set_valign(Gtk.Align.CENTER)
        self.hs_route = self.label("", "hs-route"); self.hs_then = self.label("", "hs-then"); text.append(self.hs_route); text.append(self.hs_then); bus.append(text)
        arrival = Gtk.Box(spacing=8); arrival.set_valign(Gtk.Align.CENTER)
        self.hs_minutes = self.label("", "hs-minutes"); self.hs_unit = self.label("min", "hs-unit"); self.hs_unit.set_valign(Gtk.Align.END); arrival.append(self.hs_minutes); arrival.append(self.hs_unit); bus.append(arrival)
        self.hs_cpu, self.hs_cpu_value, self.hs_cpu_detail, self.hs_cpu_area = self.build_stat_card("CPU")
        self.hs_net, self.hs_net_value, self.hs_net_detail, self.hs_net_area = self.build_stat_card("NETWORK")
        self.stat_cpu, self.stat_down, self.stat_up = [], [], []
        self.hs_cpu_area.set_draw_func(lambda area, cr, width, height, *_: self.draw_spark(cr, width, height, [(self.stat_cpu, SPARK_GREEN)], 100.0))
        self.hs_net_area.set_draw_func(lambda area, cr, width, height, *_: self.draw_spark(cr, width, height, [(self.stat_up, SPARK_GREEN), (self.stat_down, SPARK_BLUE)], None))
        self.stat_timer = None; self.stat_prev_cpu = None; self.stat_prev_net = None; self.hs_live_shown = set()
        return side

    # ---- live tiles: CPU and network, read straight from the Pi every couple of seconds ----
    def build_stat_card(self, title):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); card.add_css_class("hs-card"); card.add_css_class("hs-stat"); card.set_hexpand(True); card.set_vexpand(True)
        value = self.label("—", "hs-stat-value", 0); detail = self.label("", "hs-stat-detail", 0); detail.set_ellipsize(Pango.EllipsizeMode.END); value.set_ellipsize(Pango.EllipsizeMode.END)
        area = Gtk.DrawingArea(); area.set_vexpand(True); area.set_hexpand(True); area.set_content_height(20)
        card.append(self.label(title, "hs-stat-title", 0)); card.append(value); card.append(area); card.append(detail)
        return card, value, detail, area

    def draw_spark(self, cr, width, height, series, top):
        scale = top or max([1.0] + [max(values) for values, _ in series if values])
        for values, (red, green, blue) in series:
            if len(values) < 2: continue
            step = width / (SAMPLES - 1); first = width - step * (len(values) - 1)
            points = [(first + index * step, height - 3 - min(value, scale) / scale * (height - 6)) for index, value in enumerate(values)]
            cr.set_line_width(2.5); cr.set_source_rgba(red, green, blue, 1)
            cr.move_to(*points[0])
            for point in points[1:]: cr.line_to(*point)
            cr.stroke_preserve(); cr.line_to(points[-1][0], height); cr.line_to(points[0][0], height); cr.close_path(); cr.set_source_rgba(red, green, blue, .16); cr.fill()

    def start_system_sampling(self):
        if self.hs_live_shown and self.stat_timer is None:
            self.stat_timer = GLib.timeout_add_seconds(SAMPLE_SECONDS, self.sample_system); self.sample_system()

    def sample_system(self):
        if not self.hs_live_shown:
            self.stat_timer = None; return False
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
        def rate(bits): return f"{bits / 1e6:.1f} Mbit/s" if bits >= 1e6 else f"{bits / 1e3:.0f} kbit/s"
        if "roondeck.cpu" in self.hs_live_shown:
            self.hs_cpu_value.set_text(f"{self.stat_cpu[-1]:.0f}%" if self.stat_cpu else "—")
            try: temperature = f"{int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000:.0f} °C · "
            except (OSError, ValueError): temperature = ""
            self.hs_cpu_detail.set_text(f"{temperature}load {os.getloadavg()[0]:.1f}"); self.hs_cpu_area.queue_draw()
        if "roondeck.network" in self.hs_live_shown:
            self.hs_net_value.set_text(rate(self.stat_down[-1]) if self.stat_down else "—"); self.hs_net_detail.set_text(f"up {rate(self.stat_up[-1])}" if self.stat_up else ""); self.hs_net_area.queue_draw()
        return True

    def render_home_side(self, roon, status):
        if not self.home_dashboard_active(): return
        scale = self.home_scale()
        # The Now Playing page already works out the zone, track, controls and volume each refresh; mirror its widgets.
        options = self.hs_opts or {}
        self.hs_zone.set_text(str(options.get("label") or self.zone.get_text() or "ROON").upper()); self.hs_title.set_text(self.title.get_text()); self.hs_artist.set_text(self.artist.get_text())
        paintable = self.artwork.get_paintable()
        art = options.get("art") if options.get("art") in ("thumb", "off") else "background"
        self.hs_art.set_visible(art == "background"); self.hs_fade.set_visible(art == "background"); self.hs_thumb.set_visible(art == "thumb" and not self.hs_short)
        self.hs_thumb.set_size_request(round(104 * scale), round(104 * scale))
        for picture in (self.hs_art, self.hs_thumb):
            if paintable is not picture.get_paintable(): picture.set_paintable(paintable)
        adjustment = self.progress.get_adjustment(); upper = adjustment.get_upper()
        self.hs_progress.set_fraction(min(1.0, adjustment.get_value() / upper) if upper > 1 else 0.0)
        scrubber = bool(options.get("scrubber"))
        self.hs_progress.set_visible(not scrubber); self.hs_scrub.set_visible(scrubber)
        if scrubber:
            self.seek_updating = True; self.hs_scrub.set_range(0, max(1.0, upper)); self.hs_scrub.set_value(adjustment.get_value()); self.hs_scrub.set_sensitive(self.progress.get_sensitive()); self.seek_updating = False
        current = self.play.get_child(); icon_name = current.icon_name if isinstance(current, FamilyIcon) else "play"; glyph = round(40 * scale)
        shown = self.hs_play.get_child()
        if not isinstance(shown, FamilyIcon) or shown.icon_name != icon_name or shown.get_pixel_size() != glyph: self.hs_play.set_child(FamilyIcon(icon_name, glyph))
        for mine, theirs in ((self.hs_prev, self.prev), (self.hs_play, self.play), (self.hs_next, self.next)): mine.set_sensitive(theirs.get_sensitive())
        self.volume_updating = True
        self.hs_volume.set_value(self.volume.get_value()); self.hs_volume.set_sensitive(self.volume.get_sensitive()); self.hs_volume_row.set_visible(self.volume.get_visible() and not self.hs_short and options.get("volume") is not False)
        self.hs_zone.set_visible(not self.hs_short and options.get("heading") is not False); self.hs_title.set_lines(1 if self.hs_short else 2)
        self.volume_updating = False
        services = (status or {}).get("services") or []
        chosen = next((item for item in services if str(item.get("service")) == HOME_BUS_ROUTE), services[0] if services else None)
        self.hs_bus.set_visible(chosen is not None)
        if chosen is None: return
        minutes = [arrival.get("minutes") for arrival in chosen.get("arrivals", []) if arrival.get("minutes") is not None]
        self.hs_route.set_text(str(chosen.get("service", "")))
        self.hs_minutes.set_text("—" if not minutes else "Due" if minutes[0] == 0 else str(minutes[0])); self.hs_unit.set_visible(bool(minutes) and minutes[0] != 0)
        self.hs_then.set_text(f"then {minutes[1]} min" if len(minutes) > 1 else "")
        self.hs_then.set_visible(len(minutes) > 1)

    # ---- right: the grid of device cards ----
    def render_home_dashboard(self, home, entities):
        columns = home.get("columns") if home.get("columns") in (2, 3) else 3   # 3 unless the owner chose 2
        cols = columns * 2                                                      # the grid is counted in half columns
        scale = self.home_scale()
        self.home_grid.set_row_spacing(GAP); self.home_grid.set_column_spacing(GAP); self.home_grid.set_hexpand(True)
        # The player, the next bus and any live tiles are tiles too: placed, sized and moved like the devices.
        cards = home.get("cards") or {}
        virtual = []
        untouched = not any(isinstance((cards.get(key) or {}).get("col"), int) for key in ("roondeck.player", "roondeck.bus"))
        wanted = [("roondeck.player", self.hs_player, 2, (0, 0)), ("roondeck.bus", self.hs_bus, 1, (0, 2))]
        if (cards.get("roondeck.cpu") or {}).get("show"): wanted.append(("roondeck.cpu", self.hs_cpu, 1, None))
        if (cards.get("roondeck.network") or {}).get("show"): wanted.append(("roondeck.network", self.hs_net, 1, None))
        for key, widget, rows, home_cell in wanted:
            tile = dict(cards.get(key) or {}); tile.setdefault("rows", rows)
            if home_cell and untouched and not isinstance(tile.get("col"), int): tile["col"], tile["row"] = home_cell   # the player top-left, the bus under it
            virtual.append({"entity_id": key, "domain": "roondeck", "widget": widget, "tile": tile})
        entities = virtual + list(entities)
        self.hs_opts = dict(cards.get("roondeck.player") or {})
        def mix(front, back, amount):
            top = tuple(int(front[index:index + 2], 16) for index in (1, 3, 5)); base = tuple(int(back[index:index + 2], 16) for index in (1, 3, 5))
            return "#" + "".join(f"{round(low + (high - low) * amount):02x}" for high, low in zip(top, base))
        self.hs_live_shown = {key for key, *_ in wanted if key in ("roondeck.cpu", "roondeck.network")}
        rules = []
        for entity in virtual:                     # each card can have its own colour; without one it keeps the standard card look
            name = "hs-custom-" + entity["entity_id"].replace(".", "-"); colour = entity["tile"].get("color")
            entity["widget"].remove_css_class(name)
            if isinstance(colour, str) and len(colour) == 7 and colour.startswith("#"):
                entity["widget"].add_css_class(name); rules.append(f".hs-card.{name} {{ background: {mix(colour, '#232228', .34)}; border-color: {mix(colour, '#44414c', .58)}; }}")
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
        grid_rows = max(max((row + size_of(entities[number])[1] for number, (_, row) in placed.items()), default=1), 3)
        for column in range(cols):
            for row in range(grid_rows):
                if (column, row) not in taken:
                    spacer = Gtk.Box(); spacer.set_hexpand(True); spacer.set_vexpand(True); self.home_grid.attach(spacer, column, row, 1, 1)
        for number, entity in enumerate(entities):
            width, height = size_of(entity); column, row = placed[number]
            if entity.get("widget") is not None:
                widget = entity["widget"]
                if entity["entity_id"] == "roondeck.player": self.hs_short = height == 1
            elif is_scene(entity): widget = self.home_scene_card(entity, f"{number}-{entity.get('entity_id')}", rules, scale)
            else: widget = self.home_card(entity, number, rules, scale, columns == 3, is_half(entity))
            self.home_grid.attach(widget, column, row, width, height)
        self.home_tile_provider.load_from_data("\n".join(rules))
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
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(26 * scale)); inner.set_valign(Gtk.Align.CENTER); inner.set_vexpand(True)
        inner.set_margin_bottom(round(8 * scale))   # a little nudge up: centred blocks look low to the eye
        top = Gtk.Box(spacing=round(20 * scale))
        icon = self.home_icon_for(entity, domain, on, scale, accent)
        chip = round((48 if half else 64) * scale); button = Gtk.Button(); button.add_css_class("home-device-button"); button.add_css_class("home-icon-chip"); button.set_size_request(chip, chip)
        button.set_valign(Gtk.Align.CENTER); button.set_halign(Gtk.Align.START); button.set_child(icon); button.connect("clicked", self.toggle_home, entity_id); top.append(button)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); text.set_hexpand(True); text.set_valign(Gtk.Align.CENTER)
        name = self.label((entity.get("tile") or {}).get("label") or entity.get("name", "Device"), "home-name", 0); name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(1)   # let the card narrow the name instead of the name widening the card
        if compact: name.set_wrap(True); name.set_lines(2); name.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text.append(name); text.append(self.label(self.home_detail(entity, on), "home-state", 0))
        has_level = bool(entity.get("supports_level"))
        switch = None
        if not has_level:
            switch = Gtk.Box(); switch.add_css_class("home-switch"); switch.set_valign(Gtk.Align.CENTER)
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

    def home_scene_card(self, entity, key, rules, scale):
        domain = "scene"; entity_id = entity.get("entity_id", ""); accent = self.home_accent(entity, domain)
        button = Gtk.Button(); button.set_hexpand(True); button.set_vexpand(True)
        self.home_card_classes(button, entity, domain, key, rules, True); button.add_css_class("home-scene"); button.add_css_class("scene-action")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        chip = round(64 * scale); holder = Gtk.Box(); holder.add_css_class("home-icon-chip"); holder.set_size_request(chip, chip); holder.set_halign(Gtk.Align.START)
        icon = self.home_icon_for(entity, domain, True, scale, accent); icon.set_hexpand(True); holder.append(icon); content.append(holder)
        spacer = Gtk.Box(); spacer.set_vexpand(True); content.append(spacer)
        name = self.label((entity.get("tile") or {}).get("label") or entity.get("name", "Scene"), "home-name", 0); name.set_wrap(True); name.set_lines(2); name.set_ellipsize(Pango.EllipsizeMode.END)
        available = entity.get("available", True)
        status = self.label("TAP TO ACTIVATE" if available else "UNAVAILABLE", "home-state", 0)
        content.append(name); content.append(status)
        button.set_child(content); button.set_sensitive(bool(available))
        button.scene_tile = button; button.scene_status_label = status
        button.connect("clicked", self.activate_home_scene, entity_id)
        return button
