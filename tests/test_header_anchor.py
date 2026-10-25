"""Guard the seven-inch Gen 2 cog anchor: same top edge on every primary page."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import css_cascade_report as report  # noqa: E402


class HeaderAnchorTest(unittest.TestCase):
    def test_standard_cog_top_edge_matches_on_every_primary_page(self):
        self.check(set(), 14)

    def test_larger_cog_top_edge_matches_on_every_primary_page(self):
        self.check({"interface-larger"}, 18)

    def check(self, extra, expected):
        rules = report.load_css()
        window = report.window_classes(1280, 720) | extra
        tops = {}
        for page, element in (("bus-page", "page-header"), ("home-page", "page-header"), ("roon-page", "discover-toolbar")):
            padding = report.px(report.resolve(rules, window, page, page).get("padding-top"))
            if element == "page-header":
                margin = report.px(report.resolve(rules, window, page, "page-header").get("margin-top"))
                cog = report.resolve(rules, window, page, "discover-utility", within=("page-header",))
            else:
                margin = 0
                cog = report.resolve(rules, window, page, "discover-utility", within=("discover-toolbar",))
            tops[page] = padding + margin + report.px(cog.get("margin-top"))
        self.assertEqual(set(tops.values()), {expected}, tops)


if __name__ == "__main__":
    unittest.main()
