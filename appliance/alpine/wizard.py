"""Touch-first RoonDeck Alpine onboarding."""
import json
import socket
import threading
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
from setup_service import SOCKET

BRAND_ASSETS = Path(__file__).resolve().parent / "assets" / "brand"


def wordmark_picture(target_height=26):
    source = GdkPixbuf.Pixbuf.new_from_file(str(BRAND_ASSETS / "roondeck-wordmark.svg"))
    width = round(target_height * source.get_width() / source.get_height())
    scaled = source.scale_simple(width, target_height, GdkPixbuf.InterpType.BILINEAR)
    picture = Gtk.Picture.new_for_pixbuf(scaled); picture.set_size_request(width, target_height)
    picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.CONTAIN)
    return picture


def request(data):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(50); client.connect(SOCKET)
        client.sendall((json.dumps(data) + "\n").encode())
        return json.loads(client.makefile("rb").readline(65536))


class Wizard(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="uk.co.dallabs.PiHome.Setup")
        self.stage = 0; self.progress = {}; self.entry = None; self.fields = []; self.shift = False; self.symbols = False; self.busy = False; self.initial = True
        self.connect("activate", self.activate)

    @staticmethod
    def screen_size():
        try:
            monitor = Gdk.Display.get_default().get_monitors().get_item(0).get_geometry()
            return monitor.width, monitor.height
        except (AttributeError, TypeError):
            return 800, 480

    @classmethod
    def display_scale(cls):
        """Text and touch targets grow with the panel; the 800x480 original stays 1.0."""
        return max(1.0, min(min(cls.screen_size()) / 480, 2.2))

    @staticmethod
    def stylesheet(scale, height=480):
        def px(value): return round(value * scale)
        # Five keyboard rows must leave room for the form above them.
        key_height = round(min(34 * scale, max(34, height * 0.06)))
        return (
            "window { background:#1c1b24; color:#f5f5f5; } "
            f"button {{ min-height:{px(40)}px; padding:{px(4)}px {px(10)}px; background:#302d42; color:#fff; border-radius:{px(8)}px; font-size:{px(17)}px; }} "
            "button:active {background:#9868F9;color:#111;} "
            f"entry {{ min-height:{px(40)}px; font-size:{px(20)}px; background:#282631;color:#fff; }} "
            f".title {{font-size:{px(25)}px;font-weight:700;color:#9868F9;}} .brand {{min-width:0;min-height:0;}} .primary {{background:#9868F9;color:#111;}} "
            f".key {{min-height:{key_height}px;padding:{px(2)}px;}} label {{font-size:{px(17)}px;}} checkbutton {{font-size:{px(17)}px;}} "
            f"check {{min-width:{px(22)}px;min-height:{px(22)}px;}} dropdown {{font-size:{px(17)}px;}} dropdown button {{min-height:{px(40)}px;}} "
            ".mint .title {color:#6ed9ae;} .mint .primary, .mint button:active {background:#6ed9ae;}"
        )

    def label(self, text):
        label = Gtk.Label(label=text); label.set_wrap(True); label.set_xalign(0); return label

    def check(self, text):
        """CheckButton whose label wraps; long options otherwise widen the page past the screen."""
        button = Gtk.CheckButton(); button.set_child(self.label(text)); return button

    def button(self, title, callback):
        button = Gtk.Button(label=title); button.connect("clicked", lambda *_: callback()); return button

    def activate(self, *_):
        self.window = Gtk.ApplicationWindow(application=self); self.window.set_title("Set up RoonDeck"); self.window.set_default_size(*self.screen_size()); self.window.fullscreen()
        self.window.set_cursor_from_name("none")
        self.scale = self.display_scale()
        css = Gtk.CssProvider(); css.load_from_data(self.stylesheet(self.scale, self.screen_size()[1]).encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(8 * self.scale))
        for edge in ("start", "end", "top", "bottom"): getattr(self.outer, "set_margin_" + edge)(round(14 * self.scale))
        header = Gtk.Box(spacing=round(14 * self.scale))
        brand = wordmark_picture(round(26 * self.scale)); brand.add_css_class("brand"); brand.set_halign(Gtk.Align.START); brand.set_valign(Gtk.Align.CENTER); header.append(brand)
        self.title = self.label("Welcome to RoonDeck"); self.title.add_css_class("title"); header.append(self.title); self.outer.append(header)
        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(10 * self.scale)); scroll.set_child(self.content); self.outer.append(scroll)
        self.status = self.label(""); self.outer.append(self.status)
        self.keyboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(3 * self.scale)); self.outer.append(self.keyboard)
        self.footer = Gtk.Box(spacing=round(10 * self.scale)); self.outer.append(self.footer)
        self.window.set_child(self.outer); self.window.present()
        self.refresh()

    def async_call(self, data, callback):
        if self.busy: return
        self.busy = True; self.footer.set_sensitive(False); self.content.set_sensitive(False); self.keyboard.set_sensitive(False); self.status.set_text("Working…")
        def worker():
            try: result = request(data)
            except (OSError, ValueError): result = {"ok": False, "error": "Setup service is starting. Please retry."}
            GLib.idle_add(done, result)
        def done(result):
            self.busy = False; self.footer.set_sensitive(True); self.content.set_sensitive(True); self.keyboard.set_sensitive(True)
            self.status.set_text("" if result.get("ok") else result.get("error", "Please try again."))
            if result.get("ok"): callback(result)
            return False
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        def loaded(result):
            self.progress = result.get("progress", {})
            if self.progress.get("complete"): self.quit(); return
            if self.initial and self.progress:
                self.stage = next((index for index, key in enumerate(("orientation", "hostname", "network", "roon", "display", "software")) if not self.progress.get(key)), 6)
            self.initial = False
            self.snapshot = result
            if self.stage == 5 and self.progress.get("software"): self.stage = 6
            self.render()
            if result.get("software_busy"):
                GLib.timeout_add_seconds(2, lambda: (self.refresh(), False)[1])
        self.async_call({"action": "status"}, loaded)

    def clear(self, box):
        while child := box.get_first_child(): box.remove(child)

    def field(self, placeholder, text="", secret=False):
        entry = Gtk.Entry(); entry.set_placeholder_text(placeholder); entry.set_text(text); entry.set_visibility(not secret)
        focus = Gtk.EventControllerFocus(); focus.connect("enter", lambda *_: self.select_entry(entry)); entry.add_controller(focus)
        self.fields.append(entry); self.content.append(entry); return entry

    def secret_field(self, placeholder):
        entry = self.field(placeholder, secret=True)
        show = self.check("Show password")
        show.connect("toggled", lambda toggle: entry.set_visibility(toggle.get_active()))
        self.content.append(show)
        return entry

    def select_entry(self, entry):
        self.entry = entry; self.keyboard.set_visible(True); self.draw_keyboard()

    def draw_keyboard(self):
        self.clear(self.keyboard)
        rows = ("1234567890", "!@#$%^&*()", "-_=+[]{}:/", "\\|;,.?<>~`") if self.symbols else ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm-._@")
        for chars in rows:
            row = Gtk.Box(spacing=round(3 * self.scale)); row.set_homogeneous(True)
            for char in chars:
                value = char.upper() if self.shift else char
                key = self.button(value, lambda c=value: self.type_key(c)); key.add_css_class("key"); key.set_focusable(False); row.append(key)
            self.keyboard.append(row)
        row = Gtk.Box(spacing=round(3 * self.scale)); row.set_homogeneous(True)
        for title, callback in (("Shift", self.toggle_shift), ("ABC" if self.symbols else "Symbols", self.toggle_symbols), ("Space", lambda: self.type_key(" ")), ("⌫", self.backspace), ("Next", self.focus_next_entry), ("Hide", lambda: self.keyboard.set_visible(False))):
            key = self.button(title, callback); key.set_focusable(False); row.append(key)
        self.keyboard.append(row)

    def toggle_shift(self): self.shift = not self.shift; self.draw_keyboard()
    def toggle_symbols(self): self.symbols = not self.symbols; self.draw_keyboard()
    def type_key(self, value):
        if self.entry:
            bounds = self.entry.get_selection_bounds()
            if bounds: self.entry.delete_text(*bounds)
            position = self.entry.get_position(); self.entry.insert_text(value, position); self.entry.set_position(position + len(value))
    def backspace(self):
        if self.entry:
            bounds = self.entry.get_selection_bounds()
            if bounds: self.entry.delete_text(*bounds)
            else:
                position = self.entry.get_position()
                if position > 0: self.entry.delete_text(position - 1, position)

    def focus_next_entry(self):
        if self.entry in self.fields:
            index = self.fields.index(self.entry) + 1
            if index < len(self.fields):
                self.entry = self.fields[index]; self.entry.grab_focus(); return
        self.keyboard.set_visible(False)

    def advance(self, data):
        def saved(result): self.progress = result["progress"]; self.stage += 1; self.refresh()
        self.async_call(data, saved)

    def render(self):
        self.clear(self.content); self.clear(self.footer); self.keyboard.set_visible(False); self.entry = None; self.fields = []
        titles = ["Choose your display", "Name your device", "Connect to your network", "Connect to Roon", "Choose theme and region", "Choose optional software", "Finish setup"]
        self.title.set_text(f"{self.stage + 1}/7 · {titles[self.stage]}")
        if self.progress.get("theme") == "fresh-mint": self.window.add_css_class("mint")
        else: self.window.remove_css_class("mint")
        if self.stage:
            self.footer.append(self.button("Back", lambda: self.back()))
        self.footer.append(self.button("Refresh", self.refresh))
        if self.stage == 0:
            self.content.append(self.label("First choose your display and orientation. This screen uses the panel’s native orientation so touch matches. We’ll restart to apply picture and touch together, then continue setup."))
            profiles = ["auto", "original", "touch2-5", "touch2-7", "touch2-10"]
            profile = Gtk.DropDown.new_from_strings(["Automatic / HDMI", "Original Touch Display", "Touch Display 2 · 5-inch", "Touch Display 2 · 7-inch", "Touch Display 2 · 10-inch"])
            profile.set_selected(profiles.index(self.progress.get("profile", "auto"))); self.content.append(profile)
            rotations = ["normal", "90", "180", "270"]
            rotation = Gtk.DropDown.new_from_strings(["Native orientation", "90° clockwise · landscape", "180°", "270° clockwise · landscape"])
            rotation.set_selected(rotations.index(self.progress.get("rotation", "normal"))); self.content.append(rotation)
            profile.connect("notify::selected", lambda *_: rotation.set_selected(1 if profiles[profile.get_selected()].startswith("touch2-") else 0))
            def apply_orientation():
                def saved(result):
                    self.progress = result["progress"]
                    self.async_call({"action": "reboot"}, lambda _: self.status.set_text("Restarting to apply display and touch orientation…"))
                self.async_call({"action": "orientation", "profile": profiles[profile.get_selected()], "rotation": rotations[rotation.get_selected()]}, saved)
            self.footer.append(self.button("Apply and restart", apply_orientation))
        elif self.stage == 1:
            self.content.append(self.label("This is its network name—for example pi-home-lounge. Web settings will be at http://NAME.local:8765/admin."))
            name = self.field("Device name", self.progress.get("hostname", "pi-home"))
            self.footer.append(self.button("Save and continue", lambda: self.advance({"action": "name", "hostname": name.get_text()})))
        elif self.stage == 2:
            self.content.append(self.label("Connected" if self.snapshot.get("connected") else "Plug in Ethernet, or enter your Wi-Fi details. Roon needs the same local network, not necessarily internet access."))
            ssid = self.field("Wi-Fi name (SSID)"); password = self.secret_field("Wi-Fi password")
            self.content.append(self.button("Connect Wi-Fi", lambda: self.advance({"action": "wifi", "ssid": ssid.get_text(), "password": password.get_text()})))
            self.footer.append(self.button("Continue with current connection", lambda: self.advance({"action": "network"})))
        elif self.stage == 3:
            self.content.append(self.label("In Roon: Settings → Extensions → enable RoonDeck. Then Refresh and choose the output you want to control. Roon Bridge can optionally turn this Pi into a separate RAAT audio endpoint."))
            zones = [zone["name"] for zone in self.snapshot.get("roon", {}).get("zones", [])]
            chooser = Gtk.DropDown.new_from_strings(zones or ["Waiting for Roon authorisation…"]); self.content.append(chooser)
            select = self.button("Use this zone", lambda: self.advance({"action": "roon", "zone": zones[chooser.get_selected()]})); select.set_sensitive(bool(zones)); self.footer.append(select)
            self.content.append(self.button("Set up Roon later", lambda: self.advance({"action": "roon", "skip": True})))
        elif self.stage == 4:
            self.content.append(self.label("Your display orientation is saved. Choose your theme and local region."))
            theme = Gtk.DropDown.new_from_strings(["Roon · purple", "Fresh Mint · full colour"]); theme.set_selected(1 if self.progress.get("theme") == "fresh-mint" else 0); self.content.append(theme)
            theme.connect("notify::selected", lambda *_: self.window.add_css_class("mint") if theme.get_selected() == 1 else self.window.remove_css_class("mint"))
            self.content.append(self.label("Choose your local timezone; it cannot be inferred reliably from the Pi. UTC is not selected automatically."))
            timezone = self.field("Timezone, e.g. Asia/Singapore", self.progress.get("timezone", ""))
            regions = ["Choose region…", "Asia/Singapore", "Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "Australia/Sydney", "Pacific/Auckland", "UTC"]
            region = Gtk.DropDown.new_from_strings(regions); self.content.append(region)
            region.connect("notify::selected", lambda *_: timezone.set_text(regions[region.get_selected()]) if region.get_selected() else None)
            self.footer.append(self.button("Save and continue", lambda: self.advance({"action": "display", "profile": self.progress["profile"], "rotation": self.progress["rotation"], "theme": ("roon", "fresh-mint")[theme.get_selected()], "timezone": timezone.get_text()})))
        elif self.stage == 5:
            self.content.append(self.label("RoonDeck already includes storage expansion, time sync, downloads and diagnostics. Choose any additional services for this Pi."))
            choices = self.progress.get("software_choices", {})
            bridge = self.check("Install Roon Bridge · use this Pi as a RAAT audio endpoint"); bridge.set_active(choices.get("roon_bridge", False)); self.content.append(bridge)
            airplay = self.check("Install AirPlay · stream audio from Apple devices"); airplay.set_active(choices.get("airplay", False)); self.content.append(airplay)
            netdata = self.check("Install Netdata · official stable Agent with automatic updates"); netdata.set_active(choices.get("netdata", False)); self.content.append(netdata)
            lightweight = self.check("Lightweight Netdata · 3-second samples, no ML anomaly detection"); lightweight.set_active(choices.get("netdata_lightweight", True)); self.content.append(lightweight)
            self.content.append(self.label("Downloads the latest official stable Agent, not Alpine’s older package. Lightweight mode disables ML and six optional collectors, keeps apps/go.d, alerts, dashboard and Cloud connectivity; memory savings vary."))
            self.content.append(self.label("Netdata Cloud can be connected later in web Settings. Downloads require internet access and may take several minutes."))
            self.content.append(self.label(self.progress.get("software_status", "")))
            def install():
                self.async_call({"action": "software", "roon_bridge": bridge.get_active(), "airplay": airplay.get_active(), "netdata": netdata.get_active(), "netdata_lightweight": lightweight.get_active()}, lambda _: self.refresh())
            self.footer.append(self.button("Install and continue", install))
            self.content.append(self.button("Continue without optional software", lambda: self.async_call({"action": "software", "roon_bridge": False, "netdata": False}, lambda _: self.refresh())))
            if self.snapshot.get("software_busy"):
                self.content.set_sensitive(False); self.footer.set_sensitive(False)
            else:
                self.content.set_sensitive(True); self.footer.set_sensitive(True)
        elif self.stage == 6:
            self.content.append(self.label(f"Web settings: http://{self.progress.get('hostname')}.local:8765/admin\nChoose the device account used for both RoonDeck settings and SSH recovery."))
            username = self.field("Device username", self.progress.get("username", "admin"))
            password = self.secret_field("Choose password")
            confirmation = self.secret_field("Enter password again")
            self.content.append(self.label("Use 8–128 characters. RoonDeck may warn about a simple password, but the choice is yours; keep it private because it controls the appliance."))
            ssh = self.check("Enable SSH (recommended for recovery)"); ssh.set_active(True); self.content.append(ssh)
            self.footer.append(self.button("Finish and restart", lambda: self.finish(username.get_text(), password.get_text(), True, confirmation.get_text(), ssh.get_active())))
            self.content.append(self.button("Finish without restart", lambda: self.finish(username.get_text(), password.get_text(), False, confirmation.get_text(), ssh.get_active())))
        child = self.footer.get_first_child()
        while child:
            child.set_hexpand(True)
            child = child.get_next_sibling()
        if self.footer.get_last_child(): self.footer.get_last_child().add_css_class("primary")

    def next(self): self.stage += 1; self.render()
    def back(self): self.stage -= 1; self.render()
    def finish(self, username, password, reboot, confirmation="", ssh=True):
        if password != confirmation:
            self.status.set_text("Passwords do not match. Please enter them again."); return
        def saved(_):
            if reboot:
                self.async_call({"action": "reboot"}, lambda _: self.quit())
            else: self.quit()
        self.async_call({"action": "finish", "username": username, "password": password, "confirmation": confirmation, "ssh": ssh}, saved)


def setup_complete(path=Path("/var/lib/pi-home-setup/progress.json")):
    """Avoid presenting a completed wizard while the slower Pi 3 boots."""
    if Path("/var/lib/pi-home/setup-complete").exists():
        return True
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("complete"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


if __name__ == "__main__" and not setup_complete(): Wizard().run(None)
