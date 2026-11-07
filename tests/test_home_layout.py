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

    def test_missing_or_broken_file_means_no_custom_tiles(self):
        folder = Path(tempfile.mkdtemp())
        self.assertEqual(load_layout(folder / "none.json"), {"tiles": {}})
        (folder / "bad.json").write_text("{nope"); self.assertEqual(load_layout(folder / "bad.json"), {"tiles": {}})

    def test_layout_is_attached_to_matching_devices_only(self):
        home = {"status": "ok", "entities": [{"entity_id": "light.a"}, {"entity_id": "fan.b"}]}
        result = with_layout(home, {"tiles": {"light.a": {"size": "half"}}})
        self.assertEqual(result["entities"][0]["tile"], {"size": "half"}); self.assertNotIn("tile", result["entities"][1])
        self.assertIs(with_layout("offline", {}), "offline")
