"""SoundCloud page: search, a profile's public likes, tracks and playlists, and transport.

The player itself is the small local service in pi_bus_time_display/soundcloud_player.py (installed from the web admin).
This page only talks to it on 127.0.0.1:8767. It is not connected to Roon: the Pi's DAC plays one thing at a time, so
starting a track pauses Roon and Roon playing stops SoundCloud.
"""
from __future__ import annotations

import threading

from native_common import get_json, post_json
from gi.repository import GLib, Gtk, Pango

SOUNDCLOUD = "http://127.0.0.1:8767"
KEY_ROWS = ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")


def clock(seconds):
    seconds = max(0, int(seconds or 0)); return "%d:%02d" % (seconds // 60, seconds % 60)


class SoundCloudPageMixin:
    def build_soundcloud_view(self):
        """The page itself; the button that opens it lives in the Now Playing source row (see render_bluos_inputs)."""
        self.sc_available = False; self.sc_state = {}; self.sc_items = []; self.sc_status_text = ""; self.sc_shown = None
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); page.add_css_class("soundcloud-page"); page.set_hexpand(True); page.set_vexpand(True)
        row = Gtk.Box(spacing=8)
        self.sc_entry = Gtk.Entry(); self.sc_entry.add_css_class("browser-search-entry"); self.sc_entry.set_placeholder_text("Search SoundCloud"); self.sc_entry.set_hexpand(True); self.sc_entry.set_width_chars(1)
        self.sc_entry.set_editable(False); self.sc_entry.set_can_focus(False)
        tap = Gtk.GestureClick(); tap.connect("released", lambda *_: self.sc_show_keyboard(True)); self.sc_entry.add_controller(tap)
        row.append(self.sc_entry)
        row.append(self.button("SEARCH", self.sc_search, "browser-key browser-search-submit"))
        row.append(self.button("LIKES", lambda *_: self.sc_browse("likes"), "browser-key"))
        row.append(self.button("PLAYLISTS", lambda *_: self.sc_browse("playlists"), "browser-key"))
        page.append(row)
        self.sc_keyboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for keys in KEY_ROWS:
            key_row = Gtk.Box(spacing=6); key_row.set_homogeneous(True)
            for key in keys: key_row.append(self.button(key, lambda _button, value=key: self.sc_key(value), "browser-key"))
            self.sc_keyboard.append(key_row)
        actions = Gtk.Box(spacing=6); actions.set_homogeneous(True)
        for title, value in (("SPACE", " "), ("DELETE", "BACKSPACE"), ("CLEAR", "CLEAR")): actions.append(self.button(title, lambda _button, value=value: self.sc_key(value), "browser-key"))
        actions.append(self.button("GO", self.sc_search, "browser-key browser-search-submit")); self.sc_keyboard.append(actions)
        self.sc_keyboard.set_visible(False); page.append(self.sc_keyboard)
        self.sc_message = self.label("", "queue-subtitle"); self.sc_message.set_wrap(True); self.sc_message.set_halign(Gtk.Align.START); page.append(self.sc_message)
        self.sc_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); self.sc_list.add_css_class("queue-list")
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_kinetic_scrolling(True); scroll.set_overlay_scrolling(True)
        scroll.set_vexpand(True); scroll.set_child(self.sc_list); self.sc_scroll = scroll; page.append(scroll)
        bar = Gtk.Box(spacing=10); bar.add_css_class("queue-row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); text.set_hexpand(True)
        self.sc_title = self.label("Nothing playing", "queue-title"); self.sc_title.set_ellipsize(Pango.EllipsizeMode.END); self.sc_title.set_halign(Gtk.Align.START)
        self.sc_sub = self.label("", "queue-subtitle"); self.sc_sub.set_ellipsize(Pango.EllipsizeMode.END); self.sc_sub.set_halign(Gtk.Align.START)
        text.append(self.sc_title); text.append(self.sc_sub); bar.append(text)
        self.sc_prev = self.button("PREV", lambda *_: self.sc_post("/previous"), "browser-key")
        self.sc_play = self.button("PAUSE", lambda *_: self.sc_post("/pause"), "browser-key")
        self.sc_next = self.button("NEXT", lambda *_: self.sc_post("/next"), "browser-key")
        for widget in (self.sc_prev, self.sc_play, self.sc_next): bar.append(widget)
        page.append(bar)
        GLib.timeout_add_seconds(3, self.sc_tick)
        return page

    # ---- talking to the player service -------------------------------------------------------------------------
    def sc_call(self, path, payload=None, then=None, timeout=45):
        def work():
            result = get_json(SOUNDCLOUD + path, timeout=1.0) if payload is None and path == "/state" else post_json(SOUNDCLOUD + path, payload or {}, timeout=timeout)
            if then: GLib.idle_add(then, result)
        threading.Thread(target=work, daemon=True).start()

    def sc_post(self, path, payload=None):
        self.sc_call(path, payload or {}, lambda result: (self.sc_apply(result) if isinstance(result, dict) and "active" in result else None, False)[1])

    def sc_tick(self):
        self.sc_call("/state", None, lambda state: (self.sc_apply(state), False)[1]); return True

    def sc_apply(self, state):
        available = isinstance(state, dict) and "active" in state
        self.sc_state = state if available else {}
        if available != self.sc_available:
            self.sc_available = available; self.bluos_input_signature = None   # rebuild the source row with or without the button
            if hasattr(self, "state") and self.state is not None: self.render_bluos_inputs((self.state or {}).get("amplifier") or {}, bool((self.state or {}).get("zone")))
        if not available: return
        track = state.get("track") or {}
        self.sc_title.set_text(track.get("title") or ("Nothing playing" if not state.get("error") else state["error"]))
        self.sc_sub.set_text(("%s  ·  %s / %s" % (track.get("artist", ""), clock(state.get("position")), clock(state.get("duration")))) if track else "")
        self.sc_play.get_child().set_text("PLAY" if state.get("paused") else "PAUSE")
        self.sc_prev.set_sensitive(bool(state.get("active"))); self.sc_next.set_sensitive(bool(state.get("active"))); self.sc_play.set_sensitive(bool(state.get("active")))
        button = getattr(self, "sc_source_button", None)
        if button is not None:
            (button.add_css_class if self.requested_audio_view == "soundcloud" else button.remove_css_class)("active")

    # ---- the page -------------------------------------------------------------------------------------------------
    def show_soundcloud(self, *_):
        self.requested_audio_view = "soundcloud"
        self.set_roon_view("soundcloud")
        self.sc_apply(self.sc_state)

    def sc_show_keyboard(self, show):
        self.sc_keyboard.set_visible(show)

    def sc_key(self, value):
        text = self.sc_entry.get_text()
        self.sc_entry.set_text("" if value == "CLEAR" else text[:-1] if value == "BACKSPACE" else (text + value.lower())[:120])

    def sc_set_message(self, text): self.sc_message.set_text(text); self.sc_message.set_visible(bool(text))

    def sc_search(self, *_):
        query = self.sc_entry.get_text().strip()
        if not query: return
        self.sc_show_keyboard(False); self.sc_set_message("Searching…")
        self.sc_call("/search", {"query": query, "limit": 20}, self.sc_results)

    def sc_browse(self, kind):
        self.sc_show_keyboard(False); self.sc_set_message("Loading your " + kind + "…")
        self.sc_call("/browse", {"kind": kind, "limit": 50}, self.sc_results)

    def sc_results(self, result):
        items = (result or {}).get("items") if isinstance(result, dict) else None
        while child := self.sc_list.get_first_child(): self.sc_list.remove(child)
        self.sc_items = items or []
        if items is None:
            error = (result or {}).get("error") if isinstance(result, dict) else ""
            self.sc_set_message(error or "SoundCloud did not answer. Check the Pi's connection."); return False
        if not items:
            self.sc_set_message("Nothing found. For likes, set your SoundCloud profile name in the web admin → Integrations → SoundCloud."); return False
        self.sc_set_message("")
        for index, item in enumerate(items):
            button = Gtk.Button(); button.add_css_class("queue-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            title = self.label(item.get("title", ""), "queue-title"); title.set_ellipsize(Pango.EllipsizeMode.END); title.set_halign(Gtk.Align.START); title.set_xalign(0)
            sub = self.label((item.get("artist", "") + ("  ·  " + clock(item.get("duration")) if item.get("duration") else "")), "queue-subtitle"); sub.set_ellipsize(Pango.EllipsizeMode.END); sub.set_halign(Gtk.Align.START); sub.set_xalign(0)
            box.append(title); box.append(sub); button.set_child(box)
            button.connect("clicked", lambda _button, value=index: self.sc_play_index(value)); self.sc_list.append(button)
        self.sc_scroll.get_vadjustment().set_value(0)
        return False

    def sc_play_index(self, index):
        self.sc_post("/play", {"items": self.sc_items, "index": index})
