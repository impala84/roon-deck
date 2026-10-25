"""Construct all real GTK pages under Xvfb; no privileged/network actions."""
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
