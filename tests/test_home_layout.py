import json
import tempfile
import unittest
from pathlib import Path

from pi_bus_time_display.home_layout import load_layout, save_layout, validate_layout, with_layout


class HomeLayoutTests(unittest.TestCase):
    def test_valid_layout_round_trips(self):
        folder = Path(tempfile.mkdtemp()); path = folder / "home-layout.json"
        saved = save_layout(path, {"tiles": {"light.study_uplight": {"size": "full", "label": "Uplight", "icon": "icon-bulb-hd5.png", "image": "wood.png", "color": "#fb923c"}}})
        self.assertEqual(load_layout(path), saved)

    def test_rejects_bad_tiles(self):
        for tile in ({"size": "huge"}, {"label": "x" * 41}, {"icon": "../x.png"}, {"image": "x.jpg"}, {"color": "orange"}, {"other": 1}):
            with self.assertRaises(ValueError): validate_layout({"tiles": {"light.a": tile}})
        with self.assertRaises(ValueError): validate_layout({"tiles": {"Not An Entity": {"size": "half"}}})
        with self.assertRaises(ValueError): validate_layout({"tiles": {}, "extra": 1})

    def test_tall_tiles(self):
        self.assertEqual(validate_layout({"tiles": {"light.a": {"rows": 2}}}), {"tiles": {"light.a": {"rows": 2}}})
        self.assertEqual(validate_layout({"tiles": {"light.a": {"rows": 1, "size": "half"}}}), {"tiles": {"light.a": {"size": "half"}}})
        for rows in (0, 4, "2", True):
            with self.assertRaises(ValueError): validate_layout({"tiles": {"light.a": {"rows": rows}}})

    def test_tile_positions(self):
        self.assertEqual(validate_layout({"tiles": {"light.a": {"col": 0, "row": 1}}}), {"tiles": {"light.a": {"col": 0, "row": 1}}})
        for tile in ({"col": 4}, {"row": 8}, {"col": -1}, {"col": "1"}, {"row": True}):
            with self.assertRaises(ValueError): validate_layout({"tiles": {"light.a": tile}})

    def test_icons_are_tinted_in_the_tile_colour(self):
        from io import BytesIO
        from PIL import Image
        from pi_bus_time_display.home_layout import tint_icon
        source = Image.new("RGBA", (4, 4), (255, 255, 255, 0)); source.putpixel((1, 1), (255, 255, 255, 200)); buffer = BytesIO(); source.save(buffer, "PNG")
        out = Image.open(BytesIO(tint_icon(buffer.getvalue(), "#fb923c"))).convert("RGBA")
        self.assertEqual(out.getpixel((1, 1)), (251, 146, 60, 200)); self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(tint_icon(b"not a png", "#fb923c"), b"not a png"); self.assertEqual(tint_icon(buffer.getvalue(), "orange"), buffer.getvalue())

    def test_small_icons_are_enlarged_when_tinted(self):
        from io import BytesIO
        from PIL import Image
        from pi_bus_time_display.home_layout import tint_icon
        source = Image.new("RGBA", (240, 240), (255, 255, 255, 0))
        for x in range(100, 140):
            for y in range(100, 140): source.putpixel((x, y), (255, 255, 255, 255))
        buffer = BytesIO(); source.save(buffer, "PNG")
        out = Image.open(BytesIO(tint_icon(buffer.getvalue(), "#60a5fa"))).convert("RGBA")
        box = out.getchannel("A").getbbox()
        self.assertGreater(box[2] - box[0], 190); self.assertEqual(out.getpixel((120, 120))[:3], (96, 165, 250))

    def test_missing_or_broken_file_means_no_custom_tiles(self):
        folder = Path(tempfile.mkdtemp())
        self.assertEqual(load_layout(folder / "none.json"), {"tiles": {}})
        (folder / "bad.json").write_text("{nope"); self.assertEqual(load_layout(folder / "bad.json"), {"tiles": {}})

    def test_layout_is_attached_to_matching_devices_only(self):
        home = {"status": "ok", "entities": [{"entity_id": "light.a"}, {"entity_id": "fan.b"}]}
        result = with_layout(home, {"tiles": {"light.a": {"size": "half"}}})
        self.assertEqual(result["entities"][0]["tile"], {"size": "half"}); self.assertNotIn("tile", result["entities"][1])
        self.assertIs(with_layout("offline", {}), "offline")


class HomeDashboardLayoutTests(unittest.TestCase):
    def test_columns_and_linked_devices_are_validated(self):
        from pi_bus_time_display.home_layout import validate_layout, with_layout
        saved = validate_layout({"columns": 3, "tiles": {"switch.pihole_a": {"also": ["switch.pihole_b", "switch.pihole_b"]}}})
        self.assertEqual(saved["columns"], 3)
        self.assertEqual(saved["tiles"]["switch.pihole_a"]["also"], ["switch.pihole_b"])
        self.assertEqual(with_layout({"entities": []}, saved)["columns"], 3)
        self.assertNotIn("columns", with_layout({"entities": []}, {"tiles": {}}))
        for bad in ({"columns": 4}, {"columns": True}, {"tiles": {"switch.a": {"also": ["switch.a"]}}},
                    {"tiles": {"switch.a": {"also": ["not an entity"]}}}, {"tiles": {"switch.a": {"also": ["switch.b"] * 1 + ["switch.c", "switch.d", "switch.e", "switch.f"]}}}):
            with self.assertRaises(ValueError): validate_layout(bad)

    def test_player_and_bus_are_tiles_on_the_grid(self):
        layout = validate_layout({"columns": 3, "tiles": {"roondeck.player": {"col": 2, "row": 0, "rows": 1, "size": "half"}, "roondeck.bus": {"col": 0, "row": 2, "rows": 1}}})
        self.assertEqual(layout["tiles"]["roondeck.player"]["rows"], 1)    # a short player is remembered; for other tiles one row is the default
        self.assertNotIn("rows", layout["tiles"]["roondeck.bus"])
        home = with_layout({"entities": [{"entity_id": "light.a"}]}, layout)
        self.assertEqual(home["cards"]["roondeck.player"]["col"], 2)
        self.assertEqual(home["cards"]["roondeck.bus"]["row"], 2)

    def test_half_width_tiles_and_live_tiles_are_kept(self):
        layout = validate_layout({"columns": 3, "tiles": {"switch.lamp": {"half": True, "sub": 1, "col": 1, "row": 0}, "roondeck.cpu": {"show": True, "col": 2, "row": 2}, "roondeck.network": {"show": True}}})
        self.assertEqual(layout["tiles"]["switch.lamp"], {"half": True, "sub": 1, "col": 1, "row": 0})
        home = with_layout({"entities": []}, layout)
        self.assertTrue(home["cards"]["roondeck.cpu"]["show"]); self.assertTrue(home["cards"]["roondeck.network"]["show"])
        for bad in ({"half": 1}, {"show": "yes"}):
            self.assertNotIn(next(iter(bad)), validate_layout({"tiles": {"switch.lamp": {**bad, "col": 0}}})["tiles"]["switch.lamp"])

    def test_air_conditioner_slider_maps_to_its_own_temperature_range(self):
        from pi_bus_time_display.server import climate_percent, climate_target
        attributes = {"min_temp": 16, "max_temp": 30, "target_temp_step": 1, "temperature": 23}
        self.assertEqual(climate_percent(attributes), 50)
        self.assertEqual(climate_target(attributes, 50), 23)
        self.assertEqual(climate_target(attributes, 0), 16)
        self.assertEqual(climate_target(attributes, 100), 30)
        self.assertEqual(climate_target({**attributes, "target_temp_step": 0.5}, 53), 23.5)
        self.assertIsNone(climate_percent({"temperature": 23}))
        with self.assertRaises(ValueError): climate_target({}, 50)


class LinkedHomeDevicesTests(unittest.TestCase):
    def test_one_tap_switches_every_linked_device_together(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from pi_bus_time_display import server
        with tempfile.TemporaryDirectory() as folder:
            save_layout(Path(folder) / "home-layout.json", {"tiles": {"switch.pihole_a": {"also": ["switch.pihole_b"]}}})
            home = {"entities": [{"entity_id": "switch.pihole_a", "state": "on", "on": True}]}
            state = SimpleNamespace(state_dir=Path(folder), config=object(), home_data=home)
            with patch.object(server, "home_assistant_set_state") as set_state:
                self.assertTrue(server.home_assistant_switch_group(state, "switch.pihole_a"))
                self.assertEqual([call.args[1:] for call in set_state.call_args_list], [("switch.pihole_a", False), ("switch.pihole_b", False)])
                set_state.reset_mock(); home["entities"][0].update(state="mixed", on=False)
                server.home_assistant_switch_group(state, "switch.pihole_a")
                self.assertEqual([call.args[2] for call in set_state.call_args_list], [True, True])
                set_state.reset_mock()
                self.assertFalse(server.home_assistant_switch_group(state, "switch.other"))
                set_state.assert_not_called()


class CardOptionTests(unittest.TestCase):
    def test_now_playing_options_and_three_rows(self):
        tile = {"rows": 3, "art": "thumb", "scrubber": True, "volume": False, "heading": False, "label": "Lounge"}
        layout = validate_layout({"tiles": {"roondeck.player": dict(tile, col=0, row=0)}})
        for key, value in tile.items(): self.assertEqual(layout["tiles"]["roondeck.player"][key], value)
        defaults = validate_layout({"tiles": {"roondeck.player": {"art": "background", "scrubber": False, "volume": True, "heading": True}}})
        self.assertNotIn("art", defaults["tiles"].get("roondeck.player", {}))

    def test_network_directions(self):
        layout = validate_layout({"tiles": {"roondeck.network": {"show": True, "upload": False}}})
        self.assertEqual(layout["tiles"]["roondeck.network"], {"show": True, "upload": False})
        self.assertNotIn("download", validate_layout({"tiles": {"roondeck.network": {"show": True, "download": True}}})["tiles"]["roondeck.network"])

    def test_memory_tile_is_kept(self):
        self.assertEqual(validate_layout({"tiles": {"roondeck.memory": {"show": True}}})["tiles"]["roondeck.memory"], {"show": True})

    def test_update_and_group_tiles(self):
        tiles = {"roondeck.update": {"show": True}, "roondeck.group": {"show": True, "zone": "Kitchen", "with": " Office "}, "roondeck.group2": {"show": True}}
        out = validate_layout({"tiles": tiles})
        self.assertEqual(out["tiles"]["roondeck.group"], {"show": True, "zone": "Kitchen", "with": "Office"})
        saved = with_layout({}, out)
        for key in tiles: self.assertIn(key, saved["cards"])


class PageTests(unittest.TestCase):
    def test_pages_and_tile_pages(self):
        out = validate_layout({"pages": 3, "tiles": {"light.a": {"page": 2, "col": 1}, "light.b": {"page": 0, "label": "B"}}})
        self.assertEqual(out["pages"], 3)
        self.assertEqual(out["tiles"]["light.a"], {"page": 2, "col": 1})
        self.assertNotIn("page", out["tiles"]["light.b"])
        self.assertEqual(with_layout({}, out)["pages"], 3)

    def test_one_page_is_not_stored_and_bad_values_are_refused(self):
        self.assertNotIn("pages", validate_layout({"pages": 1}))
        for bad in ({"pages": 5}, {"pages": 0}, {"pages": True}, {"tiles": {"light.a": {"page": 4}}}, {"tiles": {"light.a": {"page": True}}}):
            with self.assertRaises(ValueError): validate_layout(bad)


class CopyTests(unittest.TestCase):
    def test_a_tile_can_be_copied_onto_another_page(self):
        layout = validate_layout({"pages": 2, "tiles": {"light.lamp": {"col": 0}, "light.lamp#1": {"page": 1, "col": 2, "label": "Lamp"}, "roondeck.player#1": {"page": 1}, "roondeck.cpu#2": {"show": True, "page": 1}}})
        home = with_layout({"entities": [{"entity_id": "light.lamp"}, {"entity_id": "fan.study"}]}, layout)
        lamps = [item for item in home["entities"] if item["entity_id"] == "light.lamp"]
        self.assertEqual([item.get("tile", {}).get("page", 0) for item in lamps], [0, 1])
        self.assertEqual(len(home["entities"]), 3)
        self.assertEqual({"roondeck.player#1", "roondeck.cpu#2"} & set(home["cards"]), {"roondeck.player#1", "roondeck.cpu#2"})

    def test_bad_copy_names_are_refused(self):
        for bad in ("light.lamp#0", "light.lamp#4", "light.lamp#", "light.lamp##1"):
            with self.assertRaises(ValueError): validate_layout({"tiles": {bad: {"page": 1}}})


class RouteColourTests(unittest.TestCase):
    def test_route_colours_override_the_defaults(self):
        from datetime import datetime, timezone
        from pi_bus_time_display.domain import normalise, parse_route_colours
        self.assertEqual(parse_route_colours("40=Rose, 42 = teal, 7=pink, junk"), {"40": "rose", "42": "teal"})
        payload = {"Services": [{"ServiceNo": "40", "Operator": "SBST"}, {"ServiceNo": "42"}, {"ServiceNo": "9"}]}
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        plain = {item["service"]: item["colour"] for item in normalise(payload, now, (), 0)}
        self.assertEqual(plain, {"40": "blue", "42": "green", "9": "amber"})
        chosen = {item["service"]: item["colour"] for item in normalise(payload, now, (), 0, parse_route_colours("40=rose, 9=teal"))}
        self.assertEqual(chosen, {"40": "rose", "42": "green", "9": "teal"})


class BusRouteTests(unittest.TestCase):
    def test_bus_tile_copies_keep_their_own_route(self):
        layout = validate_layout({"tiles": {"roondeck.bus": {"route": "42"}, "roondeck.bus#1": {"route": "40", "col": 2}}})
        self.assertEqual(layout["tiles"]["roondeck.bus"]["route"], "42")
        self.assertEqual(layout["tiles"]["roondeck.bus#1"]["route"], "40")

    def test_bus_route_must_be_letters_and_numbers(self):
        with self.assertRaises(ValueError):
            validate_layout({"tiles": {"roondeck.bus": {"route": "4 2"}}})
