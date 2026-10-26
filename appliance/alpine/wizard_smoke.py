"""Construct all real GTK pages under Xvfb; no privileged/network actions."""
import os
import shutil
import subprocess
from pathlib import Path
from gi.repository import GLib, Gtk, Gdk
from wizard import Wizard

app = Wizard()
app.register(None)
app.refresh = lambda: None
app.activate()
assert app.window.get_cursor().get_name() == "none"
app.progress = {"orientation": True, "hostname": "pi-home-lounge", "network": True, "roon": True, "zone": "Lounge", "display": True, "profile": "auto", "rotation": "normal"}
app.snapshot = {"connected": True, "roon": {"zones": [{"name": "Lounge"}]}}
context = GLib.MainContext.default()
for stage in range(7):
    app.stage = stage; app.render()
    for _ in range(30):
        while context.pending(): context.iteration(False)
    assert app.content.get_first_child() is not None
    assert app.footer.get_first_child() is not None

# Text and touch targets must grow with the panel and every page, including the
# on-screen keyboard, must still fit the screen.
monitor = Gdk.Display.get_default().get_monitors().get_item(0).get_geometry()
assert app.scale == max(1.0, min(min(monitor.width, monitor.height) / 480, 2.2)), app.scale
review = os.environ.get("PI_HOME_WIZARD_REVIEW")
for stage in range(7):
    app.stage = stage; app.render()
    if app.fields: app.select_entry(app.fields[0])
    for _ in range(30):
        while context.pending(): context.iteration(False)
    footer = app.footer.compute_bounds(app.window)[1]
    assert footer.get_y() + footer.get_height() <= monitor.height + 1, (stage, footer.get_y(), footer.get_height(), monitor.height)
    if app.keyboard.get_visible():
        board = app.keyboard.compute_bounds(app.window)[1]
        assert board.get_x() >= 0 and board.get_x() + board.get_width() <= monitor.width + 1, (stage, board.get_x(), board.get_width())
        key = app.keyboard.get_first_child().get_first_child()
        assert key.get_height() >= 34 and key.get_height() >= round(min(34 * app.scale, monitor.height * 0.06)) - 2, (stage, key.get_height())
    if review and shutil.which("import"):
        out = Path(review) / f"{monitor.width}x{monitor.height}"; out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["import", "-silent", "-window", "root", str(out / f"stage-{stage + 1}.png")], check=True)
app.stage = 0; app.progress = {}; app.render()
assert "Choose your display" in app.title.get_text()
assert app.footer.get_last_child().get_label() == "Apply and restart"
calls = []
def capture(data, callback):
    calls.append(data)
    callback({"ok": True, "progress": {"orientation": True, "profile": "auto", "rotation": "normal"}})
app.async_call = capture
app.footer.get_last_child().emit("clicked")
assert [call["action"] for call in calls] == ["orientation", "reboot"]
app.initial = True
app.async_call = lambda data, callback: callback({"ok": True, "progress": {"orientation": True, "profile": "touch2-7", "rotation": "90"}})
Wizard.refresh(app)
assert app.stage == 1
app.stage = 1; app.render()
entry = app.content.get_last_child()
app.select_entry(entry); entry.set_text(""); app.type_key("abc"); app.backspace()
assert entry.get_text() == "ab"
app.toggle_shift()
app.type_key("C")
assert entry.get_text() == "abC"
app.toggle_symbols(); app.type_key("/London")
assert entry.get_text() == "abC/London"
app.stage = 2; app.render()
ssid, password = app.fields
app.select_entry(ssid); app.focus_next_entry()
assert app.entry is password and app.keyboard.get_visible()
app.focus_next_entry()
assert not app.keyboard.get_visible()
app.window.destroy()
icons = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
assert icons.has_icon("media-skip-forward-symbolic")
assert icons.has_icon("media-skip-backward-symbolic")
print("Native setup: all seven real GTK pages and on-screen keyboard passed under Xvfb (not physical touch acceptance).")
