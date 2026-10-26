"""Real GTK Settings allocation checks and optional deterministic review capture."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from native_harness import patch_native
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

spec = importlib.util.spec_from_file_location("native_settings", "/opt/pi-home/native-display/roondeck_native.py")
native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
Gtk.init()
if "PI_HOME_SETTINGS_VIEWPORT" not in os.environ:
    matrix = json.loads(Path("/opt/pi-home/tools/viewports.json").read_text(encoding="utf-8"))["viewports"]
    for viewport in matrix:
        size = f'{viewport["width"]}x{viewport["height"]}'
        subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 " + size + "x24", sys.executable, __file__], env={**os.environ, "PI_HOME_SETTINGS_VIEWPORT":size},check=True)
    raise SystemExit(0)
def settle(timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    for _ in range(40):
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.01)

for width, height in (tuple(map(int,os.environ["PI_HOME_SETTINGS_VIEWPORT"].split("x"))),):
    window = Gtk.Window(default_width=width, default_height=height)
    window.set_decorated(False); window.set_resizable(False); window.add_css_class("theme-roon")
    provider = Gtk.CssProvider(); provider.load_from_data(native.CSS)
    Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    display = native.Display(); display.window = window
    display.build_roon(); window.set_child(display.build_settings())
    portrait=height>width
    if portrait:
        window.add_css_class("portrait")
        if width<600: window.add_css_class("compact-portrait")
    elif width>=1200: window.add_css_class("touch-landscape")
    display.configure_settings_layout(width,height)
    expected_logo_height = ((34 if width>=900 else 28) if portrait else
        44 if max(width,height)>=1600 else 43 if width>=1200 else 26 if width<1000 else 32)
    logo_width, logo_height = display.settings_wordmark.get_size_request()
    assert logo_height == expected_logo_height, (width,height,logo_height)
    assert logo_width < width * .37, (width,height,logo_width)
    display.device_status.set_text("v1.1.0 Alpine")
    display.touch_diagnostics.set_text("Memory 5.4%  ·  Load 1.53  ·  63.3°C  ·  Controller ready  ·  Bridge offline")
    display.render_touch_controls({"services":[{"name":name,"enabled":True} for name in ("40","42","401")]}, {"roon_bridge":"stopped"})
    window.present(); settle(); display.adapt_display(); settle()
    title_baseline = display.settings_title_label.get_allocation().y + display.settings_title_label.get_baseline()
    version_baseline = display.device_status.get_allocation().y + display.device_status.get_baseline()
    assert title_baseline == version_baseline, (width,height,title_baseline,version_baseline)
    # GTK's allocated widget height already excludes its margins. The visible
    # SVG baseline is therefore the allocated lower edge; subtracting the
    # margin again would measure it twice.
    wordmark_baseline = display.settings_wordmark_frame.get_allocation().y + display.settings_wordmark_frame.get_height()
    assert abs(wordmark_baseline-title_baseline) <= 1, (width,height,wordmark_baseline,title_baseline)
    rows = [display.touch_profile, display.touch_orientation, display.touch_mounting]
    seven_inch = (height < width and width <= 820 and height <= 500) or (height < width and 1000 <= width < 1500 and height <= 850)
    if seven_inch:
        assert all(not row.get_visible() for row in rows)
        assert not display.apply_display_button.get_visible()
    else:
        heights = [row.get_height() for row in rows]
        assert min(heights) > 0 and max(heights)-min(heights) <= 1, (width,height,heights)
    actions=[]; child=display.settings_actions.get_first_child()
    while child:
        if child.get_visible(): actions.append(child.get_width())
        child=child.get_next_sibling()
    assert max(actions)-min(actions) <= 1, actions
    assert display.settings_actions.get_first_child() == display.update_button
    assert display.update_button.get_next_sibling() == display.apply_display_button
    theme_widths=[button.get_width() for button in display.touch_theme_buttons.values()]
    assert max(theme_widths)-min(theme_widths)<=1, theme_widths
    if width==1280 and height==720:
        assert display.settings_daily.get_width() <= width // 2, display.settings_daily.get_width()
    if width==800 and height==480:
        assert display.settings_wordmark.get_height() == 26
        for widget in (*rows, display.settings_actions):
            bounds = widget.compute_bounds(window)[1]
            assert bounds.get_x() >= 0, (widget, bounds.get_x())
            assert bounds.get_x() + bounds.get_width() <= width, (widget, bounds.get_x(), bounds.get_width(), width)
    assert window.get_width() == width and window.get_height() == height, (width,height,window.get_width(),window.get_height())
    output=os.environ.get("PI_HOME_SCREENSHOT_DIR")
    if output:
        Path(output).mkdir(parents=True,exist_ok=True)
        subprocess.run(["import","-silent","-window","root",str(Path(output)/f"settings-{width}x{height}.png")],check=True)
    display.render_touch_controls({"services":[]},{"roon_bridge":"not_installed"})
    assert display.touch_bus_services.get_first_child() is None
    display.render_touch_controls({"services":[]},{"roon_bridge":"running"})
    bridge_check=display.touch_daily.get_first_child().get_first_child().get_first_child()
    assert bridge_check.get_active()
    from unittest.mock import patch
    restore_post_json = patch_native(native, "post_json", lambda *args, **kwargs: None)
    with patch.object(native.threading,"Thread"):
        bridge_check.set_active(False)
        display._toggle_bridge(bridge_check,False); settle()
        assert bridge_check.get_active() and bridge_check.get_sensitive()
        assert "Could not change Roon Bridge" in display.touch_diagnostics.get_text()
        restore_post_json()
    window.destroy(); settle()
print("Real GTK Settings: equal-height rows, equal-width actions and viewport bounds checked.")
