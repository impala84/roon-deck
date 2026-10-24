"""Exercise native control logic without requiring GTK on the test host."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import base64
import io
import subprocess
import uuid
from unittest.mock import Mock


SOURCE = Path(__file__).parents[1] / "native-display" / "pi_bus_native.py"


def native_method(name, dependencies=None):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(dependencies or {})
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


class Entry:
    def __init__(self, text, position, selection=(False, 0, 0)):
        self.text, self.position, self.selection = text, position, selection
    def get_text(self): return self.text
    def get_position(self): return self.position
    def get_selection_bounds(self): return self.selection
    def set_text(self, text): self.text = text
    def set_position(self, position): self.position = position


class PortraitRefinementTests(unittest.TestCase):
    def test_home_scene_feedback_centres_labels_and_pulses_the_whole_tile(self):
        code = SOURCE.read_text()
        self.assertIn('name.set_justify(Gtk.Justification.LEFT if portrait else Gtk.Justification.CENTER)', code)
        self.assertIn('button.scene_tile = box', code)
        self.assertIn('button.scene_tile.add_css_class("activated")', code)
        self.assertIn('button.scene_tile.remove_css_class("activated")', code)
        self.assertIn('.theme-roon .home-tile.activated', code)
        self.assertIn('box.add_css_class("home-domain-switch" if domain == "input_boolean" else f"home-domain-{domain}")', code)
        self.assertIn('def apply_home_colors(self, config):', code)

    def test_decoded_thumbnail_only_updates_widgets_on_ui_thread(self):
        picture = SimpleNamespace(set_paintable=Mock())
        texture = object()
        owner = SimpleNamespace(queue_thumbnail_pending={"cover"}, queue_thumbnail_cache={}, queue_thumbnail_order=[], queue_pictures={"cover": [picture]}, browser_pictures={}, discovery_pictures={}, decode_artwork=Mock())
        self.assertFalse(native_method("apply_queue_thumbnail")(owner, "cover", texture, True))
        owner.decode_artwork.assert_not_called()
        picture.set_paintable.assert_called_once_with(texture)
        self.assertIs(owner.queue_thumbnail_cache["cover"], texture)
        self.assertNotIn("cover", owner.queue_thumbnail_pending)

    def test_large_preview_uses_its_own_full_resolution_cache_and_requests_900px(self):
        code = SOURCE.read_text()
        render = code.split('if items and data.get("surprise_preview"):', 1)[1].split('title = self.label', 1)[0]
        self.assertIn('self.load_preview_artwork(picture, key)', render)
        self.assertNotIn('queue_thumbnail_cache', render)
        preview = code.split('def load_preview_artwork', 1)[1].split('def apply_queue_thumbnail', 1)[0]
        self.assertIn('&size=900', preview)
        self.assertIn('self.preview_artwork_cache.get(key)', preview)
        self.assertIn('self.preview_artwork_cache[key] = texture', preview)

    def test_gen2_daily_and_search_spacing_is_scoped_to_1280_landscape(self):
        code = SOURCE.read_text()
        self.assertIn('("touch2-7-landscape", touch2_7_landscape)', code)
        self.assertIn('.touch2-7-landscape .search-main { margin-top: 26px; margin-right: 28px; }', code)
        self.assertIn('24 if offset_discovery', code)
        self.assertIn('gen2_genre = tile_kind == "genres" and self.window.has_css_class("touch2-7-landscape")', code)

    def test_daily_track_action_keeps_its_visible_mix_row_anchor(self):
        code = SOURCE.read_text()
        method = code.split('def open_discovery_item', 1)[1].split('def browser_swipe_back', 1)[0]
        self.assertIn('self.browser_action_anchor = anchor', method)
        self.assertIn('self.discovery_action_key = key', method)
        self.assertNotIn('while child := self.discovery_list.get_first_child()', method.split('def apply_discovery_item', 1)[0])
        self.assertIn('if data.get("action_menu"):\n            self.render_browser(data)', method)
        self.assertIn('/api/discovery/track-action', code)

    def test_large_settings_and_dynamic_play_icon_keep_their_size(self):
        code = SOURCE.read_text()
        self.assertIn('.large-display .settings-page .settings-title { font-size: 44px;', code)
        self.assertIn('.large-display .settings-header .settings-utilities button { font-size: 23px;', code)
        self.assertIn('icon_size = 80 if self.window.has_css_class("large-display") else 42', code)
        self.assertIn('self.volume_row.set_size_request(round((width - 60) * .88) if portrait else -1', code)

    def test_carousel_end_changes_only_the_trailing_margin(self):
        track = Mock()
        scroller = SimpleNamespace(get_mapped=lambda: True, compute_bounds=lambda _: (True, SimpleNamespace(get_x=lambda: 165)))
        owner = SimpleNamespace(window=object())
        method = native_method("configure_carousel_end", {"CAROUSEL_END_SPACE": 30})
        self.assertFalse(method(owner, scroller, track))
        track.set_margin_end.assert_called_once_with(30)
        track.set_margin_start.assert_not_called()

    def test_carousel_spring_animates_then_returns_exactly_to_rest(self):
        import math
        now = [0.0]; callbacks = []
        owner = SimpleNamespace(elastic_offset=15.0, spring_timer=None, queue_draw=Mock(), get_mapped=lambda: True)
        owner.add_tick_callback = lambda callback: callbacks.append(callback) or 1
        owner.cancel_spring = lambda: setattr(owner, "elastic_offset", 0.0)
        glib = SimpleNamespace(timeout_add=lambda ms, callback: callbacks.append(callback) or 1)
        native_method("spring_back", {"GLib": glib, "time": SimpleNamespace(monotonic=lambda: now[0]), "math": math})(owner)
        now[0] = .08; self.assertTrue(callbacks[0](None, None))
        self.assertLess(abs(owner.elastic_offset), 15)
        now[0] = .2; self.assertTrue(callbacks[0](None, None))
        self.assertLess(owner.elastic_offset, 0)
        now[0] = .66; self.assertFalse(callbacks[0](None, None))
        self.assertEqual(owner.elastic_offset, 0)
        self.assertIsNone(owner.spring_timer)

    def test_carousel_touch_pull_resists_both_ends_without_moving_scroll(self):
        import math
        handlers = {}
        drag = SimpleNamespace(set_touch_only=Mock(), set_propagation_phase=Mock(), set_state=Mock(), connect=lambda name, handler: handlers.update({name: handler}))
        gtk = SimpleNamespace(GestureDrag=lambda: drag, PropagationPhase=SimpleNamespace(CAPTURE=1), EventSequenceState=SimpleNamespace(CLAIMED=2))
        value = [0]
        adjustment = SimpleNamespace(get_lower=lambda: 0, get_upper=lambda: 600, get_page_size=lambda: 200, get_value=lambda: value[0], set_value=Mock())
        scroller = SimpleNamespace(get_hadjustment=lambda: adjustment, add_controller=Mock())
        owner = SimpleNamespace(cancel_spring=Mock(), queue_draw=Mock(), spring_back=Mock(), elastic_offset=0)
        native_method("attach_touch_pull", {"Gtk": gtk, "math": math})(owner, scroller)
        for boundary, distance in ((0, 100), (400, -100)):
            value[0] = boundary; handlers["drag-begin"]()
            handlers["drag-update"](drag, distance, 0)
            self.assertGreater(abs(owner.elastic_offset), 0)
            self.assertLess(abs(owner.elastic_offset), 34)
            self.assertEqual(owner.elastic_offset > 0, distance > 0)
            adjustment.set_value.assert_not_called()
            handlers["drag-end"](); owner.spring_back.assert_called()
        drag.set_state.reset_mock(); handlers["drag-begin"]()
        handlers["drag-update"](drag, 20, 80)
        drag.set_state.assert_not_called()

    def test_vertical_pull_uses_vertical_adjustment_and_ignores_sideways_drag(self):
        import math
        handlers = {}
        drag = SimpleNamespace(set_touch_only=Mock(), set_propagation_phase=Mock(), set_state=Mock(), connect=lambda name, handler: handlers.update({name: handler}))
        gtk = SimpleNamespace(GestureDrag=lambda: drag, ScrolledWindow=object, PropagationPhase=SimpleNamespace(CAPTURE=1), EventSequenceState=SimpleNamespace(CLAIMED=2))
        value = [0]
        adjustment = SimpleNamespace(get_lower=lambda: 0, get_upper=lambda: 600, get_page_size=lambda: 200, get_value=lambda: value[0], set_value=Mock())
        scroller = SimpleNamespace(get_vadjustment=lambda: adjustment, add_controller=Mock())
        owner = SimpleNamespace(cancel_spring=Mock(), queue_draw=Mock(), spring_back=Mock(), elastic_offset=0, get_ancestor=lambda _: scroller)
        native_method("attach_touch_pull", {"Gtk": gtk, "math": math})(owner, scroller, vertical=True)
        for boundary, distance in ((0, 100), (400, -100)):
            value[0] = boundary; handlers["drag-begin"](); handlers["drag-update"](drag, 0, distance)
            self.assertGreater(abs(owner.elastic_offset), 18)
            self.assertLess(abs(owner.elastic_offset), 34)
            self.assertEqual(owner.elastic_offset > 0, distance > 0)
            adjustment.set_value.assert_not_called()
            handlers["drag-end"](); owner.spring_back.assert_called()
        drag.set_state.reset_mock(); handlers["drag-begin"](); handlers["drag-update"](drag, 80, 20)
        drag.set_state.assert_not_called()

    def test_http_error_is_preserved_only_for_browse(self):
        import io, json, urllib.error
        for path, expected in (("/api/browse", {"error": "Roon Browse request timed out"}), ("/api/control", None)):
            error = urllib.error.HTTPError("http://localhost" + path, 500, "error", {}, io.BytesIO(b'{"error":"Roon Browse request timed out"}'))
            urllib_mock = SimpleNamespace(error=urllib.error, request=SimpleNamespace(Request=Mock(), urlopen=Mock(side_effect=error)))
            result = native_method("post_json", {"urllib": urllib_mock, "json": json})("http://localhost" + path, {})
            self.assertEqual(result, expected)

    def test_render_failure_unlocks_browser_navigation(self):
        owner = SimpleNamespace(browser_pending_request=None,
            render_browser=Mock(side_effect=ValueError("bad view")),
            browser_loading=True, browser_rendering=True, browser_scroll_restore=20,
            browser_list=LayoutWidget(), label=lambda *args: LayoutWidget())
        native_method("apply_browser_response")(owner, {"status": "ready"})
        self.assertFalse(owner.browser_loading)
        self.assertFalse(owner.browser_rendering)
        self.assertIsNone(owner.browser_scroll_restore)
        self.assertEqual(len(owner.browser_list.children), 1)

    def test_utility_icon_receives_each_css_class(self):
        widget = LayoutWidget(); widget.update_property = Mock()
        gtk = SimpleNamespace(Button=lambda: widget, AccessibleProperty=SimpleNamespace(LABEL="label"))
        image = LayoutWidget(); image.icon_name = "clock"
        button = native_method("icon_button", {"Gtk": gtk, "FamilyIcon": lambda *_, **__: image})(SimpleNamespace(), "clock", lambda *_: None, "discover-utility discover-sleep")
        self.assertEqual(button.classes, {"discover-utility", "discover-sleep"})
        widget.update_property.assert_called_once_with(["label"], ["Clock"])

    def test_grid_margins_and_gaps_are_thirty_pixels(self):
        monitor = SimpleNamespace(get_geometry=lambda: SimpleNamespace(width=720))
        monitors = SimpleNamespace(get_n_items=lambda: 1, get_item=lambda _: monitor)
        gdk = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(get_monitors=lambda: monitors)))
        owner = SimpleNamespace(responsive_portrait=True, settings_data={"portrait_discovery_columns": 3}, window=SimpleNamespace(get_width=lambda: 720))
        self.assertEqual(native_method("discovery_grid_metrics", {"Gdk": gdk})(owner), (3, 200))
        self.assertEqual(native_method("browser_grid_metrics", {"Gdk": gdk})(owner, True), (3, 200))

    def test_portrait_search_stays_with_keyboard(self):
        owner = SimpleNamespace(responsive_portrait=True, browser_search_entry=SimpleNamespace(get_text=lambda: "Oasis"), set_roon_view=Mock(), request_browser=Mock())
        native_method("submit_browser_search")(owner)
        owner.set_roon_view.assert_called_once_with("search")
        owner.request_browser.assert_called_once_with("search", query="Oasis", source="all")

    def test_bus_count_matches_orientation_and_route_is_solid(self):
        source = SOURCE.read_text()
        self.assertIn('service.get("arrivals", [])[:3]', source)
        self.assertIn('self.render_portrait_bus_card(row, service, len(visible))', source)
        self.assertIn('sized("THEN", "bus-then"', source)
        self.assertIn('number.add_css_class("solid-route")', source)
        self.assertIn('row.append(number)', source)

    def test_portrait_back_spacer_expands(self):
        source = SOURCE.read_text()
        self.assertIn('spacer.set_hexpand(portrait)', source)
        self.assertIn('back.set_halign(Gtk.Align.END if portrait else Gtk.Align.START)', source)
class LayoutWidget:
    """Record widget construction without pretending to allocate a GTK screen."""
    def __init__(self, **kwargs):
        self.children, self.classes, self.properties = [], set(), dict(kwargs)
    def append(self, child): self.children.append(child)
    def remove(self, child): self.children.remove(child)
    def get_first_child(self): return self.children[0] if self.children else None
    def get_child(self): return self.properties.get("child", self)
    def set_child(self, child): self.properties["child"] = child
    def add_css_class(self, name): self.classes.add(name)
    def remove_css_class(self, name): self.classes.discard(name)
    def connect(self, event, callback): self.properties[event] = callback
    def cancel_spring(self): self.properties["elastic_offset"] = 0
    def __getattr__(self, name):
        if name.startswith("set_"):
            return lambda *args: self.properties.__setitem__(name[4:], args)
        raise AttributeError(name)


LAYOUT_GTK = SimpleNamespace(Box=LayoutWidget, Picture=LayoutWidget, ScrolledWindow=LayoutWidget, Button=LayoutWidget, Orientation=SimpleNamespace(VERTICAL="vertical"), Align=SimpleNamespace(START="start", END="end", CENTER="center"), PolicyType=SimpleNamespace(NEVER="never", AUTOMATIC="automatic", EXTERNAL="external"), ContentFit=SimpleNamespace(COVER="cover"))


class NativeBrowserControlsTests(unittest.TestCase):
    def test_portrait_bus_card_has_one_primary_and_two_following_predictions(self):
        gtk = SimpleNamespace(Box=LayoutWidget, Separator=LayoutWidget,
            Orientation=SimpleNamespace(VERTICAL="vertical", HORIZONTAL="horizontal"),
            Align=SimpleNamespace(CENTER="center", FILL="fill"))
        pango = SimpleNamespace(AttrList=lambda:SimpleNamespace(insert=lambda _:None),
            attr_size_new_absolute=lambda value:value, SCALE=1024)
        labels = []
        def label(text, css, align):
            widget = LayoutWidget(text=text); widget.add_css_class(css); labels.append(widget)
            return widget
        owner = SimpleNamespace(window=SimpleNamespace(get_height=lambda:1920,get_width=lambda:1200),label=label)
        method = native_method("render_portrait_bus_card", {"Gtk":gtk,"Pango":pango})
        row = LayoutWidget()
        method(owner, row, {"service":"42","arrivals":[{"minutes":0},{"minutes":11},{"minutes":25}]},2)
        self.assertEqual([widget.properties['text'] for widget in labels],
            ["ROUTE","42","Due","arriving now","THEN","11","min","25","min"])
        self.assertEqual(len(row.children[-1].children),2)
        labels.clear()
        one_later = LayoutWidget()
        method(owner, one_later, {"service":"40","arrivals":[{"minutes":8},{"minutes":28}]},2)
        self.assertEqual([widget.properties['text'] for widget in labels][-3:],["THEN","28","min"])
        self.assertEqual(len(one_later.children[-1].children),1)
        labels.clear()
        one_bus = LayoutWidget()
        method(owner, one_bus, {"service":"40","arrivals":[{"minutes":8}]},2)
        self.assertEqual([widget.properties['text'] for widget in labels],["ROUTE","40","8","minutes"])
        self.assertFalse(any(widget.properties.get('text') == "—" for widget in labels))

    def test_late_loaded_source_buttons_follow_current_orientation(self):
        for portrait in (True, False):
            owner = SimpleNamespace(responsive_portrait=portrait, roon_subnav=LayoutWidget(),
                now_playing_tab=LayoutWidget(), queue_tab=LayoutWidget(), browser_tab=LayoutWidget(),
                requested_audio_view="source", button=lambda *args: LayoutWidget(),
                refresh_music_subnav_layout=Mock())
            method = native_method("render_bluos_inputs")
            method(owner, {"inputs": [{"id": "tv", "name": "Watch TV"}, {"id": "rega", "name": "Rega P3"}],
                "active_input": {"id": "tv"}}, True)
            for button in owner.bluos_source_buttons.values():
                self.assertEqual(button.properties["hexpand"], (portrait,))
            self.assertIn("active", owner.bluos_source_buttons["tv"].classes)
            self.assertNotIn("active", owner.bluos_source_buttons["rega"].classes)
            owner.refresh_music_subnav_layout.assert_called_once_with()

    def test_optional_music_tabs_force_the_selector_to_reflow(self):
        code = SOURCE.read_text(encoding="utf-8")
        method = code.split("def refresh_music_subnav_layout", 1)[1].split("def select_bluos_input", 1)[0]
        self.assertIn("self.roon_subnav.set_halign(Gtk.Align.FILL if portrait else Gtk.Align.CENTER)", method)
        self.assertIn("child.set_hexpand(portrait)", method)
        self.assertIn("self.roon_subnav.set_size_request(-1, -1)", method)
        self.assertIn("self.roon_subnav.queue_resize()", method)
        settings = code.split('self.sync_music_navigation(); self.queue_tab.set_visible', 1)[1].split('if system is not None:', 1)[0]
        self.assertIn("self.refresh_music_subnav_layout()", settings)

    def test_music_clock_redraws_on_minute_change_not_every_tick(self):
        from datetime import datetime
        clock = Mock()
        owner = SimpleNamespace(bus_clock=Mock(), roon_clock=Mock(), home_clock=Mock(), sleep_clock=Mock(), music_clock_icon=clock)
        first = datetime(2026, 10, 6, 21, 30)
        second = datetime(2026, 10, 6, 21, 31)
        method = native_method("tick", {"datetime": SimpleNamespace(now=Mock(side_effect=[first, first, second])), "TZ": None})
        for _ in range(3): self.assertTrue(method(owner))
        self.assertEqual(clock.queue_draw.call_count, 2)
        owner.roon_clock.set_text.assert_called_with("21:31")

    def test_music_clock_hands_follow_current_time(self):
        import math
        owner = SimpleNamespace(settings_data={})
        time = SimpleNamespace(hour=3, minute=30)
        gtk = SimpleNamespace(DrawingArea=LayoutWidget)
        method = native_method("discover_utility_icon", {"Gtk": gtk, "math": math, "datetime": SimpleNamespace(now=lambda _: time), "TZ": None})
        icon = method(owner, clock=True); context = Mock()
        icon.properties["draw_func"][0](icon, context, 30, 34)
        minute, hour = context.line_to.call_args_list
        self.assertAlmostEqual(minute.args[0], 0, places=6)
        self.assertAlmostEqual(minute.args[1], 9, places=6)
        self.assertAlmostEqual(hour.args[0], math.cos(math.pi / 12) * 6)
        self.assertAlmostEqual(hour.args[1], math.sin(math.pi / 12) * 6)

    def test_loading_animation_stops_when_unmapped_and_restarts_once(self):
        callbacks = {}; removed = []
        glib = SimpleNamespace(timeout_add=lambda delay, fn: callbacks.setdefault("pulse", (delay, fn)) and 7, source_remove=removed.append)
        owner = SimpleNamespace(label=lambda *args: LayoutWidget())
        panel = native_method("loading_notice", {"Gtk": LAYOUT_GTK, "GLib": glib, "time": __import__("time"), "math": __import__("math")})(owner)
        panel.properties["map"](); panel.properties["map"]()
        self.assertEqual(callbacks["pulse"][0], 80)
        self.assertTrue(callbacks["pulse"][1]())
        for dot in panel.children[0].children:
            self.assertTrue(.25 <= dot.properties["opacity"][0] <= 1)
        panel.properties["unmap"](); panel.properties["unmap"]()
        self.assertEqual(removed, [7])
        panel.properties["map"](); panel.properties["unmap"]()
        self.assertEqual(removed, [7, 7])

    def test_portrait_discover_uses_one_toolbar_not_zone_and_clock_row(self):
        owner = SimpleNamespace(responsive_portrait=True, discovery_active=True, roon_views=SimpleNamespace(get_visible_child_name=lambda: "browse"), roon_subnav=Mock(), discover_subnav=Mock(), browser_tab=Mock(), discover_toolbar=Mock(), music_header_overlay=Mock(), portrait_music_tabs=Mock())
        native_method("sync_music_navigation")(owner)
        owner.discover_toolbar.set_visible.assert_called_with(True)
        owner.music_header_overlay.set_visible.assert_called_with(False)
        owner.portrait_music_tabs.set_visible.assert_called_with(False)
        owner.discovery_active = False
        native_method("sync_music_navigation")(owner, "now")
        owner.discover_toolbar.set_visible.assert_called_with(True)
        owner.music_header_overlay.set_visible.assert_called_with(False)

    def test_landscape_keeps_music_utility_icons(self):
        owner = SimpleNamespace(responsive_portrait=False, discovery_active=True, roon_views=SimpleNamespace(get_visible_child_name=lambda: "browse"), roon_subnav=Mock(), discover_subnav=Mock(), browser_tab=Mock(), discover_toolbar=Mock(), music_header_overlay=Mock(), portrait_music_tabs=Mock())
        for view in ("browse", "discover", "now", "queue"):
            native_method("sync_music_navigation")(owner, view)
            owner.discover_toolbar.set_visible.assert_called_with(True)
            owner.music_header_overlay.set_visible.assert_called_with(False)

    def test_now_playing_library_control_is_a_bundled_heart_and_remains_visible_for_an_album(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.library_add = self.button("", self.add_current_album)', code)
        self.assertIn('self.library_add.set_visible(has_album)', code)
        self.assertIn('self.set_library_icon(self.library_favorite is True)', code)
        self.assertIn('FamilyIcon("add", size)', code)
        self.assertIn('FamilyIcon("heart", size, filled=filled)', code)
        self.assertIn('size = 64 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 28', code)
        self.assertIn('self.library_add.set_valign(Gtk.Align.CENTER)', code)
        self.assertIn('self.library_add.set_halign(Gtk.Align.CENTER)', code)
        self.assertIn('self.library_pending = True', code)
        self.assertIn('except urllib.error.HTTPError as error:', code)
        for name in ("heart.svg", "heart-filled.svg", "heart-roon.svg", "heart-filled-roon.svg"):
            self.assertTrue((SOURCE.parent / "icons" / name).is_file())

    def test_library_busy_pulses_button_and_clears_accessible_state(self):
        button = Mock()
        owner = SimpleNamespace(library_add=button)
        gtk = SimpleNamespace(AccessibleState=SimpleNamespace(BUSY="busy"))
        method = native_method("set_library_busy", {"Gtk": gtk})
        method(owner, True)
        button.add_css_class.assert_called_once_with("library-busy")
        button.update_state.assert_called_with(["busy"], [True])
        method(owner, False)
        button.remove_css_class.assert_called_once_with("library-busy")
        button.update_state.assert_called_with(["busy"], [False])
        code = SOURCE.read_text()
        self.assertNotIn('set_text("Updating Roon…")', code)
        self.assertIn('self.library_pending = False\n                self.set_library_busy(False)', code)

    def test_now_playing_title_and_artist_fill_their_column_before_centering(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.title.set_hexpand(True); self.title.set_halign(Gtk.Align.FILL)', code)
        self.assertIn('self.title.set_wrap_mode(Pango.WrapMode.WORD_CHAR); self.title.set_lines(2); self.title.set_ellipsize(Pango.EllipsizeMode.END)', code)
        self.assertIn('self.artist.set_hexpand(True); self.artist.set_halign(Gtk.Align.FILL)', code)

    def test_display_runtime_publishes_the_resolved_source_revision(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / "native-display" / "pi_bus_native.py"
            source.parent.mkdir(); source.write_text("")
            (root / ".source-commit").write_text("a" * 40)
            run = root / "run"; run.mkdir()
            function = native_method("publish_display_source", {"Path": lambda value: run / "display-source-commit" if value == "/run/pi-home/display-source-commit" else Path(value), "re":__import__("re"), "__file__":str(source)})
            function()
            self.assertEqual((run / "display-source-commit").read_text().strip(), "a" * 40)

    def test_daily_uses_roomy_native_swipe_tracks_without_arrow_controls(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('scroller.set_kinetic_scrolling(True)', code)
        self.assertIn('scroller.set_overlay_scrolling(True)', code)
        self.assertIn('super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)', code)
        self.assertIn('track.attach_touch_pull(scroller)', code)
        self.assertIn('self.discovery_daily_sections.setdefault(section_key, scroller)', code)
        self.assertNotIn('"go-previous-symbolic"', code)
        self.assertNotIn('"go-next-symbolic"', code)
        self.assertNotIn('carousel-arrow', code)
        self.assertIn('.touch-landscape .roon-page { padding-right: 0; }', code)
        self.assertIn('.touch-landscape .roon-header, .touch-landscape .roon-page .nav', code)

    def test_genre_icons_are_bundled_svgs_not_font_glyphs(self):
        import xml.etree.ElementTree as ET
        method = native_method('browser_tile_symbol')
        for title in ('Pop/Rock', 'Classical', 'Electronic', 'Jazz', 'Stage & Screen', 'International', 'Vocal', 'Blues', 'Easy Listening', 'R&B', 'Folk', 'Reggae', 'Ambient', 'Holiday', 'Children', 'Gospel', 'Unknown genre'):
            name = method(SimpleNamespace(), title, 'genres')
            path = SOURCE.parents[1] / 'roon-controller/static/icons' / (name + '-symbolic.svg')
            tree = ET.parse(path)
            self.assertEqual(tree.getroot().tag, '{http://www.w3.org/2000/svg}svg')
            self.assertNotIn('<text', path.read_text())
        self.assertEqual(method(SimpleNamespace(), 'Any playlist', 'playlists'), 'playlist')

    def test_original_genre_tiles_separate_icon_and_bottom_label(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('get("display_profile") in {"touch2-7", "touch2-5-7"}', code)
        self.assertIn('.18 if separated_label_tile else .12', code)
        self.assertIn('title.set_margin_bottom(6 if separated_label_tile else', code)

    def test_playlist_tiles_share_genre_caption_layout_and_compact_icon(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('if tile_kind in {"genres", "playlists"}:', code)
        self.assertIn('.58 if tile_kind == "playlists" else .65', code)
        self.assertIn('caption_height = 0 if tile_kind in {"genres", "playlists"}', code)

    def test_search_uses_the_same_sidebar_alignment_class_as_browse(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('search_nav.add_css_class("browser-sidebar"); search_nav.add_css_class("library-sidebar")', code)

    def test_empty_activity_event_does_not_raise_or_change_state(self):
        owner = SimpleNamespace(last_interaction=123)
        self.assertFalse(native_method("note_activity")(owner, None, None))
        self.assertEqual(owner.last_interaction, 123)

    def test_browse_return_uses_its_own_configurable_activity_clock(self):
        now = [1000.0]
        clock = SimpleNamespace(set_text=Mock())
        owner = SimpleNamespace(
            bus_clock=clock, roon_clock=clock, home_clock=clock, sleep_clock=clock,
            last_clock_time="12:00", stack=SimpleNamespace(get_visible_child_name=lambda: "roon"),
            roon_views=SimpleNamespace(get_visible_child_name=lambda: "discover"),
            settings_data={"browse_idle_return_seconds": 60}, browse_last_interaction=999.0,
            last_interaction=1.0, show_roon_now=Mock(),
        )
        fake_datetime = SimpleNamespace(now=lambda _tz: SimpleNamespace(strftime=lambda _format: "12:00", year=2026))
        tick = native_method("tick", {"datetime": fake_datetime, "TZ": object(), "time": SimpleNamespace(monotonic=lambda: now[0])})
        self.assertTrue(tick(owner))
        owner.show_roon_now.assert_not_called()
        now[0] = 1060.0
        self.assertTrue(tick(owner))
        owner.show_roon_now.assert_called_once_with()

    def test_browse_return_can_be_disabled_and_resets_on_navigation(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('browse_timeout > 0', code)
        view_code = code.split('def set_roon_view', 1)[1].split('def ', 1)[0]
        self.assertIn('self.browse_last_interaction = time.monotonic()', view_code)
        self.assertIn('"details"', view_code)
        self.assertIn('self.browse_last_interaction = self.last_interaction', code.split('def note_activity', 1)[1].split('def ', 1)[0])

    def test_browse_return_timer_resets_during_kinetic_scrolling(self):
        now = [1234.0]
        owner = SimpleNamespace(
            stack=SimpleNamespace(get_visible_child_name=lambda: "roon"),
            roon_views=SimpleNamespace(get_visible_child_name=lambda: "browse"),
            browse_last_interaction=1.0,
        )
        native_method("note_browse_scroll", {"time": SimpleNamespace(monotonic=lambda: now[0])})(owner)
        self.assertEqual(owner.browse_last_interaction, 1234.0)
        code = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(code.count('get_vadjustment().connect("value-changed", self.note_browse_scroll)'), 2)

    def test_discover_navigation_resumes_the_existing_browse_state(self):
        buttons = {name: LayoutWidget() for name in ("recent", "browse", "daily")}
        owner = SimpleNamespace(discovery_section="browse", browser_state={"title":"Albums"},
            discover_tabs=buttons, set_roon_view=Mock(), set_mode=Mock())
        native_method("resume_discover")(owner)
        owner.set_roon_view.assert_called_once_with("browse")
        owner.set_mode.assert_called_once_with("roon")
        self.assertTrue(owner.discovery_active)
        self.assertIn("active", buttons["browse"].classes)

    def test_now_playing_volume_step_uses_one_percent_and_clamps(self):
        adjustment = SimpleNamespace(get_lower=lambda: 0, get_upper=lambda: 100)
        scale = SimpleNamespace(get_adjustment=lambda: adjustment, get_value=lambda: 99, set_value=Mock())
        owner = SimpleNamespace(state={"zone":{}}, volume=scale)
        native_method("step_volume")(owner, 1)
        scale.set_value.assert_called_once_with(100)
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.step_volume(-1)', code)
        self.assertIn('self.step_volume(1)', code)

    def test_final_play_actions_use_the_primary_colour_treatment(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"artist-play primary-play" if action == "play"', code)
        self.assertIn('"artist-play primary-play")', code)
        self.assertIn('.artist-play { margin-top: 12px;', code)
        self.assertIn('.theme-roon .artist-play { background: #9868F9;', code)

    def test_selected_soft_pill_actions_use_filled_play_and_outlined_queue(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('border-radius: 999px; background: #6ed9ae', code)
        self.assertIn('primary_play = name == "play" and "primary-play" in css', code)
        self.assertIn('filled=icon in {"play", "media-playback-start-symbolic"} and "primary-play" in css', code)
        self.assertIn('"queue-pill")', code)
        self.assertIn('.queue-pill, .theme-roon .queue-pill', code)
        self.assertIn('.surprise-action.primary-play', code)

    def test_play_pill_balance_surprise_geometry_and_splash_hold(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('padding: 12px 30px 12px 20px', code)
        self.assertIn('.surprise-action { min-width: 72px; min-height: 72px; padding: 8px; border-radius: 50%', code)
        self.assertIn('orientation=Gtk.Orientation.VERTICAL, spacing=16', code)
        self.assertIn('time.monotonic() - self.boot_started_at < 2.5', code)
        self.assertIn('def finish_boot_splash(self):', code)

    def test_detail_artwork_closes_sheet_and_dropdown_play_stays_rectangular(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('for artwork_frame in (self.detail_artist_artwork_frame, self.detail_album_artwork_frame):', code)
        self.assertIn('close_artwork.connect("released", lambda *_: self.set_roon_view("now"))', code)
        self.assertIn('border-radius: 8px; background: #6ed9ae', code)
        self.assertIn('.theme-roon .track-menu-action.primary-play { background: #9868F9; color: #111;', code)

    def test_detail_copy_order_and_compact_identity_are_consistent(self):
        code = SOURCE.read_text(encoding="utf-8")
        artist = code.split('artist_card = Gtk.Box', 1)[1].split('album_card = Gtk.Box', 1)[0]
        self.assertLess(artist.index('detail_artist_writeup'), artist.index('detail_artist_source'))
        self.assertLess(artist.index('detail_artist_source'), artist.index('detail_artist_facts'))
        self.assertIn('getattr(self, "album_focus_detail", False)', code)
        self.assertIn('.compact-detail .detail-title { font-size: 30px; }', code)
        self.assertIn('.compact-detail .detail-header { min-height: 61px; padding: 7px 20px 2px; }', code)
        self.assertIn('.album-focus-detail .detail-writeup { font-size: 19px; line-height: 1.38; }', code)

    def test_detail_columns_share_copy_spacing_and_close_icon_is_prominent(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('artist_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)', code)
        self.assertIn('detail_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)', code)
        self.assertIn('self.detail_subtitle.set_visible(bool(detail_subtitle) and not getattr(self, "album_focus_detail", False))', code)
        self.assertIn('FamilyIcon("close", 34, stroke_width=3)', code)
        self.assertIn('.detail-close-glyph { border: 2px solid #6ed9ae; border-radius: 50%; background: transparent; color: #fff; }', code)
        self.assertIn('.theme-roon .detail-close, .theme-roon .detail-close-glyph { border-color: #9868F9; }', code)

    def test_original_detail_sheet_is_fixed_and_uses_primary_artist_action(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.detail_sheet.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER if original_landscape else Gtk.PolicyType.AUTOMATIC)', code)
        self.assertIn('label.set_lines(3 if original_landscape else 5 if album_focus_detail', code)
        self.assertIn('re.sub(r"\\[\\[\\d+\\|([^\\]]+)\\]\\]", r"\\1", details.get("subtitle") or "")', code)
        self.assertIn('.original-landscape .compact-detail .detail-album-card .detail-action { min-height: 38px; margin-top: 3px; padding: 4px 12px; background: #6ed9ae; color: #111;', code)
        self.assertIn('.original-landscape.theme-roon .compact-detail .detail-album-card .detail-action { background: #9868F9; color: #111; }', code)
        self.assertIn('title.set_xalign(.5); title.set_justify(Gtk.Justification.CENTER)', code)
        self.assertIn('if name == "browse": button.add_css_class("active")', code)
        request_update = code[code.index('    def _request_update(self):'):code.index('    def request_display_settings', code.index('    def _request_update(self):'))]
        self.assertNotIn('self.update_status_seen = True', request_update)
        self.assertIn('self.last_system_fetch = 0', request_update)
        self.assertIn('scene = domain == "scene"', code)
        self.assertIn('button.connect("clicked", self.activate_home_scene', code)
        self.assertIn('button.scene_status_label.set_text("ACTIVATED"', code)

    def test_now_playing_artwork_uses_a_fixed_viewport_before_decode(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.artwork.set_can_shrink(True)', code)
        self.assertIn('self.artwork_viewport.set_child(self.artwork)', code)
        self.assertIn('artwork_button.set_child(self.artwork_viewport)', code)
        self.assertNotIn('elif self.artwork_button.get_child() is self.artwork_viewport', code)

    def test_landscape_now_playing_artwork_does_not_shrink_below_profile_size(self):
        size = native_method("now_playing_artwork_size")
        self.assertEqual(size(800, 480, False), 335)
        self.assertEqual(size(1024, 600, False), 360)
        self.assertEqual(size(1280, 720, False), 540)

    def test_touch_landscape_trims_surrounding_margins_instead_of_cover(self):
        code = SOURCE.read_text()
        self.assertIn('set_margin_top(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)', code)
        self.assertIn('set_margin_bottom(0 if original_landscape else 3 if not portrait and width >= 1200 else 8)', code)

    def test_small_landscape_settings_compact_bus_times_controls(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.touch_bus_heading.set_visible(portrait or width > 1280)', code)
        self.assertIn('Gtk.CheckButton(label="Bus Times")', code)

    def test_secondary_navigation_is_section_specific_and_actions_preserve_context(self):
        navigation = native_method("discovery_secondary_navigation")
        owner = SimpleNamespace(discovery_section="recent", discovery_recent_mode="added", discovery_picks=False, open_recent=Mock(), open_discover=Mock())
        self.assertEqual(navigation(owner), ((("added", "ADDED"), ("listened", "LISTENED")), "added"))
        select = native_method("select_discovery_secondary")
        select(owner,"listened"); owner.open_recent.assert_called_once_with("listened")
        owner.discovery_section="daily"; owner.discovery_picks=True
        owner.discovery_daily_sections={}; owner.discovery_scroll=Mock()
        self.assertEqual(navigation(owner)[1],"mixes")
        select(owner,"mixes"); select(owner,"recommendations")
        owner.open_discover.assert_not_called()
        for section in ("releases", "surprise"):
            owner.discovery_section=section
            self.assertEqual(navigation(owner), ((), ""))

    def test_switching_an_open_mix_to_for_you_returns_to_daily_home(self):
        owner = SimpleNamespace(discovery_section="daily", discovery_mix="mix-id", responsive_portrait=True,
            discovery_daily_tab="mixes", open_discover=Mock())
        native_method("select_discovery_secondary")(owner, "recommendations")
        self.assertEqual(owner.discovery_daily_tab, "recommendations")
        owner.open_discover.assert_called_once_with("daily")

    def test_secondary_rail_uses_browse_filters_and_bottom_back_outside_scroll(self):
        def button(label, callback, style):
            widget=LayoutWidget(label=label, callback=callback); widget.add_css_class(style); return widget
        owner=SimpleNamespace(discovery_sidebar=LayoutWidget(),discovery_body=LayoutWidget(),discovery_mix="aabb", discovery_secondary_navigation=lambda:((("mixes","MIXES"),("recommendations","RECOMMENDATIONS")),"mixes"), button=button, select_discovery_secondary=Mock(),open_discover=Mock())
        native_method("sync_discovery_sidebar",{"Gtk":LAYOUT_GTK})(owner)
        widgets=owner.discovery_sidebar.children
        self.assertEqual([w.properties.get("label") for w in widgets], ["MIXES","RECOMMENDATIONS",None,"BACK"])
        self.assertIn("browser-filter",widgets[0].classes); self.assertIn("active",widgets[0].classes)
        self.assertEqual(widgets[-2].properties["vexpand"],(True,))
        self.assertEqual(widgets[-1].properties["valign"],("end",))
        widgets[-1].properties["callback"](); owner.open_discover.assert_called_once_with("daily")
        native_method("sync_discovery_sidebar",{"Gtk":LAYOUT_GTK})(owner)
        self.assertEqual(len(owner.discovery_sidebar.children),4)

    def test_loading_lives_in_right_content_without_replacing_sidebar(self):
        owner=SimpleNamespace(discovery_request=1,discovery_active=True,roon_views=SimpleNamespace(get_visible_child_name=lambda:"discover"),discovery_signature=None,discovery_list=LayoutWidget(),sync_discovery_sidebar=Mock(),label=lambda text,style:LayoutWidget(text=text,style=style))
        owner.discovery_body = LayoutWidget()
        owner.discovery_scroll = LayoutWidget()
        owner.roon_page = LayoutWidget()
        owner.settings_data = {}
        owner.window = SimpleNamespace(has_css_class=lambda _: False)
        owner.loading_notice = lambda: LayoutWidget(text="Loading…", style="loading-notice")
        native_method("render_discover",{"json":__import__("json"), "Gtk":LAYOUT_GTK})(owner,1,{"status":"loading"})
        self.assertEqual(owner.discovery_list.children[0].properties,{"text":"Loading…","style":"loading-notice"})
        owner.sync_discovery_sidebar.assert_called_once()

    def test_opened_discover_item_back_restores_its_section_and_mix(self):
        def button(label, callback, style): return LayoutWidget(label=label, callback=callback, style=style)
        owner=SimpleNamespace(discovery_section="daily",discovery_mix="aabb",discovery_picks=False,discovery_secondary_navigation=lambda:((("mixes","MIXES"),("recommendations","RECOMMENDATIONS")),"mixes"),button=button,select_discovery_secondary=Mock(),open_discover=Mock())
        sidebar=LayoutWidget()
        native_method("sync_discovery_sidebar",{"Gtk":LAYOUT_GTK})(owner,sidebar,from_browser=True)
        sidebar.children[-1].properties["callback"]()
        owner.open_discover.assert_called_once_with("daily","aabb",False)

    def test_discover_uses_large_fixed_four_column_metrics_on_the_landscape_touchscreen(self):
        monitor=SimpleNamespace(get_geometry=lambda:SimpleNamespace(width=1280))
        monitors=SimpleNamespace(get_n_items=lambda:1,get_item=lambda _index:monitor)
        gdk=SimpleNamespace(Display=SimpleNamespace(get_default=lambda:SimpleNamespace(get_monitors=lambda:monitors)))
        columns,size=native_method("browser_grid_metrics",{"Gdk":gdk})(SimpleNamespace())
        self.assertEqual(columns,4)
        metrics=native_method("discovery_grid_metrics",{"Gdk":gdk})
        self.assertEqual(metrics(SimpleNamespace(),"recent"),(4,236))
        self.assertEqual(metrics(SimpleNamespace(),"releases"),(4,283))
        source=SOURCE.read_text(encoding="utf-8")
        self.assertIn('columns, size = self.discovery_grid_metrics(self.discovery_section)',source)
        self.assertIn('30 if portrait_grid or self.discovery_section == "releases"',source)
        self.assertIn('size = min(212, size)',source)
        self.assertNotIn('MORE RECOMMENDATIONS',source)

    def test_original_landscape_uses_compact_dense_grids(self):
        monitor = SimpleNamespace(get_geometry=lambda: SimpleNamespace(width=800))
        monitors = SimpleNamespace(get_n_items=lambda: 1, get_item=lambda _index: monitor)
        gdk = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(get_monitors=lambda: monitors)))
        owner = SimpleNamespace(responsive_portrait=False, viewport_height=480)
        self.assertEqual(native_method("browser_grid_metrics", {"Gdk": gdk})(owner), (4, 128))
        discovery = native_method("discovery_grid_metrics", {"Gdk": gdk})
        self.assertEqual(discovery(owner, "recent"), (3, 184))
        self.assertEqual(discovery(owner, "releases"), (4, 175))
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('.compact-landscape .settings-page .settings-action { min-height: 46px;', source)
        self.assertIn('utility_size = 26 if original_landscape else 30 if compact_landscape else 38', source)
        self.assertIn('.original-landscape .browser-filter { min-height: 39px;', source)
        session = (SOURCE.parents[1] / "appliance/alpine/display-session").read_text(encoding="utf-8")
        self.assertIn('/var/lib/pi-home/setup-complete', session)
        self.assertIn('"complete"[[:space:]]*:[[:space:]]*true', session)

    def test_daily_lazy_load_uses_each_horizontal_viewport(self):
        source=SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.discovery_card_scrollers[id(card)] = scroller',source)
        self.assertIn('horizontal.get_hadjustment()',source)
        self.assertIn('get_hadjustment().connect("value-changed", self.load_visible_discovery_artwork)',source)

    def test_portrait_grids_use_viewport_without_reserving_a_vertical_rail(self):
        monitor = SimpleNamespace(get_geometry=lambda: SimpleNamespace(width=720))
        monitors = SimpleNamespace(get_n_items=lambda: 1, get_item=lambda _: monitor)
        gdk = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(get_monitors=lambda: monitors)))
        owner = SimpleNamespace(responsive_portrait=True, settings_data={}, browser_state={}, window=SimpleNamespace(get_width=lambda: 720))
        self.assertEqual(native_method("browser_grid_metrics", {"Gdk": gdk})(owner)[0], 3)
        self.assertEqual(native_method("browser_grid_metrics", {"Gdk": gdk})(owner), (3, 200))
        owner.browser_state = {"alpha_scrub": True}
        self.assertEqual(native_method("browser_grid_metrics", {"Gdk": gdk})(owner), (3, 173))
        for section in ("recent", "releases"):
            columns, size = native_method("discovery_grid_metrics", {"Gdk": gdk})(owner, section)
            self.assertEqual(columns, 2)
            self.assertGreater(size, 300)
        owner.settings_data["portrait_discovery_columns"] = 3
        for section in ("recent", "daily", "releases"):
            self.assertEqual(native_method("discovery_grid_metrics", {"Gdk": gdk})(owner, section), (3, 200))
        self.assertIn('self.discovery_recent_mode = "added"', SOURCE.read_text())

    def test_new_release_detail_uses_discover_back_rail_not_browse_search(self):
        source=SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.discovery_section in {"recent", "daily", "releases"}',source)
        self.assertIn('from_browser and self.discovery_section == "releases"',source)

    def test_discover_fetch_is_not_queued_behind_the_general_status_poll(self):
        source=SOURCE.read_text(encoding="utf-8")
        poll=source[source.index('    def poll(self):'):source.index('    def capture_display',source.index('    def poll(self):'))]
        self.assertNotIn('/api/discovery?',poll)
        self.assertIn('threading.Thread(target=self._fetch_discovery',source)
        self.assertIn('GLib.timeout_add(600 if data and data.get("status") == "loading" else 1200',source)

    def test_admin_can_request_a_real_native_discover_view(self):
        source=SOURCE.read_text(encoding="utf-8")
        self.assertIn('view_request = device.get("display_view_request") or {}', source)
        self.assertIn('GLib.idle_add(self.apply_display_view_request, dict(view_request))', source)
        owner=SimpleNamespace(show_roon_now=Mock(),set_mode=Mock(),open_discover=Mock())
        self.assertFalse(native_method("apply_display_view_request")(owner,{"view":"daily"}))
        owner.open_discover.assert_called_once_with("daily")
        self.assertFalse(native_method("apply_display_view_request")(owner,{"view":"now"}))
        owner.show_roon_now.assert_called_once_with()
        owner.set_mode.assert_called_once_with("roon")

    def test_preview_waits_until_browser_render_finishes(self):
        posted=Mock()
        thread=SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:posted(kwargs['args'][1])))
        owner=SimpleNamespace(preview_navigation_id='ticket',roon_views=SimpleNamespace(get_visible_child_name=lambda:'browse'),browser_loading=True,browser_rendering=False,browser_state={'title':'Album','items':[{'title':'Track','item_key':'track'}]})
        method=native_method('finish_preview_navigation',{'time':SimpleNamespace(monotonic=lambda:1),'threading':thread,'post_json':Mock(),'BUS':'http://localhost'})
        self.assertTrue(method(owner,{'id':'ticket','view':'browse'},10))
        posted.assert_not_called()
        owner.browser_loading=False
        self.assertFalse(method(owner,{'id':'ticket','view':'browse'},10))
        self.assertEqual(posted.call_args.args[0]['title'],'Album')
        self.assertEqual(posted.call_args.args[0]['items'][0]['item_key'],'track')

    def test_reboot_confirmation_uses_a_full_overlay_with_a_centred_card(self):
        source=SOURCE.read_text(encoding="utf-8")
        confirm=source[source.index('    def confirm_reboot'):source.index('    def _request_update',source.index('    def confirm_reboot'))]
        self.assertIn('shade = Gtk.Overlay()',confirm)
        self.assertIn('card.set_halign(Gtk.Align.CENTER)',confirm)
        self.assertIn('card.set_valign(Gtk.Align.CENTER)',confirm)
        self.assertIn('shade.add_overlay(card)',confirm)

    def test_mix_tracks_use_playlist_rows_and_register_lazy_thumbnail_without_playback(self):
        owner=SimpleNamespace(label=lambda text,style,*args:LayoutWidget(text=text,style=style),set_browser_placeholder=Mock(),open_discovery_item=Mock(),discovery_pictures={},discovery_cards=[],queue_thumbnail_cache={})
        row=native_method("discovery_track_row",{"Gtk":LAYOUT_GTK,"Pango":SimpleNamespace(EllipsizeMode=SimpleNamespace(END="end"))})(owner,{"title":"Song","artist":"Artist","key":"track-key","artwork_key":"art"})
        self.assertIn("browser-row",row.classes)
        art=row.get_child().children[0]
        self.assertEqual(art.properties["size_request"],(72,72))
        self.assertEqual(owner.discovery_cards,[(row,"discover:art")])
        owner.open_discovery_item.assert_not_called()
        row.properties["clicked"](); owner.open_discovery_item.assert_called_once_with(row,"track-key")

    def test_discover_artwork_only_queues_visible_and_nearby_cards(self):
        jobs = Mock()
        def card(y):
            return SimpleNamespace(compute_bounds=lambda _list: (True, SimpleNamespace(get_y=lambda:y, get_height=lambda:100)))
        owner = SimpleNamespace(discovery_active=True, roon_views=SimpleNamespace(get_visible_child_name=lambda:"discover"), discovery_scroll=SimpleNamespace(get_vadjustment=lambda:SimpleNamespace(get_value=lambda:0, get_page_size=lambda:500)), discovery_list=object(), discovery_cards=[(card(0),"visible"),(card(600),"nearby"),(card(1200),"offscreen")], queue_thumbnail_cache={}, queue_thumbnail_pending=set(), queue_thumbnail_jobs=jobs)
        native_method("load_visible_discovery_artwork")(owner)
        self.assertEqual(owner.queue_thumbnail_pending, {"visible", "nearby"})
        self.assertEqual(jobs.put.call_count, 2)
        native_method("load_visible_discovery_artwork")(owner)
        self.assertEqual(jobs.put.call_count, 2)

    def test_recent_mode_switch_stays_on_recent_and_uses_added_endpoint(self):
        owner = SimpleNamespace(open_discover=Mock())
        native_method("open_recent")(owner,"added")
        owner.open_discover.assert_called_once_with("recent", recent_mode="added")
        owner.open_discover.reset_mock()
        native_method("open_recent")(owner,"listened")
        owner.open_discover.assert_called_once_with("recent", recent_mode="listened")
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('section = "added"',code)
        self.assertIn('self.discovery_recent_mode = recent_mode or "added"', code)
        self.assertIn('client=touch',code)
        self.assertIn('("recommendations", "FOR YOU")',code)

    def test_mix_duotone_preserves_alpha_and_maps_black_white_and_coloured_pixels(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "mix_duotone_matrix")
        namespace = {}; exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
        matrix = namespace["mix_duotone_matrix"]()
        transform = lambda pixel: [sum(matrix[row * 4 + column] * pixel[row] for row in range(4)) for column in range(4)]
        self.assertEqual(transform([0, 0, 0, 1]), [0, 0, 0, 1])
        for actual, expected in zip(transform([1, 1, 1, 1]), [150/255, 144/255, 237/255, 1]): self.assertAlmostEqual(actual, expected)
        red = transform([1, 0, 0, .5]); self.assertAlmostEqual(red[3], .5); self.assertGreater(red[2], red[0]); self.assertGreater(red[0], red[1])

    def test_discovery_drops_stale_results_without_touching_gtk(self):
        owner = SimpleNamespace(discovery_request=2, discovery_active=True)
        self.assertFalse(native_method("render_discover")(owner, 1, {"status":"ready"}))
        self.assertFalse(native_method("apply_discovery_item")(owner, 1, {"items":[]}))

    def test_discovery_keeps_short_tabs_and_moves_browse_out_of_now_playing(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('("releases", "NEW RELEASES")', code)
        self.assertIn('self.browser_tab.set_visible(False)', code)
        self.assertIn('self.roon_views.add_named(self.discovery_body, "discover")', code)
        self.assertIn('("daily", "DAILY")', code)
        self.assertIn('background: transparent; background-image: none; box-shadow: none;', code)

    def test_discovery_thumbnail_has_its_own_proxy_not_official_image_keys(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('/api/discovery/image?key=', code)
        self.assertIn('key.startswith("discover:")', code)
        self.assertIn('self.discovery_pictures.get(key, [])', code)

    def test_discovery_menu_stays_exclusive_across_repeated_config_refreshes(self):
        sync = native_method('sync_music_navigation')
        for active, view in ((True,'discover'),(True,'browse'),(True,'search'),(False,'now'),(False,'queue')):
            music, discover, browse = Mock(), Mock(), Mock()
            owner = SimpleNamespace(discovery_active=active,roon_views=SimpleNamespace(get_visible_child_name=lambda:view),roon_subnav=music,discover_subnav=discover,browser_tab=browse)
            owner.discover_toolbar = Mock(); owner.music_header_overlay = Mock(); owner.portrait_music_tabs = Mock()
            for _ in range(3): sync(owner)
            music.set_visible.assert_called_with(not active)
            discover.set_visible.assert_called_with(active)
            browse.set_visible.assert_called_with(False)
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('self.sync_music_navigation(); self.queue_tab', code)
        self.assertNotIn('self.roon_subnav.set_visible(True)', code)

    def test_discovery_art_and_titles_have_fixed_space_and_rounded_snapshot(self):
        code=SOURCE.read_text(encoding='utf-8')
        self.assertIn('snapshot.push_rounded_clip(clip)',code)
        self.assertIn('MixPicture(duotone=item.get("kind") == "mix" or item.get("_context_seed", False))',code)
        self.assertIn('title_label.set_justify(Gtk.Justification.CENTER)',code)
        self.assertNotIn('title_label.set_size_request(-1, 48)',code)
        self.assertIn('back.set_halign(Gtk.Align.START)',code)
        self.assertIn('group(None, data.get("items", []), "mixes")',code)

    def test_daily_context_uses_a_heading_and_seed_as_a_fixed_grid_card(self):
        code=SOURCE.read_text(encoding='utf-8')
        self.assertIn('"BECAUSE YOU LISTENED TO…"',code)
        self.assertNotIn('dict(seed, _context_seed=True)',code)
        self.assertIn('item.get("_context_seed", False)',code)
        self.assertIn('card.add_css_class("recommendation-seed-card")',code)
        self.assertNotIn('recommendation-cover-label',code)
        self.assertIn('shell.set_min_content_width(size)',code)
        self.assertIn('shell.set_max_content_width(size)',code)
        self.assertIn('.touch-landscape .roon-page .browser-view { padding-right: 0; }',code)
        self.assertIn('self.browser_scrubber.set_margin_end(18)',code)

    def test_now_playing_keeps_fixed_artwork_while_replacement_arrives(self):
        code=SOURCE.read_text(encoding='utf-8')
        build=code[code.index('    def build_roon'):code.index('    def build_home')]
        apply=code[code.index('    def apply(self,'):code.index('    def apply_artwork',code.index('    def apply(self,'))]
        missing=code[code.index('    def note_missing_artwork'):code.index('    def open_settings')]
        self.assertIn('self.set_browser_placeholder(self.artwork)',build)
        self.assertNotIn('self.set_browser_placeholder(self.artwork)',apply)
        self.assertIn('self.set_browser_placeholder(self.artwork)',missing)
        self.assertIn('self.artwork.set_paintable(Gdk.Texture.new_from_bytes',code)

    def test_mix_action_is_explicit_single_request_and_stale_result_does_not_update_ui(self):
        controls = Mock(); controls.get_first_child.return_value = None
        message = Mock(); posts = Mock(return_value={"accepted":True,"count":22})
        callbacks = []
        owner = SimpleNamespace(discovery_request=4,discovery_mix="aabb",discovery_active=True,label=Mock(return_value=message),discovery_list=Mock())
        owner.loading_notice = Mock(return_value=message)
        class Thread:
            def __init__(self,target,daemon): self.target=target
            def start(self): self.target()
        method = native_method("request_mix_action", {"threading":SimpleNamespace(Thread=Thread),"GLib":SimpleNamespace(idle_add=lambda fn,result:callbacks.append((fn,result))),"uuid":uuid,"post_json":posts,"ROON":"http://fixture"})
        method(owner,"queue",controls)
        self.assertEqual(posts.call_count,1)
        self.assertEqual(posts.call_args.args[1]["action"],"queue")
        self.assertEqual(posts.call_args.args[1]["id"],"aabb")
        self.assertTrue(owner.discovery_opening)
        owner.discovery_request=5
        fn,result=callbacks.pop(); fn(result)
        message.set_text.assert_not_called()
        code=SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('Gtk.Expander(label="VIEW TRACKS")',code)
        self.assertIn('"PLAY THIS MIX"',code)
        self.assertIn('self.labelled_icon_button("play"', code)

    def test_grouped_results_have_separate_scrollers_not_nested_in_browser_viewport(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('content.append(self.browser_search_columns)', code)
        self.assertIn('self.browser_search_columns.append(scroll)', code)
        self.assertNotIn('self.browser_list.append(scroll)', code)
        self.assertIn('columns[1 if item.get("title") in {"ALBUMS", "TRACKS"} else 0]', code)

    def test_grouped_artwork_does_not_use_hidden_single_scroller_window(self):
        jobs = Mock()
        owner = SimpleNamespace(browser_scroll=SimpleNamespace(get_vadjustment=lambda: None), browser_state={"search_routes":{"key":{}}}, browser_artwork_keys=['a','b'], queue_thumbnail_cache={}, queue_thumbnail_pending=set(), queue_thumbnail_jobs=SimpleNamespace(put=jobs))
        native_method("load_visible_browser_artwork")(owner)
        self.assertEqual(owner.queue_thumbnail_pending, {'a','b'})
        self.assertEqual(jobs.call_count, 2)

    def test_pending_search_skips_old_page_response(self):
        owner = SimpleNamespace(browser_pending_request=("search", {"query": "Oasis"}), browser_loading=True, request_browser=Mock(), render_browser=Mock(), set_roon_view=Mock())
        native_method("apply_browser_response")(owner, {"title": "Genres", "items": []})
        owner.render_browser.assert_not_called()
        owner.request_browser.assert_called_once_with("search", query="Oasis")
        self.assertFalse(owner.browser_loading)

    def test_native_placeholder_uses_local_artist_and_album_assets(self):
        method = native_method("set_browser_placeholder", {"Path": Path, "__file__": str(SOURCE)})
        picture = SimpleNamespace(set_filename=Mock())
        method(SimpleNamespace(), picture, artist=True)
        self.assertEqual(Path(picture.set_filename.call_args.args[0]), SOURCE.parent / "icons/missing-artist.svg")
        method(SimpleNamespace(), picture)
        self.assertEqual(Path(picture.set_filename.call_args.args[0]), SOURCE.parent / "icons/missing-album.svg")
        method(SimpleNamespace(artwork=picture), picture)
        self.assertEqual(Path(picture.set_filename.call_args.args[0]), SOURCE.parent / "icons/missing-album-large.svg")
        self.assertIn('width="1200" height="1200"', (SOURCE.parent / "icons/missing-album-large.svg").read_text())
        for name in ("missing-artist.svg", "missing-album.svg"):
            self.assertTrue((SOURCE.parent / "icons" / name).is_file())

    def test_native_missing_thumbnail_retains_placeholder(self):
        picture = SimpleNamespace(set_paintable=Mock())
        instance = SimpleNamespace(queue_thumbnail_pending={"missing"}, browser_pictures={"missing": [picture]})
        timeout = Mock()
        method = native_method("apply_queue_thumbnail", {"GLib": SimpleNamespace(timeout_add=timeout)})
        instance.retry_visible_thumbnail = Mock()
        self.assertFalse(method(instance, "missing", None))
        picture.set_paintable.assert_not_called()
        self.assertEqual(instance.thumbnail_failures["missing"], 1)
        timeout.assert_called_once()

    def test_back_swipe_requires_rightward_horizontal_motion_and_back_destination(self):
        swipe = native_method("browser_swipe_back")
        calls = []
        owner = SimpleNamespace(browser_state={"can_back":True}, request_browser=calls.append)
        for x, y in ((150,0),(-150,0),(60,0),(150,120),(0,150)): swipe(owner,None,x,y)
        self.assertEqual(calls, ["back"])
        owner.browser_state = {"can_back":False}; swipe(owner,None,800,0)
        self.assertEqual(calls, ["back"])

    def test_artist_panel_keeps_portrait_and_name_without_biography(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "render_artist_profile")
        code = ast.unparse(method)
        self.assertIn('Gtk.Picture()', code)
        self.assertIn("'artist-name'", code)
        self.assertNotIn('artist_bio', code)
        self.assertNotIn('get_json', code)
        self.assertIn('self.render_artist_profile(data.get("artist_profile"), artist_play)', SOURCE.read_text(encoding="utf-8"))
        web = (SOURCE.parents[1] / "roon-controller" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('renderArtistProfile(data.artist_profile, artistPlay)', web)
        self.assertNotIn('Artist background is unavailable.', web)

    def test_artist_rows_have_fixed_artwork_and_profile_uses_aligned_wide_hero(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('art_slot.set_max_content_height(72)', code)
        self.assertIn('art_slot.set_max_content_width(72)', code)
        self.assertIn('"ARTIST ALBUMS", "browser-section"', code)
        self.assertIn('.artist-albums-heading { font-size: 16px;', code)
        self.assertIn('thumb_size = 84 if original_artist_albums', code)
        self.assertIn('.original-landscape .artist-album-title { font-size: 20px;', code)
        self.assertIn('hero_height = round(hero_width * 9 / 16)', code)
        self.assertIn('overlay_play.set_halign(Gtk.Align.START); overlay_info.append(overlay_play)', code)
        self.assertIn('details.set_size_request(hero_width - 32, -1)', code)
        self.assertIn('summary_slot.artist_summary_lines = 2', code)
        self.assertIn('background: linear-gradient(to bottom, transparent 0%', code)

    def test_original_discovery_sidebar_aligns_with_browse_sidebar(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(code.count('add_css_class("discovery-sidebar")'), 2)
        self.assertIn('.original-landscape .browser-sidebar.discovery-sidebar { margin-top: -12px; }', code)
        self.assertIn('.original-landscape .roon-subnav button { min-height: 34px; padding: 3px 8px 0; font-size: 14px; letter-spacing: .2px;', code)
        self.assertIn('.original-landscape .browser-filter { min-height: 39px; padding: 3px 6px; font-size: 14px; letter-spacing: .2px;', code)

    def test_mint_defaults_do_not_contain_roon_purple(self):
        code = SOURCE.read_text(encoding="utf-8")
        allowed = ("theme-roon", "library-pulse-roon", 'accent="#9868F9"',
                   'replace("#9868F9", accent)', 'accent = "#9868F9"',
                   "alpha(#9868F9")
        leaked = [line.strip() for line in code.splitlines()
                  if any(token in line.lower() for token in ("#9868f9", "#a77cff", "152,104,249"))
                  and not any(marker in line for marker in allowed)]
        self.assertEqual(leaked, [])

    def test_scroll_activity_hook_is_safe_in_visual_review_harness(self):
        owner = SimpleNamespace()
        native_method("note_browse_scroll", {"time": SimpleNamespace(monotonic=lambda: 1)})(owner)
        self.assertFalse(hasattr(owner, "browse_last_interaction"))

    def test_active_playback_is_excluded_from_touchscreen_idle_sleep(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('inactivity_due = bool(not playing and inactivity_seconds', code)
        self.assertIn('self.playback_was_active = playing', code)
        self.assertIn('if playing and target != "/sleep.html":', code)

    def test_capture_renders_actual_gtk_tree_and_posts_image(self):
        image = b'\x89PNG\r\n\x1a\nimage'
        texture = SimpleNamespace(save_to_png_bytes=lambda:SimpleNamespace(get_data=lambda:image))
        node = object()
        snapshot = SimpleNamespace(to_node=lambda:node)
        paintable = SimpleNamespace(snapshot=Mock())
        gtk = SimpleNamespace(WidgetPaintable=SimpleNamespace(new=Mock(return_value=paintable)),Snapshot=Mock(return_value=snapshot))
        page = object()
        renderer = SimpleNamespace(unrealize=Mock(),is_realized=lambda:False,realize_for_display=lambda _:True,render_texture=Mock(return_value=texture))
        gsk = SimpleNamespace(CairoRenderer=SimpleNamespace(new=lambda:renderer))
        window = SimpleNamespace(get_child=lambda:page,get_width=lambda:800,get_height=lambda:480,get_display=lambda:object(),get_renderer=lambda:renderer,snapshot_child=Mock(),queue_draw=Mock())
        pixels = SimpleNamespace(get_pixels=lambda:bytes([255,255,255,255]),get_n_channels=lambda:4,get_rowstride=lambda:4,get_width=lambda:1,get_height=lambda:1)
        gdk = SimpleNamespace(pixbuf_get_from_texture=lambda _:pixels)
        glib = SimpleNamespace(Error=RuntimeError)
        posted = Mock()
        cairo = SimpleNamespace(Error=RuntimeError, FORMAT_ARGB32=0, ImageSurface=Mock(side_effect=RuntimeError('unavailable')))
        method = native_method('capture_display', {'Gtk':gtk,'Gsk':gsk,'Gdk':gdk,'GLib':glib,'cairo':cairo,'io':io,'base64':base64,'BUS':'http://127.0.0.1:8765','post_json':posted})
        result = method(SimpleNamespace(window=window), 'ticket')
        window.snapshot_child.assert_called_once_with(page, snapshot)
        gtk.WidgetPaintable.new.assert_not_called()
        self.assertEqual(base64.b64decode(posted.call_args.args[1]['image']), image)
        self.assertEqual(posted.call_args.args[1]['id'], 'ticket')
        self.assertFalse(result)
        renderer.unrealize.assert_not_called()
        pixels.get_pixels = lambda:bytes([0,0,0,255])
        method(SimpleNamespace(window=window), 'black-ticket', 4)
        self.assertNotIn('image', posted.call_args.args[1])
        self.assertIn('Display capture failed:', posted.call_args.args[1]['error'])
        pixels.get_pixels = lambda:bytes([255,255,255,0])
        method(SimpleNamespace(window=window), 'transparent-ticket', 4)
        self.assertNotIn('image', posted.call_args.args[1])

    def test_failed_widget_capture_returns_friendly_error(self):
        gtk = SimpleNamespace(WidgetPaintable=SimpleNamespace(new=Mock(side_effect=RuntimeError())))
        posted = Mock()
        glib = SimpleNamespace(Error=RuntimeError)
        cairo = SimpleNamespace(Error=RuntimeError)
        method = native_method('capture_display', {'Gtk':gtk,'GLib':glib,'cairo':cairo,'base64':base64,'BUS':'http://127.0.0.1:8765','post_json':posted})
        method(SimpleNamespace(window=SimpleNamespace(get_child=lambda:object(),get_width=lambda:800,get_height=lambda:480,queue_draw=Mock())), 'ticket', 4)
        self.assertIn('Display capture failed:', posted.call_args.args[1]['error'])
        self.assertNotIn('image', posted.call_args.args[1])

    def test_capture_request_is_scheduled_on_the_gtk_main_loop(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('GLib.timeout_add(350, self.capture_display, capture_id, 0)', code)

    def test_theme_updates_the_selector_without_triggering_a_save(self):
        calls = []
        owner = SimpleNamespace(settings_data={},window=SimpleNamespace(add_css_class=calls.append,remove_css_class=calls.append),browser_scrubber=SimpleNamespace(queue_draw=lambda:calls.append('draw')))
        owner.touch_theme_buttons = {value: SimpleNamespace(add_css_class=lambda cls, value=value:calls.append((value,cls)),remove_css_class=lambda cls:None) for value in ('fresh-mint','roon')}
        owner.discovery_pictures = {'discover:art': [SimpleNamespace(queue_draw=lambda:calls.append('portrait'))]}
        native_method('apply_theme')(owner, 'roon')
        self.assertEqual(owner.settings_data['display_theme'], 'roon')
        self.assertEqual(calls, ['theme-roon',('roon','active'),'draw','portrait'])
        self.assertFalse(owner.theme_updating)
        native_method('change_theme')(SimpleNamespace(theme_updating=True), 'roon')

    def test_native_search_passes_the_selected_source(self):
        for selected, expected in ((0,'library'),(1,'tidal')):
            calls = []
            owner = SimpleNamespace(browser_search_entry=SimpleNamespace(get_text=lambda:' Radiohead '),browser_search_source=SimpleNamespace(get_selected=lambda:selected),set_roon_view=lambda view:calls.append(view),request_browser=lambda action,**data:calls.append((action,data)))
            native_method('submit_browser_search')(owner)
            self.assertEqual(calls, ['browse',('search',{'query':'Radiohead','source':'all'})])

    def test_search_keyboard_keeps_browse_secondary_navigation_visible(self):
        code = SOURCE.read_text(encoding='utf-8')
        search = code.split('search_panel = Gtk.Box', 1)[1].split('self.roon_views.add_named(search_panel', 1)[0]
        for section in ('albums', 'artists', 'genres', 'playlists'):
            self.assertIn(section, search)
        self.assertIn('search_active.add_css_class("active")', search)

    def test_touch_popovers_hide_the_cursor_before_opening(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertGreaterEqual(code.count('self.hide_widget_cursor(popover); popover.popup(); self.hide_native_cursor(popover)'), 2)
        self.assertGreaterEqual(code.count('GLib.idle_add(self.hide_native_cursor, widget)'), 2)
        self.assertIn('getattr(self, "browser_sort_popover", None)', code)

    def test_failed_boot_config_fetch_keeps_last_good_settings_and_retries(self):
        code = SOURCE.read_text(encoding='utf-8')
        poll = code.split('def poll(self):', 1)[1].split('def capture_display', 1)[0]
        self.assertIn('if isinstance(fetched_config, dict) and fetched_config:', poll)
        self.assertIn('self.last_config_fetch = 0', poll)
        apply = code.split('def apply(self,', 1)[1].split('def apply_artwork', 1)[0]
        self.assertIn('effective_config = config if isinstance(config, dict) and config else self.settings_data', apply)

    def test_surprise_selection_and_bottom_back_are_present_in_both_interfaces(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('and not data.get("surprise_preview")', code)
        self.assertIn('active_section = "surprise" if data.get("surprise_preview")',code)
        self.assertIn('spacer.set_vexpand(True); self.browser_sidebar_spacer = spacer; sidebar.append(spacer); sidebar.append(self.browser_sort); sidebar.append(self.browser_back)',code)
        self.assertIn('self.button("BACK"', code)
        self.assertIn('self.browser_sort = self.button("Sort: Title, A to Z", self.show_browser_sort', code)
        self.assertIn('self.browser_sort.set_sensitive(False)', code)
        self.assertNotIn('Gtk.DropDown.new_from_strings(["Sort: Title A–Z"', code)
        self.assertNotIn('popover.sort-menu > contents { margin-top: 8px; background: #000', code)
        self.assertNotIn('box-shadow: inset 3px 0 #9868F9', code)
        self.assertIn('popover.sort-menu .track-menu-action.active:focus { background: #9868F9; color: #111; box-shadow: none; }', code)
        web = (SOURCE.parents[1] / 'roon-controller/static/app.js').read_text(encoding='utf-8')
        self.assertIn("const activeSection = data.surprise_preview ? 'surprise'", web)
        self.assertIn('!data.can_back || Boolean(data.surprise_preview)',web)

    def test_six_home_controls_fill_landscape_with_two_tall_tiles_and_a_two_by_two_group(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('if not portrait and len(entities) == 6:', code)
        self.assertIn('self.home_grid.attach(box, index, 0, 1, 2)', code)
        self.assertIn('self.home_grid.attach(box, 2 + (index - 2) % 2, (index - 2) // 2, 1, 1)', code)

    def test_missing_configured_zone_has_an_explicit_quiet_state(self):
        code = SOURCE.read_text(encoding='utf-8')
        self.assertIn('if zone.get("available") is False:', code)
        self.assertIn('self.artist.set_text("Selected zone is offline")', code)

    def test_grid_minimums_fit_physical_monitor_without_using_expanded_content(self):
        metrics = native_method("browser_grid_metrics", {"Gdk": SimpleNamespace(Display=SimpleNamespace(get_default=lambda: display))})
        for width in (480, 720, 800, 1024, 1280):
            monitor = SimpleNamespace(get_geometry=lambda:SimpleNamespace(width=width))
            display = SimpleNamespace(get_monitors=lambda:SimpleNamespace(get_n_items=lambda:1,get_item=lambda _:monitor))
            for genres in (True, False):
                columns, size = metrics(SimpleNamespace(), genres)
                self.assertLessEqual(columns * (size + 12) + (columns - 1) * 16, width - 266)
                self.assertLessEqual(size, 212)

    def test_playback_handoff_requires_successful_navigation_response(self):
        for data, expected in (({"navigate":"now"}, ["render", "now"]), ({}, ["render"]), ({"navigate":"now","error":"failed"}, ["render"])):
            calls = []
            owner = SimpleNamespace(render_browser=lambda _:calls.append("render"),set_roon_view=calls.append)
            native_method("apply_browser_response")(owner, data)
            self.assertEqual(calls, expected)

    def test_keyboard_edits_at_cursor_and_replaces_selection(self):
        entry = Entry("ac", 1)
        owner = SimpleNamespace(browser_search_entry=entry)
        key = native_method("browser_keyboard_key")
        key(owner, "B"); self.assertEqual(entry.text, "abc")
        key(owner, "BACKSPACE"); self.assertEqual(entry.text, "ac")
        entry.selection = (True, 0, 2)
        key(owner, "Z"); self.assertEqual(entry.text, "z")
        key(owner, "CLEAR"); self.assertEqual(entry.text, "")

    def test_dot_and_letter_ink_have_identical_centres_at_every_letter(self):
        class Canvas:
            def __getattr__(self, name): return lambda *_: None
            def arc(self, _x, y, *_): self.dot_y = y
            def move_to(self, _x, y): self.text_baseline = y
            def text_extents(self, _text): return (0, -13, 12, 13, 12, 0)
        draw = native_method("draw_browser_scrubber")
        for height in (240, 480, 720):
            for value in range(26):
                owner = SimpleNamespace(browser_scrub_scale=SimpleNamespace(get_value=lambda:value))
                canvas = Canvas(); draw(owner, None, canvas, 74, height)
                self.assertAlmostEqual(canvas.dot_y, canvas.text_baseline - 13 + 6.5)
                self.assertGreaterEqual(canvas.dot_y, 16); self.assertLessEqual(canvas.dot_y, height - 16)

    def test_scrubber_touch_mapping_matches_drawing_at_every_letter(self):
        at = native_method("browser_scrub_at")
        for height in (240, 480, 720):
            values = []
            owner = SimpleNamespace(browser_scrubber=SimpleNamespace(get_allocated_height=lambda:height), browser_scrub_scale=SimpleNamespace(set_value=values.append))
            for value in range(26): at(owner, 16 + (height - 32) * value / 25)
            self.assertEqual(values, list(range(26)))

    def test_latest_jump_is_retained_while_results_are_loading(self):
        owner = SimpleNamespace(browser_loading=True)
        request = native_method("request_browser")
        request(owner, "jump", letter="D"); request(owner, "jump", letter="F")
        self.assertEqual(owner.browser_pending_request, ("jump", {"letter":"F"}))

    def test_result_sync_cannot_move_scrubber_during_drag(self):
        owner = SimpleNamespace(browser_state={"alpha_scrub":True}, browser_scrub_dragging=True)
        native_method("sync_browser_scrubber")(owner)

    def test_section_switch_remembers_the_old_scroll_and_restores_the_new_one(self):
        thread = SimpleNamespace(Thread=lambda **_: SimpleNamespace(start=lambda:None))
        owner = SimpleNamespace(browser_loading=False, browser_state={"section":"artists"}, browser_section_scrolls={"albums":72}, browser_scroll=SimpleNamespace(get_vadjustment=lambda:SimpleNamespace(get_value=lambda:350)), browser_message=SimpleNamespace(set_visible=lambda _:None), _request_browser=lambda *_:None)
        native_method("request_browser", {"threading":thread})(owner, "section", section="albums")
        self.assertEqual(owner.browser_section_scrolls["artists"], 350)
        self.assertEqual(owner.browser_scroll_restore, 72)

    def test_old_scroll_restore_finishes_before_the_next_queued_request(self):
        calls = []
        owner = SimpleNamespace(browser_scroll_restore=350, restore_browser_scroll=lambda:calls.append("restore"), sync_browser_scrubber=lambda:calls.append("sync"), maybe_load_more_browser=lambda:None, browser_pending_request=("section", {"section":"albums"}), request_browser=lambda *_args, **_kwargs:calls.append("request"))
        native_method("finish_browser_render", {"GLib":SimpleNamespace(timeout_add=lambda *_:None)})(owner)
        self.assertEqual(calls, ["restore", "sync", "request"])
        self.assertFalse(owner.browser_loading); self.assertFalse(owner.browser_rendering)


if __name__ == "__main__":
    unittest.main()
