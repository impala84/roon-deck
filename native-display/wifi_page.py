"""Primary connection and Wi-Fi joining for the touchscreen Settings.

Choosing Ethernet or Wi-Fi, and joining a network, use the same 90-second trial as the web Settings: the other
connection is switched off, and unless it is kept the previous one returns by itself.
"""
import json
import threading
import urllib.error
import urllib.request

from gi.repository import Pango
from native_common import BUS, FamilyIcon, Gtk, GLib, get_json, post_json, elastic_vertical_scroll

KEY_LAYERS = (
    ("qwertyuiop", "asdfghjkl", "zxcvbnm"),
    ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"),
    ("1234567890", "-_.@#&+=!", "?/:;()$%*"),
)


class WifiPageMixin:
    def network_request(self, data, done, timeout=45):
        """POST one network operation without blocking the screen; done(result_or_None, error_text) runs on the main loop."""
        def work():
            result, error = None, ""
            try:
                request = urllib.request.Request(BUS + "/api/admin/network", data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=timeout) as response: result = json.load(response)
            except urllib.error.HTTPError as exc:
                try: error = json.load(exc).get("error", "")
                except (ValueError, OSError): error = ""
                error = error or "The connection could not be changed."
            except (ValueError, OSError): error = "The network service did not answer."
            GLib.idle_add(done, result, error)
        threading.Thread(target=work, daemon=True).start()

    def build_connection_block(self):
        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); block.add_css_class("connection-block")
        block.append(self.label("PRIMARY CONNECTION", "eyebrow"))
        choice = Gtk.Box(spacing=12); choice.set_homogeneous(True); block.append(choice)
        self.connection_buttons = {}
        for target, title in (("ethernet", "Ethernet"), ("wifi", "Wi-Fi")):
            button = self.button(title, lambda _button, value=target: self.connection_choose(value), "settings-action connection-choice")
            self.connection_buttons[target] = button; choice.append(button)
        self.connection_buttons["wifi"].set_tooltip_text("Use Wi-Fi as the primary connection")
        wifi_heading = self.label("WI-FI", "eyebrow"); block.append(wifi_heading)
        join = self.button("Join Wi-Fi network…", self.open_wifi_page, "settings-action connection-join"); block.append(join)
        self.connection_message = self.label("", "settings-diagnostic"); self.connection_message.set_wrap(False); self.connection_message.set_ellipsize(3); self.connection_message.set_xalign(0); self.connection_message.set_visible(False); block.append(self.connection_message)
        trial = Gtk.Box(spacing=12); trial.set_homogeneous(True); trial.set_visible(False); self.connection_trial = trial
        self.connection_keep_button = self.button("Keep this connection", self.connection_keep, "settings-action"); trial.append(self.connection_keep_button)
        trial.append(self.button("Go back", self.connection_undo, "settings-action reboot-action")); block.append(trial)
        # Keep/Go back takes the place of the Join button while it shows, so the column never grows past the screen.
        trial.connect("notify::visible", lambda row, _p: (wifi_heading.set_visible(not row.get_visible()), join.set_visible(not row.get_visible())))
        self.connection_status = {}; self.connection_timer = None; self.connection_busy = False; self.vpn_trial_token = ""
        self.connection_block = block
        block.connect("map", self.connection_start); block.connect("unmap", self.connection_stop)
        return block

    def connection_start(self, *_):
        self.connection_refresh()
        if self.connection_timer is None: self.connection_timer = GLib.timeout_add_seconds(4, self.connection_refresh)

    def connection_stop(self, *_):
        if self.connection_timer is not None: GLib.source_remove(self.connection_timer); self.connection_timer = None

    def connection_refresh(self):
        if self.connection_busy: return True
        def work():
            data = get_json(BUS + "/api/admin/network", timeout=6)
            GLib.idle_add(self.connection_apply_status, data)
        threading.Thread(target=work, daemon=True).start()
        return True

    def connection_apply_status(self, data):
        if not isinstance(data, dict): return False
        self.connection_status = data
        trial = data.get("trial") or {}
        active = trial.get("target") or data.get("selected") or next((item["kind"] for item in data.get("devices", []) if item.get("connected")), "")
        if getattr(self, "connection_expect_result", False) and data.get("status") in ("restored", "error", "ready") and not trial.get("token"):
            self.connection_expect_result = False
            self.connection_say({"restored": "That connection did not come up, so the previous one was restored.",
                                 "error": data.get("message") or "The connection could not be changed.",
                                 "ready": "Connection saved."}[data["status"]])
        for target, button in self.connection_buttons.items():
            (button.add_css_class if target == active else button.remove_css_class)("active")
            kinds = [item for item in data.get("devices", []) if item.get("kind") == target]
            button.set_sensitive(bool(kinds))
        # Any unfinished trial can always be undone, so a half-finished switch can never leave the screen stuck.
        has_trial = bool(trial.get("token"))
        pending = has_trial and data.get("status") == "trial"
        vpn_pending = bool(self.vpn_trial_token)
        self.connection_trial.set_visible(has_trial or vpn_pending)
        self.connection_keep_button.set_visible(pending or vpn_pending)
        message = data.get("message") or ""
        if vpn_pending and not has_trial: return False  # the VPN trial message stays until it is kept or undone
        if has_trial and not pending: message = "The switch has not finished. Tap Go back to return to the previous connection."
        if pending: message = f"Keep this connection within {trial.get('seconds', 0)} seconds, or the previous one returns."
        elif data.get("status") not in ("switching", "trial"): return False
        self.connection_message.set_text(message); self.connection_message.set_visible(bool(message))
        return False

    def connection_say(self, text):
        self.connection_message.set_text(text); self.connection_message.set_visible(bool(text))

    def connection_choose(self, target, ssid="", password=""):
        if self.connection_busy: return
        # Wi-Fi with no saved network has nothing to connect to: ask for one on the Join page instead of switching and failing.
        if target == "wifi" and not ssid and not self.connection_status.get("saved_wifi") and not any(item.get("kind") == "wifi" and item.get("connected") for item in self.connection_status.get("devices", [])):
            self.open_wifi_page(); return
        self.connection_expect_result = True
        if (self.connection_status.get("trial") or {}).get("token"):
            # An earlier switch was never kept or undone; undo it first, then make this one.
            self.connection_busy = True; self.connection_say("Going back to the previous connection first…")
            def restored(result, error):
                self.connection_busy = False
                if error: self.connection_say(error); self.connection_refresh(); return False
                self.connection_status["trial"] = {}; self.connection_choose(target, ssid, password); return False
            self.network_request({"operation": "restore"}, restored); return
        self.connection_busy = True; self.connection_say("Switching… this takes up to 30 seconds.")
        def done(result, error):
            self.connection_busy = False
            if error: self.connection_say(error)
            self.connection_refresh()
            return False
        self.network_request({"operation": "select", "target": target, "ssid": ssid, "password": password}, done)

    def connection_keep(self, *_):
        if self.vpn_trial_token:
            token, self.vpn_trial_token = self.vpn_trial_token, ""
            self.vpn_request({"operation": "vpn_confirm", "token": token}, "VPN kept."); return
        token = (self.connection_status.get("trial") or {}).get("token", "")
        def done(result, error):
            self.connection_say(error or "Connection saved."); self.connection_refresh(); return False
        self.network_request({"operation": "confirm", "token": token}, done)

    def connection_undo(self, *_):
        if self.vpn_trial_token:
            self.vpn_trial_token = ""
            self.vpn_request({"operation": "vpn_disconnect"}, "VPN disconnected."); return
        def done(result, error):
            self.connection_say(error or "Going back to the previous connection."); self.connection_refresh(); return False
        self.network_request({"operation": "restore"}, done)

    # ---- Join Wi-Fi page -------------------------------------------------------------------------------------
    def build_wifi_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); page.add_css_class("page"); page.add_css_class("settings-page"); page.add_css_class("wifi-page")
        top = Gtk.Box(spacing=20); top.add_css_class("settings-header")
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); heading.set_hexpand(True); heading.set_valign(Gtk.Align.CENTER)
        title = self.label("Join Wi-Fi", "settings-title"); title.set_halign(Gtk.Align.START); heading.append(title)
        self.wifi_message = self.label("", "settings-diagnostic"); self.wifi_message.set_wrap(True); self.wifi_message.set_xalign(0); heading.append(self.wifi_message); top.append(heading)
        back = Gtk.Button(); back.add_css_class("settings-close"); back.set_size_request(58, 58)
        back.set_hexpand(False); back.set_vexpand(False); back.set_halign(Gtk.Align.CENTER); back.set_valign(Gtk.Align.CENTER)
        back.set_tooltip_text("Back to Settings"); back.set_child(FamilyIcon("back", 32, stroke_width=3)); back.connect("clicked", self.close_wifi_page)
        utilities = Gtk.Box(spacing=12); utilities.add_css_class("settings-utilities"); utilities.set_valign(Gtk.Align.START); utilities.append(back); top.append(utilities); page.append(top)
        divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); divider.add_css_class("settings-divider"); page.append(divider)

        # Landscape: networks on the left, name, password and keyboard on the right, so nothing scrolls. Portrait stacks them.
        columns = Gtk.Box(spacing=24); columns.set_homogeneous(False); columns.set_vexpand(True); self.wifi_columns = columns; page.append(columns)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); left.set_vexpand(True); self.wifi_left = left; columns.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); right.set_hexpand(True); right.set_vexpand(True); columns.append(right)
        scan_row = Gtk.Box(spacing=12); scan_row.append(self.label("NEARBY NETWORKS", "eyebrow")); scan_row.get_first_child().set_hexpand(True)
        self.wifi_scan_button = self.button("Scan", self.wifi_scan, "settings-action wifi-scan"); scan_row.append(self.wifi_scan_button); left.append(scan_row)
        self.wifi_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_vexpand(True); scroll.set_min_content_height(150)
        scroll.set_child(self.wifi_list); elastic_vertical_scroll(scroll); left.append(scroll)

        self.wifi_ssid = Gtk.Entry(); self.wifi_ssid.set_placeholder_text("Network name"); self.wifi_ssid.add_css_class("wifi-entry")
        self.wifi_password = Gtk.Entry(); self.wifi_password.set_placeholder_text("Password"); self.wifi_password.set_visibility(False); self.wifi_password.add_css_class("wifi-entry")
        # Entries ask for about twenty characters by default, which made the page wider than the screen.
        for entry in (self.wifi_ssid, self.wifi_password): entry.set_width_chars(1); entry.set_max_width_chars(1); entry.set_hexpand(True)
        self.wifi_active_entry = self.wifi_ssid
        for entry in (self.wifi_ssid, self.wifi_password):
            focus = Gtk.EventControllerFocus(); focus.connect("enter", lambda _c, widget=entry: setattr(self, "wifi_active_entry", widget)); entry.add_controller(focus)
            entry.connect("activate", self.wifi_join)
        fields = Gtk.Box(spacing=12); fields.set_homogeneous(True); fields.append(self.wifi_ssid); fields.append(self.wifi_password); right.append(fields)

        self.wifi_layer = 0; self.wifi_keys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); right.append(self.wifi_keys); self.wifi_build_keys()
        actions = Gtk.Box(spacing=12); actions.set_homogeneous(True)
        show = self.button("Show password", self.wifi_toggle_password, "settings-action"); self.wifi_show_button = show; actions.append(show)
        self.wifi_join_button = self.button("Join", self.wifi_join, "settings-action wifi-join"); actions.append(self.wifi_join_button); right.append(actions)
        self.wifi_networks = []
        return page

    def wifi_build_keys(self):
        while child := self.wifi_keys.get_first_child(): self.wifi_keys.remove(child)
        number_row = Gtk.Box(spacing=6); number_row.set_homogeneous(True)
        for key in "1234567890" if self.wifi_layer != 2 else "~`|^{}[]<>":
            number_row.append(self.button(key, lambda _b, value=key: self.wifi_type(value), "browser-key wifi-key"))
        self.wifi_keys.append(number_row)
        for letters in KEY_LAYERS[self.wifi_layer]:
            row = Gtk.Box(spacing=6); row.set_homogeneous(True)
            for key in letters: row.append(self.button(key, lambda _b, value=key: self.wifi_type(value), "browser-key wifi-key"))
            self.wifi_keys.append(row)
        bottom = Gtk.Box(spacing=6)
        shift = self.button("abc" if self.wifi_layer else "Shift", lambda *_: self.wifi_set_layer(0 if self.wifi_layer else 1), "browser-key wifi-key"); shift.set_hexpand(True); bottom.append(shift)
        symbols = self.button("123" if self.wifi_layer != 2 else "ABC", lambda *_: self.wifi_set_layer(2 if self.wifi_layer != 2 else 1), "browser-key wifi-key"); symbols.set_hexpand(True); bottom.append(symbols)
        space = self.button("Space", lambda *_: self.wifi_type(" "), "browser-key wifi-key"); space.set_hexpand(True); bottom.append(space)
        erase = self.button("⌫", lambda *_: self.wifi_type("BACKSPACE"), "browser-key wifi-key"); erase.set_hexpand(True); bottom.append(erase)
        self.wifi_keys.append(bottom)

    def wifi_set_layer(self, layer):
        self.wifi_layer = layer; self.wifi_build_keys()

    def wifi_type(self, value):
        entry = self.wifi_active_entry; text = entry.get_text(); position = entry.get_position()
        if position < 0 or position > len(text): position = len(text)
        if value == "BACKSPACE":
            if position > 0: text = text[:position - 1] + text[position:]; position -= 1
        else: text = text[:position] + value + text[position:]; position += len(value)
        entry.set_text(text); entry.set_position(position)
        if self.wifi_layer == 1 and value != "BACKSPACE": self.wifi_set_layer(0)  # one capital at a time

    def wifi_toggle_password(self, *_):
        show = not self.wifi_password.get_visibility(); self.wifi_password.set_visibility(show)
        self.wifi_show_button.set_label("Hide password" if show else "Show password")

    def open_wifi_page(self, *_):
        if "wifi" not in getattr(self, "settings_page_names", set()): return
        self.settings_sections.set_visible_child_name("wifi"); self.wifi_scan()
        if not self.connection_status.get("saved_wifi"): self.wifi_message.set_text("No Wi-Fi network is saved yet. Scanning…")

    def close_wifi_page(self, *_):
        self.settings_sections.set_visible_child_name(self.settings_home())

    def wifi_scan(self, *_):
        self.wifi_scan_button.set_sensitive(False); self.wifi_message.set_text("Scanning…")
        def done(result, error):
            self.wifi_scan_button.set_sensitive(True)
            self.wifi_networks = (result or {}).get("networks", []) if not error else []
            self.wifi_message.set_text(error or (result or {}).get("message") or ("" if self.wifi_networks else "No networks found."))
            while child := self.wifi_list.get_first_child(): self.wifi_list.remove(child)
            for item in self.wifi_networks:
                text = f"{item['ssid']}  ·  {item.get('signal', 0)}%" + ("  ·  secured" if item.get("secured") else "") + ("  ·  connected" if item.get("in_use") else "")
                row = self.button(text, lambda _b, value=item: self.wifi_pick(value), "settings-action wifi-network")
                if isinstance(row.get_child(), Gtk.Label): row.get_child().set_xalign(0); row.get_child().set_ellipsize(Pango.EllipsizeMode.END)
                self.wifi_list.append(row)
            return False
        self.network_request({"operation": "scan"}, done, timeout=30)

    def wifi_pick(self, item):
        self.wifi_ssid.set_text(item["ssid"]); self.wifi_password.set_text(""); self.wifi_active_entry = self.wifi_password
        self.wifi_password.grab_focus()
        self.wifi_message.set_text("Enter the password." if item.get("secured") else "Open network. Tap Join.")

    def wifi_join(self, *_):
        ssid = self.wifi_ssid.get_text().strip()
        if not ssid: self.wifi_message.set_text("Choose or type a network name."); return
        password = self.wifi_password.get_text()
        self.settings_sections.set_visible_child_name(self.settings_home())
        self.wifi_password.set_text("")
        self.connection_choose("wifi", ssid, password)

    def clear_network_trial(self):
        """Blocking; call from a worker thread. The Pi refuses Update and Reboot while a connection trial is waiting to be kept or
        undone, which made both buttons do nothing. Undo the trial first, since the person asking for either is at the screen."""
        status = get_json(BUS + "/api/admin/network", timeout=6)
        if isinstance(status, dict) and (status.get("trial") or {}).get("token"):
            post_json(BUS + "/api/admin/network", {"operation": "restore"}, timeout=40)

    # ---- VPN switch ------------------------------------------------------------------------------------------
    def build_vpn_switch(self, row):
        """An on/off switch at the end of the VPN status line. On connects with the same 90-second keep-or-undo trial as the web page."""
        switch = Gtk.Switch(); switch.set_valign(Gtk.Align.CENTER); row.append(switch)
        self.settings_vpn_switch = switch; self.vpn_switch_updating = False
        switch.connect("notify::active", self.vpn_toggled)

    def vpn_switch_sync(self, vpn):
        switch = getattr(self, "settings_vpn_switch", None)
        if switch is None or getattr(self, "vpn_busy", False): return
        active = bool(vpn.get("active"))
        if switch.get_active() != active:
            self.vpn_switch_updating = True; switch.set_active(active); self.vpn_switch_updating = False

    def vpn_toggled(self, switch, *_):
        if self.vpn_switch_updating or getattr(self, "vpn_busy", False): return
        if switch.get_active(): self.vpn_request({"operation": "vpn_connect"}, "VPN connecting…")
        else: self.vpn_request({"operation": "vpn_disconnect"}, "VPN disconnected.")

    def vpn_request(self, data, message):
        self.vpn_busy = True; self.settings_vpn_switch.set_sensitive(False); self.connection_say(message if message.endswith("…") else "Working…")
        def work():
            result, error = None, ""
            try:
                request = urllib.request.Request(BUS + "/api/admin/accessories", data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=45) as response: result = json.load(response)
            except urllib.error.HTTPError as exc:
                try: error = json.load(exc).get("error", "")
                except (ValueError, OSError): error = ""
                error = error or "The VPN could not be changed."
            except (ValueError, OSError): error = "The VPN did not answer."
            GLib.idle_add(done, result, error)
        def done(result, error):
            self.vpn_busy = False; self.settings_vpn_switch.set_sensitive(True)
            token = (result or {}).get("pending_token", "") if not error else ""
            if error:
                self.connection_say(error); self.vpn_switch_updating = True; self.settings_vpn_switch.set_active(not self.settings_vpn_switch.get_active()); self.vpn_switch_updating = False
            elif token:
                self.vpn_trial_token = token; self.connection_trial.set_visible(True)
                self.connection_say("VPN on. Keep it within 90 seconds?")
            else: self.connection_say(message)
            self.settings_vpn_at = 0; self.refresh_network_pane()
            return False
        threading.Thread(target=work, daemon=True).start()
