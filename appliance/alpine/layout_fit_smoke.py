"""Real GTK fit report: does each page stay inside the screen at every interface size?

For Smaller, Standard and Larger this builds the real pages, fills Bus Times and
Browse (Albums with the alphabet scrubber) with fixture data, and reports:

  window       the width/height GTK actually asks for (it must equal the screen)
  header       cog, title and clock bounds on Bus Times
  browse       cover size, columns, rows visible before scrolling, Back button,
               scrubber bounds and the right-hand gap to the screen edge

It reports by default and writes layout-fit.txt plus one screenshot per case into
PI_HOME_SCREENSHOT_DIR. PI_HOME_LAYOUT_STRICT=1 makes a window wider/taller than
the screen fail the run.

Run with: tools/check screen layout
"""
import html
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

WIDTH = int(os.environ.get("PI_HOME_SCREEN_WIDTH", "1280"))
HEIGHT = int(os.environ.get("PI_HOME_SCREEN_HEIGHT", "720"))
STRICT = os.environ.get("PI_HOME_LAYOUT_STRICT") == "1"
OUTPUT = Path(os.environ.get("PI_HOME_SCREENSHOT_DIR", "/screenshots"))
OUTPUT.mkdir(parents=True, exist_ok=True)
ART = Path("/tmp/pi-home-fit-art")
ART.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("native_fit", "/opt/pi-home/native-display/roondeck_native.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
Gtk.init()

PROFILES = {(1280, 720): "touch2-7", (720, 1280): "touch2-7", (1920, 1200): "touch2-10", (1200, 1920): "touch2-10", (800, 480): "original", (480, 800): "original"}


def settle(rounds=50):
    context = GLib.MainContext.default()
    for _ in range(rounds):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def capture(name):
    settle()
    subprocess.run(["import", "-silent", "-window", "root", str(OUTPUT / f"{name}.png")], check=True)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child)
        child = child.get_next_sibling()


def bounds(widget, root):
    if widget is None:
        return None
    valid, rect = widget.compute_bounds(root)
    if not valid:
        return None
    return (round(rect.get_x(), 1), round(rect.get_y(), 1), round(rect.get_width(), 1), round(rect.get_height(), 1))


def fixture_art(key):
    colours = ("4d478f", "315d78", "7a5637", "4c725d", "754461", "556b37")
    colour = colours[sum(key.encode("utf-8")) % len(colours)]
    path = ART / f"{key}.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="512" height="512" '
        f'fill="#{colour}"/><circle cx="256" cy="256" r="150" fill="none" stroke="#fff" stroke-width="18" opacity=".6"/></svg>',
        encoding="utf-8",
    )
    return path


window = Gtk.Window(default_width=WIDTH, default_height=HEIGHT)
window.set_decorated(False)
window.set_resizable(False)
window.add_css_class("theme-roon")
provider = Gtk.CssProvider()
provider.load_from_data(native.CSS)
Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

display = native.Display()
display.window = window
display.settings_data["display_theme"] = "roon"
display.system_data = {"display_profile": PROFILES.get((WIDTH, HEIGHT), "touch2-7")}
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

report = [f"Layout fit at {WIDTH}x{HEIGHT} (x, y, width, height in window pixels)"]
problems = []


def check_window(label):
    width, height = window.get_width(), window.get_height()
    status = "ok" if (width, height) == (WIDTH, HEIGHT) else "TOO BIG" if width > WIDTH or height > HEIGHT else "small"
    report.append(f"  window {width}x{height} [{status}]")
    if width > WIDTH or height > HEIGHT:
        problems.append(f"{label}: window {width}x{height} exceeds {WIDTH}x{HEIGHT}")


def set_interface(size):
    display.settings_data["interface_size"] = size
    display.adapt_display()
    settle()


def bus_data(due_first, count):
    services = [
        ("40", "blue", [due_first, 16, 34]),
        ("42", "green", [2, 12, 24]),
        ("401", "violet", [7, 19, 31]),
    ][:count]
    return {
        "status": "ok",
        "updated_at": "2026-10-25T20:46:49",
        "services": [
            {"service": number, "colour": colour, "arrivals": [{"minutes": m, "monitored": index == 0} for index, m in enumerate(minutes)]}
            for number, colour, minutes in services
        ],
    }


def measure_bus(size, count, due):
    display.stack.set_visible_child_name("bus")
    display.stop.set_text("Flamingo Valley")
    display.stop_code.set_text("83249")
    display.bus_clock.set_text("20:46")
    display.render_bus(bus_data(0 if due else 1, count))
    settle()
    label = f"bus {size} {count}x{'due' if due else 'min'}"
    report.append(f"{label}")
    check_window(label)
    page = pages["bus"]
    cog = next((w for w in walk(page) if w.has_css_class("discover-utility") and w.get_mapped()), None)
    title = next((w for w in walk(page) if w.has_css_class("stop") and w.get_mapped()), None)
    clock = next((w for w in walk(page) if w.has_css_class("clock") and w.get_mapped()), None)
    for name, widget in (("cog", cog), ("title", title), ("clock", clock)):
        value = bounds(widget, window)
        centre = "" if value is None else f"  centre y {value[1] + value[3] / 2:.1f}"
        report.append(f"  {name:6} " + ("not present" if value is None else "%7.1f %7.1f %7.1f %7.1f" % value) + centre)
    capture(f"fit-{label.replace(' ', '-')}")


def measure_headers(size):
    """Cog, title and clock on Bus, Home and Now Playing/Discover: the cog must not move."""
    rows = {}
    for name, stack_name in (("bus", "bus"), ("home", "home"), ("discover", "roon")):
        display.stack.set_visible_child_name(stack_name)
        settle()
        page = pages[stack_name]
        header = next((w for w in walk(page) if w.has_css_class("discover-toolbar") and w.get_mapped()), None) if name == "discover" else None
        header = header or next((w for w in walk(page) if w.has_css_class("page-header") and w.get_mapped()), None)
        cog = clock = title = None
        for widget in walk(header) if header else []:
            if not widget.get_mapped():
                continue
            if widget.has_css_class("discover-utility") and not widget.has_css_class("discover-sleep") and cog is None:
                cog = widget
            if (widget.has_css_class("header-clock") or widget.has_css_class("discover-sleep")) and clock is None:
                clock = widget
            if (widget.has_css_class("stop") or widget.has_css_class("page-title")) and title is None:
                title = widget
        rows[name] = {"cog": bounds(cog, window), "clock": bounds(clock, window), "title": bounds(title, window)}
        capture(f"fit-header-{name}-{size}")
    report.append(f"headers {size}")
    for element in ("cog", "title", "clock"):
        for name, row in rows.items():
            value = row[element]
            centre = "" if value is None else f"  centre y {value[1] + value[3] / 2:.1f}  right {value[0] + value[2]:.1f}"
            report.append(f"  {element:6} {name:9}" + ("not present" if value is None else "%7.1f %7.1f %7.1f %7.1f" % value) + centre)
    tops = {name: row["cog"][1] + row["cog"][3] / 2 for name, row in rows.items() if row["cog"]}
    if tops and max(tops.values()) - min(tops.values()) > 1:
        problems.append(f"headers {size}: cog centre y differs " + ", ".join(f"{n}={v:.1f}" for n, v in tops.items()))
    lefts = {name: row["cog"][0] for name, row in rows.items() if row["cog"]}
    if lefts and max(lefts.values()) - min(lefts.values()) > 1:
        problems.append(f"headers {size}: cog x differs " + ", ".join(f"{n}={v:.1f}" for n, v in lefts.items()))
    rights = {name: row["clock"][0] + row["clock"][2] for name, row in rows.items() if row["clock"]}
    if rights and max(rights.values()) - min(rights.values()) > 1:
        problems.append(f"headers {size}: clock right edge differs " + ", ".join(f"{n}={v:.1f}" for n, v in rights.items()))


def measure_browse(size):
    display.stack.set_visible_child_name("roon")
    display.discovery_active = True
    display.discovery_section = "browse"
    display.set_roon_view("browse")
    for name, button in display.discover_tabs.items():
        (button.add_css_class if name == "browse" else button.remove_css_class)("active")
    items = [
        {"title": f"Album {n}", "subtitle": "Artist", "item_key": f"k{n}", "image_key": f"art-{n}"}
        for n in range(24)
    ]
    display.render_browser({"status": "ready", "section": "albums", "section_root": True, "layout": "covers", "alpha_scrub": True, "items": items})
    for key, pictures in display.browser_pictures.items():
        for picture in pictures:
            picture.set_filename(str(fixture_art(key)))
    settle()
    label = f"browse {size}"
    report.append(label)
    check_window(label)
    cards = [bounds(card, window) for card, _item in display.browser_cards]
    cards = [c for c in cards if c]
    scroll = bounds(display.browser_scroll, window)
    if cards and scroll:
        first = cards[0]
        columns = len({round(c[0]) for c in cards})
        row_tops = sorted({round(c[1]) for c in cards})
        visible_rows = sum(1 for top in row_tops if top < scroll[1] + scroll[3] - 24)
        report.append(f"  covers {first[2]:.0f}x{first[3]:.0f}  columns {columns}  first x {first[0]:.0f}  last right edge {max(c[0] + c[2] for c in cards):.0f}")
        report.append(f"  scroll area  y {scroll[1]:.0f}..{scroll[1] + scroll[3]:.0f}   rows with their top visible: {visible_rows}   row tops {row_tops[:4]}")
        covered_bottom = [top for top in row_tops if top < scroll[1] + scroll[3]]
        if covered_bottom:
            report.append(f"  gap below the last visible row: {scroll[1] + scroll[3] - (covered_bottom[-1] + first[3]):.0f}px (negative = a row is cut off)")
    for name, widget in (("back", display.browser_back), ("scrubber", display.browser_scrubber), ("sidebar", display.browser_discovery_sidebar if display.browser_discovery_sidebar.get_visible() else display.browser_sidebar)):
        value = bounds(widget, window) if widget.get_visible() else None
        report.append(f"  {name:8} " + ("hidden" if value is None else "%7.1f %7.1f %7.1f %7.1f" % value))
    scrubber = bounds(display.browser_scrubber, window)
    if scrubber:
        report.append(f"  scrubber right edge to screen edge: {WIDTH - (scrubber[0] + scrubber[2]):.0f}px")
    capture(f"fit-browse-{size}")


landscape = WIDTH > HEIGHT
for size in ("standard", "larger", "smaller"):
    report.append(f"=== interface size: {size}")
    set_interface(size)
    for count, due in ((2, False), (3, False), (2, True)):
        measure_bus(size, count, due)
    measure_headers(size)
    if landscape:
        measure_browse(size)

report.append("")
report.extend(["MISMATCH " + problem for problem in problems] or ["Every measured page fits the screen."])
text = "\n".join(report)
print(text, flush=True)
(OUTPUT / "layout-fit.txt").write_text(text + "\n", encoding="utf-8")
if STRICT and problems:
    sys.exit(1)
