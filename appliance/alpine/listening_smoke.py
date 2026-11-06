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
display = native.Display(); display.window = window; display.settings_data = {"display_theme": "roon"}
display.stack = Gtk.Stack(); display.stack.add_named(display.build_home(), "home"); window.set_child(display.stack)
display.render_home({"status":"ok","entities":[{"entity_id":"light.desk","name":"Desk light","domain":"light","state":"on","brightness":128,"supports_level":True}]})
state = {"enabled":True,"kef":{"connected":True,"powered":True,"input":"aux","volume":20,"muted":False},
         "modes":[{"id":"pi","name":"Pi / Roon","available":False,"reason":"Topping input switching is not available yet"},
                  {"id":"kef","name":"Speakers only","available":True}],"error":""}
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
buttons = {widget.get_label():widget for widget in walk(display.listening_box) if isinstance(widget,Gtk.Button)}
assert not buttons["Pi / Roon"].get_sensitive()
assert buttons["Speakers only"].get_sensitive()
calls = []
restore = patch_native(native, "post_json", lambda *args, **kwargs: calls.append(args) or {"ok":True})
buttons["+ Volume"].emit("clicked")
settle()
assert calls and calls[0][1] == {"action":"volume_delta","value":2}, calls
restore()
output = Path(os.environ["PI_HOME_SCREENSHOT_DIR"])
subprocess.run(["import","-silent","-window","root",str(output / f"listening-{width}x{height}.png")],check=True)
display.render_listening({**state,"kef":{"connected":False},"error":"Speaker unavailable"})
settle()
assert "Speaker unavailable" == display.listening_feedback.get_text()
display.render_listening({"enabled":False})
assert not display.listening_box.get_visible()
window.close()
print(f"Listening GTK checks passed at {width}x{height}")
