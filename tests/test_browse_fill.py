import unittest
from types import SimpleNamespace

from test_native_browser_controls import native_method


def metrics(interface_size):
    monitor = SimpleNamespace(get_geometry=lambda: SimpleNamespace(width=1280))
    display = SimpleNamespace(get_monitors=lambda: SimpleNamespace(get_n_items=lambda: 1, get_item=lambda _: monitor))
    fn = native_method("browser_grid_metrics", {"Gdk": SimpleNamespace(Display=SimpleNamespace(get_default=lambda: display))})
    app = SimpleNamespace(viewport_width=1280, viewport_height=720, responsive_portrait=False,
                          settings_data={"interface_size": interface_size},
                          system_data={"display_profile": "touch2-7"})
    return fn(app)


class BrowseFillTests(unittest.TestCase):
    def test_standard_covers_fill_the_sketched_area(self):
        columns, size = metrics("standard")
        self.assertEqual((columns, size), (4, 221))
        # Four cards (size + 6) and three 12px gaps from x=197 end before the 64px rail at x=1188.
        self.assertLessEqual(197 + 4 * (size + 6) + 3 * 12, 1280 - 133)

    def test_larger_fills_with_a_small_reserve(self):
        self.assertEqual(metrics("larger")[1], 218)


if __name__ == "__main__":
    unittest.main()


class ScrollMarginTests(unittest.TestCase):
    def margin(self, **state):
        return native_method("browser_scroll_bottom_margin")(SimpleNamespace(**state))

    def test_every_layout_returns_a_margin_without_raising(self):
        self.assertEqual(self.margin(viewport_width=1280, viewport_height=720, settings_data={}), 16)
        self.assertEqual(self.margin(viewport_width=1280, viewport_height=720, settings_data={"interface_size": "larger"}), 19)
        self.assertEqual(self.margin(viewport_width=1200, viewport_height=1920, responsive_portrait=True, settings_data={}), 10)
        self.assertEqual(self.margin(viewport_width=800, viewport_height=480, settings_data={}), 10)
        self.assertEqual(native_method("browser_scroll_bottom_margin")(SimpleNamespace(), True), 0)
