"""Now Playing page: transport, volume, details and queue."""
from __future__ import annotations

from native_common import ElasticVerticalTrack, FamilyIcon, ROON, elastic_vertical_scroll, post_json, release_period_label, release_type_label
import json
import re
import threading
import time
import urllib.error
import urllib.request
from gi.repository import GLib, Gdk, Gtk, Pango


class NowPlayingPageMixin:
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
        self.header_utility_buttons = getattr(self, "header_utility_buttons", []) + [settings, sleep]
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
        times = Gtk.Box(); times.add_css_class("now-times"); self.elapsed = self.label("0:00", "time"); self.remaining = self.label("−0:00", "time", 1); self.remaining.set_hexpand(True); times.append(self.elapsed); times.append(self.remaining); centre.append(times); self.roon_times = times
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
        # Genre drill-down: the parent list stays on the left while its child list opens on the right.
        self.genre_stack = []; self.genre_pending = None; self.genre_sibling_target = None; self.browser_last_action = None
        self.browser_trail_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.browser_trail_scroll = Gtk.ScrolledWindow(); self.browser_trail_scroll.add_css_class("genre-trail"); self.browser_trail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL); self.browser_trail_scroll.set_size_request(300, -1); self.browser_trail_scroll.set_hexpand(False); self.browser_trail_scroll.set_vexpand(True); self.browser_trail_scroll.set_child(self.browser_trail_list); self.browser_trail_scroll.set_visible(False); content.prepend(self.browser_trail_scroll)
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

    def render_touch_controls(self, device, system):
        signature = json.dumps({"services": device.get("services", []), "bridge": (system or {}).get("roon_bridge"), "netdata": (system or {}).get("netdata"), "background": self.settings_data.get("display_background")}, sort_keys=True)
        if signature == getattr(self, "touch_controls_signature", None): return
        self.touch_controls_signature = signature
        while child := self.touch_daily.get_last_child():
            if child.has_css_class("setting-line"): self.settings_row_sizes.remove_widget(child)
            self.touch_daily.remove(child)
        bridge_state = (system or {}).get("roon_bridge")
        service_pair = Gtk.Box(spacing=16); service_pair.set_homogeneous(True)
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
        # 800x480: the Bus Times and Home cog is a 36px box whose icon fills it. The music pages pinned the glyph to the
        # left edge of the same box (3px left of that cog); centring it still drew it a pixel smaller. Fill it identically.
        original = getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        self.music_settings_button.get_child().set_halign(Gtk.Align.FILL if original and not full else Gtk.Align.START)
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
        self.discover_toolbar.set_margin_bottom(1 if original_landscape and name in {"now", "details"} else 20 if original_landscape else 14)
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
        # Portrait and other non-inline layouts: the Roon theme makes the sheet transparent, so the
        # page beneath (artwork, scrubber, controls, tabs) showed through. Hide it while the sheet is up.
        sheet_over_page = name == "details" and not inline_details
        self.roon_page.set_opacity(0 if sheet_over_page else 1)
        self.roon_page.set_can_target(not sheet_over_page)
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
        # Wide portrait: both headings get the taller one's height and sit on its last line, so the two
        # columns' last heading lines share a baseline and both write-ups start on the same line grid.
        for heading in (self.detail_artist_name, self.detail_title):
            heading.set_yalign(1.0 if getattr(self, "large_detail_portrait", False) else .5)
        if getattr(self, "large_detail_portrait", False):
            # Measure against the real card width. An unconstrained measure can
            # claim an album title fits on one line, only for GTK to wrap it
            # after allocation and push the album write-up below the artist's.
            heading_width = max(1, getattr(self, "detail_heading_width", 500))
            heading_height = max(heading.measure(Gtk.Orientation.VERTICAL, heading_width)[1] for heading in (self.detail_artist_name, self.detail_title))
            for heading in (self.detail_artist_name, self.detail_title): heading.set_size_request(-1, heading_height)
        writeup = metadata.get("full_writeup") or metadata.get("writeup") or ""
        if not writeup and getattr(self, "large_detail_portrait", False):
            # The album summary arrives after the page opens (and can be unavailable). Keep the column's
            # copy slot visible, as the artist column does, instead of leaving it blank.
            writeup = "Loading album summary…" if details.get("metadata_pending") else "Album summary is unavailable."
        self.detail_writeup.set_text(writeup); self.detail_writeup.set_visible(bool(writeup))
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

    def play_queue_item(self, _button, queue_item_id):
        if queue_item_id is not None:
            threading.Thread(target=post_json, args=(ROON + "/api/queue/play", {"queue_item_id": queue_item_id}), daemon=True).start()

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
