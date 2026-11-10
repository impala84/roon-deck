"""Home page: Home Assistant switches, scenes and values."""
from __future__ import annotations

from native_common import BUS, FamilyIcon, PORTRAIT_CONTENT_GAP, elastic_vertical_scroll, get_bytes, post_json
from pi_bus_time_display.home_layout import KEF_CARDS
import json
import threading
import time
from gi.repository import Gdk, GLib, Gtk, Pango


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
        self.hs_drag_claimed = False; self.hs_page = 0; self.hs_pages = 1; self.hs_last_home = {}; self.hs_paged_at = 0.0
        self.home_dots = Gtk.Box(spacing=0); self.home_dots.set_halign(Gtk.Align.CENTER); self.home_dots.add_css_class("hs-dots"); self.home_dots.set_visible(False); self.home_dots.set_valign(Gtk.Align.CENTER); header_overlay.add_overlay(self.home_dots)   # centred in the header row, so the tiles keep their place
        self.home_grid = Gtk.Grid(column_spacing=18, row_spacing=18); self.home_grid.add_css_class("home-grid"); self.home_grid.set_column_homogeneous(True); self.home_grid.set_row_homogeneous(True); self.home_grid.set_vexpand(True)
        self.home_scroll = Gtk.ScrolledWindow(); self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.home_scroll.set_propagate_natural_height(False); self.home_scroll.set_min_content_height(1); self.home_scroll.set_vexpand(True); home_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.kef_tiles = {}; self.listening_data = {}; self.home_side = self.build_home_side(); self.home_row = Gtk.Box(spacing=18); self.home_grid.set_hexpand(True); self.home_row.append(self.home_side); self.home_stack = Gtk.Stack(); self.home_stack.set_hexpand(True); self.home_stack.set_vexpand(True); self.home_stack.set_transition_duration(280); self.home_stack.set_hhomogeneous(True); self.home_stack.set_vhomogeneous(True)
        self.home_ghost = Gtk.Picture(); self.home_ghost.set_can_shrink(True); self.home_ghost.set_content_fit(Gtk.ContentFit.FILL)   # the page just left, drawn as a picture so it can slide away
        self.home_stack.add_named(self.home_grid, "grid"); self.home_stack.add_named(self.home_ghost, "ghost"); self.home_stack.set_visible_child(self.home_grid); self.home_row.append(self.home_stack); home_content.append(self.home_row); self.home_scroll.set_child(home_content); page.append(self.home_scroll)
        drag = Gtk.GestureDrag(); drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE); drag.connect("drag-begin", self.home_drag_begin); drag.connect("drag-update", self.home_drag_update); drag.connect("drag-end", self.home_drag_end); self.home_scroll.add_controller(drag); self.hs_drag_ok = True
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
        self.home_scroll.set_policy(Gtk.PolicyType.EXTERNAL if dashboard else Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait or dashboard or bool(self.kef_tiles) else Gtk.PolicyType.NEVER)
        signature = json.dumps({"status": home.get("status"), "entities": home.get("entities", []), "cards": home.get("cards"), "theme": self.settings_data.get("display_theme"), "portrait": portrait, "original": self.window.has_css_class("original-landscape"), "dashboard": dashboard, "columns": home.get("columns"), "width": getattr(self, "viewport_width", 0), "page": self.hs_page, "pages": home.get("pages")}, sort_keys=True, default=str)
        if signature == self.home_signature: return
        self.home_signature = signature
        while child := self.home_dots.get_first_child(): self.home_dots.remove(child)
        for number in range(self.hs_pages):
            dot = Gtk.Box(); dot.add_css_class("hs-dot"); dot.set_size_request(12, 12); dot.set_halign(Gtk.Align.CENTER); dot.set_valign(Gtk.Align.CENTER)
            if number == self.hs_page: dot.add_css_class("current")
            hit = Gtk.Box(); hit.set_size_request(34, 34); hit.append(dot)   # a finger-sized target around each dot: tap it to go to that page
            tap = Gtk.GestureClick(); tap.connect("released", lambda *_, page=number: self.home_go_to_page(page)); hit.add_controller(tap)
            self.home_dots.append(hit)
        self.home_dots.set_visible(self.hs_pages > 1)
        while child := self.home_grid.get_first_child():
            if getattr(child, "clip_wrapper", False): child.set_child(None)   # let the tile go before its frame, so it can be placed again
            self.home_grid.remove(child)
        entities = home.get("entities", []) if dashboard else [entity for entity in home.get("entities", []) if not (entity.get("tile") or {}).get("page")]   # small screens have no pages
        if not dashboard:
            entities = [{"entity_id": key, "widget": self.kef_tile(key), "tile": tile} for key, tile in (home.get("cards") or {}).items()
                        if key.split("#")[0] in KEF_CARDS and tile.get("show") and not tile.get("page")] + entities
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
            if entity.get("widget") is not None:
                widget = entity["widget"]; self.style_kef_tile(widget, tile)
                frame = self.clip_cell(widget)
                if custom:
                    span, height = size_of(entity); column, row = placed[index]
                    self.home_grid.attach(frame, column, row, span, height)
                else: self.home_grid.attach(frame, 0 if portrait else index % 4, index if portrait else index // 4, 1, 1)
                continue
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
            if scene: detail = "" if entity.get("available", True) else "UNAVAILABLE"
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
            if scene: button.scene_status_label = state_label; state_label.set_visible(bool(detail))
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
        button.add_css_class("activated"); button.scene_tile.add_css_class("activated"); button.set_sensitive(False); button.scene_status_label.set_text("ACTIVATING…"); button.scene_status_label.set_visible(True)
        def send():
            result = post_json(BUS + "/api/device/home-toggle", {"entity_id": entity_id})
            def finish():
                button.scene_status_label.set_text("ACTIVATED" if result and not result.get("error") else "COULD NOT ACTIVATE"); button.scene_status_label.set_visible(True)
                GLib.timeout_add(900, self.reset_home_scene, button)
                return False
            GLib.idle_add(finish)
        threading.Thread(target=send, daemon=True).start()

    def reset_home_scene(self, button):
        button.remove_css_class("activated"); button.scene_tile.remove_css_class("activated"); button.set_sensitive(True); button.scene_status_label.set_text(""); button.scene_status_label.set_visible(False); return False

    def home_drag_begin(self, gesture, x, y):
        # A drag that starts on a slider belongs to the slider, never to the page.
        widget = self.home_scroll.pick(x, y, Gtk.PickFlags.DEFAULT); self.hs_drag_ok = True; self.hs_drag_claimed = False; self.hs_drag_started = time.monotonic()
        while widget is not None:
            if isinstance(widget, Gtk.Scale): self.hs_drag_ok = False; break
            widget = widget.get_parent()

    def home_drag_update(self, gesture, dx, dy):
        # Once the finger is clearly moving sideways the page keeps the touch: otherwise the scroll area or a tile under the finger can take it
        # part-way through, and the swipe only works some of the time.
        if self.hs_drag_ok and not self.hs_drag_claimed and self.hs_pages > 1 and abs(dx) > 24 and abs(dx) > abs(dy) * 1.3:
            self.hs_drag_claimed = True; gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def home_drag_end(self, gesture, dx, dy):
        if not self.hs_drag_ok or self.hs_pages < 2 or abs(dx) < abs(dy) * 1.5: return
        quick = time.monotonic() - getattr(self, "hs_drag_started", 0) < 0.4   # a short, quick flick counts as a swipe too
        if abs(dx) < (50 if quick else 100): return
        self.home_go_to_page(max(0, min(self.hs_pages - 1, self.hs_page + (1 if dx < 0 else -1))))

    def home_go_to_page(self, target):
        """Show another page, sliding from the side it lies on (a swipe and a tap on a dot both come here)."""
        target = max(0, min(self.hs_pages - 1, target))
        if target == self.hs_page: return
        forward = target > self.hs_page
        ghost = self.home_snapshot()   # the page being left, taken before the new one is built
        self.hs_page = target; self.hs_paged_at = time.monotonic(); self.home_signature = None; self.render_home(self.hs_last_home)
        if ghost is None: return
        # The old page is put on show first and the slide starts on the next frame, so the switch is always drawn as a slide and never as a jump.
        self.home_ghost.set_paintable(ghost); self.home_stack.set_transition_type(Gtk.StackTransitionType.NONE); self.home_stack.set_visible_child(self.home_ghost)
        direction = Gtk.StackTransitionType.SLIDE_LEFT if forward else Gtk.StackTransitionType.SLIDE_RIGHT
        def slide():
            self.home_stack.set_transition_duration(280); self.home_stack.set_transition_type(direction); self.home_stack.set_visible_child(self.home_grid); return False
        GLib.idle_add(slide)

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
                GLib.idle_add(self.kef_feedback, result["error"])
        threading.Thread(target=work, daemon=True).start()

    def kef_feedback(self, text):
        for card in self.kef_tiles.values(): card.feedback.set_text(text)
        return False

    KEF_INPUT_NAMES = {"wifi": "Wi-Fi", "bluetooth": "Bluetooth", "aux": "AUX", "optical": "Optical"}

    def kef_current_input(self, data):
        """The input the KEF is on: Roon says so when it is on Wi-Fi; otherwise the last input chosen (kept across restarts)."""
        if (data.get("kef") or {}).get("input") == "wifi": return "wifi"
        return (data.get("presets") or {}).get("last") or ""

    def kef_next_input(self, card, data):
        """The input a tap on the KEF input tile will select: the preset, or the other one of two presets."""
        tile = getattr(card, "tile", None) or {}; primary, alt = tile.get("input") or "", tile.get("input_alt") or ""
        return primary, (alt if alt and self.kef_current_input(data) == primary else primary)

    def tap_kef_power(self):
        speaker = (self.listening_data or {}).get("kef") or {}
        self.listening_command("power", not speaker.get("powered"))

    def tap_kef_input(self, key):
        tile = getattr(self.kef_tiles.get(key), "tile", None) or {}
        self.listening_command("preset", {"primary": tile.get("input") or "", "alt": tile.get("input_alt") or ""})

    def kef_action_tile(self, key, kind):
        """The KEF input and power tiles are ordinary tap tiles, like Update and Group."""
        card, _value, _detail = self.build_action_card("KEF input" if kind == "_input" else "KEF power", (lambda: self.tap_kef_input(key)) if kind == "_input" else self.tap_kef_power)
        card.feedback = card.detail_label; card.kef_kind = kind
        if kind == "_input":
            # Icon and speaker name on top, the input it is on in large type, and a small hint underneath.
            card.input_label = self.label("", "hs-action-input", 0); card.input_label.set_xalign(0); card.input_label.set_ellipsize(Pango.EllipsizeMode.END); card.input_label.set_max_width_chars(1); card.input_label.set_hexpand(True)
            card.insert_child_after(card.input_label, card.head); card.input_label.set_margin_top(5); card.value_label.set_wrap(False); card.value_label.set_lines(1); card.value_label.set_xalign(0); card.value_label.set_hexpand(False); card.value_label.set_halign(Gtk.Align.START); card.value_label.set_max_width_chars(14)   # as wide as the name, right beside the icon
        self.kef_tiles[key] = card; self.populate_kef_tile(key, card, self.listening_data)
        return card

    def populate_kef_action_tile(self, card, data):
        speaker = data.get("kef") or {}; enabled = bool(data.get("enabled")); connected = enabled and bool(speaker.get("connected")); note = data.get("error") or data.get("notice") or ""
        if card.kef_kind == "_power":
            on = enabled and speaker.get("powered") is True
            speaker_name = (getattr(card, "tile", None) or {}).get("label") or "KEF"
            card.value_label.set_text(("On" if on else "Off") if enabled else speaker_name)
            card.detail_label.set_text((data.get("notice") or "Tap to turn on") if enabled and not on else note or ("Tap to turn off" if on else "Not enabled"))
            self.set_action_state(card, "power", "ok" if on else None)
            return
        primary, nxt = self.kef_next_input(card, data)
        speaker_name = (getattr(card, "tile", None) or {}).get("label") or "KEF"   # the speaker's name is the tile's label, set in the Home builder
        card.value_label.set_text(speaker_name)
        if not enabled or not primary or not data.get("ir_available"):
            card.input_label.set_text("—")
            card.detail_label.set_text(note or ("Not enabled" if not enabled else "Choose the input in the tile options" if not primary else "Choose the Broadlink remote in Settings"))
            self.set_action_state(card, "input", "alert"); return
        current = self.kef_current_input(data)
        standby = speaker.get("powered") is not True   # in standby, or Roon cannot see it: either way it is off as far as anyone can tell
        if standby:
            card.input_label.set_text("Off")
            card.detail_label.set_text(data.get("notice") or "Tap to turn on")   # a "cannot see the speaker" error is just what off looks like
            self.set_action_state(card, "input", None); return
        card.input_label.set_text(self.KEF_INPUT_NAMES.get(current, "Unknown"))   # what the speaker is on now
        card.detail_label.set_text(note or ("Tap to cycle" if (getattr(card, "tile", None) or {}).get("input_alt") else "Tap to switch"))
        self.set_action_state(card, "input", {"wifi": "light", "aux": "green", "bluetooth": "blue", "optical": "purple"}.get(current))

    def kef_tile(self, key):
        if key in self.kef_tiles: return self.kef_tiles[key]
        kind = key.split("#")[0].removeprefix("roondeck.kef")
        if kind in ("_input", "_power"): return self.kef_action_tile(key, kind)
        return self.kef_volume_tile(key, kind)

    def kef_volume_tile(self, key, kind):
        """KEF volume: a headline and a large number with a small minus and plus. The combined KEF speaker tile adds power and input buttons below."""
        full = kind == ""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); card.add_css_class("hs-card"); card.add_css_class("hs-voltile"); card.add_css_class("hs-kefvol"); card.set_hexpand(True); card.set_vexpand(True)
        card.kef_vol = True; card.default_title = "KEF speaker" if full else "KEF volume"
        card.title = self.label(card.default_title, "hs-stat-title", 0); card.title.set_xalign(0); card.title.set_ellipsize(Pango.EllipsizeMode.END); card.append(card.title)
        row = Gtk.Box(spacing=8); row.set_vexpand(True); row.set_valign(Gtk.Align.CENTER)
        if not full: row.set_margin_bottom(18); row.set_margin_end(12)   # the title sits above, so lift and nudge the number to the middle of the whole tile
        card.minus = Gtk.Button(label="\u2212"); card.plus = Gtk.Button(label="+")
        for button, step in ((card.minus, -2), (card.plus, 2)):
            button.add_css_class("hs-volstep"); button.set_valign(Gtk.Align.CENTER); button.connect("clicked", lambda *_, step=step: self.listening_command("volume_delta", step))
        card.value = self.label("\u2014", "hs-volbig", 0); card.value.set_hexpand(True); card.value.set_halign(Gtk.Align.CENTER)
        tap = Gtk.GestureClick(); tap.connect("released", lambda *_: self.listening_command("mute", None)); card.value.add_controller(tap)   # tap the number to mute or unmute
        row.append(card.minus); row.append(card.value); row.append(card.plus); card.append(row)
        if full:
            buttons = Gtk.Box(spacing=8); buttons.set_homogeneous(True)
            card.power = Gtk.Button(label="Power"); card.power.connect("clicked", lambda *_: self.tap_kef_power())
            card.input_button = Gtk.Button(label="Input"); card.input_button.connect("clicked", lambda *_, key=key: self.tap_kef_input(key))
            for button in (card.power, card.input_button): button.add_css_class("hs-kefbtn"); buttons.append(button)
            card.append(buttons)
        card.feedback = self.label("", "hs-stat-detail", 0); card.feedback.set_xalign(0); card.feedback.set_ellipsize(Pango.EllipsizeMode.END); card.feedback.set_visible(False); card.append(card.feedback)
        self.kef_tiles[key] = card; self.populate_kef_tile(key, card, self.listening_data)
        return card

    def style_kef_tile(self, card, tile):
        if hasattr(card, "kef_kind"):
            changed = getattr(card, "tile", None) != tile; card.tile = tile
            if changed: self.populate_kef_action_tile(card, self.listening_data)
            card.set_tooltip_text(tile.get("label") or ("KEF input" if card.kef_kind == "_input" else "KEF power")); return
        changed = getattr(card, "tile", None) != tile; card.tile = tile
        card.title.set_text(tile.get("label") or card.default_title)
        if changed:
            # Plus and minus need a wide tile; a half-column tile shows the number alone, a little larger.
            narrow = bool(tile.get("half")); (card.add_css_class if narrow else card.remove_css_class)("hs-kefnarrow")
            self.populate_kef_tile("", card, self.listening_data)

    def populate_kef_tile(self, key, card, data):
        if hasattr(card, "kef_kind"): self.populate_kef_action_tile(card, data); return
        speaker = data.get("kef") or {}; enabled = bool(data.get("enabled")); connected = enabled and bool(speaker.get("connected"))
        volume = speaker.get("volume") if connected and isinstance(speaker.get("volume"), (int, float)) else None
        off = enabled and speaker.get("powered") is not True
        card.value.set_text("Off" if off else "\u2014" if volume is None else str(round(volume)))
        (card.value.add_css_class if connected and speaker.get("muted") else card.value.remove_css_class)("is-muted")
        narrow = card.has_css_class("hs-kefnarrow")
        for button in (card.minus, card.plus): button.set_sensitive(connected and not off); button.set_visible(not narrow)
        note = (data.get("notice") or "") if off else data.get("error") or data.get("notice") or ("Not enabled" if not enabled else "" if off else "Muted" if speaker.get("muted") else "")
        card.feedback.set_text(note); card.feedback.set_visible(bool(note) and hasattr(card, "input_button"))   # only the combined KEF tile has room for a notice line; on the volume tile it pushed the number about
        if hasattr(card, "input_button"):
            on = connected and bool(speaker.get("powered"))
            card.power.set_label("Standby" if on else "Wake"); card.power.set_sensitive(connected)
            primary, nxt = self.kef_next_input(card, data)
            ready = enabled and bool(primary) and bool(data.get("ir_available"))
            card.input_button.set_label(self.KEF_INPUT_NAMES.get(nxt, nxt) if ready else "Input"); card.input_button.set_sensitive(ready)

    def render_listening(self, data):
        signature = json.dumps(data, sort_keys=True)
        if signature == getattr(self, "listening_signature", None): return
        self.listening_signature = signature; self.listening_data = data
        for key, card in self.kef_tiles.items():
            self.populate_kef_tile(key, card, data)
            self.style_kef_tile(card, (self.hs_last_home.get("cards") or {}).get(key, {}))
