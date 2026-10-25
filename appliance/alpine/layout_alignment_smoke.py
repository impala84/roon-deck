"""Real GTK cross-page alignment report for the shared header and navigation.

Builds the actual Display pages in a Gtk window of the viewport size, shows each
page in turn and measures where the shared elements really sit (window
coordinates, pixels):

  header row       .page-header (Bus / Home), .discover-toolbar (Now Playing, which
                   hides the shared header) or .settings-header
  settings cog     .discover-utility inside that header
  clock / sleep    .header-clock, or the .discover-sleep icon on music pages
  navigation row   .nav

By default this only REPORTS (and writes layout-alignment.txt next to the
screenshots when PI_HOME_SCREENSHOT_DIR is set) so the first run shows the real
numbers. Set PI_HOME_LAYOUT_STRICT=1 to fail when Bus, Now Playing and Home
disagree (cog and nav) by more than PI_HOME_LAYOUT_TOLERANCE pixels (default 1).

Run with: tools/check screen layout
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

spec = importlib.util.spec_from_file_location("native_layout", "/opt/pi-home/native-display/roondeck_native.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
Gtk.init()

WIDTH = int(os.environ.get("PI_HOME_SCREEN_WIDTH", "1280"))
HEIGHT = int(os.environ.get("PI_HOME_SCREEN_HEIGHT", "720"))
STRICT = os.environ.get("PI_HOME_LAYOUT_STRICT") == "1"
TOLERANCE = float(os.environ.get("PI_HOME_LAYOUT_TOLERANCE", "1"))
SHARED_PAGES = ("bus", "roon", "home")
PAGES = SHARED_PAGES + ("settings",)


def settle():
    for _ in range(60):
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.01)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child)
        child = child.get_next_sibling()


def find(root, css_class):
    """First mapped descendant (or root) carrying css_class."""
    for widget in walk(root):
        if widget.has_css_class(css_class) and widget.get_mapped():
            return widget
    return None


def bounds(widget, window):
    if widget is None:
        return None
    valid, rect = widget.compute_bounds(window)
    if not valid:
        return None
    return (round(rect.get_x(), 1), round(rect.get_y(), 1), round(rect.get_width(), 1), round(rect.get_height(), 1))


window = Gtk.Window(default_width=WIDTH, default_height=HEIGHT)
window.set_decorated(False)
window.set_resizable(False)
provider = Gtk.CssProvider()
provider.load_from_data(native.CSS)
Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

display = native.Display()
display.window = window
# Mirror Display.do_activate: build every page into one stack.
display.home_color_provider = Gtk.CssProvider()
Gtk.StyleContext.add_provider_for_display(window.get_display(), display.home_color_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
display.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, transition_duration=0)
display.stack.set_hhomogeneous(False)
display.stack.set_vhomogeneous(False)
pages = {}
for name, builder in (
    ("boot", display.build_boot_splash),
    ("bus", display.build_bus),
    ("roon", display.build_roon),
    ("home", display.build_home),
    ("settings", display.build_settings),
    ("sleep", display.build_sleep),
):
    pages[name] = builder()
    display.stack.add_named(pages[name], name)
window.set_child(display.stack)
window.present()
settle()
display.adapt_display()
settle()

measurements = {}
header_kind = {}
for name in PAGES:
    display.stack.set_visible_child_name(name)
    settle()
    page = pages[name]
    # The Now Playing page hides the shared .page-header and uses .discover-toolbar
    # as its header, so measure whichever header is actually mapped.
    header = find(page, "discover-toolbar")
    kind = "discover-toolbar"
    if header is None:
        header, kind = find(page, "page-header"), "page-header"
    if header is None:
        header, kind = find(page, "settings-header"), "settings-header"
    header_kind[name] = kind if header is not None else "none"
    cog = clock = None
    if header is not None:
        for widget in walk(header):
            if not widget.get_mapped():
                continue
            if widget.has_css_class("discover-utility") and not widget.has_css_class("discover-sleep") and cog is None:
                cog = widget
            if (widget.has_css_class("header-clock") or widget.has_css_class("discover-sleep")) and clock is None:
                clock = widget
    measurements[name] = {
        "header row": bounds(header, window),
        "settings cog": bounds(cog, window),
        "clock / sleep": bounds(clock, window),
        "navigation": bounds(find(page, "nav"), window),
    }

lines = [f"Layout alignment at {WIDTH}x{HEIGHT} (x, y, width, height in window pixels)"]
for element in ("header row", "settings cog", "clock / sleep", "navigation"):
    lines.append(f"  {element}")
    for name in PAGES:
        value = measurements[name][element]
        suffix = f"   [{header_kind[name]}]" if element == "header row" else ""
        lines.append(f"    {name:9} {'not present' if value is None else '%7.1f %7.1f %7.1f %7.1f' % value}{suffix}")

problems = []
# Header rows may legitimately differ in height (different widgets); the cog and
# navigation are the things that must stay put between pages.
for element in ("settings cog", "navigation"):
    present = {name: measurements[name][element] for name in SHARED_PAGES if measurements[name][element]}
    if len(present) < 2:
        continue
    for axis, label in ((0, "x"), (1, "y"), (2, "width"), (3, "height")):
        values = [value[axis] for value in present.values()]
        if max(values) - min(values) > TOLERANCE:
            problems.append(f"{element}: {label} differs across pages " + ", ".join(f"{n}={v[axis]}" for n, v in present.items()))
# Clock width follows its content (full time on Bus/Home, an icon on music pages),
# so compare only its right edge.
clock = {name: measurements[name]["clock / sleep"] for name in SHARED_PAGES if measurements[name]["clock / sleep"]}
if len(clock) >= 2:
    values = [v[0] + v[2] for v in clock.values()]
    if max(values) - min(values) > TOLERANCE:
        problems.append("clock / sleep: right edge differs across pages " + ", ".join(f"{n}={v[0] + v[2]:.1f}" for n, v in clock.items()))

lines.append("")
lines.extend(["MISMATCH " + problem for problem in problems] or ["Cog and navigation agree between Bus / Now Playing / Home within %.1fpx." % TOLERANCE])
report = "\n".join(lines)
print(report, flush=True)

output = os.environ.get("PI_HOME_SCREENSHOT_DIR")
if output:
    Path(output, "layout-alignment.txt").write_text(report + "\n", encoding="utf-8")
if STRICT and problems:
    sys.exit(1)
