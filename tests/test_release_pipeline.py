"""Release ordering and exact-commit guards, without network or publication."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def release_module():
    loader = importlib.machinery.SourceFileLoader('release_pipeline_test', str(ROOT / 'tools/release-beta'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ReleasePipelineTests(unittest.TestCase):
    def test_rebase_precedes_final_checks_and_publication_uses_checked_sha(self):
        module = release_module(); calls = []
        def run(*args, capture=False):
            calls.append(args)
            if args[:3] == ('git', 'branch', '--show-current'): return 'main'
            if args[:3] == ('gh', 'release', 'list'): return '[]'
            if args[:2] == ('git', 'status'): return 'M pyproject.toml'
            if args[:2] == ('git', 'rev-parse'): return 'checked-sha'
            return ''
        with patch.object(module, 'run', side_effect=run), patch.object(module, 'top_entry', return_value=('1.2.0-beta.134', 'notes')), patch.object(module, 'current_version', return_value='1.2.0-beta.134'), patch.object(module, 'wait_for_publication') as wait, patch.object(module.sys, 'argv', ['release-beta']):
            module.main()
        self.assertLess(calls.index(('git', 'pull', '--rebase', 'origin', 'main')), calls.index(('tools/check', 'fast')))
        self.assertLess(calls.index(('tools/check', 'fast')), calls.index(('git', 'push', 'origin', 'HEAD:main')))
        self.assertEqual(calls.count(('tools/check', 'fast')), 1)
        self.assertFalse(any(call[:3] == ('gh', 'release', 'create') for call in calls))
        wait.assert_called_once_with('v1.2.0-beta.134', 'checked-sha')

    def test_changed_release_notes_after_rebase_stop_before_check_or_push(self):
        module = release_module(); calls = []
        def run(*args, capture=False):
            calls.append(args)
            if args[:3] == ('git', 'branch', '--show-current'): return 'main'
            if args[:3] == ('gh', 'release', 'list'): return '[]'
            return ''
        with patch.object(module, 'run', side_effect=run), patch.object(module, 'top_entry', side_effect=[('1.2.0-beta.134', 'notes'), ('1.2.0-beta.135', 'other')]), patch.object(module, 'current_version', return_value='1.2.0-beta.134'), patch.object(module.sys, 'argv', ['release-beta']):
            with self.assertRaisesRegex(SystemExit, 'rebase changed'):
                module.main()
        self.assertNotIn(('tools/check', 'fast'), calls)
        self.assertFalse(any(call[:2] == ('git', 'push') for call in calls))

    def test_failed_baseline_stops_even_if_a_release_exists(self):
        module = release_module(); calls = []
        def run(*args, capture=False):
            calls.append(args)
            if args[:3] == ('gh', 'run', 'list'): return json.dumps([{'databaseId': 42}])
            if args[:3] == ('gh', 'run', 'watch'): raise SystemExit('baseline failed')
            self.fail(f'Unexpected command after failed baseline: {args}')
        with patch.object(module, 'run', side_effect=run):
            with self.assertRaisesRegex(SystemExit, 'baseline failed'): module.wait_for_publication('v1.2.0-beta.134', 'expected')
        self.assertEqual(len(calls), 2)

    def test_existing_tag_must_match_checked_commit(self):
        module = release_module()
        with patch.object(module, 'run', side_effect=[json.dumps([{'databaseId': 42}]), '', json.dumps([{'tagName': 'v1.2.0-beta.134'}]), 'wrong-sha']):
            with self.assertRaisesRegex(SystemExit, 'different commit'): module.wait_for_publication('v1.2.0-beta.134', 'expected')

    def test_appliance_safety_command_does_not_run_visuals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); log = root / 'calls'
            docker = root / 'docker'; docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHECK_CALLS"\n'); docker.chmod(0o755)
            import os
            env = {**os.environ, 'PATH': f'{root}:'+os.environ['PATH'], 'CHECK_CALLS': str(log)}
            result = subprocess.run(['bash', str(ROOT / 'tools/check'), 'appliance'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text()
            self.assertIn('updater_smoke.py', commands)
            self.assertIn('update_button_smoke.py', commands)
            self.assertNotIn('xvfb', commands)
            self.assertNotIn('discover_smoke.py', commands)
