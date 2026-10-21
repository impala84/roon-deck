"""Render deterministic native Discover screenshots in Alpine GTK/Xvfb."""
import html
import base64
import importlib.util
import os
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


OUTPUT = Path(os.environ.get("PI_HOME_SCREENSHOT_DIR", "/screenshots"))
ART = Path("/tmp/pi-home-visual-art")
OUTPUT.mkdir(parents=True, exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)

source = Path("/opt/pi-home/native-display/pi_bus_native.py")
spec = importlib.util.spec_from_file_location("pi_home_native_visual", source)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def fixture_art(key, label):
    """Create distinct fake artwork without shipping or downloading media."""
    palette = ("4d478f", "315d78", "7a5637", "4c725d", "754461", "556b37", "75463b", "3f567e")
    colour = palette[sum(key.encode("utf-8")) % len(palette)]
    path = ART / f"{key}.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
        f'<rect width="512" height="512" fill="#{colour}"/>'
        '<circle cx="256" cy="218" r="130" fill="none" stroke="#f2eee8" stroke-width="18" opacity=".62"/>'
        '<circle cx="256" cy="218" r="30" fill="#f2eee8" opacity=".72"/>'
        f'<text x="256" y="420" text-anchor="middle" fill="#fff" font-family="sans-serif" font-size="34" font-weight="700">{html.escape(label[:22])}</text>'
        '</svg>',
        encoding="utf-8",
    )
    return path


def settle(rounds=40):
    context = native.GLib.MainContext.default()
    for _ in range(rounds):
        while context.pending():
            context.iteration(False)
        time.sleep(.01)


def capture(name):
    settle()
    subprocess.run(["import", "-silent", "-window", "root", str(OUTPUT / f"{name}.png")], check=True)


def item(title, artist, number, kind="album"):
    return {"title": title, "artist": artist, "kind": kind, "key": f"item-{number}", "id": f"mix-{number}", "artwork_key": f"art-{number}"}


Gtk.init()
screen_width = int(os.environ.get("PI_HOME_SCREEN_WIDTH", "1280"))
screen_height = int(os.environ.get("PI_HOME_SCREEN_HEIGHT", "720"))
window = Gtk.Window(default_width=screen_width, default_height=screen_height)
window.set_decorated(False)
window.set_resizable(False)
window.add_css_class("theme-roon")
provider = Gtk.CssProvider(); provider.load_from_data(native.CSS)
Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
display = native.Display()
display.settings_data["display_theme"] = "roon"
page = display.build_roon()
window.set_child(page)
window.present()
settle()
display.window = window
display.adapt_display()
display.discovery_active = True
display.discovery_request = 1
display.set_roon_view("discover")
display.roon_clock.set_text("07:26")
display.zone.set_text("NAD M33")


def render(section, data):
    display.discovery_section = section
    display.discovery_mix = ""
    display.discovery_signature = None
    for name, button in display.discover_tabs.items():
        if name == section: button.add_css_class("active")
        else: button.remove_css_class("active")
    display.render_discover(display.discovery_request, data)
    settle()
    for artwork_key, pictures in display.discovery_pictures.items():
        label = artwork_key.removeprefix("discover:").replace("art-", "COVER ")
        path = fixture_art(artwork_key.replace(":", "-"), label)
        for picture in pictures:
            picture.set_filename(str(path))
    settle()
    assert window.get_width() == screen_width, (
        section, "loaded Discover content expanded the window", window.get_width(), screen_width)


recent = [
    item("Jah Victory", "Alpha Blondy", 1),
    item("Heyday", "The Church", 2),
    item("Mickey Mouse Operation", "Little People", 3),
    item("Chrysalis", "Emancipator", 4),
    item("Tsunami Sea", "Spiritbox", 5),
    item("Greyview", "Invent Animate", 6),
    item("Astro Lounge", "Smash Mouth", 7),
    item("Collected Reworks", "Foals", 8),
]
render("recent", {"status": "ready", "items": recent})
capture("recent-listened")

releases = [
    item("Happiness Anytime", "Leon Bridges", 11),
    item("Freedom Call: Sextet – Unity", "Dave Holland", 12),
    item("Aurora (Deluxe Edition)", "Yes", 13),
    item("Freedom Call: Prism – Freedom", "Dave Holland", 14),
    item("Freedom Call: Quintet – Synergism", "Dave Holland", 15),
    item("Utility Modern", "Brandon Seabrook / Bill Frisell / Rahsaan Carter / Marcus Gilmore", 16),
    item("fabric presents Max Cooper", "Max Cooper", 17),
    item("Sad Wings of Destiny (50th Anniversary Remixed & Remastered)", "Judas Priest", 18),
]
render("releases", {"status": "ready", "items": releases})
capture("new-releases")

mixes = [
    item("Coheed and Cambria Mix", "Coheed and Cambria", 21, "mix"),
    item("The Beatles Mix", "The Beatles", 22, "mix"),
    item("+44 Mix", "+44", 23, "mix"),
    item("Stray From the Path Mix", "Stray From the Path", 24, "mix"),
    item("The Band Mix", "The Band", 25, "mix"),
]
recommendations = [
    item("Painkiller", "Judas Priest", 31),
    item("British Steel", "Judas Priest", 32),
    item("Screaming for Vengeance", "Judas Priest", 33),
    item("Defenders of the Faith", "Judas Priest", 34),
    item("Firepower", "Judas Priest", 35),
]
daily = {
    "status": "ready",
    "items": mixes,
    "groups": [{
        "reason": "recent",
        "seed": item("Sad Wings of Destiny (50th Anniversary Remixed & Remastered)", "Judas Priest", 30),
        "items": recommendations,
    }],
}
render("daily", daily)
capture("daily-mixes")
if screen_width >= 1200 and screen_height < screen_width:
    recommendation_row = display.discovery_daily_sections["recommendations"]
    track = recommendation_row.get_child()
    if isinstance(track, Gtk.Viewport): track = track.get_child()
    first_cover = track.get_first_child().compute_bounds(page)[1]
    child = display.discovery_list.get_first_child()
    while child:
        if child.has_css_class("recommendation-heading") or child.has_css_class("recommendation-album"):
            text_left = child.compute_bounds(page)[1].get_x()
            assert abs(text_left - first_cover.get_x()) <= 1, (text_left, first_cover.get_x())
        child = child.get_next_sibling()
    for row in display.discovery_daily_sections.values():
        bounds = row.compute_bounds(page)[1]
        assert abs(bounds.get_x() + bounds.get_width() - screen_width) <= 1
        track = row.get_child()
        if isinstance(track, Gtk.Viewport): track = track.get_child()
        start_x = track.get_first_child().compute_bounds(page)[1].get_x()
        assert track.get_margin_end() == native.CAROUSEL_END_SPACE == 30
        adjustment = row.get_hadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        settle()
        final = track.get_last_child().compute_bounds(page)[1]
        if adjustment.get_upper() > adjustment.get_page_size() + 1:
            assert abs(screen_width - final.get_x() - final.get_width() - 30) <= 2
        else:
            # A wider 10-inch fixture may fit every card without scrolling.
            # Preserve the start position; do not spread cards to fill it.
            assert screen_width - final.get_x() - final.get_width() >= 30
        capture("daily-carousel-end-" + ("mixes" if row is display.discovery_daily_sections["mixes"] else "recommendations"))
        adjustment.set_value(adjustment.get_lower())
        settle()
        assert abs(track.get_first_child().compute_bounds(page)[1].get_x() - start_x) <= 1
        # Exercise the actual GTK paint-only spring at both ends, independent
        # of synthetic input delivery; physical touch feel still needs Pi testing.
        for pull in (16.0, -16.0):
            track.elastic_offset = pull; track.queue_draw(); track.spring_back()
            settle()
            assert abs(track.elastic_offset) < 16
            time.sleep(.5); settle()
            assert track.elastic_offset == 0
            assert abs(track.get_first_child().compute_bounds(page)[1].get_x() - start_x) <= 1
assert "discover:" + daily["groups"][0]["seed"]["artwork_key"] not in display.discovery_pictures
if screen_height > screen_width:
    assert "recommendations" not in display.discovery_daily_sections
    display.select_discovery_secondary("recommendations")
    capture("daily-for-you")
    assert "mixes" not in display.discovery_daily_sections
    assert isinstance(display.discovery_daily_sections["recommendations"], Gtk.Grid)
    display.settings_data["portrait_discovery_columns"] = 3
    display.discovery_signature = None
    render("daily", daily)
    capture("daily-for-you-three-columns")
    assert display.discovery_grid_metrics("daily")[0] == 3
    display.select_discovery_secondary("mixes")
    display.discovery_signature = None
    render("daily", daily)
    capture("daily-mixes-three-columns")
    first = display.discovery_cards[0][0].compute_bounds(display.discovery_list)[1]
    second_row = display.discovery_cards[3][0].compute_bounds(display.discovery_list)[1]
    gap = second_row.get_y() - first.get_y() - first.get_height()
    assert 0 <= gap <= 24, gap
    display.settings_data["portrait_discovery_columns"] = 2
    display.discovery_signature = None
    render("daily", daily)
else:
    for_you = display.discovery_daily_sections["recommendations"]
    vertical = display.discovery_scroll.get_vadjustment()
    vertical.set_value(max(vertical.get_lower(), min(vertical.get_upper() - vertical.get_page_size(), for_you.get_allocation().y - 42)))
    capture("daily-for-you")
    horizontal = for_you.get_hadjustment()
    horizontal.set_value(min(horizontal.get_upper() - horizontal.get_page_size(), 240))
    capture("daily-for-you-scrolled")

# Check actual allocated portrait geometry, not just requested widget sizes.
if screen_height > screen_width:
    assert not display.music_header_overlay.get_visible()
    toolbar = display.discover_toolbar.compute_bounds(page)[1]
    sidebar = display.discovery_sidebar.compute_bounds(page)[1]
    assert toolbar.get_y() + toolbar.get_height() <= sidebar.get_y()
    assert display.discovery_sidebar.get_height() < 100
    assert display.discovery_scroll.get_height() > screen_height * .6
    first = display.discovery_cards[0][0]
    assert first.get_width() > screen_width * .3

display.discovery_mix = "aabb"
display.discovery_signature = None
display.render_discover(display.discovery_request, {"status": "ready", "mix": {"title": "Creed Mix"},
    "items": [item("Is This The End?", "Creed", 91, "track")]})
capture("mix-detail")
mix_controls = display.discovery_list.get_first_child().get_next_sibling()
assert mix_controls.get_first_child().get_child().get_first_child().icon_name == "play"
display.discovery_mix = ""
display.discovery_active = True
display.discovery_section = "browse"
display.set_roon_view("browse")
for name, button in display.discover_tabs.items():
    (button.add_css_class if name == "browse" else button.remove_css_class)("active")
def browse_fixture(section, labels):
    display.render_browser({"status": "ready", "section": section, "section_root": True, "layout": "covers", "show_labels": labels, "alpha_scrub": True, "items": [{"title": value["title"] + (" and a particularly long artist name" if labels else ""), "subtitle": value["artist"], "item_key": value["key"], "image_key": value["artwork_key"]} for value in recent * 3]})
    for key, pictures in display.browser_pictures.items():
        for picture in pictures: picture.set_filename(str(fixture_art(key, "LOADED COVER")))
    settle()
    if window.get_width() != screen_width:
        print("Page width diagnostic:", tuple(page.measure(Gtk.Orientation.HORIZONTAL, -1)), flush=True)
        for name in ("music_header_overlay", "discover_toolbar", "discover_toolbar_tabs", "discover_subnav", "roon_views", "browser_body", "browser_sidebar", "browser_scroll", "browser_scrubber", "browser_list"):
            widget = getattr(display, name)
            print("Width diagnostic:", name, widget.get_width(), tuple(widget.measure(Gtk.Orientation.HORIZONTAL, -1)), flush=True)
        capture("browse-overflow")
    assert window.get_width() == screen_width, (section, window.get_width(), screen_width)
    assert display.discover_toolbar.get_visible()
    assert not display.music_header_overlay.get_visible()
    clock = display.discover_toolbar.get_last_child().compute_bounds(page)[1]
    assert clock.get_x() + clock.get_width() <= screen_width
    scrub = display.browser_scrubber.compute_bounds(page)[1]
    assert scrub.get_x() >= 0 and scrub.get_x() + scrub.get_width() <= screen_width - 4
    if screen_height > screen_width:
        assert display.discover_toolbar.get_visible()
        assert not display.music_header_overlay.get_visible()
        toolbar = display.discover_toolbar.compute_bounds(page)[1]
        subsection = display.browser_sidebar.compute_bounds(page)[1]
        assert toolbar.get_y() + toolbar.get_height() <= subsection.get_y()
        child = display.discover_toolbar.get_first_child()
        previous_right = 0
        while child:
            bounds = child.compute_bounds(page)[1]
            assert bounds.get_x() >= previous_right
            previous_right = bounds.get_x() + bounds.get_width()
            child = child.get_next_sibling()
        assert previous_right <= screen_width - 4
browse_fixture("albums", False)
settle()
capture("browse")
if screen_height > screen_width and screen_width >= 1000:
    assert display.browser_sort.get_visible()
    display.show_browser_sort(display.browser_sort)
    settle(); capture("browse-sort-menu")
    popup = display.browser_sort_popover
    if isinstance(popup, Gtk.Popover): popup.unparent()
if screen_width >= 1000 and screen_height < screen_width:
    tabs = display.discover_subnav.compute_bounds(page)[1]
    cog = display.music_settings_button.compute_bounds(page)[1]
    clock = display.music_clock_button.compute_bounds(page)[1]
    assert abs(tabs.get_x() + tabs.get_width() / 2 - (cog.get_x() + cog.get_width() + clock.get_x()) / 2) <= 3
    display.settings_data["landscape_music_clock"] = "full"
    display.configure_music_clock()
    display.music_full_clock.set_text("09:12")
    capture("browse-full-clock")
    assert display.music_clock_button.get_child() is display.music_full_clock
    assert window.get_width() == screen_width
    display.settings_data["landscape_music_clock"] = "icon"
    display.configure_music_clock()
while child := display.browser_list.get_first_child(): display.browser_list.remove(child)
display.browser_list.append(display.loading_notice())
capture("browse-loading")
browse_fixture("albums", False)
settle()
if screen_height > screen_width:
    assert display.browser_sidebar.get_height() < 100
    assert display.browser_scroll.get_height() > screen_height * .6
    assert display.browser_grid_metrics()[0] == 3
browse_fixture("artists", True)
capture("browse-artists")
display.render_browser({"status": "ready", "section": "artists", "layout": "list", "can_back": True,
    "artist_profile": {"name": "ABBA", "image_key": "artist-abba"},
    "items": [{"title": "Play Artist", "action": True, "item_key": "play-artist"},
              {"title": "ABBA Gold", "subtitle": "ABBA", "item_key": "abba-gold", "image_key": "abba-gold"},
              {"title": "Voyage", "subtitle": "ABBA", "item_key": "voyage", "image_key": "voyage"}]})
for key, pictures in display.browser_pictures.items():
    for picture in pictures: picture.set_filename(str(fixture_art(key, key.upper())))
capture("artist-profile")
if screen_height > screen_width:
    assert display.browser_artist_panel.get_orientation() == Gtk.Orientation.HORIZONTAL
    portrait_art = display.browser_artist_panel.get_first_child()
    assert portrait_art.get_width() <= screen_width * (.4 if screen_width >= 1000 else .36), portrait_art.get_width()
    assert portrait_art.get_height() == portrait_art.get_width()
    artist_bounds = display.browser_artist_scroll.compute_bounds(page)[1]
    albums_bounds = display.browser_scroll.compute_bounds(page)[1]
    assert albums_bounds.get_y() >= artist_bounds.get_y() + artist_bounds.get_height()
    assert albums_bounds.get_y() - artist_bounds.get_y() - artist_bounds.get_height() < 70, (artist_bounds, albums_bounds)
display.render_browser({"status": "ready", "section": "genres", "layout": "tiles", "show_labels": True,
    "items": [{"title": name, "item_key": name} for name in ("Pop/Rock", "Classical", "Electronic", "Jazz", "Stage & Screen", "International", "Vocal", "Blues", "Easy Listening")]})
capture("genres")
tabs_y = display.browser_section_buttons["genres"].compute_bounds(window)[1].get_y()
display.render_browser({"status":"ready", "section":"genres", "layout":"menu", "can_back":True,
    "items":[{"title":name, "item_key":name} for name in ("Shuffle Genre", "Artists", "Albums", "G-Funk")]})
capture("genre-navigation")
if screen_height > screen_width:
    assert abs(display.browser_section_buttons["genres"].compute_bounds(window)[1].get_y() - tabs_y) <= 1
    card = display.browser_list.get_first_child().get_first_child()
    assert abs(card.get_width() - card.get_height()) <= 2, (card.get_width(), card.get_height())
for batch, names in enumerate((("R&B", "Rap", "Avant-Garde", "Folk", "New Age", "Reggae"), ("Country", "Latin", "Religious", "Holiday", "Children’s", "Comedy")), 2):
    display.render_browser({"status": "ready", "section": "genres", "layout": "tiles", "show_labels": True,
        "items": [{"title": name, "item_key": name} for name in names]})
    capture("genres-" + str(batch))
assert window.get_width() == screen_width

display.render_browser({"status": "ready", "section": "playlists", "layout": "tiles", "show_labels": True,
    "items": [{"title": name, "item_key": name} for name in ("Evening vibes", "Entertain", "South Africa", "Braai Vibes", "Vocal Jazz", "Jazz Vibes")]})
capture("playlists")
if screen_height > screen_width:
    assert display.browser_tile_size == (screen_width - 120) // 3, display.browser_tile_size

display.set_roon_view("search")
capture("keyboard")
entry_bounds = display.browser_search_entry.compute_bounds(window)[1]
keyboard = display.browser_search_entry.get_parent().get_parent()
keyboard_bounds = keyboard.compute_bounds(window)[1]
# GTK can report logical coordinates for this nested stack at fractional HiDPI
# scales even though the captured framebuffer retains the intended 30px page
# gutter.  Guard the useful invariant here: the panel stays inset and its two
# outer gutters remain symmetrical.
search_gutter = entry_bounds.get_x()
right_gutter = screen_width - keyboard_bounds.get_x() - keyboard_bounds.get_width()
if screen_height > screen_width:
    assert 10 <= search_gutter <= 30, search_gutter
    assert abs(right_gutter - search_gutter) <= 1, (search_gutter, right_gutter)
else:
    # Compact landscape keeps the same left navigation rail as Browse.
    assert 100 <= search_gutter <= 180, search_gutter
    assert (10 <= right_gutter <= 30) if screen_width < 1000 else (0 <= right_gutter <= 30), right_gutter

for track in (display.browser_list, display.queue_list, display.discovery_list):
    for offset in (24.0, -24.0):
        track.elastic_offset = offset; track.spring_back()
        time.sleep(.6); settle()
        assert track.elastic_offset == 0

if screen_height > screen_width:
    display.set_roon_view("search")
    search_items = []
    for group in ("TOP RESULTS", "ARTISTS", "ALBUMS", "TRACKS"):
        search_items.append({"hint": "header", "title": group})
        search_items.extend({"title": f"{group.title()} result with a longer readable title {index}", "subtitle": "Oasis", "item_key": f"{group}-{index}"} for index in range(5))
        search_items.append({"title": "View all " + group.title(), "subtitle": "39 Results", "item_key": group})
    display.render_browser({"status": "ready", "section": "search", "layout": "list", "search_routes": {"fixture": {}}, "items": search_items})
    capture("search-docked")
    assert display.browser_list.get_ancestor(Gtk.ScrolledWindow) is display.search_results_scroll
    results_bounds = display.search_results_scroll.compute_bounds(page)[1]
    entry_bounds = display.browser_search_entry.compute_bounds(page)[1]
    assert results_bounds.get_y() + results_bounds.get_height() <= entry_bounds.get_y()
    assert entry_bounds.get_y() > screen_height * (.25 if screen_width < 600 else .4)
    assert window.get_width() == screen_width and window.get_height() == screen_height
    display.set_roon_view("browse")
    assert display.browser_list.get_ancestor(Gtk.ScrolledWindow) is display.browser_scroll
    # Leaving the keyboard cancels both delayed and queued search work.
    display.set_roon_view("search")
    display.browser_search_entry.set_text("Oasis")
    assert display.browser_search_timer is not None
    display.browser_pending_request = ("search", {"query": "Oasis"})
    display.set_roon_view("browse")
    assert display.browser_search_timer is None
    assert display.browser_pending_request is None
    # Exercise the real worker -> GLib -> rendering path, including a slow
    # search superseded by navigation, rather than calling render directly.
    import threading
    gate = threading.Event()
    original_post_json = native.post_json
    def fixture_post_json(_url, payload, **_kwargs):
        if payload["action"] == "search":
            assert gate.wait(5), "fixture search was not released"
            return {"status": "ready", "section": "search", "layout": "list",
                    "search_routes": {"fixture": {}}, "items": search_items}
        return {"status": "ready", "section": "albums", "layout": "covers",
                "items": [{"title": "Album after search", "item_key": "after-search"}]}
    native.post_json = fixture_post_json
    try:
        settle()
        display.set_roon_view("search")
        display.request_browser("search", query="Oasis", source="all")
        assert display.browser_loading
        display.set_roon_view("browse")
        display.request_browser("section", section="albums")
        gate.set()
        settle(100)
        assert display.browser_state["section"] == "albums", display.browser_state
        assert not display.browser_loading
        assert display.browser_list.get_ancestor(Gtk.ScrolledWindow) is display.browser_scroll
        assert window.get_width() == screen_width
    finally:
        gate.set()
        native.post_json = original_post_json

display.render_browser({"status": "ready", "section": "albums", "layout": "covers", "surprise_preview": True, "items": [{"title": "Based on a True Story", "subtitle": "Fat Freddy's Drop", "item_key": "surprise", "image_key": "surprise-art"}]})
for picture in display.browser_pictures.get("surprise-art", []): picture.set_filename(str(fixture_art("surprise-art", "SURPRISE")))
capture("surprise")
assert window.get_width() == screen_width and window.get_height() == screen_height, (window.get_width(), window.get_height(), screen_width, screen_height)
if screen_height > screen_width:
    stage = display.browser_list.get_first_child().get_first_child()
    assert stage.get_orientation() == Gtk.Orientation.VERTICAL

# Entering Recent resets Added, while its explicit Listened choice still works.
display.request_discovery = lambda *args: False
display.set_mode = lambda *args: None
display.open_recent("listened")
assert display.discovery_recent_mode == "listened"
display.open_discover("recent")
assert display.discovery_recent_mode == "added"

display.set_roon_view("now")
display.title.set_text("Solarium"); display.artist.set_text("Emancipator")
display.library_status = "in_library"; display.library_add.set_visible(True); display.set_library_icon(False)
display.artwork.set_filename(str(fixture_art("now-playing", "NOW PLAYING")))
display.adapt_display()
display.render_bluos_inputs({"inputs": [{"id": "tv", "name": "Watch TV"}, {"id": "rega", "name": "Rega P3"}]}, True)
capture("now-playing")
display.detail_artist_profile_name = "Emancipator"
display.detail_artist_profile = {"full_writeup": "Emancipator is an American electronic producer known for richly layered downtempo compositions.", "source": "Wikipedia", "type": "Person", "area": "Portland", "country": "US", "formed": "2003", "genres": ["downtempo", "electronic"]}
display.render_details({"status":"ready", "album":"Soon It Will Be Cold Enough", "artist":"Emancipator", "subtitle":"2006", "metadata":{"full_writeup":"The debut album blends acoustic instrumentation, field recordings and patient electronic rhythms into a cinematic whole.", "writeup_source":"Wikipedia", "release_date":"2006-01-17", "genres":["Electronic", "Downtempo"], "type":"Album", "label":"Loci Records", "format":"CD", "track_count":3}, "tracks":[{"title":"Eve"},{"title":"Soon It Will Be Cold Enough"},{"title":"First Snow"}]})
display.detail_artist_artwork.set_filename(str(fixture_art("artist-fact", "ARTIST")))
display.detail_album_artwork.set_filename(str(fixture_art("album-fact", "ALBUM")))
display.set_roon_view("details")
capture("album-artist-fact-sheet")
takeover_bounds = display.detail_takeover.compute_bounds(window)[1]
assert takeover_bounds.get_x() == 0 and takeover_bounds.get_y() == 0, (takeover_bounds.get_x(), takeover_bounds.get_y())
assert takeover_bounds.get_width() == screen_width and takeover_bounds.get_height() == screen_height, (takeover_bounds.get_width(), takeover_bounds.get_height(), screen_width, screen_height)
assert display.detail_close.get_visible()
assert display.detail_browse_action.get_visible()
assert display.detail_close.get_width() == display.detail_close.get_height(), (display.detail_close.get_width(), display.detail_close.get_height())
if screen_width == 1280 and screen_height == 720:
    assert display.compact_detail
    assert display.album_focus_detail
    assert not display.detail_artist_card.get_visible()
    assert display.detail_album_card.get_orientation() == Gtk.Orientation.HORIZONTAL
    assert display.detail_album_artwork.get_width() >= 420, display.detail_album_artwork.get_width()
    art_bounds = display.detail_album_artwork_frame.compute_bounds(display.detail_takeover)[1]
    copy_bounds = display.detail_album_content.compute_bounds(display.detail_takeover)[1]
    assert art_bounds.get_x() == 20, art_bounds.get_x()
    assert copy_bounds.get_x() > art_bounds.get_x() + art_bounds.get_width(), (copy_bounds.get_x(), art_bounds.get_x(), art_bounds.get_width())
    action_bounds = display.detail_browse_action.compute_bounds(display.detail_takeover)[1]
    assert round(screen_height - action_bounds.get_y() - action_bounds.get_height()) == 20, (action_bounds.get_y(), action_bounds.get_height())
if screen_width == 1200 and screen_height == 1920:
    artist_art_bounds = display.detail_artist_artwork_frame.compute_bounds(display.detail_takeover)[1]
    artist_name_bounds = display.detail_artist_name.compute_bounds(display.detail_takeover)[1]
    album_art_bounds = display.detail_album_artwork_frame.compute_bounds(display.detail_takeover)[1]
    album_title_bounds = display.detail_title.compute_bounds(display.detail_takeover)[1]
    assert artist_art_bounds.get_x() == artist_name_bounds.get_x(), (artist_art_bounds.get_x(), artist_name_bounds.get_x())
    assert album_art_bounds.get_x() == album_title_bounds.get_x(), (album_art_bounds.get_x(), album_title_bounds.get_x())
    action_bounds = display.detail_browse_action.compute_bounds(display.detail_takeover)[1]
    assert round(screen_height - action_bounds.get_y() - action_bounds.get_height()) == 28, (action_bounds.get_y(), action_bounds.get_height())
display.set_roon_view("now")
nav_buttons = [button for button in (display.music_navigation.get_first_child(),) if button]
while nav_buttons[-1].get_next_sibling(): nav_buttons.append(nav_buttons[-1].get_next_sibling())
assert max(button.get_width() for button in nav_buttons) - min(button.get_width() for button in nav_buttons) <= 1, [button.get_width() for button in nav_buttons]
display.bus_nav_buttons[0].set_visible(False); settle()
visible_nav = [button for button in nav_buttons if button.get_visible()]
assert len(visible_nav) == 3
assert max(button.get_width() for button in visible_nav) - min(button.get_width() for button in visible_nav) <= 1, [button.get_width() for button in visible_nav]
display.bus_nav_buttons[0].set_visible(True)
if min(screen_width, screen_height) >= 1000:
    for control in (display.library_add, display.prev, display.next):
        assert control.get_width() == control.get_height(), (control.get_width(), control.get_height())
        assert control.get_width() >= 120
button_bounds = display.library_add.compute_bounds(window)[1]
display.library_add.set_sensitive(False); display.set_library_busy(True)
assert display.library_add.has_css_class("library-busy")
capture("library-busy")
capture("library-busy-next")
if Gtk.Settings.get_default().get_property("gtk-enable-animations"):
    crop = f"{int(button_bounds.get_width()) + 24}x{int(button_bounds.get_height()) + 24}+{int(button_bounds.get_x()) - 12}+{int(button_bounds.get_y()) - 12}"
    frames = [subprocess.check_output(["convert", str(OUTPUT / f"{name}.png"), "-crop", crop, "rgb:-"]) for name in ("library-busy", "library-busy-next")]
    assert frames[0] != frames[1], "Library ring must visibly animate, not just show a static outline"
busy_bounds = display.library_add.compute_bounds(window)[1]
assert button_bounds.get_y() == busy_bounds.get_y()
assert not display.library_message.get_visible()
display.set_library_busy(False); display.library_add.set_sensitive(True)
assert not display.library_add.has_css_class("library-busy")
capture_results = []
if os.environ.get("PI_HOME_REQUIRE_GL"):
    assert "GL" in type(window.get_renderer()).__name__, type(window.get_renderer()).__name__
native.post_json = lambda url, data, **kwargs: capture_results.append(data)
display.capture_display("native-capture-check")
assert capture_results and "image" in capture_results[-1], capture_results
capture_file = OUTPUT / "live-display-capture.png"
capture_file.write_bytes(base64.b64decode(capture_results[-1]["image"]))
capture_mean = float(subprocess.check_output(["identify", "-format", "%[fx:mean]", str(capture_file)], text=True))
assert capture_mean > .03, ("Live capture is black", capture_mean)
if screen_height > screen_width:
    for button in display.bluos_source_buttons.values():
        assert button.get_hexpand(), "Late-loaded source tabs must expand like existing tabs"
    source_buttons = list(display.bluos_source_buttons.values())
    first_bounds = source_buttons[0].compute_bounds(page)[1]
    next_bounds = source_buttons[1].compute_bounds(page)[1]
    assert next_bounds.get_x() - first_bounds.get_x() - first_bounds.get_width() >= 7
assert window.get_width() == screen_width and window.get_height() == screen_height, (window.get_width(), window.get_height(), screen_width, screen_height)
footer_bounds = page.get_last_child().compute_bounds(page)[1]
assert footer_bounds.get_y() + footer_bounds.get_height() <= screen_height - 4
if screen_height > screen_width:
    assert display.artwork.get_width() == display.artwork.get_height()
    assert display.discover_toolbar.get_visible()
    assert not display.music_header_overlay.get_visible()
    artwork_bounds = display.artwork_button.compute_bounds(page)[1]
    menu_bounds = display.discover_toolbar.compute_bounds(page)[1]
    metadata_bounds = display.now_playing_centre.compute_bounds(page)[1]
    above = artwork_bounds.get_y() - menu_bounds.get_y() - menu_bounds.get_height()
    below = metadata_bounds.get_y() - artwork_bounds.get_y() - artwork_bounds.get_height()
    assert above > below >= 16, (above, below)

display.set_roon_view("source")
display.source_title.set_text("WATCH TV"); display.source_volume.set_text("77")
capture("watch-tv")
assert window.get_width() == screen_width and window.get_height() == screen_height
if min(screen_width, screen_height) >= 1000:
    assert display.source_volume.get_height() > 350
display.set_roon_view("now")

display.set_roon_view("browse")
display.render_browser({"status":"ready", "section":"albums", "title":"Fixture Album", "layout":"list", "can_back":True,
    "album_profile":{"name":"Fixture Album", "artist":"Fixture Artist", "image_key":None, "review":""},
    "items":[{"title":"Play Album", "action":True, "item_key":"play"}] + [{"title":f"Track {index}", "subtitle":"Fixture Artist", "item_key":f"track-{index}"} for index in range(1, 9)]})
capture("album-detail")
if screen_width > screen_height and screen_height <= 600:
    # Xvfb's root capture remains the exact physical viewport; GTK may retain
    # the scrollable album list's natural height after the frame is rendered.
    assert window.get_width() == screen_width and window.get_height() <= screen_height + 100, (window.get_width(), window.get_height(), screen_width, screen_height)
else:
    assert window.get_width() == screen_width and window.get_height() == screen_height
assert display.browser_list.get_first_child().has_css_class("album-profile")
display.browser_action_anchor = display.browser_list.get_first_child().get_next_sibling()
display.render_browser({"status":"ready", "layout":"list", "action_menu":True, "items":[{"title":"Play Now", "action":True, "item_key":"play-now"},{"title":"Add Next", "action":True, "item_key":"next"},{"title":"Queue", "action":True, "item_key":"queue"}]})
capture("track-actions")
display.capture_display("track-menu-capture-check")
assert "image" in capture_results[-1], capture_results[-1]
(OUTPUT / "track-actions-live-capture.png").write_bytes(base64.b64decode(capture_results[-1]["image"]))
popup = display.browser_action_popover
valid, popup_bounds = popup.compute_bounds(page)
anchor_bounds = display.browser_action_anchor.compute_bounds(page)[1]
assert valid and popup_bounds.get_x() >= 0 and popup_bounds.get_y() >= 0
assert popup_bounds.get_x() + popup_bounds.get_width() <= screen_width
if screen_height <= 600:
    expected_x = anchor_bounds.get_x() + min(116, anchor_bounds.get_width()) - 18
    # GTK includes the compact popover's opaque dismissal gutter in these
    # bounds; the visible bordered menu remains aligned with the text column.
    assert abs(popup_bounds.get_x() - expected_x) <= 64, (popup_bounds.get_x(), expected_x)
    assert popup_bounds.get_height() < 340, popup_bounds.get_height()
# Dismiss without issuing a fixture request to the real controller.
if isinstance(popup, Gtk.Popover): popup.unparent()
display.set_roon_view("now")

bus = display.build_bus(); window.set_child(bus)
display.render_bus({"status": "ok", "stop_name": "Flamingo Valley", "stop_code": "83249", "services": [{"service": number, "arrivals": [{"minutes": value, "monitored": True} for value in (1, 14, 28)]} for number in ("40", "42")]})
capture("bus-times")
if min(screen_width, screen_height) >= 1000:
    display.render_bus({"status":"ok", "services":[{"service":number,"arrivals":[{"minutes":value,"monitored":True} for value in (0,123)]} for number in ("40","42")]})
    capture("bus-times-due")
    assert window.get_width() == screen_width and window.get_height() == screen_height
    display.render_bus({"status":"ok", "services":[{"service":number,"arrivals":[{"minutes":value,"monitored":True} for value in (1,14,28)]} for number in ("40","42")]})
    settle()
bus_content_top = display.services.get_first_child().compute_bounds(bus)[1].get_y()
bus_stroke = display.services.get_first_child().get_style_context().get_border().left
bus_clock_bounds = display.bus_clock.compute_bounds(bus)[1]
bus_clock_right = bus_clock_bounds.get_x() + bus_clock_bounds.get_width()
bus_clock_top = bus_clock_bounds.get_y()
assert bus.get_first_child().get_first_child().get_tooltip_text() == "Settings"
assert bus.get_first_child().get_last_child().get_child() is display.bus_clock
first_arrivals = display.services.get_first_child().get_last_child()
arrival_count = 0; arrival_child = first_arrivals.get_first_child()
while arrival_child:
    arrival_count += 1; arrival_child = arrival_child.get_next_sibling()
assert arrival_count == (2 if screen_height > screen_width else 3), arrival_count
# Portrait cards have one primary arrival and two secondary arrivals.
if screen_height > screen_width:
    assert first_arrivals.get_first_child().get_first_child().get_text() == "14"
    assert first_arrivals.get_last_child().get_first_child().get_text() == "28"
if screen_height > screen_width:
    assert display.services.get_first_child().get_orientation() == Gtk.Orientation.VERTICAL
    assert not display.services.get_first_child().get_vexpand()
    last_panel = display.services.get_last_child().compute_bounds(display.bus_content)[1]
    status_bounds = display.bus_status.get_parent().compute_bounds(display.bus_content)[1]
    gap = status_bounds.get_y() - last_panel.get_y() - last_panel.get_height()
    assert 0 <= gap <= 20, gap
assert window.get_width() == screen_width and window.get_height() == screen_height, (window.get_width(), window.get_height(), screen_width, screen_height)
display.render_bus({"status": "ok", "stop_name": "Flamingo Valley", "stop_code": "83249", "services": [{"service": number, "arrivals": [{"minutes": value} for value in (1, 14, 28)]} for number in ("40", "42", "401", "14")]})
capture("bus-times-four-routes")
if window.get_height() != screen_height:
    print("Bus height diagnostic:", tuple(display.bus_scroll.measure(Gtk.Orientation.VERTICAL, screen_width)), tuple(display.services.measure(Gtk.Orientation.VERTICAL, screen_width)), flush=True)
if screen_width > screen_height and screen_height <= 600:
    assert window.get_width() == screen_width and window.get_height() <= screen_height + 60, (window.get_width(), window.get_height(), screen_width, screen_height)
else:
    assert window.get_width() == screen_width and window.get_height() == screen_height, (window.get_width(), window.get_height(), screen_width, screen_height)

home = display.build_home(); window.set_child(home)
display.settings_data["display_theme"] = "roon"
display.render_home({"status": "ok", "entities": [{"entity_id": f"{domain}.fixture{index}", "domain": domain, "name": name, "state": "on", "supports_level": domain in ("fan", "light"), "percentage": 50} for index, (domain, name) in enumerate((("fan", "Living Room Fan"), ("light", "Living Room"), ("switch", "Pi-Hole Master"), ("switch", "Pi-Hole Slave")))]})
capture("home")
assert not display.home_status.get_visible()
assert abs(display.home_grid.get_first_child().compute_bounds(home)[1].get_y() - bus_content_top) <= 1
assert display.home_grid.get_first_child().get_style_context().get_border().left == bus_stroke == native.PANEL_STROKE
home_clock_bounds = display.home_clock.compute_bounds(home)[1]
assert abs(home_clock_bounds.get_x() + home_clock_bounds.get_width() - bus_clock_right) <= 1
assert abs(home_clock_bounds.get_y() - bus_clock_top) <= 1
assert home.get_first_child().get_first_child().get_tooltip_text() == "Settings"
assert home.get_first_child().get_last_child().get_child() is display.home_clock
icon = display.home_grid.get_first_child().get_first_child().get_first_child().get_child()
original_icon_size = max(64, min(240, round((screen_height - 190) / 4 * .7))) if screen_height > screen_width else 108 if max(screen_width, screen_height) >= 1200 else 72
assert icon.get_pixel_size() == round(original_icon_size * .75)
assert icon.get_width() >= original_icon_size
if screen_height > screen_width:
    assert display.home_grid.get_first_child().get_orientation() == Gtk.Orientation.HORIZONTAL

settings = display.build_settings()
window.set_child(settings)
display.configure_settings_layout(screen_width, screen_height)
display.device_status.set_text("v1.1.3 Alpine")
display.touch_diagnostics.set_text("Memory 6.1%  ·  Load 0.65  ·  62.8°C  ·  Controller ready  ·  Bridge offline")
capture("settings")
assert window.get_width() == screen_width and window.get_height() == screen_height, (window.get_width(), window.get_height())
assert display.settings_actions.get_last_child().has_css_class("reboot-action")
assert display.touch_bus_enabled.get_visible()
assert display.touch_bus_heading.get_visible() == (screen_height > screen_width or screen_width > 1280)
assert display.touch_bus_enabled.get_label() == "Bus Times"

# The optional black canvas preserves all foreground controls and works on
# every native page without changing the selected colour theme.
window.add_css_class("background-black")
capture("settings-black")
window.set_child(bus)
capture("bus-times-black")
window.set_child(page)
capture("music-black")
display.set_roon_view("queue")
display.render_queue({"items":[{"title":name, "artist":"Bloc Party", "album":"Silent Alarm", "queue_item_id":index, "image_key":"queue-fixture", "length":234, "is_current":index==1} for index, name in enumerate(("Helicopter", "Positive Tension", "She's Hearing Voices"))]})
for picture in display.queue_pictures.get("queue-fixture", []): picture.set_filename(str(fixture_art("queue", "SILENT ALARM")))
capture("queue-black")
window.remove_css_class("background-black")

window.set_child(None)
display.root_overlay = Gtk.Overlay(); display.root_overlay.set_child(home); window.set_child(display.root_overlay)
display.confirm_reboot()
capture("reboot-confirmation")
card = display.reboot_confirmation.get_last_child()
bounds = card.compute_bounds(display.root_overlay)[1]
assert bounds.get_y() + bounds.get_height() / 2 < screen_height / 2 - 10

print(f"Wrote native Alpine visual review frames to {OUTPUT}")
