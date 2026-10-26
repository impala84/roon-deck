#!/usr/bin/env python3
"""Native GTK4 touchscreen for RoonDeck."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_common import *  # noqa: F401,F403  shared imports, helpers and widgets
from native_common import Gtk
from bus_page import BusPageMixin
from home_page import HomePageMixin
from settings_page import SettingsPageMixin
from sleep_and_touch import SleepAndTouchMixin
from now_playing_page import NowPlayingPageMixin
from discover_page import DiscoverPageMixin
from browse_page import BrowsePageMixin
from artwork import ArtworkMixin
from screen_preview import ScreenPreviewMixin


class Display(BusPageMixin, HomePageMixin, SettingsPageMixin, SleepAndTouchMixin, NowPlayingPageMixin, DiscoverPageMixin, BrowsePageMixin, ArtworkMixin, ScreenPreviewMixin, Gtk.Application):
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
        width, height = getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)
        original = width <= 820 and height <= 500
        portrait = getattr(self, "responsive_portrait", False)
        gen2_seven = not portrait and 1200 <= width < 1500 and 650 <= height < 850
        # Portrait: the dots sit about a quarter of the way down. Elsewhere they are centred in whatever area the
        # panel fills, so Browse, Discover and Search all agree; Gen 2 Browse is then nudged to the middle of the
        # cover area (right of the 170px rail) once the dots are on screen.
        top = 18 if original else round(height * .26) if portrait else 48
        panel.set_margin_top(top); panel.set_margin_bottom(18 if original else 48)
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
        def centre(*_):
            if not gen2_seven: return False
            try:
                point = panel.translate_coordinates(self.window, 0, 0)
                if point is None: return False
                browsing = self.roon_views.get_visible_child_name() in {"browse", "search"}
                wanted = 687 if browsing else self.window.get_width() / 2
                middle = point[0] + panel.get_width() / 2
                shift = round(middle - wanted)
                if abs(shift) > 2:
                    if shift > 0: panel.set_margin_end(panel.get_margin_end() + 2 * shift)
                    else: panel.set_margin_start(panel.get_margin_start() - 2 * shift)
            except Exception: pass
            return False
        def start(*_):
            if gen2_seven: GLib.timeout_add(60, centre)
            if timer[0] is None:
                started[0] = time.monotonic(); pulse(); timer[0] = GLib.timeout_add(80, pulse)
        def stop(*_):
            if timer[0] is not None: GLib.source_remove(timer[0]); timer[0] = None
        panel.connect("map", start); panel.connect("unmap", stop)
        return panel

    def do_activate(self):
        provider = Gtk.CssProvider(); provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.home_color_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.home_color_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = create_display_window(application=self); self.window.set_decorated(False); self.window.set_default_size(800, 480); self.window.fullscreen()
        # Apply saved theme before the first frame, not after an API poll.
        initial_config = {}
        try:
            initial_config = tomllib.loads(Path("/etc/pi-home/config.toml").read_text())
            if initial_config.get("display_theme") == "roon": self.window.add_css_class("theme-roon")
        except (OSError, ValueError): pass
        self.window.set_cursor_from_name("none")
        try: Gtk.Settings.get_default().set_property("gtk-cursor-theme-name", "pi-home-touch")
        except (AttributeError, TypeError): pass
        print("RoonDeck cursor theme: XCURSOR_THEME=%s XCURSOR_PATH=%s" % (os.environ.get("XCURSOR_THEME"), os.environ.get("XCURSOR_PATH")), flush=True)
        activity = Gtk.EventControllerLegacy(); activity.set_propagation_phase(Gtk.PropagationPhase.CAPTURE); activity.connect("event", self.note_activity); self.window.add_controller(activity)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, transition_duration=0)
        self.stack.set_hhomogeneous(False); self.stack.set_vhomogeneous(False)
        self.boot_started_at = time.monotonic(); self.boot_transition_timer = None; self.pending_boot_mode = None
        self.stack.add_named(self.build_boot_splash(), "boot"); self.stack.add_named(self.build_bus(), "bus"); self.stack.add_named(self.build_roon(), "roon"); self.stack.add_named(self.build_home(), "home"); self.stack.add_named(self.build_settings(), "settings"); self.stack.add_named(self.build_sleep(), "sleep")
        self.root_overlay = Gtk.Overlay(); self.root_overlay.set_child(self.stack)
        self.window.set_child(self.root_overlay)
        # Apply the saved interface size and background before the first frame. Waiting for the first API poll drew the
        # standard layout and then rescaled it about a second later.
        try:
            if initial_config.get("display_background") == "black": self.window.add_css_class("background-black")
            if initial_config.get("interface_size") in {"smaller", "larger"}: self.apply_interface_size(initial_config["interface_size"])
        except (NameError, AttributeError, TypeError, ValueError): pass
        self.window.present()
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
        # Seven-inch Gen 2: anchor the cog and clock icon to the top of their header
        # row instead of centring them in it. Row height differs per page (Bus and Home
        # are taller than the Now Playing toolbar), so centring made the cog drift.
        # A new display geometry or interface size starts the cog alignment afresh.
        # adapt_display also runs on every track change and Browse render, so only restart when the geometry changed;
        # resetting the margins each time made the cog visibly jump back and forth.
        cog_signature = (width, height, (self.settings_data or {}).get("interface_size"))
        if cog_signature != getattr(self, "cog_signature", None):
            self.cog_signature = cog_signature
            for cog in [getattr(self, "music_settings_button", None)] + list(getattr(self, "header_cogs", [])):
                if cog is not None: cog.set_margin_start(0); cog.set_margin_top(0)
            self.cog_reference_x = None; self.cog_reference_y = None
            GLib.timeout_add(250, lambda: self.align_header_cogs() and False)
        for button in getattr(self, "header_utility_buttons", []):
            button.set_valign(Gtk.Align.START if touch2_7_landscape or original_landscape else Gtk.Align.CENTER)
        self.now_playing_content.set_orientation(Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL)
        self.now_playing_content.set_spacing(24 if portrait else 20 if original_landscape else 26)
        self.now_playing_content.set_margin_top(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)
        self.now_playing_content.set_margin_bottom(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)
        self.now_playing_centre.set_valign(Gtk.Align.START if portrait else Gtk.Align.CENTER)
        # 800x480: centre the block on the artwork; a two-line title still fits inside the artwork's height.
        self.now_playing_centre.set_spacing(4 if original_landscape else 7)
        self.controls.set_margin_top(2 if original_landscape else 6); self.controls.set_margin_bottom(10 if original_landscape else 16)
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
        self.browser_scroll.set_margin_bottom(self.browser_scroll_bottom_margin(original_landscape))
        compact_browser_scrubber = portrait or compact_landscape or touch2_7_landscape
        # The alphabet letter is drawn 26px left of the track, so the rail needs ~64px;
        # 42px clipped the letter. On the 7-inch Gen 2 the track sits 12px inside the
        # page's 28px edge, centred under the clock icon.
        self.browser_scrubber.set_size_request(54 if original_landscape else 64 if touch2_7_landscape else 52 if compact_browser_scrubber else 74, -1)
        self.browser_scrubber.set_margin_end(28 if touch2_7_landscape else 0 if compact_browser_scrubber else 18)
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
            label.set_lines(2 if original_landscape else 4 if inline_detail and (self.settings_data or {}).get("interface_size") == "larger" else 5 if album_focus_detail else 24 if large_detail_portrait else 3 if compact_detail else -1)
            label.set_ellipsize(Pango.EllipsizeMode.END if compact_detail or large_detail_portrait else Pango.EllipsizeMode.NONE)
        # EXTERNAL does not feed the text's minimum height into the window, so opening details can never grow it.
        self.detail_sheet.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL if inline_detail else Gtk.PolicyType.AUTOMATIC)
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
        self.header_utility_buttons = getattr(self, "header_utility_buttons", []) + [settings]
        self.header_cogs = getattr(self, "header_cogs", []) + [settings]
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

    def apply(self, target, status, roon, config, system, device, image_key, image):
        effective_config = config if isinstance(config, dict) and config else self.settings_data
        background = (effective_config or status or {}).get("display_background")
        if background is not None:
            if background == "black": self.window.add_css_class("background-black")
            else: self.window.remove_css_class("background-black")
        if status and "display_theme" in status and config is None: self.apply_theme(status["display_theme"])
        if isinstance(config, dict) and config:
            grid_changed = self.settings_data.get("portrait_discovery_columns", 2) != config.get("portrait_discovery_columns", 2)
            previous_interface_size = (self.settings_data or {}).get("interface_size", "standard")
            self.settings_data = config
            self.apply_interface_size(config.get("interface_size", "standard"))
            if config.get("interface_size", "standard") != previous_interface_size:
                # Artwork size, line counts and other pixel budgets depend on the interface size, but
                # adapt_display first runs before the saved config has loaded. Recalculate when the saved
                # size arrives, as change_interface_size already does when the dropdown is used.
                GLib.idle_add(self.adapt_display)
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
            self.sync_appearance_selects()
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
            now_playing_check = time.monotonic()
            # Playback that merely restarts between tracks (a "loading" blink) is not a new start, and nobody who is
            # touching the screen should be pulled away from what they are doing.
            gap = now_playing_check - getattr(self, "playback_last_playing", 0.0)
            fresh_start = was_sleeping or (not getattr(self, "playback_was_active", False) and gap > 20)
            browsing_now = now_playing_check - self.browse_last_interaction < 30 and not was_sleeping
            if target and ":8766/" in target and fresh_start and not browsing_now and not self.settings_open:
                self.set_roon_view("now")
            self.playback_last_playing = now_playing_check
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

    def prewarm_views(self):
        started = time.monotonic()
        for name in ("roon", "home"):
            child = self.stack.get_child_by_name(name)
            child.measure(Gtk.Orientation.HORIZONTAL, 800)
            child.measure(Gtk.Orientation.VERTICAL, 480)
        print(f"RoonDeck views pre-measured in {(time.monotonic() - started) * 1000:.1f}ms", flush=True)
        return False

    def set_mode(self, mode):
        started = time.monotonic(); self.settings_open = False; self.last_mode = mode; self.pending_mode = mode; self.pending_mode_started_at = started; self.stack.set_visible_child_name(mode); print(f"RoonDeck switched to {mode} in {(time.monotonic() - started) * 1000:.1f}ms", flush=True); threading.Thread(target=post_json, args=(BUS + "/api/admin/display-mode", {"mode": mode}), daemon=True).start()
        GLib.timeout_add(150, self.align_header_cogs)

    def align_header_cogs(self, retry=True):
        """Put every page's cog on the same centre point.

        Buttons can only be pushed right or down (Python margins are never negative), so each page aligns to the
        right-most, lowest cog centre seen on any page. Centres, not left edges: the Bus Times and Home cog box is a
        different width from the music pages' box, so equal left edges still left the glyphs a pixel or two apart."""
        if getattr(self, "responsive_portrait", False): return False
        # The original 7-inch display has identical cog geometry on every page from CSS alone;
        # moving it at run time could only make it visibly jump.
        if getattr(self, "viewport_width", 0) <= 820 and getattr(self, "viewport_height", 0) <= 500: return False
        try:
            def centre(button):
                point = button.translate_coordinates(self.window, button.get_width() / 2, button.get_height() / 2)
                return None if point is None else (point[0], point[1])
            buttons = [button for button in [getattr(self, "music_settings_button", None)] + list(getattr(self, "header_cogs", []))
                       if button is not None and button.get_mapped()]
            target_x, target_y = getattr(self, "cog_reference_x", None), getattr(self, "cog_reference_y", None)
            for button in buttons:
                point = centre(button)
                if point is None: continue
                if target_x is None or point[0] > target_x: target_x = point[0]
                if target_y is None or point[1] > target_y: target_y = point[1]
            if target_x is None: return False
            self.cog_reference_x, self.cog_reference_y = target_x, target_y
            moved = False
            for button in buttons:
                point = centre(button)
                if point is None: continue
                dx, dy = round(target_x - point[0]), round(target_y - point[1])
                if dx > 0: button.set_margin_start(button.get_margin_start() + dx); moved = True
                if dy > 0: button.set_margin_top(button.get_margin_top() + dy); moved = True
            if moved and retry: GLib.timeout_add(120, lambda: self.align_header_cogs(False) and False)
        except Exception as error:
            print("RoonDeck cog alignment skipped: " + type(error).__name__, flush=True)
        return False


if __name__ == "__main__":
    # A native crash (segfault) now leaves a Python traceback in /var/log/pi-home/display-error.log.
    import faulthandler
    faulthandler.enable(all_threads=True)
    publish_display_source()
    Display().run(None)
