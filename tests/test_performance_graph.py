import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native-display"))

from native_source import native_text


def pure():
    """performance_graph without GTK: load only the pure helpers."""
    import ast
    source = (Path(__file__).resolve().parents[1] / "native-display" / "performance_graph.py").read_text()
    tree = ast.parse(source)
    keep = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.Import, ast.ImportFrom))
            and not (isinstance(node, ast.ImportFrom) and node.module in {"native_common", "gi.repository"}) and not (isinstance(node, ast.ClassDef) and node.name == "PerformanceGraph")
            and not (isinstance(node, ast.FunctionDef) and node.name == "curve")]
    namespace = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "performance_graph", "exec"), namespace)
    return namespace


class PerformanceGraphTests(unittest.TestCase):
    def setUp(self):
        self.p = pure()

    def test_cpu_percent_from_proc_stat(self):
        first = self.p["parse_cpu_times"]("cpu  100 0 100 800 0 0 0 0 0 0\n")
        second = self.p["parse_cpu_times"]("cpu  150 0 150 900 0 0 0 0 0 0\n")
        self.assertAlmostEqual(self.p["cpu_percent"](first, second), 50.0)
        self.assertIsNone(self.p["cpu_percent"](None, second))

    def test_memory_percent_uses_available_memory(self):
        text = "MemTotal:        1000 kB\nMemFree:          100 kB\nMemAvailable:     250 kB\n"
        self.assertAlmostEqual(self.p["memory_percent"](text), 75.0)
        self.assertIsNone(self.p["memory_percent"]("nonsense"))

    def test_network_bytes_skips_loopback_and_sums_receive_and_send(self):
        text = ("Inter-|   Receive\n face |bytes\n"
                "    lo: 1000 1 0 0 0 0 0 0 1000 1 0 0 0 0 0 0\n"
                "  wlan0: 4000 5 0 0 0 0 0 0 2000 4 0 0 0 0 0 0\n")
        self.assertEqual(self.p["network_bytes"](text), 6000)

    def test_sampler_reports_rate_and_scales_network_to_its_peak(self):
        sampler = self.p["PerformanceSampler"]()
        header = "a\nb\n"
        sampler.sample(0, "cpu 0 0 0 100\n", "MemTotal: 100 kB\nMemAvailable: 50 kB\n", "48000\n", header + "w: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
        latest = sampler.sample(1, "cpu 10 0 0 190\n", "MemTotal: 100 kB\nMemAvailable: 50 kB\n", "48000\n", header + "w: 1250000 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
        self.assertAlmostEqual(latest["network"], 10.0)
        self.assertAlmostEqual(latest["temp"], 48.0)
        self.assertAlmostEqual(latest["cpu"], 10.0)
        self.assertEqual(self.p["format_value"]("network", 2.44), "2.4 Mb/s")
        self.assertEqual(self.p["format_value"]("temp", 47.6), "48°C")
        self.assertEqual(self.p["format_value"]("cpu", None), "—")
        self.assertTrue(all(0 <= value <= 100 for value in sampler.plotted("network")))

    def test_settings_page_wires_the_row_and_graph_for_10_inch_portrait_only(self):
        code = native_text()
        self.assertIn("wide_portrait = portrait and width >= 1000", code)
        self.assertIn("self.settings_display_row.set_visible(wide_portrait); self.performance_graph.set_visible(wide_portrait)", code)
        self.assertIn(".portrait.large-portrait .settings-display-row .settings-select { font-size: 21px; }", code)


if __name__ == "__main__":
    unittest.main()
