"""Optional remote/accessory settings, inside the existing display window."""
import json
import threading
import urllib.request
import urllib.error

from native_common import BUS, Gtk, GLib, get_json


class AccessoriesPageMixin:
    def build_accessories(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.add_css_class("page"); page.add_css_class("settings-page")
        header = Gtk.Box(spacing=10)
        title = self.label("Remote & Bluetooth", "settings-title"); title.set_hexpand(True)
        title.set_wrap(True); title.set_width_chars(1); title.set_max_width_chars(20)
        header.append(title)
        header.append(self.button("BACK", lambda *_: self.settings_sections.set_visible_child_name("main"), "settings-action"))
        page.append(header)
        self.accessory_message = self.label("Optional beta features. Refresh status to begin.", "settings-diagnostic")
        self.accessory_message.set_wrap(True); page.append(self.accessory_message)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); scroll.set_vexpand(True)
        self.accessory_scroll = scroll
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.add_css_class("settings-card"); scroll.set_child(body); page.append(scroll)
        self.accessory_buttons = []

        target = body

        def button(text, operation):
            widget = self.button(text, lambda *_: self.accessory_operation(operation), "settings-action")
            self.accessory_buttons.append(widget); target.append(widget)
            return widget

        button("REFRESH STATUS", "status")
        self.accessory_vpn_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.append(self.accessory_vpn_section); target = self.accessory_vpn_section
        target.append(self.label("NETWORK & REMOTE ACCESS", "eyebrow"))
        self.accessory_vpn = self.label("Disconnected", "settings-diagnostic"); self.accessory_vpn.set_wrap(True); target.append(self.accessory_vpn)
        note = self.label("Import your WireGuard .conf in web Settings → Remote & Bluetooth. A connected tunnel does not prove Roon Bridge audio playback.", "settings-diagnostic")
        note.set_wrap(True); target.append(note)
        button("CONNECT · 90-SECOND TRIAL", "vpn_connect")
        self.accessory_confirm = button("KEEP THIS CONNECTION", "vpn_confirm"); self.accessory_confirm.set_visible(False)
        button("DISCONNECT REMOTE ACCESS", "vpn_disconnect")
        button("RUN CONNECTIVITY TESTS", "diagnostics")
        self.accessory_dial_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.append(self.accessory_dial_section); target = self.accessory_dial_section
        target.append(self.label("BLUETOOTH ACCESSORIES", "eyebrow"))
        self.accessory_dial_status = self.label("Not running", "settings-diagnostic"); self.accessory_dial_status.set_wrap(True); target.append(self.accessory_dial_status)
        note = self.label("Put the Surface Dial in pairing mode, then scan. Pairing does not change volume.", "settings-diagnostic")
        note.set_wrap(True); target.append(note)
        button("SCAN FOR SURFACE DIAL", "bluetooth_scan")
        self.accessory_devices = []
        self.accessory_device = Gtk.DropDown.new_from_strings(["Choose a Surface Dial"])
        self.accessory_device.add_css_class("settings-select"); target.append(self.accessory_device)
        button("PAIR DIAL", "bluetooth_pair")
        button("CONNECT DIAL", "bluetooth_connect")
        button("DISCONNECT DIAL", "bluetooth_disconnect")
        # Forget requires a second explicit tap rather than a modal window.
        self.accessory_forget_pending = False
        self.accessory_forget = button("FORGET DIAL…", "bluetooth_forget")
        self.accessory_enabled = Gtk.CheckButton(label="Enable Roon controls"); target.append(self.accessory_enabled)
        self.accessory_outputs = []
        self.accessory_target = Gtk.DropDown.new_from_strings(["Follow selected Roon zone"])
        self.accessory_target.add_css_class("settings-select"); target.append(self.accessory_target)
        target.append(self.label("VOLUME SENSITIVITY", "eyebrow"))
        self.accessory_sensitivity = Gtk.DropDown.new_from_strings(["Fine", "Normal", "Fast"])
        self.accessory_sensitivity.add_css_class("settings-select"); target.append(self.accessory_sensitivity)
        self.accessory_acceleration = Gtk.CheckButton(label="Accelerate fast rotation"); target.append(self.accessory_acceleration)
        self.accessory_limit_enabled = Gtk.CheckButton(label="Limit Dial volume (Roon output units)"); target.append(self.accessory_limit_enabled)
        self.accessory_limit = Gtk.SpinButton.new_with_range(-150, 100, .5); self.accessory_limit.add_css_class("settings-select"); self.accessory_limit.set_sensitive(False); target.append(self.accessory_limit)
        self.accessory_limit_enabled.connect("toggled", lambda check: self.accessory_limit.set_sensitive(check.get_active()))
        note = self.label("Fixed-volume outputs cannot be adjusted. Use dB or the number scale shown by Roon. Haptics are not enabled in this beta.", "settings-diagnostic")
        note.set_wrap(True); target.append(note)
        self.accessory_mappings = {}
        for name, label in (("single", "SINGLE PRESS"), ("double", "DOUBLE PRESS"), ("long", "LONG PRESS")):
            target.append(self.label(label, "eyebrow"))
            choice = Gtk.DropDown.new_from_strings(["No action", "Play / pause", "Next track", "Previous track", "Mute / unmute"])
            choice.add_css_class("settings-select"); target.append(choice); self.accessory_mappings[name] = choice
        button("SAVE DIAL CONFIGURATION", "dial_save")
        self.accessory_snapshot = {}
        self.accessory_vpn_section.set_visible(False); self.accessory_dial_section.set_visible(False)
        return page

    def sync_accessory_visibility(self, features):
        vpn, dial = features.get("vpn") is True, features.get("dial") is True
        self.settings_accessories_button.set_visible(vpn or dial)
        self.settings_accessories_button.set_label("REMOTE & BLUETOOTH" if vpn and dial else "REMOTE ACCESS" if vpn else "BLUETOOTH ACCESSORIES")
        self.accessory_vpn_section.set_visible(vpn); self.accessory_dial_section.set_visible(dial)
        if not (vpn or dial): self.settings_sections.set_visible_child_name("main")

    def open_accessories(self, *_):
        self.settings_sections.set_visible_child_name("accessories")
        self.accessory_operation("status", fill=True)

    def accessory_operation(self, operation, fill=False):
        if getattr(self, "accessory_busy", False): return
        fill = fill or operation in {"bluetooth_disconnect", "bluetooth_forget", "dial_save"}
        selected = self.accessory_device.get_selected()
        address = self.accessory_devices[selected]["address"] if selected < len(self.accessory_devices) else ""
        data = {"operation": operation, "address": address}
        if operation == "bluetooth_forget" and self.accessory_forget_pending != address:
            self.accessory_forget_pending = address
            self.accessory_forget.set_label("TAP AGAIN TO FORGET DIAL")
            return
        self.accessory_forget_pending = False; self.accessory_forget.set_label("FORGET DIAL…")
        if operation == "vpn_confirm": data["token"] = self.accessory_snapshot.get("vpn", {}).get("pending_token", "")
        if operation == "dial_save":
            index = self.accessory_target.get_selected()
            config = {"enabled": self.accessory_enabled.get_active(), "address": address,
                      "target": "output" if index > 0 else "selected", "output_id": self.accessory_outputs[index - 1]["id"] if 0 < index <= len(self.accessory_outputs) else "",
                      "sensitivity": ("fine", "normal", "fast")[self.accessory_sensitivity.get_selected()],
                      "acceleration": self.accessory_acceleration.get_active(),
                      "maximum_volume": self.accessory_limit.get_value() if self.accessory_limit_enabled.get_active() else None}
            for name, choice in self.accessory_mappings.items():
                config[name] = ("none", "playpause", "next", "previous", "mute")[choice.get_selected()]
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
                if not snapshot: error = "Accessory status is unavailable. Check the web Settings for details."
                if fill: outputs = get_json(BUS + "/roon/api/accessory/outputs", timeout=3)
            except urllib.error.HTTPError as exc:
                try: error = json.load(exc).get("error", "Could not apply this setting.")
                except (ValueError, OSError): error = "Could not apply this setting."
            except (ValueError, OSError): error = "The connection timed out. Refresh status before retrying."
            GLib.idle_add(self.finish_accessory_operation, snapshot, outputs, result, error, fill)
        threading.Thread(target=work, daemon=True).start()

    def finish_accessory_operation(self, snapshot, outputs, result, error, fill):
        self.accessory_busy = False
        for widget in self.accessory_buttons: widget.set_sensitive(True)
        message = error or "Settings updated. Refresh status to check connection progress."
        if result.get("diagnostics"):
            labels = {"home_gateway_reachable": "Gateway", "home_server_reachable": "Home server", "roon_bridge_running": "Bridge service", "roon_connected": "Roon controller"}
            message = " · ".join(f"{labels.get(name, name)}: {'not configured' if value is None else 'yes' if value else 'no'}" for name, value in result["diagnostics"].items())
        self.accessory_message.set_text(message)
        if not snapshot: return False
        if snapshot.get("installation", {}).get("status") in {"installing", "error"}:
            self.accessory_message.set_text(snapshot["installation"]["message"])
        self.accessory_snapshot = snapshot
        self.sync_accessory_visibility(snapshot.get("features", {}))
        self.accessory_dial_status.set_text(snapshot.get("dial_status", "Not running"))
        vpn = snapshot["vpn"]
        text = vpn["status"] + (" · " + vpn["address"] if vpn["address"] else "")
        if vpn["pending_token"]: text += f" · Confirm within {vpn['confirm_seconds']} seconds"
        self.accessory_vpn.set_text(text); self.accessory_confirm.set_visible(bool(vpn["pending_token"]))
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
            self.accessory_sensitivity.set_selected(("fine", "normal", "fast").index(config["sensitivity"]))
            self.accessory_acceleration.set_active(config["acceleration"])
            self.accessory_limit_enabled.set_active(config["maximum_volume"] is not None)
            self.accessory_limit.set_value(config["maximum_volume"] if config["maximum_volume"] is not None else 0)
            for name, choice in self.accessory_mappings.items():
                choice.set_selected(("none", "playpause", "next", "previous", "mute").index(config[name]))
            self.accessory_outputs = (outputs or {}).get("outputs", [])
            self.accessory_target.set_model(Gtk.StringList.new(["Follow selected Roon zone"] + [output["name"] for output in self.accessory_outputs]))
            self.accessory_target.set_selected(0)
            for index, output in enumerate(self.accessory_outputs):
                if config["target"] == "output" and output["id"] == config["output_id"]: self.accessory_target.set_selected(index + 1)
        return False
