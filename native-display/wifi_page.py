"""Primary connection and Wi-Fi joining for the touchscreen Settings.

Choosing Ethernet or Wi-Fi, and joining a network, use the same 90-second trial as the web Settings: the other
connection is switched off, and unless it is kept the previous one returns by itself.
"""
import json
import threading
import urllib.error
import urllib.request

from native_common import BUS, Gtk, GLib, get_json, elastic_vertical_scroll

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
        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); block.add_css_class("connection-block")
        block.append(self.label("PRIMARY CONNECTION", "eyebrow"))
        choice = Gtk.Box(spacing=12); choice.set_homogeneous(True); block.append(choice)
        self.connection_buttons = {}
        for target, title in (("ethernet", "Ethernet"), ("wifi", "Wi-Fi")):
            button = self.button(title, lambda _button, value=target: self.connection_choose(value), "settings-action connection-choice")
            self.connection_buttons[target] = button; choice.append(button)
        self.connection_buttons["wifi"].set_tooltip_text("Use Wi-Fi as the primary connection")
        join = self.button("Join Wi-Fi network…", self.open_wifi_page, "settings-action connection-join"); block.append(join)
        self.connection_message = self.label("", "settings-diagnostic"); self.connection_message.set_wrap(True); self.connection_message.set_xalign(0); self.connection_message.set_visible(False); block.append(self.connection_message)
        trial = Gtk.Box(spacing=12); trial.set_homogeneous(True); trial.set_visible(False); self.connection_trial = trial
        trial.append(self.button("Keep this connection", self.connection_keep, "settings-action"))
        trial.append(self.button("Go back", self.connection_undo, "settings-action reboot-action")); block.append(trial)
        self.connection_status = {}; self.connection_timer = None; self.connection_busy = False
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
        for target, button in self.connection_buttons.items():
            (button.add_css_class if target == active else button.remove_css_class)("active")
            kinds = [item for item in data.get("devices", []) if item.get("kind") == target]
            button.set_sensitive(bool(kinds) and not trial.get("token"))
        pending = bool(trial.get("token")) and data.get("status") == "trial"
        self.connection_trial.set_visible(pending)
        message = data.get("message") or ""
        if pending: message = f"Keep this connection within {trial.get('seconds', 0)} seconds, or the previous one returns."
        elif data.get("status") not in ("switching", "trial"): message = message if data.get("status") == "failed" else ""
        self.connection_message.set_text(message); self.connection_message.set_visible(bool(message))
        return False

    def connection_say(self, text):
        self.connection_message.set_text(text); self.connection_message.set_visible(bool(text))

    def connection_choose(self, target, ssid="", password=""):
        if self.connection_busy: return
        self.connection_busy = True; self.connection_say("Switching… this takes up to 30 seconds.")
        def done(result, error):
            self.connection_busy = False
            if error: self.connection_say(error)
            self.connection_refresh()
            return False
        self.network_request({"operation": "select", "target": target, "ssid": ssid, "password": password}, done)

    def connection_keep(self, *_):
        token = (self.connection_status.get("trial") or {}).get("token", "")
        def done(result, error):
            self.connection_say(error or "Connection saved."); self.connection_refresh(); return False
        self.network_request({"operation": "confirm", "token": token}, done)

    def connection_undo(self, *_):
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
        back = self.button("Back", self.close_wifi_page, "settings-action wifi-back"); back.set_valign(Gtk.Align.CENTER); top.append(back); page.append(top)
        divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); divider.add_css_class("settings-divider"); page.append(divider)

        # Landscape: networks on the left, name, password and keyboard on the right, so nothing scrolls. Portrait stacks them.
        columns = Gtk.Box(spacing=24); columns.set_homogeneous(True); columns.set_vexpand(True); self.wifi_columns = columns; page.append(columns)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); left.set_vexpand(True); columns.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); columns.append(right)
        scan_row = Gtk.Box(spacing=12); scan_row.append(self.label("NEARBY NETWORKS", "eyebrow")); scan_row.get_first_child().set_hexpand(True)
        self.wifi_scan_button = self.button("Scan", self.wifi_scan, "settings-action wifi-scan"); scan_row.append(self.wifi_scan_button); left.append(scan_row)
        self.wifi_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_vexpand(True); scroll.set_min_content_height(150)
        scroll.set_child(self.wifi_list); elastic_vertical_scroll(scroll); left.append(scroll)

        self.wifi_ssid = Gtk.Entry(); self.wifi_ssid.set_placeholder_text("Network name"); self.wifi_ssid.add_css_class("wifi-entry")
        self.wifi_password = Gtk.Entry(); self.wifi_password.set_placeholder_text("Password"); self.wifi_password.set_visibility(False); self.wifi_password.add_css_class("wifi-entry")
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
                if isinstance(row.get_child(), Gtk.Label): row.get_child().set_xalign(0)
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
