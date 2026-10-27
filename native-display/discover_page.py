"""Discover page: daily sections, mixes, recent plays and artist profiles."""
from __future__ import annotations

from native_common import CAROUSEL_END_SPACE, ElasticCarouselTrack, FamilyIcon, MixPicture, ROON, TZ, get_json, post_json
from datetime import datetime
from urllib.parse import quote, urlencode
import json
import math
import threading
import time
import uuid
from gi.repository import GLib, Gdk, Gtk, Pango


class DiscoverPageMixin:
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
            self.apply_discovery_layout()
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

    def apply_discovery_layout(self):
        """Margins and scroll policy for the current Discover section. Applied when a section opens, not only when its data
        arrives, so the loading dots do not jump when the first response rebuilds the list with different margins."""
        portrait_grid = getattr(self, "responsive_portrait", False)
        original_daily = not portrait_grid and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500 and getattr(self, "discovery_section", "") == "daily"
        (self.roon_page.add_css_class if original_daily else self.roon_page.remove_css_class)("daily-edge")
        self.discovery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL if original_daily else Gtk.PolicyType.AUTOMATIC)
        self.discovery_body.set_margin_end(0 if portrait_grid or getattr(self, "discovery_section", "") == "daily" else 28 if getattr(self, "viewport_width", 800) >= 1200 else 0)
        gen2_landscape = self.window.has_css_class("touch2-7-landscape")
        offset_discovery = gen2_landscape and getattr(self, "discovery_section", "") in {"recent", "daily", "releases"}
        self.discovery_list.set_margin_top(22 if portrait_grid and self.discovery_section == "releases" else 24 if offset_discovery else 5 if not portrait_grid and getattr(self, "discovery_section", "") in {"recent", "daily", "releases"} else 0)

    def render_discover(self, request, data):
        if request != self.discovery_request or not self.discovery_active or self.roon_views.get_visible_child_name() != "discover": return False
        data = data or {"status": "unavailable", "message": "Discover is unavailable. Normal Roon controls are unaffected."}
        portrait_grid = getattr(self, "responsive_portrait", False)
        signature = json.dumps([data, portrait_grid, self.settings_data.get("portrait_discovery_columns", 2), getattr(self, "discovery_daily_tab", "mixes")], sort_keys=True)
        if signature == self.discovery_signature: return False
        self.discovery_signature = signature
        self.discovery_data = data
        # Already showing the loading dots for this section: keep that very widget instead of replacing it with an identical
        # one, which restarted the animation and made the dots flicker and jump.
        first = self.discovery_list.get_first_child()
        if data.get("status") == "loading" and first is not None and getattr(first, "is_loading_notice", False) and first.get_next_sibling() is None:
            self.apply_discovery_layout(); return False
        self.discovery_list.cancel_spring()
        while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
        self.discovery_pictures = {}
        self.discovery_cards = []
        self.discovery_card_scrollers = {}
        self.sync_discovery_sidebar()
        self.apply_discovery_layout()
        gen2_landscape = self.window.has_css_class("touch2-7-landscape")
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
        section = "mix" if self.discovery_mix else ("daily-home" if self.discovery_section == "daily" else self.discovery_section)
        if section == "recent" and getattr(self, "discovery_recent_mode", "added") == "added": section = "added"
        def load():
            # Send the section so the controller can rebuild a card key that a background refresh replaced, and retry once
            # before reporting failure: a first attempt that races the refresh used to flash "could not be opened".
            payload = {"session": "touch", "key": key, "section": section, "id": self.discovery_mix}
            result = post_json(ROON + "/api/discovery/open", payload, timeout=20.0)
            if not result or result.get("error"):
                time.sleep(0.4)
                retry = post_json(ROON + "/api/discovery/open", payload, timeout=20.0)
                if retry and not retry.get("error"): result = retry
            GLib.idle_add(self.apply_discovery_item, request, result)
        threading.Thread(target=load, daemon=True).start()

    def apply_discovery_item(self, request, data):
        if request != self.discovery_request or not self.discovery_active: return False
        if not data or data.get("error"):
            # Keep the cards on screen; only report the failure once the retry has also failed.
            self.discovery_opening = False
            self.discovery_list.append(self.label((data or {}).get("error") or "This item could not be opened. Try again from Discover.", "browser-message")); return False
        self.discovery_opening = False
        if data.get("action_menu"):
            self.render_browser(data)
        else:
            self.set_roon_view("browse"); self.render_browser(data)
        return False

    def render_artist_profile(self, profile, play_action=None):
        portrait = getattr(self, "responsive_portrait", False)
        original = not portrait and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        # 800x480 stacks the profile above the albums as one full-width column (small picture, name,
        # Play Artist Radio and a short summary), so album names are readable.
        seven_landscape = not portrait and not original and getattr(self, "viewport_height", 480) <= 720
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
            panel.set_size_request(-1 if portrait or original else 260, -1)
            if original:
                panel.set_orientation(Gtk.Orientation.HORIZONTAL); panel.set_spacing(16); panel.set_halign(Gtk.Align.FILL)
                self.browser_artist_scroll.set_hexpand(True); self.browser_artist_scroll.set_vexpand(False); self.browser_artist_scroll.set_valign(Gtk.Align.START)
                self.browser_artist_scroll.set_propagate_natural_height(False); self.browser_artist_scroll.set_size_request(-1, 212)
                self.browser_artist_scroll.set_min_content_height(212); self.browser_artist_scroll.set_max_content_height(212)
                size = 200
                artwork = Gtk.ScrolledWindow(); artwork.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); artwork.set_propagate_natural_width(False); artwork.set_propagate_natural_height(False)
                artwork.set_min_content_width(size); artwork.set_max_content_width(size); artwork.set_min_content_height(size); artwork.set_max_content_height(size); artwork.set_size_request(size, size); artwork.set_valign(Gtk.Align.START)
                artwork.add_css_class("artist-hero-frame"); artwork.set_overflow(Gtk.Overflow.HIDDEN)
            elif portrait:
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
        details.set_valign(Gtk.Align.START if seven_landscape else Gtk.Align.CENTER if not original else Gtk.Align.START); details.set_hexpand(True)
        if seven_landscape:
            details.add_css_class("artist-overlay-info"); details.set_halign(Gtk.Align.FILL); details.set_valign(Gtk.Align.END); details.set_hexpand(True)
            details.set_size_request(hero_width, -1); artwork_area.add_overlay(details)
        else: panel.append(details)
        title = self.label(name, "artist-name", 0 if portrait or original else .5); title.set_wrap(True); title.set_max_width_chars(24 if original else 20); details.append(title)
        if seven_landscape: title.set_xalign(0)
        if play_action:
            play = self.labelled_icon_button("play", "Play Artist Radio", lambda *_: self.open_browser_item(None, play_action.get("item_key")), "artist-play primary-play")
            play.set_halign(Gtk.Align.START if portrait or seven_landscape or original else Gtk.Align.CENTER); details.append(play)
        summary_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if seven_landscape:
            summary_slot.add_css_class("artist-profile-summary"); panel.append(summary_slot)
        else: details.append(summary_slot)
        summary_slot.artist_summary_lines = 4 if seven_landscape else 4 if original else 5
        summary_slot.artist_summary_chars = max(28, round((hero_width - (32 if original else 64)) / 9)) if seven_landscape else 46 if original else 52
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
