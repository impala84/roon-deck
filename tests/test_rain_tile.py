from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pi_bus_time_display.config import RAIN_SENSOR, load_config
from pi_bus_time_display.server import rain_tile_detail


class RainTileTests(TestCase):
    def test_sensor_can_be_added_only_to_the_home_display(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(f'home_assistant_entities = ["{RAIN_SENSOR}"]')
            self.assertEqual(load_config(path).home_assistant_entities, (RAIN_SENSOR,))
            for setting, entity in (("home_assistant_deck_entities", RAIN_SENSOR),
                                    ("home_assistant_entities", "sensor.other")):
                path.write_text(f'{setting} = ["{entity}"]')
                with self.assertRaisesRegex(ValueError, "Unsupported Home Assistant entity"):
                    load_config(path)

    def test_rain_detail_uses_scan_age_and_absolute_arrival_time(self):
        now = datetime(2026, 11, 15, 1, tzinfo=timezone.utc)
        attrs = {"radar_at": now.isoformat(),
                 "arrival_at": (now + timedelta(minutes=22)).isoformat()}
        self.assertEqual(rain_tile_detail("approaching", attrs, now), "Rain possible in 20–30 min")
        self.assertEqual(rain_tile_detail("approaching", attrs, now + timedelta(minutes=6)),
                         "Rain possible in 15–25 min")
        self.assertEqual(rain_tile_detail("raining", attrs, now), "Rain now")
        self.assertEqual(rain_tile_detail("raining", attrs, now + timedelta(minutes=11)),
                         "Radar unavailable")
        self.assertEqual(rain_tile_detail("approaching", {}, now), "Radar unavailable")
