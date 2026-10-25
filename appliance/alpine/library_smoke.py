"""Verify real GTK library-button state and square allocation, not a screenshot mock."""
import importlib.util
import time
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

spec = importlib.util.spec_from_file_location("pi_home_native_library", Path("/opt/pi-home/native-display/roondeck_native.py"))
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
Gtk.init()
context = GLib.MainContext.default()

def settle():
    for _ in range(30):
        while context.pending(): context.iteration(False)
        time.sleep(.01)

for width, height in ((800, 480), (480, 800), (1280, 720), (720, 1280), (1920, 1200), (1200, 1920)):
    window = Gtk.Window(default_width=width, default_height=height)
    window.set_decorated(False)
    window.add_css_class("theme-roon")
    provider = Gtk.CssProvider(); provider.load_from_data(native.CSS)
    Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    display = native.Display(); window.set_child(display.build_roon()); display.window = window
    display.roon_views.set_visible_child_name("now")
    window.present(); settle(); display.adapt_display()
    for state, favorite, tip in (("not_in_library", False, "Add album to library"), ("in_library", False, "Favourite album"), ("in_library", True, "Unfavourite album")):
        display.render_details({"status":"ready", "album":"Album", "track":"Track", "artist":"Artist", "library_status":state, "album_id":"123", "favorite":favorite})
        settle()
        button = display.library_add
        assert button.get_visible() and button.get_sensitive()
        assert button.get_tooltip_text() == tip
        assert button.get_width() > 0 and abs(button.get_width() - button.get_height()) <= 1, (width, height, button.get_width(), button.get_height())
    display.render_details({"status":"ready", "album":"Album", "library_status":"unknown"})
    assert not display.library_add.get_sensitive()
    window.destroy(); settle()
print("Library +/outline/filled controls have square GTK allocations at six landscape/portrait viewport sizes.")
