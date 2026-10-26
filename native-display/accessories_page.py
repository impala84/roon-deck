"""Surface Dial settings ("Controls"), inside the existing display window.

Only Bluetooth accessories live here. VPN is managed in the web Settings, never on the touchscreen.
"""
import json
import threading
import urllib.request
import urllib.error

from native_common import BUS, FamilyIcon, Gtk, GLib, get_json

DIAL_ACTIONS = ("none", "playpause", "next", "previous", "mute")
DIAL_LABELS = ["No action", "Play / pause", "Next track", "Previous track", "Mute / unmute"]
SENSITIVITY = ("fine", "normal", "fast")


class AccessoriesPageMixin:
    def build_accessories(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.add_css_class("page"); page.add_css_class("settings-page"); page.add_css_class("controls-page")
        top = Gtk.Box(spacing=20); top.add_css_class("settings-header")
        title = self.label("Controls", "settings-title"); title.set_hexpand(True); title.set_halign(Gtk.Align.START); title.set_valign(Gtk.Align.CENTER)
        top.append(title)
        # Same circular control as the Settings close button.
        back = Gtk.Button(); back.add_css_class("settings-close"); back.set_size_request(58, 58)
        back.set_hexpand(False); back.set_vexpand(False); back.set_halign(Gtk.Align.CENTER); back.set_valign(Gtk.Align.CENTER)
        back.set_tooltip_text("Back to Settings"); back.set_child(FamilyIcon("back", 32, stroke_width=3))
        back.connect("clicked", self.close_accessories); self.accessory_back = back
        utilities = Gtk.Box(spacing=12); utilities.add_css_class("settings-utilities"); utilities.set_valign(Gtk.Align.START); utilities.append(back)
        top.append(utilities); page.append(top)
        divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); divider.add_css_class("settings-divider"); page.append(divider)

        self.accessory_message = self.label("", "settings-diagnostic"); self.accessory_message.set_wrap(True); self.accessory_message.set_xalign(0)
        page.append(self.accessory_message)

        self.accessory_buttons = []
        self.accessory_tabs = {}
        tabs = Gtk.Box(spacing=10); tabs.set_homogeneous(True)
        for name, text in (("device", "SURFACE DIAL"), ("volume", "VOLUME"), ("buttons", "BUTTONS")):
            choice = self.button(text, lambda _button, selected=name: self.show_accessory_tab(selected), "theme-choice")
            choice.add_css_class("settings-theme-choice"); self.accessory_tabs[name] = choice; tabs.append(choice)
        page.append(tabs)

        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_vexpand(True)
        self.accessory_scroll = scroll
        self.accessory_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.accessory_stack.set_hhomogeneous(True); self.accessory_stack.set_vhomogeneous(False)
        scroll.set_child(self.accessory_stack); page.append(scroll)

        def action(parent, text, operation, css="settings-action"):
            widget = self.button(text, lambda *_: self.accessory_operation(operation), css)
            widget.set_hexpand(True); self.accessory_buttons.append(widget); parent.append(widget)
            return widget

        def pane(name):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14); box.add_css_class("settings-card")
            self.accessory_stack.add_named(box, name); return box

        def row(parent):
            line = Gtk.Box(spacing=12); line.set_homogeneous(True); parent.append(line); return line

        def toggle(parent, text):
            line = Gtk.Box(spacing=8); line.add_css_class("setting-line")
            check = Gtk.CheckButton(label=text); line.append(check); parent.append(line)
            return check

        def dropdown(parent, heading, strings):
            if heading: parent.append(self.label(heading, "eyebrow"))
            choice = Gtk.DropDown.new_from_strings(strings); choice.add_css_class("settings-select"); parent.append(choice)
            return choice

        # SURFACE DIAL: find, pair and switch it on.
        device = pane("device")
        self.accessory_dial_status = self.label("Not running", "settings-diagnostic"); self.accessory_dial_status.set_wrap(True); self.accessory_dial_status.set_xalign(0)
        device.append(self.accessory_dial_status)
        line = row(device)
        action(line, "REFRESH", "status"); action(line, "SCAN", "bluetooth_scan")
        self.accessory_devices = []
        self.accessory_device = dropdown(device, "", ["Choose a Surface Dial"])
        line = row(device); line.set_spacing(10)
        action(line, "PAIR", "bluetooth_pair"); action(line, "CONNECT", "bluetooth_connect")
        action(line, "DISCONNECT", "bluetooth_disconnect")
        # Forget needs a second tap instead of a modal window.
        self.accessory_forget_pending = False
        self.accessory_forget = action(line, "FORGET", "bluetooth_forget")
        self.accessory_enabled = toggle(device, "Enable Roon controls")
        note = self.label("Put the Dial in pairing mode, scan, pair, then enable Roon controls and save. Turning the Dial changes the volume of the selected Roon zone from any screen.", "settings-diagnostic")
        note.set_wrap(True); note.set_xalign(0); device.append(note)

        # VOLUME: which zone, how fast, how loud.
        volume = pane("volume")
        self.accessory_outputs = []
        self.accessory_target = dropdown(volume, "ZONE", ["Follow selected Roon zone"])
        self.accessory_sensitivity = dropdown(volume, "SENSITIVITY", ["Fine", "Normal", "Fast"])
        self.accessory_acceleration = toggle(volume, "Accelerate fast rotation")
        limit_row = Gtk.Box(spacing=12)
        limit_line = Gtk.Box(spacing=8); limit_line.add_css_class("setting-line"); limit_line.set_hexpand(True)
        self.accessory_limit_enabled = Gtk.CheckButton(label="Limit volume"); limit_line.append(self.accessory_limit_enabled); limit_row.append(limit_line)
        self.accessory_limit = Gtk.SpinButton.new_with_range(-150, 100, .5); self.accessory_limit.add_css_class("settings-select")
        self.accessory_limit.set_sensitive(False); self.accessory_limit.set_hexpand(True); limit_row.append(self.accessory_limit); volume.append(limit_row)
        self.accessory_limit_enabled.connect("toggled", lambda check: self.accessory_limit.set_sensitive(check.get_active()))
        note = self.label("The limit uses the units Roon shows for the output (dB or 0–100). Fixed-volume outputs cannot be changed.", "settings-diagnostic")
        note.set_wrap(True); note.set_xalign(0); volume.append(note)

        # BUTTONS: what pressing the Dial does in Roon.
        buttons = pane("buttons")
        self.accessory_mappings = {}
        for name, heading in (("single", "SINGLE PRESS"), ("double", "DOUBLE PRESS"), ("long", "LONG PRESS")):
            self.accessory_mappings[name] = dropdown(buttons, heading, DIAL_LABELS)
        note = self.label("A single press waits a moment to tell whether a second press follows.", "settings-diagnostic")
        note.set_wrap(True); note.set_xalign(0); buttons.append(note)

        save = self.button("SAVE", lambda *_: self.accessory_operation("dial_save"), "settings-action")
        self.accessory_buttons.append(save); self.accessory_save = save; page.append(save)

        self.accessory_snapshot = {}
        self.accessory_poll = None
        self.show_accessory_tab("device")
        return page

    def show_accessory_tab(self, name):
        self.accessory_stack.set_visible_child_name(name)
        for key, choice in self.accessory_tabs.items():
            (choice.add_css_class if key == name else choice.remove_css_class)("active")
        adjustment = self.accessory_scroll.get_vadjustment(); adjustment.set_value(adjustment.get_lower())

    def sync_accessory_visibility(self, features):
        dial = features.get("dial") is True
        self.settings_accessories_button.set_visible(dial)
        if not dial: self.settings_sections.set_visible_child_name("main")

    def open_accessories(self, *_):
        self.settings_sections.set_visible_child_name("accessories")
        self.show_accessory_tab("device")
        self.accessory_message.set_text("")
        self.accessory_operation("status", fill=True)

    def close_accessories(self, *_):
        self.settings_sections.set_visible_child_name("main")

    def accessory_operation(self, operation, fill=False):
        if getattr(self, "accessory_busy", False): return
        fill = fill or operation in {"bluetooth_disconnect", "bluetooth_forget", "dial_save"}
        selected = self.accessory_device.get_selected()
        address = self.accessory_devices[selected]["address"] if selected < len(self.accessory_devices) else ""
        data = {"operation": operation, "address": address}
        if operation == "bluetooth_forget" and self.accessory_forget_pending != address:
            self.accessory_forget_pending = address
            self.accessory_forget.set_label("TAP AGAIN")
            return
        self.accessory_forget_pending = False; self.accessory_forget.set_label("FORGET")
        if operation == "dial_save":
            index = self.accessory_target.get_selected()
            config = {"enabled": self.accessory_enabled.get_active(), "address": address,
                      "target": "output" if index > 0 else "selected", "output_id": self.accessory_outputs[index - 1]["id"] if 0 < index <= len(self.accessory_outputs) else "",
                      "sensitivity": SENSITIVITY[self.accessory_sensitivity.get_selected()],
                      "acceleration": self.accessory_acceleration.get_active(),
                      "maximum_volume": self.accessory_limit.get_value() if self.accessory_limit_enabled.get_active() else None}
            for name, choice in self.accessory_mappings.items():
                config[name] = DIAL_ACTIONS[choice.get_selected()]
            data["config"] = config
        self.accessory_busy = True
        for widget in self.accessory_buttons: widget.set_sensitive(False)
        self.accessory_message.set_text("Working…")

        def work():
            error, result, snapshot, outputs = "", {}, None, None
            try:
                if operation != "status":
                    request = urllib.request.Request(BUS + "/api/admin/accessories", data=json.dumps(data).encode(),
                                                     headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(request, timeout=65) as response: result = json.load(response)
                snapshot = get_json(BUS + "/api/admin/accessories", timeout=60)
                if not snapshot: error = "Dial status is unavailable. Check the web Settings for details."
                if fill: outputs = get_json(BUS + "/roon/api/accessory/outputs", timeout=3)
            except urllib.error.HTTPError as exc:
                try: error = json.load(exc).get("error", "Could not apply this setting.")
                except (ValueError, OSError): error = "Could not apply this setting."
            except (ValueError, OSError): error = "The connection timed out. Refresh before retrying."
            GLib.idle_add(self.finish_accessory_operation, snapshot, outputs, result, error, fill)
        threading.Thread(target=work, daemon=True).start()

    def finish_accessory_operation(self, snapshot, outputs, result, error, fill):
        self.accessory_busy = False
        for widget in self.accessory_buttons: widget.set_sensitive(True)
        message = error or ("Saved." if result.get("ok") and not result.get("scanning") and not result.get("pairing") else "")
        self.accessory_message.set_text(message)
        if not snapshot: return False
        installation = snapshot.get("installation", {})
        pairing = snapshot.get("pairing", {})
        if installation.get("status") in {"installing", "error"}: self.accessory_message.set_text(installation.get("message", ""))
        if pairing.get("status") in {"pairing", "ready", "error"} and not error: self.accessory_message.set_text(pairing.get("message", ""))
        if snapshot.get("scanning"): self.accessory_message.set_text("Scanning for Surface Dial… keep its pairing light flashing.")
        elif snapshot.get("scan_message") and not error: self.accessory_message.set_text(snapshot["scan_message"])
        # Poll while Bluetooth is working in the background.
        if (pairing.get("status") == "pairing" or snapshot.get("scanning")) and not getattr(self, "accessory_poll", None):
            def poll():
                self.accessory_poll = None
                if self.settings_sections.get_visible_child_name() == "accessories":
                    self.accessory_operation("status")
                return False
            self.accessory_poll = GLib.timeout_add(2000, poll)
        self.accessory_snapshot = snapshot
        self.sync_accessory_visibility(snapshot.get("features", {}))
        status = snapshot.get("dial_hint") or snapshot.get("dial_status", "Not running")
        self.accessory_dial_status.set_text(status)
        previous = self.accessory_device.get_selected()
        address = snapshot["dial"]["address"] if fill else self.accessory_devices[previous]["address"] if previous < len(self.accessory_devices) else ""
        self.accessory_devices = snapshot["devices"]
        names = [f"Surface Dial · {'Connected' if device['connected'] else 'Paired' if device['paired'] else 'Not paired'}" + (f" · {device['battery']}%" if device['battery'] is not None else "") for device in self.accessory_devices]
        self.accessory_device.set_model(Gtk.StringList.new(names or ["No Surface Dial found"]))
        for index, device in enumerate(self.accessory_devices):
            if device["address"] == address: self.accessory_device.set_selected(index)
        if fill:
            config = snapshot["dial"]
            self.accessory_enabled.set_active(config["enabled"])
            self.accessory_sensitivity.set_selected(SENSITIVITY.index(config["sensitivity"]))
            self.accessory_acceleration.set_active(config["acceleration"])
            self.accessory_limit_enabled.set_active(config["maximum_volume"] is not None)
            self.accessory_limit.set_value(config["maximum_volume"] if config["maximum_volume"] is not None else 0)
            for name, choice in self.accessory_mappings.items():
                choice.set_selected(DIAL_ACTIONS.index(config[name]))
            self.accessory_outputs = (outputs or {}).get("outputs", [])
            self.accessory_target.set_model(Gtk.StringList.new(["Follow selected Roon zone"] + [output["name"] for output in self.accessory_outputs]))
            self.accessory_target.set_selected(0)
            for index, output in enumerate(self.accessory_outputs):
                if config["target"] == "output" and output["id"] == config["output_id"]: self.accessory_target.set_selected(index + 1)
        return False
