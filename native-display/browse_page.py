"""Browse pages: albums, artists, genres, search, scrubber and album headers."""
from __future__ import annotations

from native_common import ElasticVerticalTrack, FamilyIcon, ROON, browser_request_timeout, get_json, post_json
from pathlib import Path
import threading
import unicodedata
import urllib.error
import urllib.request
from gi.repository import GLib, Gdk, Graphene, Gtk, Pango


class BrowsePageMixin:
    def show_browser(self, *_):
        self.discovery_browser_origin = False
        self.discovery_active = True; self.discovery_section = "browse"
        self.set_roon_view("browse")
        if self.browser_state is None: self.request_browser("section", section="albums")

    def browse_detail_artist(self, *_):
        artist = (self.detail_artist_profile_name or self.detail_artist.get_text() or "").strip()
        if not artist: return
        # Global Search is only how Roon resolves the catalogue artist. Keep
        # that internal stack out of visible navigation and remember the page
        # beneath the detail sheet as the user's real Back destination.
        departure = self.roon_views.get_visible_child_name() or "now"
        self.browser_departure_view = departure if departure in {"now", "queue", "source", "discover", "browse"} else "now"
        self.discovery_browser_origin = False
        self.discovery_active = True; self.discovery_section = "browse"
        for name, button in self.discover_tabs.items():
            if name == "browse": button.add_css_class("active")
            else: button.remove_css_class("active")
        self.set_roon_view("browse")
        self.request_browser("artist", name=artist)

    def browser_back_action(self, *_):
        departure = getattr(self, "browser_departure_view", None)
        state = self.browser_state or {}
        if departure and state.get("artist_profile") and not state.get("album_profile"):
            self.browser_departure_view = None
            self.set_roon_view(departure)
            return
        self.request_browser("back")

    def browser_swipe_back(self, _gesture, distance_x, distance_y):
        if distance_x > 90 and distance_x > abs(distance_y) * 2 and (self.browser_state or {}).get("can_back"):
            self.browser_back_action()

    def show_browser_sort(self, button):
        popover = Gtk.Popover(); popover.add_css_class("track-menu"); popover.add_css_class("sort-menu"); popover.set_parent(button); popover.set_has_arrow(False); popover.set_autohide(True); popover.set_position(Gtk.PositionType.BOTTOM); popover.set_halign(Gtk.Align.START); popover.set_offset(-18, 4)
        choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); choices.set_size_request(max(1, button.get_width()), -1)
        for order, title in (("title", "Title, A to Z"), ("reverse", "Title, Z to A"), ("artist", "Artist, A to Z")):
            def choose(_choice, value=order, menu=popover):
                menu.popdown(); self.browser_sort.set_sensitive(False); self.browser_sort.get_child().set_text("Sorting…"); self.request_browser("sort", order=value)
            choice = self.button(title, choose, "track-menu-action"); choice.set_focusable(False)
            if order == self.browser_sort_order: choice.add_css_class("active")
            choices.append(choice)
        def closed(*_):
            if getattr(self, "browser_sort_popover", None) is popover: self.browser_sort_popover = None
            popover.unparent()
        popover.connect("closed", closed)
        popover.connect("map", lambda widget: GLib.idle_add(self.hide_native_cursor, widget))
        popover.set_child(choices); self.hide_widget_cursor(popover); popover.popup(); self.hide_native_cursor(popover); self.browser_sort_popover = popover

    def request_browser(self, action, **payload):
        if action == "artist":
            self.browser_scroll.set_visible(True)
            self.browser_artist_scroll.set_visible(False); self.browser_search_columns.set_visible(False)
            self.browser_scrubber.set_visible(False); self.browser_message.set_visible(False)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
            self.browser_list.append(self.loading_notice())
        if action == "search":
            self.browser_search_columns.set_visible(False); self.browser_scroll.set_visible(True)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
            self.browser_list.append(self.loading_notice())
            self.browser_artist_scroll.set_visible(False); self.browser_scrubber.set_visible(False)
            self.browser_search_button.add_css_class("active")
            for button in self.browser_section_buttons.values(): button.remove_css_class("active")
        if self.browser_loading:
            if action in {"jump", "section", "search", "surprise", "artist"}: self.browser_pending_request = (action, payload)
            return
        if action == "surprise" and not (self.browser_state or {}).get("surprise_preview"):
            self.browser_section_scrolls[(self.browser_state or {}).get("section", "albums")] = self.browser_scroll.get_vadjustment().get_value()
        if action in {"section", "search"}:
            self.browser_section_scrolls[(self.browser_state or {}).get("section", "albums")] = self.browser_scroll.get_vadjustment().get_value()
            self.browser_scroll_restore = self.browser_section_scrolls.get(payload.get("section", "search"), 0.0) if action == "section" else 0.0
        elif action == "more": self.browser_scroll_restore = self.browser_scroll.get_vadjustment().get_value()
        elif action == "previous":
            self.browser_previous_height = self.browser_scroll.get_vadjustment().get_upper()
            self.browser_scroll_restore = self.browser_scroll.get_vadjustment().get_value()
        elif action == "back" and (self.browser_state or {}).get("surprise_preview"): self.browser_scroll_restore = self.browser_section_scrolls.get(self.browser_state.get("return_section", "albums"), 0.0)
        elif action in {"jump", "open", "back", "surprise"}: self.browser_scroll_restore = 0.0
        self.browser_loading = True; self.browser_message.set_visible(False); self.browser_last_action = action
        threading.Thread(target=self._request_browser, args=(action, payload), daemon=True).start()

    def _request_browser(self, action, payload):
        if action == "current": result = get_json(f"{ROON}/api/browse?session=touch", timeout=3.0)
        else: result = post_json(ROON + "/api/browse", {"session": "touch", "action": action, **payload}, timeout=browser_request_timeout(action))
        GLib.idle_add(self.apply_browser_response, result or {"status": "ready", "title": "Browse", "items": [], "message": "Roon Browse did not respond.", "error": True})

    def apply_browser_response(self, data):
        pending = getattr(self, "browser_pending_request", None)
        if pending:
            self.browser_pending_request = None; self.browser_loading = False
            self.request_browser(pending[0], **pending[1])
            return False
        try:
            self.render_browser(data)
        except Exception as error:
            # A rendering exception must not permanently lock navigation.
            self.browser_loading = False; self.browser_rendering = False
            self.browser_scroll_restore = None
            print("RoonDeck Browse render failed: " + type(error).__name__, flush=True)
            while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
            self.browser_list.append(self.label("This view could not be displayed. Choose a music tab to try again.", "browser-message"))
            return False
        if data.get("navigate") == "now" and not data.get("error"): self.set_roon_view("now")
        return False

    def browser_scroll_bottom_margin(self, original_view=False):
        if original_view: return 0
        width, height = getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)
        gen2_seven = not getattr(self, "responsive_portrait", False) and 1200 <= width < 1500 and 650 <= height < 850
        # The clip line sits at y = 609 - margin. Covers start at y~101 and 230px covers put the third row at
        # y~614, so a 4px margin lets the visible area run to the bottom of the Back button (y~605).
        return 4 if gen2_seven else 10

    def browser_grid_metrics(self, genres=False, artists=False):
        monitors = Gdk.Display.get_default().get_monitors()
        monitor = monitors.get_item(0) if monitors.get_n_items() else None
        # Never derive minimum tile sizes from content that may have already
        # expanded the window. Reserve the section rail, scrubber and padding.
        monitor_width = monitor.get_geometry().width if monitor else 800
        width = min(monitor_width, getattr(self, "viewport_width", monitor_width))
        profile = (getattr(self, "system_data", {}) or {}).get("display_profile")
        # KMS can briefly expose the source mode (often 1920 wide) before the
        # configured Touch Display 2 canvas settles at 1280. A grid rendered in
        # that interval permanently widens GTK's natural allocation. Use the
        # physical profile as the hard layout budget instead.
        if not getattr(self, "responsive_portrait", False):
            if profile in {"touch2-7", "touch2-5-7"}: width = min(width, 1280)
            elif profile == "original": width = min(width, 800)
        if getattr(self, "responsive_portrait", False):
            width = min(self.window.get_width() or width, width)
            # Includes outer margins, the alphabet rail, queue-list padding
            # and each button's CSS padding; none may depend on image size.
            margin = 30
            available = width - margin * 2 - (80 if not genres and (self.browser_state or {}).get("alpha_scrub") else 0)
            gap = 30
            return 3, max(48, (available - gap * 2) // 3)
        viewport_height = getattr(self, "viewport_height", None)
        original = width <= 820 and viewport_height is not None and viewport_height <= 500
        if original:
            # Measured 800px budget includes page (24), the rail's realised
            # 122px, the full 54px scrubber, scroller chrome and safety gutter.
            available = max(140, width - 252)
            return 4, max(64, (available - 12 * 3) // 4)
        larger_seven = profile in {"touch2-7", "touch2-5-7"} and (getattr(self, "settings_data", {}) or {}).get("interface_size") == "larger"
        # The scrubber rail is 64px with a 28px page edge, 50px wider than before.
        # Larger covers are the only size that had no spare width for that.
        available = max(140, width - (320 if genres else 280) - (18 if larger_seven else 0))
        # The 7-inch Gen 2 has room for four covers at the larger scale when
        # the grid uses its measured page inset and a 22px gutter. Keep the
        # same four-column rhythm for albums, artists and genre results.
        columns = min(4, max(1, available // 140))
        gap = 21 if larger_seven else 24
        cap = 228 if larger_seven else 212
        # Each card contributes 3px padding on both sides in addition to the
        # grid gap. Account for it here rather than allowing the fifth/right
        # edge to be clipped by the alphabet scrubber.
        size = max(64, min(cap, (available - gap * (columns - 1)) // columns - 7))
        view_width, view_height = getattr(self, "viewport_width", width), getattr(self, "viewport_height", None) or 720
        if 1200 <= view_width < 1500 and 650 <= view_height < 850:
            # Seven-inch Gen 2. Measured on the Pi: a 212px grid plus the 43px gutter, the 64px
            # scrubber rail and the 28px page edge made the window 1311px wide (1293px in Larger).
            # 217px covers (223px cards, 14px column gaps) end at x~1134, leaving ~54px before the rail.
            size = min(size, 217)
            # Measured on the Pi: without the fill class (it used to skip Larger) everything right of the grid took 133px
            # and 229px covers made the window 1312px wide. The fill class removes the 28px scroll margin and 8px list
            # padding, leaving 97px for the rail and page edge. Four cards (size + 6) from x=197, three 12px gaps and
            # 6px spare must fit in the rest, so the covers keep their full size and the window stays 1280px.
            size = max(64, min(236, (view_width - 97 - 197 - 12 * 3 - 24 - 6) // 4))
        return columns, size

    def browser_scrub_changed(self, scale):
        if getattr(self, "browser_scrub_sync", False): return
        value = max(0, min(25, round(scale.get_value()))); letter = chr(65 + value); self.position_browser_scrub_letter(letter, value)
        if timer := getattr(self, "browser_scrub_timer", None): GLib.source_remove(timer)
        self.browser_scrub_timer = GLib.timeout_add(220, self.commit_browser_scrub, letter)

    def position_browser_scrub_letter(self, letter, value):
        self.browser_scrubber.queue_draw()

    def draw_browser_scrubber(self, _area, cr, width, height, *_data):
        # One shared centre for the dot and the letter's actual ink bounds.
        value = max(0, min(25, round(self.browser_scrub_scale.get_value())))
        center = 16 + max(1, height - 32) * value / 25
        x = width - 12
        track = (.27, .26, .29) if getattr(self, "settings_data", {}).get("display_theme") == "roon" else (.145, .192, .18)
        cr.set_source_rgb(*track); cr.set_line_width(5); cr.set_line_cap(1); cr.move_to(x, 16); cr.line_to(x, max(16, height - 16)); cr.stroke()
        accent = (.506, .478, .922) if getattr(self, "settings_data", {}).get("display_theme") == "roon" else (.431, .851, .682)
        cr.set_source_rgb(*accent); cr.arc(x, center, 9, 0, 6.283185307); cr.fill()
        cr.select_font_face("Inter", 0, 1)
        large_interface = getattr(self, "settings_data", {}).get("interface_size") == "larger"
        cr.set_font_size(25 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 22 if large_interface else 18)
        letter = chr(65 + value); extents = cr.text_extents(letter)
        cr.move_to(x - 26 - extents[2], center - extents[1] - extents[3] / 2); cr.show_text(letter)

    def browser_scrub_at(self, y):
        height = self.browser_scrubber.get_allocated_height()
        value = max(0, min(25, round((y - 16) * 25 / max(1, height - 32))))
        self.browser_scrub_scale.set_value(value)

    def browser_scrub_begin(self, _gesture, _x, y):
        self.browser_scrub_dragging = True; self.browser_scrub_start_y = y; self.browser_scrub_at(y); self.browser_scrub_changed(self.browser_scrub_scale)

    def browser_scrub_drag(self, _gesture, _x, y):
        self.browser_scrub_at(self.browser_scrub_start_y + y)

    def browser_scrub_end(self, _gesture, _x, y):
        self.browser_scrub_at(self.browser_scrub_start_y + y); self.browser_scrub_dragging = False

    def browser_scrub_pressed(self, *_):
        self.browser_scrub_dragging = True

    def browser_scrub_released(self, *_):
        self.browser_scrub_dragging = False

    def show_browser_search(self, *_):
        self.set_roon_view("search"); self.browser_search_entry.grab_focus()

    def browser_keyboard_key(self, value):
        entry = self.browser_search_entry; text = entry.get_text(); position = entry.get_position()
        bounds = entry.get_selection_bounds()
        selected, start, end = bounds if len(bounds) == 3 else (bool(bounds), *(bounds if len(bounds) == 2 else (0, 0)))
        if selected: text = text[:start] + text[end:]; position = start
        if value == "CLEAR": text = ""; position = 0
        elif value == "BACKSPACE":
            if not selected and position > 0: text = text[:position - 1] + text[position:]; position -= 1
        else: text = text[:position] + value.lower() + text[position:]; position += len(value)
        entry.set_text(text); entry.set_position(position)

    def submit_browser_search(self, *_):
        query = self.browser_search_entry.get_text().strip()
        if query:
            if getattr(self, "browser_search_timer", None):
                GLib.source_remove(self.browser_search_timer); self.browser_search_timer = None
            self.set_roon_view("search" if getattr(self, "responsive_portrait", False) else "browse")
            self.request_browser("search", query=query, source="all")

    def schedule_browser_search(self, *_):
        if getattr(self, "browser_search_timer", None): GLib.source_remove(self.browser_search_timer)
        self.browser_search_timer = None
        if getattr(self, "responsive_portrait", False) and self.roon_views.get_visible_child_name() == "search":
            if len(self.browser_search_entry.get_text().strip()) >= 2:
                self.browser_search_timer = GLib.timeout_add(600, self.run_scheduled_browser_search)
            else:
                while child := self.browser_list.get_first_child(): self.browser_list.remove(child)

    def run_scheduled_browser_search(self):
        self.browser_search_timer = None
        if self.roon_views.get_visible_child_name() == "search": self.submit_browser_search()
        return False

    def commit_browser_scrub(self, letter):
        self.browser_scrub_timer = None; self.request_browser("jump", letter=letter); return False

    def sync_browser_scrubber(self, item=None):
        if not self.browser_state or not getattr(self, "browser_scrubber_active", False) or getattr(self, "browser_scrub_dragging", False) or getattr(self, "browser_scrub_timer", None) or getattr(self, "browser_pending_request", None): return
        if item is None:
            items = [entry for entry in (self.browser_state.get("items") or []) if not entry.get("action") and entry.get("title")]
            item = items[0] if items else None
            value = self.browser_scroll.get_vadjustment().get_value()
            for card, entry in getattr(self, "browser_cards", []):
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() > value:
                    item = entry; break
        field = "subtitle" if self.browser_state.get("sort_order") == "artist" else "title"
        title = str((item or {}).get(field) or "A").strip()
        if title.lower().startswith("the "): title = title[4:]
        first = unicodedata.normalize("NFKD", title)[:1].upper(); value = ord(first) - 65 if "A" <= first <= "Z" else 0
        self.browser_scrub_sync = True; self.browser_scrub_scale.set_value(value); self.browser_scrub_sync = False; self.position_browser_scrub_letter(chr(65 + value), value)

    def show_browser_loading(self):
        """Leave the old page immediately and show the loading dots while Roon builds the next one."""
        self.browser_scroll.set_visible(True)
        self.browser_artist_scroll.set_visible(False); self.browser_search_columns.set_visible(False)
        self.browser_scrubber.set_visible(False); self.browser_message.set_visible(False)
        while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
        self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
        self.browser_list.append(self.loading_notice())

    def open_browser_item(self, _button, item_key):
        if item_key:
            self.browser_action_anchor = _button
            if getattr(_button, "opens_page", False) and not self.browser_loading:
                state = self.browser_state or {}
                self.show_browser_loading()
            if getattr(self, "responsive_portrait", False) and self.roon_views.get_visible_child_name() == "search": self.set_roon_view("browse")
            self.request_browser("open", item_key=item_key)

    def browser_item_icon(self, title):
        value = (title or "").lower()
        if "library" in value: return "folder-music-symbolic"
        if "playlist" in value: return "view-list-symbolic"
        if "genre" in value: return "audio-x-generic-symbolic"
        if "artist" in value: return "avatar-default-symbolic"
        if "album" in value: return "media-optical-symbolic"
        if "track" in value or "radio" in value: return "audio-x-generic-symbolic"
        return "folder-symbolic"

    def browser_tile_symbol(self, title, kind):
        value = (title or "").lower()
        if kind == "playlists": return "playlist"
        if value.startswith("shuffle"): return "shuffle"
        if value in {"artists", "genre artists"}: return "artist"
        if value in {"albums", "genre albums"}: return "album"
        if "jazz" in value: return "jazz"
        if "classical" in value: return "classical"
        if "electronic" in value: return "electronic"
        if "pop" in value or "rock" in value: return "rock"
        if "stage" in value or "screen" in value or "soundtrack" in value: return "stage"
        if "avant" in value: return "avant"
        if "folk" in value: return "folk"
        if "country" in value: return "country"
        if "blues" in value: return "blues"
        if "rap" in value or "hip-hop" in value: return "rap"
        if "r&b" in value or "rhythm" in value: return "rb"
        if "reggae" in value: return "reggae"
        if "latin" in value: return "latin"
        if "world" in value or "international" in value: return "world"
        if "easy listening" in value: return "easy"
        if "vocal" in value: return "vocal"
        if "new age" in value or "ambient" in value: return "ambient"
        if "holiday" in value: return "holiday"
        if "children" in value: return "children"
        if "comedy" in value: return "comedy"
        if "religious" in value or "gospel" in value: return "religious"
        return "music"

    def browser_action_icon(self, title):
        value = (title or "").lower()
        if "add next" in value: return "list-add-symbolic"
        if "queue" in value: return "view-list-symbolic"
        if "shuffle" in value: return "media-playlist-shuffle-symbolic"
        if "from here" in value: return "go-jump-symbolic"
        return "play"

    def browser_svg_icon(self, name, size=54):
        icon = FamilyIcon(name, size, stroke_width=.7)
        icon.set_size_request(size, size)
        icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("browser-tile-icon")
        return icon

    def browser_menu_card(self, item, compact=False):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); content.set_halign(Gtk.Align.CENTER); content.set_valign(Gtk.Align.CENTER)
        portrait = getattr(self, "responsive_portrait", False)
        width = getattr(self, "viewport_width", 800)
        columns = 4 if width >= 1000 else 2
        side = max(64, (width - 60 - (columns - 1) * 12) // columns)
        icon = FamilyIcon(self.browser_item_icon(item.get("title")), round(side * .48) if portrait else 58 if compact else 78, stroke_width=.8); icon.add_css_class("browser-home-icon"); content.append(icon)
        title = self.label(item.get("title") or "Roon", "browser-home-title", .5); title.set_wrap(True); title.set_justify(Gtk.Justification.CENTER); content.append(title)
        button = Gtk.Button(); button.add_css_class("browser-home-card");
        if portrait: button.set_size_request(side, side)
        if compact: button.add_css_class("compact")
        button.set_hexpand(not portrait); button.set_vexpand(not portrait); button.set_child(content); button.set_sensitive(bool(item.get("item_key"))); button.connect("clicked", self.open_browser_item, item.get("item_key")); return button

    def set_browser_placeholder(self, picture, artist=False):
        name = "missing-artist.svg" if artist else "missing-album.svg"
        # Gtk.Picture rasterises SVGs at their intrinsic size before scaling.
        # Keep thumbnails small, but never magnify a 256px disc on Now Playing.
        if not artist and picture is getattr(self, "artwork", None):
            name = "missing-album-large.svg"
        picture.set_filename(str(Path(__file__).with_name("icons") / name))

    def browser_cover_card(self, item, show_labels, tile_kind=None):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); content.set_halign(Gtk.Align.FILL)
        size = getattr(self, "browser_tile_size", 172)
        original_tile = (not getattr(self, "responsive_portrait", False)
                         and getattr(self, "viewport_width", 800) <= 820
                         and getattr(self, "viewport_height", 480) <= 500)
        separated_label_tile = original_tile or (
            not getattr(self, "responsive_portrait", False)
            and getattr(self, "system_data", {}).get("display_profile") in {"touch2-7", "touch2-5-7"})
        artwork = Gtk.Overlay(); picture = Gtk.Picture(); picture.add_css_class("browser-cover-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); artwork.set_child(picture)
        if not tile_kind:
            self.set_browser_placeholder(picture, artist=(self.browser_state or {}).get("section") == "artists")
        # An AspectFrame only requests a minimum; loaded textures can grow it.
        # Bound artwork and text so a real cover cannot widen the GTK window.
        square = Gtk.ScrolledWindow(); square.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); square.set_propagate_natural_width(False); square.set_propagate_natural_height(False); square.set_min_content_width(size); square.set_max_content_width(size); square.set_min_content_height(size); square.set_max_content_height(size); square.set_size_request(size, size); square.set_halign(Gtk.Align.CENTER); square.set_child(artwork); content.append(square)
        key = item.get("image_key"); self.browser_artwork_keys.append(key)
        if key:
            self.browser_pictures.setdefault(key, []).append(picture)
            texture = self.queue_thumbnail_cache.get(key)
            if texture: picture.set_paintable(texture)
        elif tile_kind:
            gen2_genre = tile_kind == "genres" and self.window.has_css_class("touch2-7-landscape")
            icon_scale = .56 if gen2_genre else .58 if tile_kind == "playlists" else .65
            icon = self.browser_svg_icon(self.browser_tile_symbol(item.get("title"), tile_kind), size=max(54, round(size * icon_scale))); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER); icon.set_margin_bottom(round(size * (.26 if gen2_genre else .18 if separated_label_tile else .12))); artwork.add_overlay(icon)
        if show_labels:
            title = self.label(item.get("title") or "Untitled", "browser-cover-title", .5); title.set_max_width_chars(22); title.set_ellipsize(Pango.EllipsizeMode.END); content.append(title)
            if tile_kind in {"genres", "playlists"}:
                content.remove(title); title.add_css_class("tile"); title.set_wrap(True); title.set_lines(2); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_xalign(.5); title.set_justify(Gtk.Justification.CENTER); title.set_halign(Gtk.Align.FILL); title.set_valign(Gtk.Align.END); artwork.add_overlay(title)
                title.set_margin_bottom(6 if separated_label_tile else max(12, round(size * .075)))
            if item.get("subtitle") and not tile_kind:
                subtitle = self.label(item.get("subtitle"), "browser-cover-subtitle", .5); subtitle.set_max_width_chars(22); subtitle.set_ellipsize(Pango.EllipsizeMode.END); content.append(subtitle)
        caption_height = 0 if tile_kind in {"genres", "playlists"} else 96 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 60
        shell = Gtk.ScrolledWindow(); shell.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); shell.set_propagate_natural_width(False); shell.set_propagate_natural_height(False); shell.set_min_content_width(size); shell.set_max_content_width(size); shell.set_min_content_height(size + (caption_height if show_labels else 0)); shell.set_max_content_height(size + (caption_height if show_labels else 0)); shell.set_child(content)
        button = Gtk.Button(); button.add_css_class("browser-cover-card")
        if tile_kind: button.add_css_class(f"{tile_kind[:-1]}-tile")
        button.opens_page = True
        button.set_child(shell); button.set_sensitive(bool(item.get("item_key"))); button.connect("clicked", self.open_browser_item, item.get("item_key")); return button

    def album_header(self, profile, items):
        width = getattr(self, "viewport_width", 800)
        narrow_portrait = bool(getattr(self, "responsive_portrait", False) and width < 600)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if narrow_portrait else Gtk.Orientation.HORIZONTAL, spacing=16 if narrow_portrait else 24); header.add_css_class("album-profile")
        original_view = not getattr(self, "responsive_portrait", False) and width <= 820 and getattr(self, "viewport_height", 480) <= 500
        # Larger text on the 800x480 panel leaves little height, so the cover stays a modest square there.
        size = (min(190, round(width * .24)) if original_view else min(380, round(width * .32))) if width >= 1000 or original_view else min(240, round(width * .3))
        picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
        self.set_browser_placeholder(picture)
        slot = Gtk.ScrolledWindow(); slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        slot.set_propagate_natural_width(False); slot.set_propagate_natural_height(False)
        slot.set_min_content_width(size); slot.set_max_content_width(size)
        slot.set_min_content_height(size); slot.set_max_content_height(size)
        slot.set_size_request(size, size); slot.set_valign(Gtk.Align.START); slot.set_hexpand(False); slot.set_child(picture); header.append(slot)
        if key := profile.get("image_key"): self.load_preview_artwork(picture, key)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); copy.set_hexpand(True); copy.set_valign(Gtk.Align.START if width <= 820 and getattr(self, "viewport_height", 480) <= 500 else Gtk.Align.CENTER)
        title = self.label(profile.get("name") or "Album", "artist-name"); title.set_wrap(True); title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); title.set_max_width_chars(28); copy.append(title)
        if artist := profile.get("artist"):
            link = self.button(artist, lambda *_: self.request_browser("artist", name=artist), "album-artist")
            link.get_child().set_wrap(True); link.get_child().set_wrap_mode(Pango.WrapMode.WORD_CHAR); link.get_child().set_max_width_chars(23)
            link.set_halign(Gtk.Align.START); link.set_tooltip_text("View artist"); copy.append(link)
        if play := next((item for item in items if item.get("action") and item.get("title", "").lower() == "play album"), None):
            split = Gtk.Box(spacing=0); split.add_css_class("album-play-split"); split.set_halign(Gtk.Align.START)
            button = self.labelled_icon_button("play", "Play Album", lambda *_: self.open_browser_item(None, play.get("item_key")), "artist-play primary-play")
            menu = self.icon_button("chevron-play", lambda arrow, key=play.get("item_key"): self.open_album_play_menu(arrow, key), "album-play-menu")
            # The chevron fills under half of its icon box, so a 34px icon drew a ~16px arrow. Use a larger
            # icon (the button's own min-width and padding give a wide touch area).
            vw, vh = getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)
            menu.set_child(FamilyIcon("chevron-play", 24 if min(vw, vh) >= 1000 else 14 if vw <= 820 and vh <= 500 else 16))
            menu.set_tooltip_text("More album play options"); split.append(button); split.append(menu)
            if narrow_portrait:
                play_slot = Gtk.ScrolledWindow(); play_slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
                play_slot.set_propagate_natural_width(False); play_slot.set_propagate_natural_height(True)
                play_width = max(150, width - 64)
                play_slot.set_min_content_width(play_width); play_slot.set_max_content_width(play_width); play_slot.set_size_request(play_width, -1)
                play_slot.set_child(split); copy.append(play_slot)
            else: copy.append(split)
        if review := profile.get("review"):
            summary = self.label(review[:1800], "queue-meta"); summary.set_wrap(True); summary.set_lines(2 if original_view else 6); summary.set_ellipsize(Pango.EllipsizeMode.END); summary.set_max_width_chars(50); copy.append(summary)
        else:
            summary_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); copy.append(summary_slot)
            self.load_album_notes(profile, summary_slot)
        header.append(copy)
        return header

    def open_album_play_menu(self, anchor, item_key):
        if item_key:
            self.browser_action_anchor = anchor
            self.request_browser("open", item_key=item_key, menu_only=True)

    def load_album_notes(self, profile, slot):
        album, artist = profile.get("name"), profile.get("artist")
        if not album or not artist: return
        status = self.label("Loading album summary…", "queue-meta"); status.set_wrap(True); slot.append(status)
        def load():
            query = urllib.parse.urlencode({"album": album, "artist": artist})
            notes = get_json(ROON + "/api/album-notes?" + query, timeout=30) or {}
            def apply():
                # Navigation may have replaced this album while lookup ran.
                if slot.get_root() is None: return False
                while child := slot.get_first_child(): slot.remove(child)
                summary = self.label(notes.get("writeup") or "No album summary is available.", "queue-meta")
                summary.set_wrap(True); summary.set_lines(2 if original_view else 6); summary.set_ellipsize(Pango.EllipsizeMode.END); summary.set_max_width_chars(50)
                slot.append(summary)
                return False
            GLib.idle_add(apply)
        threading.Thread(target=load, daemon=True).start()

    @staticmethod
    def genre_action_item(item):
        """Shuffle Genre, Genre Artists and Genre Albums act on the genre itself; everything else is a sub-genre."""
        title = (item.get("title") or "").strip().lower()
        return bool(item.get("action") or (not item.get("image_key") and (title in {"artists", "albums", "genre artists", "genre albums"} or title.startswith("shuffle"))))

    def prepare_genre_columns(self, data, layout, items):
        """Wide genre pages: actions for this genre on the left, its sub-genres on the right. Returns the right-hand items."""
        columns = False
        try:
            wide = not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) >= 1000
            plain_list = (layout == "list" and data.get("section") == "genres" and not data.get("section_root")
                          and not data.get("artist_profile") and not data.get("album_profile") and not data.get("surprise_preview"))
            actions = [item for item in items if item.get("hint") != "header" and self.genre_action_item(item)]
            columns = bool(plain_list and wide and actions)
            while child := self.browser_trail_list.get_first_child(): self.browser_trail_list.remove(child)
            self.browser_trail_scroll.set_visible(columns)
            if not columns: return items
            heading = self.label(data.get("title") or "", "genre-heading"); heading.set_ellipsize(Pango.EllipsizeMode.END); self.browser_trail_list.append(heading)
            for item in actions:
                copy = Gtk.Box(spacing=18); copy.set_valign(Gtk.Align.CENTER)
                frame = Gtk.CenterBox(); frame.add_css_class("genre-action-icon"); frame.set_size_request(84, 84); frame.set_valign(Gtk.Align.CENTER)
                frame.set_center_widget(self.browser_svg_icon(self.browser_tile_symbol(item.get("title"), "genres"), 62)); copy.append(frame)
                title = self.label(item.get("title") or "", "genre-action-title"); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_xalign(0); title.set_hexpand(True); copy.append(title)
                row = Gtk.Button(); row.add_css_class("genre-action-row"); row.set_child(copy); row.set_focusable(False)
                row.set_sensitive(bool(item.get("item_key"))); row.browse_item_key = item.get("item_key")
                if item.get("action"): row.add_css_class("browser-action")
                else: row.opens_page = True
                row.connect("clicked", self.open_browser_item, item.get("item_key")); self.browser_trail_list.append(row)
            rest = [item for item in items if item.get("hint") == "header" or not self.genre_action_item(item)]
            self.browser_list.append(self.label("SUB-GENRES", "browser-section"))
            if not [item for item in rest if item.get("hint") != "header"]:
                self.browser_list.append(self.label("No sub-genres", "queue-empty", 0))
            return rest
        except Exception as error:
            print("RoonDeck genre columns skipped: " + type(error).__name__, flush=True)
            self.browser_trail_scroll.set_visible(False)
            return items

    def render_browser(self, data):
        self.browser_list.cancel_spring()
        if data.get("action_menu"):
            self.browser_state = data; self.browser_loading = False; self.browser_rendering = False
            anchor = getattr(self, "browser_action_anchor", None) or self.browser_body
            popover = Gtk.Popover(); popover.add_css_class("track-menu"); popover.set_parent(anchor); popover.set_autohide(True)
            popover.set_has_arrow(False); popover.set_position(Gtk.PositionType.RIGHT)
            popover.set_valign(Gtk.Align.START)
            rect = Gdk.Rectangle(); rect.x = max(1, anchor.get_width()) + 8; rect.y = 0; rect.width = 1; rect.height = 1
            tap = getattr(self, "last_tap_point", None)
            if tap and getattr(self, "window", None) is not None:
                # Open beside the finger rather than at the far edge of a full-width row.
                try:
                    point = self.window.compute_point(anchor, Graphene.Point().init(tap[0], tap[1]))
                    if point is not None:
                        rect.x = round(max(1, min(anchor.get_width() - 1, point.x))) + 12
                        rect.y = round(max(0, min(anchor.get_height() - 1, point.y)))
                except (AttributeError, TypeError, GLib.Error): pass
            popover.set_pointing_to(rect)
            self.browser_action_popover = popover
            choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6 if getattr(self, "compact_detail", False) else 10)
            selected = {"value": False}
            self.browser_action_selected = selected
            discovery_actions = bool(data.get("discovery_track_actions"))
            def choose(_button, key):
                selected["value"] = True; popover.popdown()
                if discovery_actions: self.request_discovery_track_action(key)
                else: self.request_browser("open", item_key=key)
            for item in data.get("items", []):
                if item.get("action"):
                    final_play = item.get("title", "").strip().casefold() in {"play now", "play album", "play artist", "play artist radio"}
                    choice = self.labelled_icon_button(self.browser_action_icon(item["title"]), item["title"], lambda button, key=item.get("item_key"): choose(button, key), "track-menu-action primary-play" if final_play else "track-menu-action"); choice.set_focusable(False); choices.append(choice)
            def closed(*_):
                self.browser_action_popover = None
                popover.unparent()
                if not selected["value"] and not discovery_actions: self.request_browser("back")
            popover.connect("closed", closed)
            popover.connect("map", lambda widget: GLib.idle_add(self.hide_native_cursor, widget))
            popover.set_child(choices); self.hide_widget_cursor(popover); popover.popup(); self.hide_native_cursor(popover)
            return False
        self.browser_rendering = True; self.browser_loading = True; self.browser_state = data; self.browser_back.set_visible(bool(data.get("can_back")) and not data.get("surprise_preview")); self.browser_back.set_sensitive(bool(data.get("can_back")))
        self.browser_scrubber_active = bool(data.get("alpha_scrub")) and not data.get("artist_profile") and data.get("layout") in {"covers", "tiles"}
        self.browser_scrubber.set_visible(self.browser_scrubber_active)
        # The page's 28px right margin and the list's 8px padding are redundant next to the 7-inch rail.
        if (self.browser_scrubber_active and not getattr(self, "responsive_portrait", False) and 1200 <= getattr(self, "viewport_width", 800) < 1500
                and 650 <= (getattr(self, "viewport_height", None) or 720) < 850): self.browser_scroll.add_css_class("browser-scroll-fill")
        else: self.browser_scroll.remove_css_class("browser-scroll-fill")
        if hasattr(self, "browser_sort"):
            self.browser_sort.set_visible(data.get("section") == "albums" and bool(data.get("section_root")) and getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) >= 1000)
            self.browser_sort.set_sensitive(True)
            self.browser_sort_order = data.get("sort_order", "title")
            self.browser_sort.get_child().set_text({"title":"Sort: Title, A to Z", "reverse":"Sort: Title, Z to A", "artist":"Sort: Artist, A to Z"}.get(self.browser_sort_order, "Sort: Title, A to Z"))
        active_section = "surprise" if data.get("surprise_preview") else (data.get("section") or "albums")
        original_view = not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
        self.browser_content.set_margin_top(0 if data.get("surprise_preview") and original_view else 16)
        self.browser_scroll.set_margin_bottom(0 if data.get("surprise_preview") and original_view else self.browser_scroll_bottom_margin(original_view))
        from_discover = self.discovery_active and self.discovery_browser_origin
        self.browser_sidebar.set_visible(not data.get("surprise_preview") and not from_discover)
        self.browser_discovery_sidebar.set_visible(from_discover)
        if from_discover: self.sync_discovery_sidebar(self.browser_discovery_sidebar, from_browser=True)
        self.browser_surprise_button.set_visible(False); self.browser_surprise_button.set_label("SURPRISE!")
        self.browser_surprise_button.get_child().set_xalign(0)
        if active_section == "surprise": self.browser_surprise_button.add_css_class("active")
        else: self.browser_surprise_button.remove_css_class("active")
        if active_section == "search": self.browser_search_button.add_css_class("active")
        else: self.browser_search_button.remove_css_class("active")
        for section, button in self.browser_section_buttons.items():
            if section == active_section: button.add_css_class("active")
            else: button.remove_css_class("active")
        message = data.get("message") or (data.get("error") if isinstance(data.get("error"), str) else "") or ""; self.browser_message.set_text(message); self.browser_message.set_visible(bool(message))
        self.browser_pictures = {}; self.browser_artwork_keys = []; self.browser_cards = []; self.artist_hero_keys = set()
        while child := self.browser_list.get_first_child(): self.browser_list.remove(child)
        artist_play = next((item for item in data.get("items", []) if item.get("action") and item.get("title", "").strip().lower() in {"play artist", "play artist radio"}), None) if data.get("artist_profile") else None
        self.render_artist_profile(data.get("artist_profile"), artist_play)
        items = data.get("items") or []
        # Merged artist catalogues also carry search_routes so every album can
        # reopen its originating My Catalog or TIDAL session.  They are still
        # artist album lists, not grouped search results.  Treating them as a
        # grouped search hides browser_list on seven-inch landscape displays.
        grouped_results = bool(data.get("search_routes")) and not data.get("artist_profile")
        grouped_search = grouped_results and not getattr(self, "responsive_portrait", False)
        if grouped_results and getattr(self, "responsive_portrait", False) and hasattr(self, "search_results_scroll"):
            self.search_results_scroll.get_vadjustment().set_value(0)
        self.browser_list.set_spacing(12 if data.get("artist_profile") and getattr(self, "responsive_portrait", False) else 2)
        self.browser_list.set_orientation(Gtk.Orientation.VERTICAL)
        while child := self.browser_search_columns.get_first_child(): self.browser_search_columns.remove(child)
        self.browser_search_columns.set_visible(grouped_search)
        self.browser_scroll.set_visible(not grouped_search)
        self.browser_list.set_homogeneous(False)
        self.browser_list.set_vexpand(grouped_search)
        self.browser_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER if grouped_search else Gtk.PolicyType.AUTOMATIC)
        album_profile = data.get("album_profile")
        if album_profile:
            self.browser_list.append(self.album_header(album_profile, items))
            items = [item for item in items if not (item.get("action") and item.get("title", "").lower() == "play album")]
        if data.get("artist_profile"):
            heading = self.label("ARTIST ALBUMS", "browser-section"); heading.add_css_class("artist-albums-heading"); self.browser_list.append(heading)
            items = [item for item in items if item is not artist_play]
        self.browser_list.set_valign(Gtk.Align.START if data.get("layout") == "list" else Gtk.Align.FILL)
        browser_content = self.browser_artist_scroll.get_parent()
        browser_content.set_homogeneous(False)
        browser_content.set_orientation(Gtk.Orientation.VERTICAL if data.get("artist_profile") and (getattr(self, "responsive_portrait", False) or original_view) else Gtk.Orientation.HORIZONTAL)
        if not items:
            self.browser_list.append(self.label(message or ("Roon Browse is unavailable." if data.get("status") == "unavailable" else "Nothing is available here."), "queue-empty", .5))
        layout = "list" if data.get("artist_profile") else (data.get("layout") or "list")
        items = self.prepare_genre_columns(data, layout, items)
        if items and data.get("surprise_preview"):
            album = items[0]
            monitor = Gdk.Display.get_default().get_monitors().get_item(0)
            screen_width = monitor.get_geometry().width if monitor else 800
            portrait = getattr(self, "responsive_portrait", False)
            large_display = min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000
            compact_landscape = not portrait and getattr(self, "viewport_width", 800) < 1000
            original = compact_landscape and screen_width <= 820
            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0 if original else 12); preview.set_halign(Gtk.Align.CENTER); preview.set_hexpand(True)
            preview.set_margin_top(round(getattr(self, "viewport_height", 1280) * .05) if portrait else 18 if original else 12)
            size = max(100, min(760 if large_display else 480, screen_width - (96 if portrait else 350 if original else 360 if compact_landscape else 400), self.browser_scroll.get_allocated_height() - (640 if large_display and portrait else 500 if portrait else 92 if original else 90 if compact_landscape else 135)))
            picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
            square = Gtk.ScrolledWindow(); square.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); square.set_propagate_natural_width(False); square.set_propagate_natural_height(False); square.set_min_content_width(size); square.set_max_content_width(size); square.set_min_content_height(size); square.set_max_content_height(size); square.set_size_request(size, size); square.set_halign(Gtk.Align.CENTER); square.set_child(picture)
            stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if portrait else Gtk.Orientation.HORIZONTAL, spacing=38 if portrait else 40); stage.set_halign(Gtk.Align.CENTER); stage.set_valign(Gtk.Align.CENTER)
            play_controls = None
            for caption, icon, action in (("Surprise Again" if portrait else "Surprise Me", "view-refresh-symbolic", "surprise"), ("Play Now", "media-playback-start-symbolic", "surprise_play")):
                controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10 if original else 16); controls.set_size_request(104 if original else 120, -1); controls.set_valign(Gtk.Align.CENTER); controls.set_halign(Gtk.Align.CENTER)
                button = self.icon_button(icon, lambda _button, value=action: self.request_browser(value), "surprise-action primary-play" if action == "surprise_play" else "surprise-action"); button.set_tooltip_text(caption); button.set_halign(Gtk.Align.CENTER)
                controls.append(button); controls.append(self.label(caption, "surprise-caption", .5))
                if portrait and action == "surprise_play": play_controls = controls
                else: stage.append(controls)
                if action == "surprise": stage.append(square)
            preview.append(stage)
            key = album.get("image_key"); self.browser_artwork_keys.append(key)
            if key:
                # Large previews must not share the 256px scrolling-thumbnail cache.
                self.load_preview_artwork(picture, key)
            else: square.set_child(self.browser_svg_icon("music"))
            title = self.label(album.get("title") or "Untitled", "surprise-title", .5); title.set_wrap(True); title.set_lines(2); title.set_max_width_chars(40); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_justify(Gtk.Justification.CENTER); title.set_margin_top(14 if original else 0); preview.append(title)
            artist = self.label(album.get("subtitle") or "", "surprise-artist", .5); artist.set_ellipsize(Pango.EllipsizeMode.END); artist.set_max_width_chars(40); preview.append(artist)
            if play_controls:
                play_controls.set_margin_top(round(getattr(self, "viewport_height", 1280) * .072)); preview.append(play_controls)
            self.browser_list.append(preview)
        elif items and layout in {"home", "menu"} and (getattr(self, "responsive_portrait", False) or data.get("section") != "genres"):
            grid = Gtk.Grid(column_spacing=12, row_spacing=12); grid.add_css_class("browser-home-grid"); grid.set_column_homogeneous(True); grid.set_row_homogeneous(True); columns = 4 if not getattr(self, "responsive_portrait", False) or getattr(self, "viewport_width", 800) >= 1000 else 2
            if getattr(self, "responsive_portrait", False): grid.set_valign(Gtk.Align.START); grid.set_vexpand(False)
            for index, item in enumerate(item for item in items if item.get("hint") != "header"): grid.attach(self.browser_menu_card(item, layout == "menu"), index % columns, index // columns, 1, 1)
            self.browser_list.append(grid)
        elif items and (layout in {"covers", "tiles"} or (layout in {"home", "menu"} and not getattr(self, "responsive_portrait", False))):
            portrait = getattr(self, "responsive_portrait", False)
            menu_tiles = layout in {"home", "menu"}
            grid = Gtk.Grid(column_spacing=24, row_spacing=24); grid.add_css_class("browser-cover-grid"); grid.set_column_homogeneous(False); grid.set_halign(Gtk.Align.START); grid.set_hexpand(False); columns = 5 if layout == "tiles" and active_section == "genres" else 4
            profile = (getattr(self, "system_data", {}) or {}).get("display_profile")
            larger_seven = (not portrait and profile in {"touch2-7", "touch2-5-7"}
                            and (getattr(self, "settings_data", {}) or {}).get("interface_size") == "larger")
            if larger_seven:
                grid.set_column_spacing(23)
            if (not portrait and 1200 <= getattr(self, "viewport_width", 800) < 1500
                    and 650 <= (getattr(self, "viewport_height", None) or 720) < 850):
                # Seven-inch Gen 2: tighter columns let the covers grow; a looser row gap
                # puts the second row's bottom near the Back button's.
                grid.set_column_spacing(12); grid.set_row_spacing(22 if (getattr(self, "settings_data", {}) or {}).get("interface_size") == "larger" else 26)
            original = not portrait and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
            if original:
                grid.set_column_spacing(12); grid.set_row_spacing(12)
                grid.set_halign(Gtk.Align.START); grid.set_hexpand(False)
            if portrait:
                grid.set_column_spacing(30)
                grid.set_row_spacing(30)
                grid.set_halign(Gtk.Align.START); grid.set_hexpand(False)
            columns, self.browser_tile_size = self.browser_grid_metrics(
                menu_tiles or (layout == "tiles" and active_section in {"genres", "playlists"}),
                active_section == "artists",
            )
            tile_kind = "genres" if menu_tiles else (active_section if layout == "tiles" else None)
            for index, item in enumerate(item for item in items if item.get("hint") != "header"):
                card = self.browser_cover_card(item, bool(data.get("show_labels")) or menu_tiles, tile_kind); self.browser_cards.append((card, item)); grid.attach(card, index % columns, index // columns, 1, 1)
            self.browser_list.append(grid)
        else:
            columns = []
            if grouped_search:
                for _ in range(2):
                    column = ElasticVerticalTrack(spacing=2); column.add_css_class("search-column")
                    scroll = Gtk.ScrolledWindow(); scroll.add_css_class("queue-scroll"); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_kinetic_scrolling(True); scroll.set_hexpand(True); scroll.set_vexpand(True); scroll.set_propagate_natural_width(False); scroll.set_propagate_natural_height(False); scroll.set_min_content_width(1); scroll.set_size_request(1, 1); scroll.set_child(column); scroll.get_vadjustment().connect("value-changed", lambda *_: self.load_visible_browser_artwork()); self.browser_search_columns.append(scroll); columns.append(column)
                    column.connect_scroll(scroll)
            else: self.browser_list.set_homogeneous(False)
            group_index = -1; group_count = 0; group_title = ""; target = self.browser_list
            for item in items:
                if item.get("hint") == "header":
                    group_index += 1; group_count = 0; group_title = item.get("title", "")
                    target = columns[1 if item.get("title") in {"ALBUMS", "TRACKS"} else 0] if columns else self.browser_list
                    target.append(self.label(item.get("title") or "", "browser-section")); continue
                if grouped_results and not item.get("title", "").startswith("View all "):
                    group_count += 1
                    if group_count > (3 if getattr(self, "responsive_portrait", False) and group_title == "ARTISTS" else 4): continue
                if item.get("action") and item.get("title", "").strip().lower() == "play playlist":
                    play_playlist = self.labelled_icon_button("play", "Play Playlist", lambda *_args, key=item.get("item_key"): self.open_browser_item(None, key), "artist-play primary-play browser-primary-action")
                    play_playlist.set_sensitive(bool(item.get("item_key"))); play_playlist.set_halign(Gtk.Align.START); target.append(play_playlist); continue
                row = Gtk.Box(spacing=14); row.set_hexpand(True)
                key = item.get("image_key")
                row_title = (item.get("title") or "").strip().lower()
                # Genre lists: Shuffle Genre / Artists / Albums act on the genre itself, so they get the larger
                # key-line tile icons; the sub-genres below them open another list and keep the plain thumbnail.
                genre_shortcut = (data.get("section") == "genres" and not key and (row_title in {"artists", "albums", "genre artists", "genre albums"} or row_title.startswith("shuffle")))
                if item.get("action") or genre_shortcut:
                    action_icon = self.browser_svg_icon(self.browser_tile_symbol(item.get("title"), "genres"), 62) if genre_shortcut else FamilyIcon(self.browser_action_icon(item.get("title")), 42)
                    action_frame = Gtk.CenterBox(); action_frame.add_css_class("browser-action-icon"); action_frame.set_size_request(84, 84); action_frame.set_hexpand(False); action_frame.set_halign(Gtk.Align.START); action_frame.set_valign(Gtk.Align.CENTER); action_frame.set_center_widget(action_icon); row.append(action_frame)
                elif album_profile:
                    action_icon = FamilyIcon("play", 60 if self.window.has_css_class("large-display") else 40)
                    action_frame = Gtk.CenterBox(); action_frame.add_css_class("browser-action-icon"); action_frame.set_size_request(84, 84); action_frame.set_valign(Gtk.Align.CENTER); action_frame.set_center_widget(action_icon); row.append(action_frame)
                else:
                    picture = Gtk.Picture(); picture.add_css_class("queue-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER)
                    self.set_browser_placeholder(picture, item.get("result_type") == "artists")
                    # A fixed viewport prevents the texture's natural dimensions
                    # or the number of rows from enlarging album thumbnails.
                    artist_albums = bool(data.get("artist_profile"))
                    original_artist_albums = artist_albums and not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500
                    seven_artist_albums = artist_albums and not getattr(self, "responsive_portrait", False) and getattr(self, "viewport_height", 480) <= 720
                    thumb_size = 84 if original_artist_albums else 112 if seven_artist_albums else (210 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 132) if artist_albums else (116 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 84)
                    art_slot = Gtk.ScrolledWindow(); art_slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); art_slot.set_propagate_natural_width(False); art_slot.set_propagate_natural_height(False); art_slot.set_min_content_width(thumb_size); art_slot.set_max_content_width(thumb_size); art_slot.set_min_content_height(thumb_size); art_slot.set_max_content_height(thumb_size); art_slot.set_size_request(thumb_size, thumb_size); art_slot.set_halign(Gtk.Align.START); art_slot.set_valign(Gtk.Align.CENTER); art_slot.set_child(picture); row.append(art_slot)
                    self.browser_artwork_keys.append(key)
                    if key:
                        self.browser_pictures.setdefault(key, []).append(picture)
                        texture = self.queue_thumbnail_cache.get(key)
                        if texture: picture.set_paintable(texture)
                copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); copy.set_valign(Gtk.Align.CENTER); copy.set_hexpand(True)
                title = self.label(item.get("title") or "Untitled", "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); copy.append(title)
                if data.get("artist_profile"): title.add_css_class("artist-album-title")
                if grouped_results and getattr(self, "responsive_portrait", False):
                    title.set_wrap(True); title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); title.set_lines(2)
                subtitle = self.label(item.get("subtitle") or "Roon", "queue-meta"); subtitle.set_ellipsize(Pango.EllipsizeMode.END); copy.append(subtitle); row.append(copy)
                row.append(self.label(item.get("duration") or "", "browser-arrow", 1))
                button = Gtk.Button(); button.add_css_class("browser-row"); button.set_child(row); button.set_sensitive(bool(item.get("item_key")))
                button.browse_item_key = item.get("item_key")
                button.set_vexpand(False); button.set_valign(Gtk.Align.START)
                if item.get("action"): button.add_css_class("browser-action")
                else: button.opens_page = not album_profile
                button.connect("clicked", self.open_browser_item, item.get("item_key")); target.append(button)
        GLib.timeout_add(100, self.load_visible_browser_artwork)
        GLib.timeout_add(60, self.finish_browser_render)
        return False

    def finish_browser_render(self):
        # Restore the old view before dispatching the next section/letter.
        # Otherwise an older restore callback can move a newer page's cursor.
        if self.browser_scroll_restore is not None: self.restore_browser_scroll()
        self.browser_rendering = False; self.browser_loading = False; self.sync_browser_scrubber()
        GLib.timeout_add(120, self.maybe_load_more_browser)
        pending = getattr(self, "browser_pending_request", None)
        if pending:
            self.browser_pending_request = None
            self.request_browser(pending[0], **pending[1])
        return False

    def restore_browser_scroll(self):
        self.browser_rendering = True
        value = self.browser_scroll_restore; self.browser_scroll_restore = None
        previous_height = getattr(self, "browser_previous_height", None)
        if previous_height is not None:
            value = (value or 0) + self.browser_scroll.get_vadjustment().get_upper() - previous_height
            self.browser_previous_height = None
        if value is not None: self.browser_scroll.get_vadjustment().set_value(value)
        self.browser_rendering = False
        self.sync_browser_scrubber()
        return False

    def schedule_scroll_artwork(self, name, callback):
        # Scrolling remains native; bound visibility scans/image jobs instead
        # of walking every card on every touch/kinetic animation frame.
        attribute = "scroll_artwork_" + name
        if getattr(self, attribute, None): return
        def load():
            setattr(self, attribute, None)
            callback()
            return False
        setattr(self, attribute, GLib.timeout_add(80, load))

    def browser_scrolled(self, *_):
        if self.browser_rendering or self.browser_loading or self.browser_scroll_restore is not None or getattr(self, "browser_scrub_timer", None): return
        self.schedule_scroll_artwork("browser", self.load_visible_browser_artwork)
        self.schedule_scroll_artwork("scrubber", self.update_scrolled_scrubber)
        if not self.browser_rendering: self.maybe_load_more_browser()

    def update_scrolled_scrubber(self):
        if self.browser_state and getattr(self, "browser_scrubber_active", False):
            value = self.browser_scroll.get_vadjustment().get_value()
            for card, item in getattr(self, "browser_cards", []):
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() > value:
                    self.sync_browser_scrubber(item); break
            if value < 40 and self.browser_state.get("offset", 0) > 0: self.request_browser("previous")
        return False

    def browser_previous_scroll(self, _controller, _dx, dy):
        if dy < 0 and self.browser_scroll.get_vadjustment().get_value() < 40 and (self.browser_state or {}).get("offset", 0) > 0 and not self.browser_loading:
            self.request_browser("previous")
        return False

    def maybe_load_more_browser(self):
        adjustment = self.browser_scroll.get_vadjustment()
        remaining = adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size()
        if self.browser_state and self.browser_state.get("has_more") and remaining < 220 and not self.browser_loading and not self.browser_rendering:
            self.request_browser("more")
        return False

    def load_visible_browser_artwork(self, *_):
        adjustment = self.browser_scroll.get_vadjustment()
        if self.browser_state and self.browser_state.get("search_routes"):
            # Grouped previews are bounded (four rows per group). Load all
            # their artwork rather than consulting the hidden single scroller.
            for key in self.browser_artwork_keys:
                if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                    self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
            return False
        cards = getattr(self, "browser_cards", [])
        if cards:
            keys = []
            for card, item in cards:
                valid, bounds = card.compute_bounds(self.browser_list)
                if valid and bounds.get_y() + bounds.get_height() >= adjustment.get_value() - 220 and bounds.get_y() <= adjustment.get_value() + adjustment.get_page_size() + 220: keys.append(item.get("image_key"))
            for key in keys:
                if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                    self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
            return False
        row_height = 100 if self.window.has_css_class("high-resolution") else 68
        start = max(0, int(adjustment.get_value() / row_height) - 2)
        count = max(8, int(adjustment.get_page_size() / row_height) + 5)
        for key in self.browser_artwork_keys[start:start + count]:
            if key and (key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)) and key not in self.queue_thumbnail_pending:
                self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False
