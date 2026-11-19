"""SoundCloud on the touchscreen, built from the existing screens.

Browsing and search live in Discover (a SoundCloud tab, using the same search keyboard as Roon). Playing shows on the
normal Now Playing screen. The player itself is the small local service in pi_bus_time_display/soundcloud_player.py
(installed from the web admin), reached on 127.0.0.1:8767. It is not connected to Roon: the Pi's DAC plays one thing at a
time, so starting a track pauses Roon and Roon playing stops SoundCloud.
"""
from __future__ import annotations

import threading
import time

from native_common import FamilyIcon, get_bytes, get_json, post_json
from gi.repository import Gdk, GLib, Gtk, Pango

SOUNDCLOUD = "http://127.0.0.1:8767"
HINT = "Add your SoundCloud profile name in the web admin (Services → Music → SoundCloud) to see your likes and playlists."


def clock(seconds):
    seconds = max(0, int(seconds or 0)); return "%d:%02d" % (seconds // 60, seconds % 60)


class SoundCloudPageMixin:
    def setup_soundcloud(self):
        self.sc_available = False; self.sc_state = {}; self.sc_items = []; self.sc_shown = None; self.sc_source_button = None
        self.sc_mode = "likes"; self.sc_search_mode = False; self.sc_request = 0; self.sc_art_url = ""; self.sc_viewing = False; self.sc_search_nav = None
        # A tab beside Recent, Browse and Daily, shown only once the player is installed and running.
        self.sc_tab = self.button("SOUNDCLOUD", lambda *_: self.open_discover("soundcloud"), "")
        self.discover_tabs["soundcloud"] = self.sc_tab; self.discover_subnav.append(self.sc_tab); self.sc_tab.set_visible(False)
        # Long mixes are hard to scrub, so SoundCloud's page gets 30-second jumps either side of the transport.
        self.sc_back = self.icon_button("skip-back-thirty", lambda *_: self.sc_skip(-30), "sc-skip"); self.sc_forward = self.icon_button("skip-forward-thirty", lambda *_: self.sc_skip(30), "sc-skip")
        self.sc_back.set_tooltip_text("Back 30 seconds"); self.sc_forward.set_tooltip_text("Forward 30 seconds")
        for button in (self.sc_back, self.sc_forward): button.set_size_request(50, 50); button.set_valign(Gtk.Align.CENTER); button.set_visible(False)
        if not (getattr(self, "viewport_width", 800) <= 820 and getattr(self, "viewport_height", 480) <= 500):
            for button in (self.sc_back, self.sc_forward): button.get_child().set_pixel_size(50)
        self.controls.insert_child_after(self.sc_back, self.library_add); self.controls.append(self.sc_forward)
        GLib.timeout_add_seconds(3, self.sc_tick)

    # ---- the player service ------------------------------------------------------------------------------------
    def sc_call(self, path, payload=None, then=None, timeout=60):
        def work():
            GLib.idle_add(self.sc_keep_awake)
            result = get_json(SOUNDCLOUD + path, timeout=1.0) if payload is None else post_json(SOUNDCLOUD + path, payload, timeout=timeout)
            if then: GLib.idle_add(then, result)
            GLib.idle_add(self.sc_keep_awake)
        threading.Thread(target=work, daemon=True).start()

    def sc_keep_awake(self):
        """A slow SoundCloud search must not let the idle timer put the screen to sleep while you wait for the answer."""
        if getattr(self, "sc_search_mode", False) or self.discovery_section == "soundcloud": self.last_interaction = time.monotonic()
        return False

    def sc_post(self, path, payload=None):
        self.sc_call(path, payload or {}, lambda result: (self.sc_apply(result), False)[1])

    def sc_tick(self):
        self.sc_call("/state", None, lambda state: (self.sc_apply(state, poll=True), False)[1]); return True

    def sc_now_active(self): return bool((self.sc_state or {}).get("active"))

    def sc_viewing_active(self):
        """True while the SoundCloud Now Playing page is the one on screen (Roon's has its own NOW PLAYING tab)."""
        return bool(self.sc_viewing and self.sc_now_active())

    def sc_sync_tabs(self):
        """NOW PLAYING is Roon's page and SOUNDCLOUD is the player's: only one of them is lit."""
        if not hasattr(self, "sc_viewing"): return
        on_now = self.roon_views.get_visible_child_name() in {"now", "details"}
        if self.sc_source_button is not None:
            (self.sc_source_button.add_css_class if on_now and self.sc_viewing else self.sc_source_button.remove_css_class)("active")
        if on_now and self.sc_viewing: self.now_playing_tab.remove_css_class("active")
        elif on_now: self.now_playing_tab.add_css_class("active")

    def sc_apply(self, state, poll=False):
        """Take a state reply from the player. A failed command (an older player without it, a timeout) must not look like the
        player going away and drop you off the page, so only repeated failed polls count as unavailable."""
        if isinstance(state, dict) and "active" in state: self.sc_misses = 0
        elif poll and state is None:
            self.sc_misses = getattr(self, "sc_misses", 0) + 1
            if self.sc_misses < 2: return
        elif poll: return
        else: return
        available = isinstance(state, dict) and "active" in state
        self.sc_state = state if available else {}
        if available != self.sc_available:
            self.sc_available = available; self.sc_tab.set_visible(available); self.bluos_input_signature = None   # rebuild the source row
            if getattr(self, "state", None) is not None: self.render_bluos_inputs((self.state or {}).get("amplifier") or {}, bool((self.state or {}).get("zone")))
        if not self.sc_now_active(): self.sc_art_url = ""   # the next track loads its cover again
        if self.sc_viewing and not self.sc_now_active(): self.sc_leave_page()   # the track ended or was stopped: Roon's page again
        elif available and self.sc_viewing_active() and self.roon_views.get_visible_child_name() == "now": self.apply_soundcloud_now()

    def sc_leave_page(self):
        """Hand the Now Playing page back to Roon without moving you off whatever screen you are on."""
        self.sc_viewing = False
        if self.roon_views.get_visible_child_name() == "now" and self.state is not None: self.image_key = None; self.render_roon_body(self.state)
        self.sc_sync_tabs()

    def show_soundcloud(self, *_):
        """The source button: SoundCloud's own Now Playing page while it has a track, otherwise Discover to pick one."""
        if self.sc_now_active():
            self.sc_viewing = True; self.set_roon_view("now"); self.apply_soundcloud_now(); self.sc_sync_tabs()
        else: self.open_discover("soundcloud")

    # ---- Now Playing ---------------------------------------------------------------------------------------------
    def apply_soundcloud_now(self):
        """While SoundCloud is playing the normal Now Playing screen shows it, with its own cover, progress and transport."""
        for button in (self.sc_back, self.sc_forward): button.set_visible(True); button.set_sensitive(True)
        state = self.sc_state or {}; track = state.get("track") or {}
        self.zone.set_text(("SOUNDCLOUD · " + state["stream"]).upper() if state.get("stream") else "SOUNDCLOUD"); self.title.set_text(track.get("title") or "SoundCloud"); self.artist.set_text(track.get("artist") or "")
        position, duration = int(state.get("position") or 0), int(state.get("duration") or 0)
        self.seek_updating = True; self.progress.set_range(0, max(1, duration)); self.progress.set_value(min(position, duration) if duration else 0)
        self.progress.set_sensitive(bool(duration)); self.seek_updating = False
        self.elapsed.set_text(clock(position)); self.remaining.set_text("−" + clock(max(0, duration - position)) if duration else "")
        size = 80 if self.window.has_css_class("large-display") else 42
        icon = "play" if state.get("paused") else "pause"
        current = self.play.get_child()
        if not isinstance(current, FamilyIcon) or current.icon_name != icon or current.get_pixel_size() != size: self.play.set_child(FamilyIcon(icon, size))
        index = int(state.get("index") or 0)
        self.prev.set_sensitive(index > 0); self.next.set_sensitive(index + 1 < int(state.get("queue") or 0)); self.play.set_sensitive(True)
        for control in (self.mute, self.volume_down, self.volume, self.volume_up): control.set_visible(False)   # the DAC sets the volume
        self.volume_value.set_text((state.get("stream") or "FIXED VOLUME").upper()); self.volume_value.set_hexpand(True); self.volume_value.set_xalign(.5); self.volume_value.add_css_class("fixed-volume-label")
        self.library_add.set_visible(False)
        art = track.get("cover") or track.get("artwork") or ""
        if art and art != self.sc_art_url:
            self.sc_art_url = art
            threading.Thread(target=self.sc_load_art, args=(art,), daemon=True).start()
        elif not art and self.sc_art_url == "":
            self.idle_artwork()

    def sc_load_art(self, url):
        data = get_bytes(url, timeout=6.0)
        if data and url == self.sc_art_url:
            def apply():
                try: self.artwork.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))); self.image_key = "soundcloud:" + url
                except GLib.Error: pass
                return False
            GLib.idle_add(apply)

    def sc_control(self, action):
        self.sc_post({"previous": "/previous", "next": "/next"}.get(action, "/pause"))

    def sc_skip(self, seconds):
        state = self.sc_state or {}; duration = float(state.get("duration") or 0)
        position = max(0.0, float(state.get("position") or 0) + seconds)
        state["position"] = min(position, duration) if duration else position   # show the jump at once; the next poll corrects it
        self.apply_soundcloud_now(); self.sc_post("/skip", {"seconds": seconds})

    def sc_seek(self, seconds): self.sc_post("/seek", {"position": seconds})

    # ---- Discover → SoundCloud ----------------------------------------------------------------------------------
    def sc_end_search_mode(self):
        if not getattr(self, "sc_search_mode", False): return
        self.sc_search_mode = False
        self.browser_search_entry.set_placeholder_text("Search Roon"); self.search_nav.set_visible(True)
        if self.sc_search_nav is not None: self.sc_search_nav.set_visible(False)

    def sc_ensure_search_nav(self):
        """The Roon search page's left column, with SoundCloud's own sections, so searching keeps the same layout."""
        if self.sc_search_nav is None:
            nav = Gtk.Box(spacing=2); nav.add_css_class("browser-sidebar"); nav.add_css_class("library-sidebar")
            for value, label in (("likes", "LIKES"), ("playlists", "PLAYLISTS"), ("search", "SEARCH")):
                button = self.button(label, lambda _button, choice=value: self.sc_select(choice) if choice != "search" else None, "browser-filter"); button.get_child().set_xalign(0)
                if value == "search": button.add_css_class("active")
                nav.append(button)
            portrait = getattr(self, "responsive_portrait", False)
            nav.set_orientation(Gtk.Orientation.HORIZONTAL if portrait else Gtk.Orientation.VERTICAL)
            nav.set_vexpand(not portrait); nav.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
            self.browser_search_panel.insert_child_after(nav, self.search_nav); self.sc_search_nav = nav
        return self.sc_search_nav

    def sc_open_section(self):
        """Called by open_discover once the Discover page is showing the SoundCloud tab."""
        self.sc_end_search_mode()
        if not self.sc_available:
            self.sc_message("SoundCloud is not running. Install it in the web admin: Services → Music → SoundCloud."); return
        self.sc_select("likes")

    def sc_header(self, text, css):
        """A heading or notice whose line sits level with the first item of the left-hand column."""
        first = next(iter((getattr(self, "discovery_sidebar_buttons", None) or {}).values()), None)
        height = first.measure(Gtk.Orientation.VERTICAL, -1)[0] if first is not None else 44
        top = 0 if self.window.has_css_class("original-landscape") else 4   # the column's own top padding
        label = self.label(text, css); label.add_css_class("sc-heading"); label.set_hexpand(True)
        if len(text) > 60:
            label.set_wrap(True); label.set_valign(Gtk.Align.START); label.set_margin_top(top + max(0, (height - 20) // 2)); return label
        label.set_wrap(False); label.set_ellipsize(Pango.EllipsizeMode.END); label.set_valign(Gtk.Align.CENTER)
        row = Gtk.Box(); row.set_size_request(-1, height); row.set_margin_top(top); row.append(label); return row

    def sc_message(self, text):
        self.sc_request += 1
        while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
        self.discovery_list.append(self.sc_header(text, "browser-message"))

    def sc_select(self, value):
        self.sc_mode = value; self.sc_request += 1
        self.sync_discovery_sidebar()
        if value == "search":
            self.sc_search_mode = True
            self.browser_search_entry.set_text(""); self.browser_search_entry.set_placeholder_text("Search SoundCloud"); self.search_nav.set_visible(False); self.sc_ensure_search_nav().set_visible(True)
            self.set_roon_view("search"); self.browser_search_entry.grab_focus()
            return
        self.sc_end_search_mode(); self.set_roon_view("discover")
        if not (self.sc_state or {}).get("profile"): self.sc_message(HINT); return
        self.sc_show_loading()
        request = self.sc_request
        self.sc_call("/browse", {"kind": value, "limit": 50}, lambda result: (self.sc_results(request, result, "YOUR " + value.upper(), value == "playlists"), False)[1])

    def sc_submit_search(self):
        query = self.browser_search_entry.get_text().strip()
        if not query: return
        self.sc_mode = "search"; self.sc_request += 1; request = self.sc_request
        self.set_roon_view("discover"); self.sync_discovery_sidebar(); self.sc_show_loading()
        self.sc_call("/search", {"query": query, "limit": 20}, lambda result: (self.sc_results(request, result, "RESULTS FOR “" + query.upper() + "”", False), False)[1])

    def sc_show_loading(self):
        while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
        self.discovery_list.append(self.loading_notice())

    def sc_results(self, request, result, heading, playlists):
        if request != self.sc_request or not self.discovery_active or self.discovery_section != "soundcloud": return
        items = result.get("items") if isinstance(result, dict) else None
        if items is None:
            self.sc_message((result or {}).get("error") if isinstance(result, dict) and result.get("error") else "SoundCloud did not answer. Check the Pi's connection and try again."); return
        if not items:
            profile = (self.sc_state or {}).get("profile") or ""
            self.sc_message({"likes": "No public likes found for “%s”. Check the profile name in the web admin, and that your likes are public." % profile,
                             "playlists": "No public playlists found for “%s”." % profile}.get(self.sc_mode, "Nothing found.")); return
        self.sc_items = items
        while child := self.discovery_list.get_first_child(): self.discovery_list.remove(child)
        self.discovery_list.append(self.sc_header(heading, "browser-section"))
        for index, item in enumerate(items): self.discovery_list.append(self.sc_row(item, index, playlists))
        self.discovery_scroll.get_vadjustment().set_value(0)

    def sc_row(self, item, index, playlist):
        row = Gtk.Box(spacing=14); row.set_hexpand(True)
        picture = Gtk.Picture(); picture.add_css_class("queue-art"); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.COVER); self.set_browser_placeholder(picture)
        slot = Gtk.ScrolledWindow(); slot.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER); slot.set_propagate_natural_width(False); slot.set_propagate_natural_height(False)
        slot.set_min_content_width(72); slot.set_max_content_width(72); slot.set_min_content_height(72); slot.set_max_content_height(72); slot.set_valign(Gtk.Align.CENTER); slot.set_child(picture); row.append(slot)
        self.sc_load_thumbnail(picture, item.get("artwork"))
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); copy.set_valign(Gtk.Align.CENTER); copy.set_hexpand(True)
        title = self.label(item.get("title") or "Untitled", "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); copy.append(title)
        subtitle = self.label(item.get("artist") or "SoundCloud", "queue-meta"); subtitle.set_ellipsize(Pango.EllipsizeMode.END); copy.append(subtitle); row.append(copy)
        row.append(self.label("›" if playlist else clock(item.get("duration")) if item.get("duration") else "", "browser-arrow", 1))
        button = Gtk.Button(); button.add_css_class("browser-row"); button.add_css_class("mix-track-row"); button.set_child(row); button.set_vexpand(False)
        button.connect("clicked", lambda *_: self.sc_open_playlist(item) if playlist else self.sc_play(index))
        return button

    def sc_load_thumbnail(self, picture, url):
        if not url: return
        cache = self.__dict__.setdefault("sc_thumbnails", {})
        if url in cache: picture.set_paintable(cache[url]); return
        def load():
            texture = self.decode_artwork(get_bytes(url, timeout=6.0))
            def apply():
                if texture:
                    if len(cache) > 120: cache.clear()
                    cache[url] = texture
                    if picture.get_root() is not None: picture.set_paintable(texture)
                return False
            GLib.idle_add(apply)
        threading.Thread(target=load, daemon=True).start()

    def sc_open_playlist(self, item):
        self.sc_request += 1; request = self.sc_request; self.sc_show_loading()
        self.sc_call("/tracks", {"url": item.get("url")}, lambda result: (self.sc_results(request, result, (item.get("title") or "PLAYLIST").upper(), False), False)[1])

    def sc_play(self, index):
        self.sc_post("/play", {"items": self.sc_items, "index": index})
        self.sc_viewing = True; self.set_roon_view("now")   # playing opens SoundCloud's Now Playing page; the NOW PLAYING tab stays Roon's
        self.sc_sync_tabs()
