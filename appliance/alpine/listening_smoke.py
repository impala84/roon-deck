"""Render optional listening controls in real GTK without contacting devices."""
import importlib.util
import os
from pathlib import Path
import subprocess
import time
from native_harness import patch_native
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

spec = importlib.util.spec_from_file_location("native_listening", "/opt/pi-home/native-display/roondeck_native.py")
native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
Gtk.init()
width = int(os.environ["PI_HOME_SCREEN_WIDTH"]); height = int(os.environ["PI_HOME_SCREEN_HEIGHT"])
window = Gtk.Window(default_width=width, default_height=height)
window.set_decorated(False); window.set_resizable(False); window.add_css_class("theme-roon")
if height > width:
    window.add_css_class("portrait")
    if width < 600: window.add_css_class("compact-portrait")
elif width <= 820: window.add_css_class("original-landscape")
provider = Gtk.CssProvider(); provider.load_from_data(native.CSS)
Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
display = native.Display(); display.home_tile_provider = Gtk.CssProvider(); display.window = window; display.settings_data = {"display_theme": "roon"}
display.viewport_width = width; display.viewport_height = height
display.stack = Gtk.Stack(); display.stack.add_named(display.build_home(), "home"); window.set_child(display.stack)
keys = ("roondeck.kef", "roondeck.kef_power", "roondeck.kef_input", "roondeck.kef_volume")
home = {"status":"ok", "cards": {key:{"show":True,"rows":2 if key == keys[0] else 1,"size":"half" if key == keys[0] else "quarter"} for key in keys}, "entities":[]}
display.render_home(home)
state = {"enabled":True,"kef":{"connected":True,"powered":True,"input":"aux","volume":20,"muted":False},
         "ir_available":True,"error":""}
display.render_listening(state)
window.present()
def settle():
    end = time.monotonic() + .5
    while time.monotonic() < end:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.01)
settle()
assert window.get_width() == width and window.get_height() == height, (width,height,window.get_width(),window.get_height())
def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child); child = child.get_next_sibling()
assert len(display.kef_tiles) == 4
assert not hasattr(display, "listening_box")
assert all(card.get_parent() is not None for card in display.kef_tiles.values())
buttons = {widget.get_label():widget for widget in walk(display.kef_tiles["roondeck.kef_volume"]) if isinstance(widget,Gtk.Button)}
calls = []
restore = patch_native(native, "post_json", lambda *args, **kwargs: calls.append(args) or {"ok":True})
buttons["+"].emit("clicked")
settle()
assert calls and calls[0][1] == {"action":"volume_delta","value":2}, calls
restore()
output = Path(os.environ["PI_HOME_SCREENSHOT_DIR"])
subprocess.run(["import","-silent","-window","root",str(output / f"listening-{width}x{height}.png")],check=True)
display.render_listening({**state, "kef": {"connected":True, "powered":True, "input":"wifi", "volume":20, "control_path":"roon", "direct_inputs_available":False}, "ir_available":False})
settle()
pick = display.kef_tiles["roondeck.kef_input"].input_pick
assert pick.get_model().get_n_items() == 2
state = {**state, "kef": {"connected":False, "direct_inputs_available":False}, "ir_available":True, "notice":"Sent AUX via infrared. Input readback is unavailable."}
display.render_listening(state)
settle()
pick = display.kef_tiles["roondeck.kef_input"].input_pick
assert pick.get_sensitive() and pick.get_model().get_n_items() == 5
assert "readback is unavailable" in display.kef_tiles["roondeck.kef_input"].feedback.get_text()
calls = []; display.listening_command = lambda action, value: calls.append((action, value))
pick.set_selected(2)
assert calls == [("input", "aux")] and pick.get_selected() == 0
# A moved tile keeps its controls; removing it leaves no panel or stale widget above the grid.
display.render_home({**home, "cards": {"roondeck.kef_input":{"show":True,"size":"half","col":0,"row":0,"label":"Study input"}}})
assert display.kef_tiles["roondeck.kef_input"].title.get_text() == "Study input"
display.render_home({"status":"ok", "entities":[], "cards":{}})
assert all(card.get_parent() is None for card in display.kef_tiles.values())
window.close()
print(f"Listening GTK checks passed at {width}x{height}")
