import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_bus_time_display.config import Config, load_config
from pi_bus_time_display.releases import ReleaseChecker, SemVer, select_release
from pi_bus_time_display.server import write_config, initialise_update_channel


def release(tag, **fields):
    return {"tag_name": tag, **fields}


class ReleaseTests(unittest.TestCase):
    def test_existing_alpine_beta_migration_is_once_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'PI_HOME_APPLIANCE_PLATFORM': 'alpine-prototype'}):
            root = Path(directory)
            path = root / 'config.toml'
            config = Config(display_theme='roon')
            write_config(path, config)
            migrated = initialise_update_channel(config, path, root)
            self.assertEqual(migrated.release_channel, 'beta')
            self.assertEqual(load_config(path).display_theme, 'roon')
            stable = Config(release_channel='stable')
            self.assertEqual(initialise_update_channel(stable, path, root).release_channel, 'stable')

    def test_fresh_alpine_marker_preserves_stable(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'PI_HOME_APPLIANCE_PLATFORM': 'alpine-prototype'}):
            root = Path(directory)
            (root / 'update-channel-initialized').touch()
            self.assertEqual(initialise_update_channel(Config(), root / 'config.toml', root).release_channel, 'stable')

    def test_distribution_isolation_and_alpine_stable_version(self):
        items = [release('v1.1.0'), release('v1.2.0-alpine'), release('v1.3.0-beta.1-alpine', prerelease=True)]
        self.assertEqual(select_release(items, 'beta', '1.0.0')['tag'], 'v1.1.0')
        result = select_release(items, 'stable', '1.0.0', 'alpine')
        self.assertEqual(result['tag'], 'v1.2.0-alpine')
        self.assertEqual(result['latest_version'], '1.2.0')
        self.assertEqual(select_release(items, 'beta', '1.0.0', 'alpine')['tag'], 'v1.3.0-beta.1-alpine')
        self.assertEqual(select_release(items, 'stable', '1.4.0', 'alpine')['status'], 'ahead')

    def test_alpine_accepts_plain_tags_and_rpi_ignores_alpine_tags(self):
        items = [release('v1.3.0-beta.1-alpine', prerelease=True), release('v1.3.0-beta.2', prerelease=True)]
        result = select_release(items, 'beta', '1.3.0-beta.1', 'alpine')
        self.assertEqual(result['tag'], 'v1.3.0-beta.2')
        self.assertEqual(result['latest_version'], '1.3.0-beta.2')
        self.assertTrue(result['update_available'])
        self.assertEqual(select_release(items, 'beta', '1.0.0')['tag'], 'v1.3.0-beta.2')
        self.assertEqual(select_release([items[0]], 'beta', '1.0.0')['status'], 'unavailable')

    def test_cache_includes_installed_version_and_distribution(self):
        with patch('pi_bus_time_display.releases.published_releases', return_value=[release('v1.1.0'), release('v1.1.0-alpine')]) as fetch:
            checker = ReleaseChecker()
            checker.check('stable', '1.0.0')
            checker.check('stable', '1.1.0')
            checker.check('stable', '1.1.0', distribution='alpine')
            self.assertEqual(fetch.call_count, 3)

    def test_semver_numeric_prerelease_order_and_final(self):
        values = ['1.1.0-beta.2', '1.1.0-beta.10', '1.1.0', '1.10.0', '2.0.0']
        self.assertEqual(sorted(values, key=SemVer), values)
        self.assertEqual(SemVer('1.0.0+build.5'), SemVer('v1.0.0'))
        for invalid in ('main', '1.0', '01.0.0', '1.0.0-beta.01', 'v1.0.0;reboot'):
            with self.assertRaises(ValueError): SemVer(invalid)

    def test_stable_excludes_beta_draft_and_invalid_tags(self):
        items = [release('v1.0.1'), release('v1.1.0-beta.1', prerelease=True), release('v9.0.0', draft=True), release('main'), release('v3.0.0', prerelease=True)]
        result = select_release(items, 'stable', '1.0.0')
        self.assertEqual(result['tag'], 'v1.0.1')
        self.assertTrue(result['update_available'])

    def test_beta_selects_highest_semver_not_publication_order(self):
        items = [release('v1.0.0'), release('v1.1.0-beta.10', prerelease=True), release('v1.1.0-beta.2', prerelease=True)]
        self.assertEqual(select_release(items, 'beta', '1.0.0')['tag'], 'v1.1.0-beta.10')
        items.append(release('v1.1.0'))
        self.assertEqual(select_release(items, 'beta', '1.1.0-beta.10')['tag'], 'v1.1.0')

    def test_return_to_stable_never_downgrades(self):
        result = select_release([release('v1.0.0')], 'stable', '1.1.0-beta.1')
        self.assertEqual(result['status'], 'ahead')
        self.assertFalse(result['update_available'])
        self.assertFalse(select_release([release('v1.0.0')], 'stable', '1.0.0')['update_available'])

    def test_empty_or_failed_catalogue_is_not_up_to_date(self):
        self.assertEqual(select_release([], 'stable', '1.0.0')['status'], 'unavailable')
        with patch('pi_bus_time_display.releases.published_releases', side_effect=OSError('offline')):
            self.assertEqual(ReleaseChecker().check('stable', '1.0.0')['status'], 'unavailable')

    def test_cache_refreshes_after_channel_change(self):
        with patch('pi_bus_time_display.releases.published_releases', return_value=[release('v1.0.0')]) as fetch:
            checker = ReleaseChecker()
            checker.check('stable', '1.0.0'); checker.check('stable', '1.0.0')
            self.assertEqual(fetch.call_count, 1)
            checker.check('beta', '1.0.0'); checker.check('beta', '1.0.0', refresh=True)
            self.assertEqual(fetch.call_count, 3)

    def test_channel_persists_and_rejects_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            self.assertEqual(Config().release_channel, 'stable')
            write_config(path, Config(release_channel='beta'))
            self.assertEqual(load_config(path).release_channel, 'beta')
            write_config(path, Config(release_channel='main'))
            with self.assertRaises(ValueError): load_config(path)

    def test_updater_uses_exact_release_tag_not_main(self):
        script = (Path(__file__).parents[1] / 'scripts/pi-bus-update').read_text()
        self.assertIn('releases.py', script)
        self.assertIn('checkout --detach "refs/tags/${PI_HOME_UPDATE_TARGET}"', script)
        self.assertNotIn('checkout -B main origin/main', script)
        self.assertLess(script.index('if [[ -z ${release_tag} ]]'), script.index('stash push'))
        self.assertIn('|| -z ${PI_HOME_UPDATE_TARGET:-}', script)


if __name__ == '__main__': unittest.main()
