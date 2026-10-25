"""Exercise the real native Discover widgets under Alpine GTK/Xvfb."""
import importlib.util
import time
from pathlib import Path
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

source = Path("/opt/pi-home/native-display/roondeck_native.py")
spec = importlib.util.spec_from_file_location("pi_home_native", source)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

Gtk.init()
window = Gtk.Window(default_width=1280, default_height=720)
# This fixture builds widgets directly rather than launching Display.activate;
# mirror the real application's landscape classes before checking alignment.
window.add_css_class("touch-landscape"); window.add_css_class("display-landscape")
provider = Gtk.CssProvider(); provider.load_from_data(native.CSS)
Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
display = native.Display()
display.window = window
page = display.build_roon()
window.set_child(page); window.present()
context = native.GLib.MainContext.default()
for _ in range(20):
    while context.pending(): context.iteration(False)
    time.sleep(.01)

assert display.discover_tabs["daily"].get_label() == "DAILY"
horizontal, vertical = display.discovery_scroll.get_policy()
assert horizontal == Gtk.PolicyType.NEVER and vertical == Gtk.PolicyType.AUTOMATIC
display.discovery_section = "daily"
display.discovery_picks = True
navigation, selected = display.discovery_secondary_navigation()
assert navigation == (("mixes", "MIXES"), ("recommendations", "FOR YOU"))
assert selected == "mixes"

display.discovery_active = True
display.discovery_request = 1
display.roon_views.set_visible_child_name("discover")
items = [{"title": f"Mix {number}", "artist": "Artist", "kind": "mix"} for number in range(1, 6)]
groups = [{"reason":"recent","seed":{"title":"Sad Wings of Destiny (50th Anniversary Remixed & Remastered)","artist":"Judas Priest","artwork_key":"seed-art"},"items":items}]
assert display.render_discover(1, {"status": "ready", "items": items, "groups": groups}) is False
for _ in range(20):
    while context.pending(): context.iteration(False)
    time.sleep(.01)
scroller = display.discovery_list.get_first_child()
assert isinstance(scroller, Gtk.ScrolledWindow)
track = scroller.get_child()
if not isinstance(track, Gtk.Box): track = track.get_child()
assert isinstance(track, Gtk.Box)
cards=[]; child=track.get_first_child()
while child: cards.append(child); child=child.get_next_sibling()
assert len(cards) == 5
first = cards[0]
assert first.has_css_class("daily-card")
requested_width, requested_height = first.get_size_request()
assert requested_width > 0 and requested_height > 0
shell = first.get_child()
assert isinstance(shell, Gtk.ScrolledWindow)
assert shell.get_min_content_width() == shell.get_max_content_width()
body = shell.get_child()
if not isinstance(body, Gtk.Box): body = body.get_child()
art = body.get_first_child()
assert isinstance(art, Gtk.ScrolledWindow)
assert art.get_min_content_width() == art.get_max_content_width()
assert art.get_min_content_height() == art.get_max_content_height()
horizontal, vertical = scroller.get_policy()
assert horizontal == Gtk.PolicyType.AUTOMATIC and vertical == Gtk.PolicyType.NEVER
heading = scroller.get_next_sibling()
assert heading.get_text() == "BECAUSE YOU LISTENED TO…"
seed_title = heading.get_next_sibling()
assert isinstance(seed_title, Gtk.Label)
assert seed_title.get_text() == groups[0]["seed"]["title"].upper()
assert seed_title.has_css_class("recommendation-album")
recommendations = seed_title.get_next_sibling()
assert isinstance(recommendations, Gtk.ScrolledWindow)
recommendation_track = recommendations.get_child()
if not isinstance(recommendation_track, Gtk.Box): recommendation_track = recommendation_track.get_child()
recommendation_cards = []; child = recommendation_track.get_first_child()
while child: recommendation_cards.append(child); child = child.get_next_sibling()
assert len(recommendation_cards) == len(items)
assert all(not card.has_css_class("recommendation-seed-card") for card in recommendation_cards)
assert "discover:seed-art" not in display.discovery_pictures
for label in (heading, seed_title):
    label_bounds = label.compute_bounds(window)[1]
    card_bounds = recommendation_cards[0].compute_bounds(window)[1]
    assert abs(label_bounds.get_x() - card_bounds.get_x()) <= 1
for row in (track, recommendation_track):
    assert row.get_margin_end() == native.CAROUSEL_END_SPACE == 30
assert display.discovery_daily_sections.keys() == {"mixes", "recommendations"}
assert display.discovery_daily_sections["mixes"] is scroller
for swipe in (scroller, recommendations):
    valid, bounds = swipe.compute_bounds(window)
    assert valid and bounds.get_x() + bounds.get_width() >= window.get_width() - 1, (bounds, window.get_width())
display.browser_sidebar.set_visible(True)
display.browser_list.append(display.label("Stale Browse content"))
requests = []
display.request_browser = lambda action, **_payload: requests.append(action)
display.set_mode = lambda _mode: None
display.open_discover("surprise")
assert requests == ["surprise"]
assert not display.browser_sidebar.get_visible()
loading = display.browser_list.get_first_child()
assert isinstance(loading, Gtk.Box)
assert loading.get_last_child().get_text() == "Loading…"
dot = loading.get_first_child().get_first_child()
for _ in range(3):
    assert dot.has_css_class("loading-dots")
    dot = dot.get_next_sibling()
assert dot is None
display.root_overlay = Gtk.Overlay(); display.root_overlay.set_child(Gtk.Box())
display.device_status = display.label("")
display.confirm_reboot()
shade = display.reboot_confirmation
assert isinstance(shade, Gtk.Overlay)
card = shade.get_last_child()
assert card.get_halign() == Gtk.Align.CENTER and card.get_valign() == Gtk.Align.CENTER
print("Native Alpine GTK Discover has working touch scrollers, fixed cards, a clean Surprise transition and a centred restart panel.")
