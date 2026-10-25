"""Home page: Home Assistant switches, scenes and values."""
from __future__ import annotations

from native_common import BUS, FamilyIcon, PORTRAIT_CONTENT_GAP, elastic_vertical_scroll, post_json
import json
import threading
from gi.repository import GLib, Gtk


class HomePageMixin:
    def build_home(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); page.add_css_class("page"); page.add_css_class("home-page")
        self.home_title = self.label("Home Controls", "page-title"); self.home_clock = self.label("--:--", "clock", 1); page.append(self.header(self.home_title, self.home_clock))
        self.home_status = self.label("Connecting to Home Assistant…", "muted", .5); page.append(self.home_status)
        self.home_grid = Gtk.Grid(column_spacing=18, row_spacing=18); self.home_grid.add_css_class("home-grid"); self.home_grid.set_column_homogeneous(True); self.home_grid.set_row_homogeneous(True); self.home_grid.set_vexpand(True)
        self.home_scroll = Gtk.ScrolledWindow(); self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.home_scroll.set_propagate_natural_height(False); self.home_scroll.set_min_content_height(1); self.home_scroll.set_vexpand(True); self.home_scroll.set_child(self.home_grid); page.append(self.home_scroll)
        elastic_vertical_scroll(self.home_scroll)
        page.append(self.navigation("home")); return page

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

    def render_home(self, home):
        portrait = self.window.has_css_class("portrait")
        self.home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait else Gtk.PolicyType.NEVER)
        signature = json.dumps({"status": home.get("status"), "entities": home.get("entities", []), "theme": self.settings_data.get("display_theme"), "portrait": portrait, "original": self.window.has_css_class("original-landscape")}, sort_keys=True, default=str)
        if signature == self.home_signature: return
        self.home_signature = signature
        while child := self.home_grid.get_first_child(): self.home_grid.remove(child)
        entities = home.get("entities", [])[:8]
        original = self.window.has_css_class("original-landscape")
        self.home_grid.set_row_spacing(10 if original else 18); self.home_grid.set_column_spacing(12 if original else 18)
        self.home_status.set_text("Home Assistant offline" if home.get("status") == "offline" else ("Choose Home Assistant devices in web settings" if not entities else ""))
        self.home_status.set_visible(bool(self.home_status.get_text()))
        self.home_grid.set_margin_top((0 if getattr(self, "viewport_width", 800) >= 1000 else PORTRAIT_CONTENT_GAP) if portrait else 0)
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
            if original: icon_size = 82 if (len(entities) == 6 and index < 2) else 50
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
