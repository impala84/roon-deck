"""Settings page: layout, theme, services, software and display options."""
from __future__ import annotations

from native_common import BUS, FamilyIcon, elastic_vertical_scroll, post_json, wordmark_paintable_tinted
from performance_graph import PerformanceGraph
import threading
from gi.repository import GLib, Gtk, Pango


class SettingsPageMixin:
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
        # Keep the identity and utilities on one deliberate header line when
        # width permits. The original 480px portrait needs a second line or
        # the utilities push the native window beyond the physical viewport.
        narrow_portrait = portrait and width < 600
        self.settings_header.set_orientation(Gtk.Orientation.VERTICAL if narrow_portrait else Gtk.Orientation.HORIZONTAL)
        self.settings_utilities.set_halign(Gtk.Align.END if narrow_portrait else Gtk.Align.START)
        if hasattr(self, "touch_bus_pair"):
            self.touch_bus_pair.set_orientation(Gtk.Orientation.VERTICAL if width < 1000 else Gtk.Orientation.HORIZONTAL)
            self.touch_bus_heading.set_visible(portrait or width > 1280)
        seven_inch = original or (not portrait and 1000 <= width < 1500 and height <= 850)
        # Touch Display 2 (7-inch) landscape: a smaller, perfectly round close control.
        # The size request is the floor; the CSS below stops the generic Settings
        # button padding from stretching it into an oval.
        gen2_seven_landscape = not portrait and 1200 <= width < 1500 and 650 <= height < 850
        self.settings_close.set_size_request(*((40, 40) if original else (52, 52) if gen2_seven_landscape else (58, 58)))
        if hasattr(self, "settings_actions"): self.settings_actions.set_spacing(24 if portrait and width >= 1000 else 16)
        if hasattr(self, "settings_utilities"): self.settings_utilities.set_spacing(32 if portrait and width >= 1000 else 12)
        (self.window.add_css_class if seven_inch else self.window.remove_css_class)("seven-inch-settings")
        # Both seven-inch landscape panels: Install Update on the left, Reboot on the right in one row.
        if hasattr(self, "settings_reboot"):
            target = self.settings_actions if seven_inch and not portrait else self.settings_action_stack
            if self.settings_reboot.get_parent() is not target:
                self.settings_reboot.get_parent().remove(self.settings_reboot); target.append(self.settings_reboot)
        # Profile, mounting and orientation are installation controls. On the
        # two seven-inch panels they consume most of the daily Settings view,
        # despite normally being used only once during setup.
        for control in (self.touch_profile, self.touch_orientation, self.touch_mounting, self.apply_display_button, self.display_settings_heading):
            control.set_visible(not seven_inch)
        # 10-inch portrait: one row of three drop-downs, then the performance graph in the remaining height.
        wide_portrait = portrait and width >= 1000
        for control in (self.touch_profile, self.touch_orientation, self.touch_mounting):
            target = self.settings_display_row if wide_portrait else self.settings_display_column
            if control.get_parent() is not target:
                control.get_parent().remove(control); target.append(control)
        self.settings_display_row.set_visible(wide_portrait); self.performance_graph.set_visible(wide_portrait)
        self.settings_display_column.set_vexpand(wide_portrait)
        self.settings_controls.set_valign(Gtk.Align.FILL if wide_portrait else Gtk.Align.START)
        (self.window.add_css_class if wide_portrait else self.window.remove_css_class)("settings-with-graph")

    def resize_settings_wordmark(self, width, height):
        """Match the wordmark to the adjacent Settings title at every profile."""
        if height > width:
            target_height = 48 if width >= 1000 else 34 if width >= 900 else 28
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
        baseline_lift = 10 if max(width, height) >= 1600 or (width >= 1200 and width > height) else 9 if height > width and width < 600 else 10 if height > width and width >= 1000 else 7 if height > width else 6 if width < 1000 else 8
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
        self.device_status = self.label("", "settings-version"); self.device_status.set_valign(Gtk.Align.BASELINE); self.device_status.set_max_width_chars(64); self.device_status.set_hexpand(True); self.device_status.set_halign(Gtk.Align.START); self.device_status.set_ellipsize(Pango.EllipsizeMode.END); title_row.append(self.device_status); heading.append(title_row)
        self.touch_diagnostics = self.label("Loading diagnostics…", "settings-diagnostic"); self.touch_diagnostics.set_wrap(True); self.touch_diagnostics.set_margin_top(2); heading.append(self.touch_diagnostics); top.append(heading)
        utilities = Gtk.Box(spacing=12); utilities.add_css_class("settings-utilities"); utilities.set_valign(Gtk.Align.START); self.settings_utilities = utilities
        sleep_button = self.button("SLEEP", self.sleep, "settings-sleep"); utilities.append(sleep_button)
        close = Gtk.Button(); close.add_css_class("settings-close"); close.set_size_request(58, 58); close.set_hexpand(False); close.set_vexpand(False); close.set_halign(Gtk.Align.CENTER); close.set_valign(Gtk.Align.CENTER); close.set_tooltip_text("Close settings"); close.set_child(FamilyIcon("close", 32, stroke_width=3)); close.connect("clicked", self.close_settings); self.settings_close = close; utilities.append(close)
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
        self.touch_bus_heading = self.label("BUS TIMES", "eyebrow"); daily.append(self.touch_bus_heading); bus_pair = Gtk.Box(spacing=16); self.touch_bus_pair = bus_pair; bus_visibility = Gtk.Box(spacing=8); bus_visibility.add_css_class("setting-line"); self.touch_bus_enabled = Gtk.CheckButton(label="Bus Times"); self.touch_bus_enabled.set_active(True); self.touch_bus_enabled.connect("toggled", self.toggle_bus_visibility); bus_visibility.append(self.touch_bus_enabled); bus_pair.append(bus_visibility); self.touch_bus_services = Gtk.Box(spacing=8); self.touch_bus_services.add_css_class("setting-line"); self.touch_bus_services.set_hexpand(True); bus_pair.append(self.touch_bus_services); daily.append(bus_pair); self.touch_bus_visibility_row = bus_visibility
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
        # 10-inch portrait: the three installation drop-downs share one row and the space they free holds a live
        # performance graph. Other displays keep the drop-downs stacked and never show the graph.
        display_row = Gtk.Box(spacing=16); display_row.set_homogeneous(True); display_row.add_css_class("settings-display-row"); display_row.set_visible(False)
        self.settings_display_row = display_row; display_column.append(display_row); display_column.reorder_child_after(display_row, self.touch_mounting)
        self.performance_graph = PerformanceGraph(); self.performance_graph.set_visible(False)
        display_column.append(self.performance_graph); display_column.reorder_child_after(self.performance_graph, display_row)
        for row in (self.touch_profile, self.touch_orientation, self.touch_mounting, self.touch_bus_visibility_row): self.settings_row_sizes.add_widget(row)
        action_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); action_stack.add_css_class("settings-action-stack"); action_stack.set_valign(Gtk.Align.END)
        actions = Gtk.Box(spacing=18); actions.add_css_class("settings-primary-actions"); actions.set_homogeneous(True); self.settings_actions = actions; self.apply_display_button = self.button("APPLY DISPLAY", self.request_display_settings, "settings-action"); self.apply_display_button.set_hexpand(True); self.update_button = self.button("INSTALL UPDATE", self.request_update, "settings-action"); self.update_button.set_hexpand(True); actions.append(self.update_button); actions.append(self.apply_display_button); action_stack.append(actions)
        reboot = self.button("REBOOT", self.confirm_reboot, "settings-action"); reboot.add_css_class("reboot-action"); reboot.set_hexpand(True); action_stack.append(reboot); self.settings_reboot = reboot; self.settings_action_stack = action_stack; card.append(action_stack); page.append(card)
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

    def open_settings(self, *_): self.settings_open = True; self.last_system_fetch = 0; self.stack.set_visible_child_name("settings"); self.start_poll()

    def close_settings(self, *_): self.settings_open = False; self.stack.set_visible_child_name(self.last_mode)

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

    def change_brightness(self, scale):
        self.touch_brightness_value.set_text(f"{round(scale.get_value())}%")
        if self.brightness_updating: return
        if self.brightness_timeout is not None: GLib.source_remove(self.brightness_timeout)
        self.brightness_timeout = GLib.timeout_add(180, self.send_brightness, round(scale.get_value()))

    def send_brightness(self, value):
        self.brightness_timeout = None
        threading.Thread(target=post_json, args=(BUS + "/api/device/brightness", {"brightness": value}), daemon=True).start()
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
