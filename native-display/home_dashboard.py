"""Landscape Home page: one grid (2 or 3 columns) holding the player card, the next bus and the device cards.

Used on the 7-inch and larger landscape displays. The original 800x480 panel and portrait displays keep the
classic tile grid in home_page.py.
"""
from __future__ import annotations

from native_common import FamilyIcon
from home_page import tile_colour_rules
from gi.repository import Gtk, Pango

GAP = 18                    # the one gap used between every card, column and row on the page
HOME_BUS_ROUTE = "42"       # shown when the stop serves it; otherwise the stop's first route
CLIMATE_COLOUR = "#4fc3d9"
CARD_DOMAINS = {"light": "light", "fan": "fan", "climate": "snow"}


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
        fade = Gtk.Box(); fade.add_css_class("hs-fade"); fade.set_can_target(False); player.add_overlay(fade)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); content.add_css_class("hs-content")
        self.hs_zone = self.label("", "hs-zone"); content.append(self.hs_zone)
        spacer = Gtk.Box(); spacer.set_vexpand(True); content.append(spacer)
        self.hs_title = self.label("", "hs-title"); self.hs_title.set_wrap(True); self.hs_title.set_lines(2); self.hs_title.set_ellipsize(Pango.EllipsizeMode.END); self.hs_title.set_max_width_chars(1)
        self.hs_artist = self.label("", "hs-artist"); self.hs_artist.set_ellipsize(Pango.EllipsizeMode.END)
        content.append(self.hs_title); content.append(self.hs_artist)
        self.hs_progress = Gtk.ProgressBar(); self.hs_progress.add_css_class("hs-progress"); content.append(self.hs_progress)
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
        return side

    def render_home_side(self, roon, status):
        if not self.home_dashboard_active(): return
        scale = self.home_scale()
        # The Now Playing page already works out the zone, track, controls and volume each refresh; mirror its widgets.
        self.hs_zone.set_text((self.zone.get_text() or "ROON").upper()); self.hs_title.set_text(self.title.get_text()); self.hs_artist.set_text(self.artist.get_text())
        paintable = self.artwork.get_paintable()
        if paintable is not self.hs_art.get_paintable(): self.hs_art.set_paintable(paintable)
        adjustment = self.progress.get_adjustment(); upper = adjustment.get_upper()
        self.hs_progress.set_fraction(min(1.0, adjustment.get_value() / upper) if upper > 1 else 0.0)
        current = self.play.get_child(); icon_name = current.icon_name if isinstance(current, FamilyIcon) else "play"; glyph = round(40 * scale)
        shown = self.hs_play.get_child()
        if not isinstance(shown, FamilyIcon) or shown.icon_name != icon_name or shown.get_pixel_size() != glyph: self.hs_play.set_child(FamilyIcon(icon_name, glyph))
        for mine, theirs in ((self.hs_prev, self.prev), (self.hs_play, self.play), (self.hs_next, self.next)): mine.set_sensitive(theirs.get_sensitive())
        self.volume_updating = True
        self.hs_volume.set_value(self.volume.get_value()); self.hs_volume.set_sensitive(self.volume.get_sensitive()); self.hs_volume_row.set_visible(self.volume.get_visible() and not self.hs_short)
        self.hs_zone.set_visible(not self.hs_short); self.hs_title.set_lines(1 if self.hs_short else 2)
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
        scale = self.home_scale()
        self.home_grid.set_row_spacing(GAP); self.home_grid.set_column_spacing(GAP); self.home_grid.set_hexpand(True)
        # The player and the next bus are tiles too: placed, sized and moved like the devices, with the player two rows tall unless the owner shortens it.
        cards = home.get("cards") or {}
        virtual = []
        untouched = not any(isinstance((cards.get(key) or {}).get("col"), int) for key in ("roondeck.player", "roondeck.bus"))
        for key, widget, rows, home_cell in (("roondeck.player", self.hs_player, 2, (0, 0)), ("roondeck.bus", self.hs_bus, 1, (0, 2))):
            tile = dict(cards.get(key) or {}); tile.setdefault("rows", rows)
            if untouched and not isinstance(tile.get("col"), int): tile["col"], tile["row"] = home_cell   # the player top-left, the bus under it
            virtual.append({"entity_id": key, "domain": "roondeck", "widget": widget, "tile": tile})
        entities = virtual + list(entities)
        rules = []
        for domain, accent in (getattr(self, "home_domain_colours", None) or {}).items():
            rules.append(f".home-card.home-domain-{domain} .home-switch.on {{ background: {accent}; }}")
        def tile_of(entity): return entity.get("tile") or {}
        def is_scene(entity): return entity.get("domain") in {"scene", "script"}
        def plain(entity): return tile_of(entity).get("size") in (None, "auto") and tile_of(entity).get("rows") != 2
        def has_place(entity): return isinstance(tile_of(entity).get("col"), int) and isinstance(tile_of(entity).get("row"), int)
        # Neighbouring scenes share one cell as two square buttons.
        units, index = [], 0
        while index < len(entities):
            entity = entities[index]
            other = entities[index + 1] if index + 1 < len(entities) else None
            same_cell = other is not None and has_place(entity) and has_place(other) and (tile_of(entity)["col"], tile_of(entity)["row"]) == (tile_of(other)["col"], tile_of(other)["row"])
            if columns == 2 and other is not None and is_scene(entity) and is_scene(other) and plain(entity) and plain(other) and ((not has_place(entity) and not has_place(other)) or same_cell):
                units.append([entity, other]); index += 2
            else: units.append([entity]); index += 1
        spans = {"quarter": 1, "half": min(2, columns), "full": columns}
        def size_of(unit): return min(columns, spans.get(tile_of(unit[0]).get("size"), 1)), 2 if tile_of(unit[0]).get("rows") == 2 else 1
        taken, placed = set(), {}
        def spots(column, row, width, height): return {(column + dx, row + dy) for dx in range(width) for dy in range(height)}
        def free_slot(width, height):
            row = 0
            while True:
                for column in range(columns - width + 1):
                    if not spots(column, row, width, height) & taken: return column, row
                row += 1
        for number, unit in enumerate(units):
            width, height = size_of(unit); tile = tile_of(unit[0])
            if has_place(unit[0]) and tile["col"] + width <= columns and not spots(tile["col"], tile["row"], width, height) & taken:
                placed[number] = (tile["col"], tile["row"]); taken |= spots(tile["col"], tile["row"], width, height)
        for number, unit in enumerate(units):
            if number in placed: continue
            width, height = size_of(unit); column, row = free_slot(width, height); placed[number] = (column, row); taken |= spots(column, row, width, height)
        grid_rows = max(max((row + size_of(units[number])[1] for number, (_, row) in placed.items()), default=1), 3)
        for column in range(columns):
            for row in range(grid_rows):
                if (column, row) not in taken:
                    spacer = Gtk.Box(); spacer.set_hexpand(True); spacer.set_vexpand(True); self.home_grid.attach(spacer, column, row, 1, 1)
        for number, unit in enumerate(units):
            width, height = size_of(unit); column, row = placed[number]
            if unit[0].get("widget") is not None:
                widget = unit[0]["widget"]
                if unit[0]["entity_id"] == "roondeck.player": self.hs_short = height == 1
            elif is_scene(unit[0]):
                cell = Gtk.Box(spacing=GAP); cell.set_homogeneous(True); cell.set_hexpand(True); cell.set_vexpand(True)
                for entity in unit: cell.append(self.home_scene_card(entity, f"{number}-{entity.get('entity_id')}", rules, scale))
                widget = cell
            else: widget = self.home_card(unit[0], number, rules, scale, columns == 3)
            self.home_grid.attach(widget, column, row, width, height)
        self.home_tile_provider.load_from_data("\n".join(rules))

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
            icon = Gtk.Image.new_from_paintable(texture); icon.set_pixel_size(glyph); icon.set_opacity(1 if on else .55)
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

    def home_card(self, entity, number, rules, scale, compact=False):
        domain = entity.get("domain", "switch"); state = str(entity.get("state", "unknown"))
        on = bool(entity.get("on", state in {"on", "open", "playing"})); accent = self.home_accent(entity, domain); entity_id = entity.get("entity_id", "")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); card.set_hexpand(True); card.set_vexpand(True)
        self.home_card_classes(card, entity, domain, number, rules, on)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(26 * scale)); inner.set_valign(Gtk.Align.CENTER); inner.set_vexpand(True)
        inner.set_margin_bottom(round(8 * scale))   # a little nudge up: centred blocks look low to the eye
        top = Gtk.Box(spacing=round(20 * scale))
        icon = self.home_icon_for(entity, domain, on, scale, accent)
        chip = round(64 * scale); button = Gtk.Button(); button.add_css_class("home-device-button"); button.add_css_class("home-icon-chip"); button.set_size_request(chip, chip)
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
        # One row for icon, name and toggle keeps every card short enough for three rows to fit the screen.
        top.append(text)
        if switch is not None: top.append(switch)
        if compact: inner.set_spacing(round(14 * scale)); top.set_spacing(round(16 * scale))
        inner.append(top)
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
