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
        for rows in (0, 3, "2", True):
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
