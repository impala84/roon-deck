"""Home page: Home Assistant switches, scenes and values."""
from __future__ import annotations

from native_common import BUS, FamilyIcon, PORTRAIT_CONTENT_GAP, elastic_vertical_scroll, get_bytes, post_json
import json
import threading
import time
from gi.repository import Gdk, GLib, Gtk


def tile_colour_rules(selector_domains, name, accent):
    """The same look as the shared colour rules, for one tile whose colour was chosen on its own."""
    def blend(foreground, background, amount):
        front = tuple(int(foreground[index:index + 2], 16) for index in (1, 3, 5)); back = tuple(int(background[index:index + 2], 16) for index in (1, 3, 5))
        return "#" + "".join(f"{round(base + (top - base) * amount):02x}" for top, base in zip(front, back))
    idle = blend(accent, "#232228", .18); active = blend(accent, "#232228", .34); border = blend(accent, "#44414c", .58)
    rules = []
    for domain in selector_domains:
        tile = f".home-tile.home-domain-{domain}.{name}"
        rules += [f"{tile} {{ background: {idle}; border-color: {border}; }}", f"{tile}.on {{ background: {active}; border-color: {accent}; }}",
                  f"{tile} .home-icon, {tile}.on .home-device-button {{ color: {accent}; }}", f"{tile} .home-level highlight {{ background: {accent}; }}",
                  f"{tile}.activated {{ background: {active}; border-color: {accent}; box-shadow: 0 0 18px {accent}; }}"]
    return rules


class HomePageMixin:
    def home_art(self, name, colour=None):
        """A saved icon or image as a texture; fetched once from the Pi's own web service, then kept. An icon can be asked for in one colour."""
        cache = getattr(self, "home_art_cache", None)
        if cache is None: cache = self.home_art_cache = {}
        key = (name, colour)
        if key not in cache:
            data = get_bytes(BUS + "/api/device/home-art/" + name + (("?color=%23" + colour.lstrip("#")) if colour else ""), timeout=1.5)
            texture = None
            if data:
                try: texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                except GLib.Error: texture = None
            if texture is not None or len(cache) > 60: cache[key] = texture
            else: return None
        return cache[key]

    def build_home(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); page.add_css_class("page"); page.add_css_class("home-page")
        self.home_title = self.label("Home Controls", "page-title"); self.home_clock = self.label("--:--", "clock", 1); header_row = self.header(self.home_title, self.home_clock); header_overlay = Gtk.Overlay(); header_overlay.set_child(header_row); page.append(header_overlay)
        self.home_status = self.label("Connecting to Home Assistant…", "muted", .5); page.append(self.home_status)
        self.hs_page = 0; self.hs_pages = 1; self.hs_last_home = {}; self.hs_paged_at = 0.0
        self.home_dots = Gtk.Box(spacing=10); self.home_dots.set_halign(Gtk.Align.CENTER); self.home_dots.add_css_class("hs-dots"); self.home_dots.set_visible(False); self.home_dots.set_valign(Gtk.Align.CENTER); self.home_dots.set_can_target(False); header_overlay.add_overlay(self.home_dots)   # centred in the header row, so the tiles keep their place
        self.home_grid = Gtk.Grid(column_spacing=18, row_spacing=18); self.home_grid.add_css_class("home-grid"); self.home_grid.set_column_homogeneous(True); self.home_grid.set_row_homogeneous(True); self.home_grid.set_vexpand(True)
        self.home_scroll = Gtk.ScrolledWindow(); self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.home_scroll.set_propagate_natural_height(False); self.home_scroll.set_min_content_height(1); self.home_scroll.set_vexpand(True); home_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.listening_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.listening_box.add_css_class("listening-controls"); self.listening_box.set_visible(False); home_content.append(self.listening_box); self.home_side = self.build_home_side(); self.home_row = Gtk.Box(spacing=18); self.home_grid.set_hexpand(True); self.home_row.append(self.home_side); self.home_stack = Gtk.Stack(); self.home_stack.set_hexpand(True); self.home_stack.set_vexpand(True); self.home_stack.set_transition_duration(280); self.home_stack.set_hhomogeneous(True); self.home_stack.set_vhomogeneous(True)
        self.home_ghost = Gtk.Picture(); self.home_ghost.set_can_shrink(True); self.home_ghost.set_content_fit(Gtk.ContentFit.FILL)   # the page just left, drawn as a picture so it can slide away
        self.home_stack.add_named(self.home_grid, "grid"); self.home_stack.add_named(self.home_ghost, "ghost"); self.home_stack.set_visible_child(self.home_grid); self.home_row.append(self.home_stack); home_content.append(self.home_row); self.home_scroll.set_child(home_content); page.append(self.home_scroll)
        drag = Gtk.GestureDrag(); drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE); drag.connect("drag-begin", self.home_drag_begin); drag.connect("drag-end", self.home_drag_end); self.home_scroll.add_controller(drag); self.hs_drag_ok = True
        elastic_vertical_scroll(self.home_scroll)
        page.append(self.navigation("home")); return page

    def apply_home_colors(self, config):
        defaults = {"light": "#fb923c", "fan": "#60a5fa", "switch": "#9868f9", "scene": "#a3e635"}
        self.home_domain_colours = {}
        def colour(domain):
            key = "home_assistant_single_color" if config.get("home_assistant_color_mode") == "single" else f"home_assistant_{domain}_color"
            value = str(config.get(key, defaults[domain]))
            return value if len(value) == 7 and value.startswith("#") and all(character in "0123456789abcdefABCDEF" for character in value[1:]) else defaults[domain]
        def blend(foreground, background, amount):
            front = tuple(int(foreground[index:index + 2], 16) for index in (1, 3, 5)); back = tuple(int(background[index:index + 2], 16) for index in (1, 3, 5))
            return "#" + "".join(f"{round(base + (accent - base) * amount):02x}" for accent, base in zip(front, back))
        rules = []
        for domain in defaults:
            accent = colour(domain); self.home_domain_colours[domain] = accent; idle = blend(accent, "#232228", .18); active = blend(accent, "#232228", .34); border = blend(accent, "#44414c", .58)
            rules.append(f".home-tile.home-domain-{domain} {{ background: {idle}; border-color: {border}; }}")
            rules.append(f".home-tile.home-domain-{domain}.on {{ background: {active}; border-color: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain} .home-icon, .home-tile.home-domain-{domain}.on .home-device-button {{ color: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain} .home-level highlight {{ background: {accent}; }}")
            rules.append(f".home-tile.home-domain-{domain}.activated {{ background: {active}; border-color: {accent}; box-shadow: 0 0 18px {accent}; }}")
        self.home_color_provider.load_from_data("\n".join(rules))
        self.home_signature = None   # icons are drawn in these colours, so redraw them

    def render_home(self, home):
        portrait = self.window.has_css_class("portrait")
        dashboard = self.home_dashboard_active(); self.hs_last_home = home
        self.hs_pages = home.get("pages") if dashboard and isinstance(home.get("pages"), int) and home.get("pages") > 1 else 1
        self.hs_page = max(0, min(self.hs_pages - 1, self.hs_page))
        # The dashboard may scroll as a last resort, so cards that are too tall can never push the page past the screen.
        self.home_scroll.set_policy(Gtk.PolicyType.EXTERNAL if dashboard else Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait or dashboard or self.listening_box.get_visible() else Gtk.PolicyType.NEVER)
        signature = json.dumps({"status": home.get("status"), "entities": home.get("entities", []), "cards": home.get("cards"), "theme": self.settings_data.get("display_theme"), "portrait": portrait, "original": self.window.has_css_class("original-landscape"), "dashboard": dashboard, "columns": home.get("columns"), "width": getattr(self, "viewport_width", 0), "page": self.hs_page, "pages": home.get("pages")}, sort_keys=True, default=str)
        if signature == self.home_signature: return
        self.home_signature = signature
        while child := self.home_dots.get_first_child(): self.home_dots.remove(child)
        for number in range(self.hs_pages):
            dot = Gtk.Box(); dot.add_css_class("hs-dot"); dot.set_size_request(12, 12)
            if number == self.hs_page: dot.add_css_class("current")
            self.home_dots.append(dot)
        self.home_dots.set_visible(self.hs_pages > 1)
        while child := self.home_grid.get_first_child():
            if getattr(child, "clip_wrapper", False): child.set_child(None)   # let the tile go before its frame, so it can be placed again
            self.home_grid.remove(child)
        entities = home.get("entities", []) if dashboard else [entity for entity in home.get("entities", []) if not (entity.get("tile") or {}).get("page")]   # small screens have no pages
        entities = entities[:64 if dashboard else 8]
        original = self.window.has_css_class("original-landscape")
        self.home_grid.set_row_spacing(10 if original else 18); self.home_grid.set_column_spacing(12 if original else 18)
        self.home_status.set_text("Home Assistant offline" if home.get("status") == "offline" else ("Choose Home Assistant devices in web settings" if not entities else ""))
        self.home_status.set_visible(bool(self.home_status.get_text()) and not dashboard)   # on the dashboard a message line would push the tiles down
        self.home_grid.set_margin_top((0 if getattr(self, "viewport_width", 800) >= 1000 else PORTRAIT_CONTENT_GAP) if portrait else 0)
        if dashboard:
            self.render_home_dashboard(home, entities)
            return
        # Tiles with a chosen size are placed on a 4-column grid (2 in portrait); with none chosen the original arrangement is used.
        def has_place(entity): return isinstance((entity.get("tile") or {}).get("col"), int) and isinstance((entity.get("tile") or {}).get("row"), int)
        custom = any((entity.get("tile") or {}).get("size") not in (None, "auto") or (entity.get("tile") or {}).get("rows") == 2 or has_place(entity) for entity in entities)
        columns = (2 if portrait else 4) if custom else 4
        spans = {"quarter": 1, "half": 1 if portrait else 2, "full": columns}
        row_mode = portrait and not custom
        tile_rules, taken, placed = [], set(), {}
        def spots(column, row, span, height): return {(column + dx, row + dy) for dx in range(span) for dy in range(height)}
        def free_slot(span, height):
            # First free place, scanning left to right then down: the same rule the web designer uses.
            row = 0
            while True:
                for column in range(columns - span + 1):
                    if not spots(column, row, span, height) & taken: return column, row
                row += 1
        if custom:
            def size_of(entity):
                tile = entity.get("tile") or {}
                return min(columns, spans.get(tile.get("size"), 1)), 2 if tile.get("rows") == 2 else 1
            # Tiles the owner placed on the grid keep their place; the rest fill the first free spaces.
            for index, entity in enumerate(entities):
                span, height = size_of(entity); tile = entity.get("tile") or {}
                if has_place(entity) and tile["col"] + span <= columns and not spots(tile["col"], tile["row"], span, height) & taken:
                    placed[index] = (tile["col"], tile["row"]); taken |= spots(tile["col"], tile["row"], span, height)
            for index, entity in enumerate(entities):
                if index in placed: continue
                span, height = size_of(entity); column, row = free_slot(span, height); placed[index] = (column, row); taken |= spots(column, row, span, height)
            used_rows = max((row + size_of(entities[i])[1] for i, (_, row) in placed.items()), default=1)
            grid_rows = max(used_rows, -(-8 // columns))
            # Empty cells get invisible spacers so every column and row keeps its share of the screen.
            for column in range(columns):
                for row in range(grid_rows):
                    if (column, row) not in taken:
                        spacer = Gtk.Box(); spacer.set_hexpand(True); spacer.set_vexpand(True); self.home_grid.attach(spacer, column, row, 1, 1)
        for index, entity in enumerate(entities):
            tile = entity.get("tile") or {}
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if row_mode else Gtk.Orientation.VERTICAL, spacing=18 if row_mode else 4); box.add_css_class("home-tile"); box.set_vexpand(True)
            art_image = self.home_art(tile["image"]) if tile.get("image") else None
            if tile.get("image") and art_image is None: self.home_signature = None   # try again on the next refresh
            tile_widget = box
            if art_image is not None:
                # A picture behind the tile: the frame is an overlay holding the picture and, on top, the controls.
                tile_widget = Gtk.Overlay(); tile_widget.add_css_class("home-tile"); tile_widget.set_overflow(Gtk.Overflow.HIDDEN); tile_widget.set_vexpand(True)
                picture = Gtk.Picture.new_for_paintable(art_image); picture.set_content_fit(Gtk.ContentFit.COVER); picture.set_can_shrink(True); picture.set_opacity(.55)
                tile_widget.set_child(picture); tile_widget.add_overlay(box); box.remove_css_class("home-tile"); box.add_css_class("home-tile-content")
            state = str(entity.get("state", "unknown")); detail = state.upper()
            if entity.get("percentage") is not None: detail += f" · {entity['percentage']}%"
            if state in {"on", "open", "playing"}: tile_widget.add_css_class("on")
            control_row = Gtk.Box(spacing=5); control_row.set_vexpand(True)
            domain = entity.get("domain", "switch")
            if domain == "script": domain = "scene"  # a script is a tap-to-run action, shown like a scene
            domain_class = "home-domain-switch" if domain == "input_boolean" else f"home-domain-{domain}"
            tile_widget.add_css_class(domain_class)
            if tile.get("color"):
                name = f"home-custom-{index}"; tile_widget.add_css_class(name); tile_rules += tile_colour_rules(("light", "fan", "switch", "scene"), name, tile["color"])
            scene = domain == "scene"
            if scene: detail = "TAP TO ACTIVATE" if entity.get("available", True) else "UNAVAILABLE"
            icon_size = 108 if self.window.has_css_class("high-resolution") else 82
            if original: icon_size = 82 if (len(entities) == 6 and index < 2) else 50
            if row_mode: icon_size = max(64, min(240, round((self.window.get_height() - 190) / max(4, len(entities)) * .7)))
            icon_slot = icon_size; icon_size = round(icon_size * .75)
            accent = tile.get("color") or getattr(self, "home_domain_colours", {}).get("switch" if domain == "input_boolean" else domain)
            icon_texture = self.home_art(tile["icon"], accent) if tile.get("icon") else None
            if tile.get("icon") and icon_texture is None: self.home_signature = None
            if icon_texture is not None:
                icon = Gtk.Image.new_from_paintable(icon_texture); icon.set_pixel_size(icon_size); icon.set_opacity(1 if (state in {"on", "open", "playing"} or scene) else .72)
            else: icon = FamilyIcon("check" if scene else domain if domain in {"fan", "light"} else "switchon" if state == "on" else "switch", icon_size)
            icon.set_size_request(icon_slot, icon_slot); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.add_css_class("home-icon")
            button = Gtk.Button(); button.add_css_class("home-device-button"); button.set_hexpand(not row_mode); button.set_vexpand(True); button.set_child(icon)
            if scene:
                button.add_css_class("scene-action"); button.scene_tile = tile_widget; button.set_sensitive(bool(entity.get("available", True))); button.connect("clicked", self.activate_home_scene, entity.get("entity_id", ""))
            else: button.connect("clicked", self.toggle_home, entity.get("entity_id", ""))
            control_row.append(button)
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); details.set_hexpand(True); details.set_valign(Gtk.Align.CENTER)
            if entity.get("supports_level"):
                level = entity.get("percentage")
                if level is None and entity.get("brightness") is not None: level = round(float(entity["brightness"]) * 100 / 255)
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL if row_mode else Gtk.Orientation.VERTICAL, 0, 100, 1); scale.add_css_class("home-level"); scale.set_draw_value(False); scale.set_inverted(not row_mode); scale.set_hexpand(row_mode); scale.set_value(float(level or 0)); scale.connect("value-changed", self.change_home_value, entity.get("entity_id", "")); (details if portrait else control_row).append(scale)
            if domain in {"switch", "input_boolean"}:
                swipe = Gtk.GestureSwipe(); swipe.connect("swipe", self.swipe_home_switch, entity.get("entity_id", "")); button.add_controller(swipe)
            box.append(control_row)
            name = self.label(tile.get("label") or entity.get("name", "Device"), "home-name", 0 if row_mode else .5); name.set_wrap(True); name.set_lines(2); name.set_justify(Gtk.Justification.LEFT if row_mode else Gtk.Justification.CENTER); (details if row_mode else box).append(name)
            state_label = self.label(detail, "home-state", 0 if row_mode else .5); (details if row_mode else box).append(state_label)
            if scene: button.scene_status_label = state_label
            if row_mode: box.append(details)
            if custom:
                span, height = size_of(entity); column, row = placed[index]
                self.home_grid.attach(tile_widget, column, row, span, height)
            elif not portrait and len(entities) == 6:
                # Two full-height primary controls plus a compact 2x2 group
                # use the complete landscape canvas without empty grid cells.
                if index < 2: self.home_grid.attach(tile_widget, index, 0, 1, 2)
                else: self.home_grid.attach(tile_widget, 2 + (index - 2) % 2, (index - 2) // 2, 1, 1)
            else:
                self.home_grid.attach(tile_widget, 0 if portrait else index % 4, index if portrait else index // 4, 1, 1)
        self.home_tile_provider.load_from_data("\n".join(tile_rules))

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

    def home_drag_begin(self, gesture, x, y):
        # A drag that starts on a slider belongs to the slider, never to the page.
        widget = self.home_scroll.pick(x, y, Gtk.PickFlags.DEFAULT); self.hs_drag_ok = True
        while widget is not None:
            if isinstance(widget, Gtk.Scale): self.hs_drag_ok = False; break
            widget = widget.get_parent()

    def home_drag_end(self, gesture, dx, dy):
        if not self.hs_drag_ok or self.hs_pages < 2 or abs(dx) < 140 or abs(dx) < abs(dy) * 1.8: return
        target = max(0, min(self.hs_pages - 1, self.hs_page + (1 if dx < 0 else -1)))
        if target == self.hs_page: return
        ghost = self.home_snapshot()   # the page being left, taken before the new one is built
        self.hs_page = target; self.hs_paged_at = time.monotonic(); self.home_signature = None; self.render_home(self.hs_last_home)
        if ghost is not None:
            # The new page slides in from the side the finger moved away from, pushing the old one out.
            self.home_ghost.set_paintable(ghost); self.home_stack.set_transition_type(Gtk.StackTransitionType.NONE); self.home_stack.set_visible_child(self.home_ghost)
            self.home_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT if dx < 0 else Gtk.StackTransitionType.SLIDE_RIGHT); self.home_stack.set_visible_child(self.home_grid)

    def home_snapshot(self):
        try:
            width, height = self.home_grid.get_width(), self.home_grid.get_height()
            renderer = self.home_grid.get_native().get_renderer() if self.home_grid.get_native() else None
            if width < 2 or height < 2 or renderer is None: return None
            snapshot = Gtk.Snapshot(); Gtk.WidgetPaintable.new(self.home_grid).snapshot(snapshot, width, height)
            node = snapshot.to_node()
            return renderer.render_texture(node, None) if node is not None else None
        except Exception:
            return None   # no animation is better than no page change

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


    def listening_command(self, action, value=None):
        def work():
            result = post_json(BUS + "/api/listening/command", {"action": action, "value": value}, timeout=15)
            if result is None: result = {"error": "Listening command timed out or the service is unavailable"}
            if isinstance(result, dict) and result.get("error"):
                GLib.idle_add(self.listening_feedback.set_text, result["error"])
        threading.Thread(target=work, daemon=True).start()

    def render_listening(self, data):
        self.listening_box.set_visible(bool(data.get("enabled")))
        self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if data.get("enabled") or self.window.has_css_class("portrait") else Gtk.PolicyType.NEVER)
        if not data.get("enabled"): return
        signature = json.dumps(data, sort_keys=True)
        if signature == getattr(self, "listening_signature", None): return
        self.listening_signature = signature
        while child := self.listening_box.get_first_child(): self.listening_box.remove(child)
        speaker = data.get("kef", {})
        detail = "KEF LSX · Offline"
        if speaker.get("connected"):
            detail = f"KEF LSX · {'On' if speaker.get('powered') else 'Standby'} · {speaker.get('input', '')} · {speaker.get('volume', 0)}%"
            if speaker.get("muted"): detail += " · Muted"
        detail_label = self.label(detail, "home-name"); detail_label.set_wrap(True); self.listening_box.append(detail_label)
        controls = Gtk.FlowBox(); controls.set_selection_mode(Gtk.SelectionMode.NONE); controls.set_min_children_per_line(1); controls.set_max_children_per_line(2 if self.window.has_css_class("portrait") else 4); controls.set_row_spacing(6); controls.set_column_spacing(6)
        for label, action, value in [("Power on", "power", True), ("Standby", "power", False), ("− Volume", "volume_delta", -2), ("+ Volume", "volume_delta", 2), ("Mute", "mute", None)]:
            button = self.button(label, lambda _button, a=action, v=value: self.listening_command(a, v), "")
            button.set_sensitive(bool(speaker.get("connected"))); controls.append(button)
        for source in ("wifi", "aux", "optical", "bluetooth"):
            button = self.button(source.title(), lambda _button, v=source: self.listening_command("input", v), "")
            button.set_sensitive(bool(speaker.get("connected")))
            if speaker.get("input") == source: button.add_css_class("active")
            controls.append(button)
        for mode in data.get("modes", []):
            button = self.button(mode.get("name", mode["id"]), lambda _button, value=mode["id"]: self.listening_command("mode", value), "")
            button.set_sensitive(bool(mode.get("available") and speaker.get("connected"))); button.set_tooltip_text(mode.get("reason") or "")
            if data.get("last_mode") == mode["id"]: button.add_css_class("active")
            controls.append(button)
        self.listening_box.append(controls)
        pending = any(not mode.get("available") for mode in data.get("modes", []))
        self.listening_feedback = self.label(data.get("error") or ("Topping input switching is not available yet." if pending else ""), "muted")
        self.listening_feedback.set_wrap(True); self.listening_box.append(self.listening_feedback)
