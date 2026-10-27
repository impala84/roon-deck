import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pi_bus_time_display.config import Config
from pi_bus_time_display.performance import PerformanceHistory
from pi_bus_time_display.server import State, make_handler


class PerformanceHistoryTests(unittest.TestCase):
    def test_clients_share_one_bounded_history_and_do_not_oversample(self):
        now = [0]
        def reader(path):
            if path == '/proc/stat': return f'cpu {now[0] * 20} 0 0 {100 + now[0] * 80}\n'
            if path == '/proc/meminfo': return 'MemTotal: 1000 kB\nMemAvailable: 250 kB\n'
            if path.endswith('/temp'): return '48000'
            return 'a\nb\neth0: ' + str(now[0] * 125000) + ' 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n'
        history = PerformanceHistory(reader, lambda: now[0])
        for second in range(80):
            now[0] = second
            history.snapshot()
            history.snapshot()  # A second browser adds no extra sample.
        data = history.snapshot()
        self.assertEqual(len(data['history']['cpu']), 60)
        self.assertEqual(len(data['history']['memory']), 60)
        self.assertAlmostEqual(data['latest']['cpu'], 20)
        self.assertAlmostEqual(data['latest']['memory'], 75)
        self.assertAlmostEqual(data['latest']['network'], 1)
        self.assertEqual(data['latest']['temp'], 48)
        data['history']['memory'].clear()
        self.assertEqual(len(history.snapshot()['history']['memory']), 60)

    def test_a_sampling_gap_does_not_join_old_points_into_the_last_minute(self):
        now = [0]
        history = PerformanceHistory(lambda path: 'MemTotal: 100 kB\nMemAvailable: 50 kB\n' if path == '/proc/meminfo' else '', lambda: now[0])
        history.snapshot()
        now[0] = 1
        history.snapshot()
        now[0] = 100
        self.assertEqual(history.snapshot()['history']['memory'], [50])

    def test_a_missing_metric_does_not_keep_a_stale_line_at_now(self):
        now = [0]
        def reader(path):
            if path == '/proc/meminfo': return 'MemTotal: 100 kB\nMemAvailable: 50 kB\n'
            if path.endswith('/temp') and now[0] == 0: return '48000'
            return ''
        history = PerformanceHistory(reader, lambda: now[0])
        self.assertEqual(history.snapshot()['history']['temp'], [48])
        now[0] = 1
        data = history.snapshot()
        self.assertIsNone(data['latest']['temp'])
        self.assertEqual(data['history']['temp'], [])
        self.assertTrue(data['available'])
        self.assertEqual(data['history']['memory'], [50, 50])

    def test_missing_linux_measurements_are_unavailable_not_zero(self):
        history = PerformanceHistory(lambda _: '', lambda: 1)
        data = history.snapshot()
        self.assertFalse(data['available'])
        self.assertTrue(all(value is None for value in data['latest'].values()))
        self.assertTrue(all(not values for values in data['history'].values()))

    def test_performance_endpoint_requires_authentication_and_returns_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = State(Config(), root)
            state.performance = Mock()
            state.performance.snapshot.return_value = {'seconds': 60, 'history': {'cpu': [10, 20]}}
            handler_type = make_handler(state, root / 'config', root / 'env', root / 'mode')
            handler = object.__new__(handler_type)
            handler.path = '/api/admin/performance'
            handler.send_json = Mock()
            handler.authorised = lambda: False
            handler.do_GET()
            state.performance.snapshot.assert_not_called()
            handler.send_json.assert_not_called()
            handler.authorised = lambda: True
            handler.do_GET()
            self.assertEqual(handler.send_json.call_args.args[0], 200)
            self.assertEqual(json.loads(handler.send_json.call_args.args[1])['history']['cpu'], [10, 20])
