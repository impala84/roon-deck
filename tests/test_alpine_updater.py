import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alpine_updater", ROOT / "appliance/alpine/updater.py")
updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)


class AlpineUpdaterTests(unittest.TestCase):
    def test_updates_follow_the_renamed_alpine_beta_branch(self):
        self.assertEqual(updater.BRANCH, "alpine-beta")

    def test_check_reports_an_available_release_without_installing(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, "APP", Path(folder)), patch.object(updater, "wait_for_clock"), patch.object(updater, "verified_revision", return_value="a" * 40), patch.object(updater, "status") as status:
            updater.check()
        status.assert_called_once()

    def test_stage_space_tracks_current_release_size_with_a_bounded_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "application").write_bytes(b"x" * 1_000_000)
            required = updater.required_stage_space(root)
        self.assertGreaterEqual(required, updater.MIN_STAGE_BYTES)
        self.assertLess(required, 400_000_000)

    def test_update_leaves_live_release_directory_before_any_pruning(self):
        with patch.object(updater.os, "chdir") as chdir, patch.object(updater, "wait_for_clock", side_effect=RuntimeError("stop")):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                updater.update()
        chdir.assert_called_once_with("/")

    def test_wait_for_clock_is_bounded_and_visible(self):
        with patch.object(updater.time, "gmtime", return_value=type("Clock", (), {"tm_year": 1970})()), patch.object(updater.time, "monotonic", side_effect=[0, 0, 2]), patch.object(updater.time, "sleep"), patch.object(updater, "status") as status:
            with self.assertRaisesRegex(RuntimeError, "clock is not ready"):
                updater.wait_for_clock(timeout=1)
        status.assert_called_once_with("Update · Waiting for network time…")

    def test_old_and_failed_managed_releases_are_pruned_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            releases = Path(folder)
            current = releases / ("a" * 40 + "-1"); current.mkdir()
            old = releases / ("b" * 40 + "-2"); old.mkdir(); (old / "large").write_text("old")
            initial = releases / "initial-image"; initial.mkdir()
            unrelated = releases / "keep-me"; unrelated.mkdir()
            linked = releases / ("c" * 40 + "-3"); linked.symlink_to(unrelated, target_is_directory=True)
            updater.prune_releases(releases, {current})
            self.assertTrue(current.is_dir())
            self.assertFalse(old.exists()); self.assertFalse(initial.exists())
            self.assertTrue(unrelated.is_dir()); self.assertTrue(linked.is_symlink())

    def test_health_requires_display_process_revision_marker(self):
        with tempfile.TemporaryDirectory() as folder, patch("urllib.request.urlopen") as urlopen, patch.object(updater, "run"), patch.object(updater.time, "sleep"):
            marker = Path(folder) / "display-source-commit"
            marker.write_text("a" * 40)
            response = urlopen.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps({"revision": "a" * 40}).encode()
            with patch.object(updater, "DISPLAY_REVISION", marker):
                self.assertTrue(updater.healthy("a" * 40))
                self.assertFalse(updater.healthy("b" * 40))

    def test_health_rejects_a_stale_roon_controller(self):
        with tempfile.TemporaryDirectory() as folder, patch("urllib.request.urlopen") as urlopen, patch.object(updater, "run"), patch.object(updater.time, "sleep"):
            marker = Path(folder) / "display-source-commit"; marker.write_text("a" * 40)
            response = urlopen.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps({"revision": "b" * 40}).encode()
            with patch.object(updater, "DISPLAY_REVISION", marker):
                self.assertFalse(updater.healthy("a" * 40))

    def test_restart_stops_display_once_and_disables_dependency_cascades(self):
        with patch.object(updater, "run") as run:
            updater.restart()
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["rc-service", "--nodeps", "pi-home-display", "stop"],
            ["rc-service", "--nodeps", "seatd", "restart"],
            ["rc-service", "--nodeps", "pi-home-setup", "restart"],
            ["rc-service", "--nodeps", "pi-home-api", "restart"],
            ["rc-service", "--nodeps", "pi-home-roon", "restart"],
            ["rc-service", "--nodeps", "pi-home-display", "start"],
        ])

    def test_restart_failure_does_not_start_display_over_a_failing_backend(self):
        with patch.object(updater, "run", side_effect=[None, None, None, RuntimeError("backend failed")]) as run:
            with self.assertRaisesRegex(RuntimeError, "backend failed"):
                updater.restart()
        self.assertEqual(run.call_count,4)

    def test_restart_clears_stale_display_revision_before_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, "run"):
            marker = Path(folder) / "display-source-commit"; marker.write_text("old")
            with patch.object(updater, "DISPLAY_REVISION", marker):
                updater.restart()
            self.assertFalse(marker.exists())

    def test_command_logs_are_private_and_timeout_is_explicit(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, "STATE", Path(folder)):
            updater.run(["printf", "test-dependency-output"])
            log = Path(folder) / "update.log"
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            self.assertIn("test-dependency-output", log.read_text())
            with patch.object(updater.subprocess, "run", side_effect=subprocess.TimeoutExpired("pip", 300)), self.assertRaisesRegex(RuntimeError, "timed out"):
                updater.run(["pip", "install"])

    def test_completed_pre_marker_installation_is_migrated_before_display_restart(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, "STATE", Path(folder) / "pi-home"):
            legacy = Path(folder) / "pi-home-setup" / "progress.json"
            legacy.parent.mkdir(parents=True); legacy.write_text('{"complete": true}')
            self.assertTrue(updater.migrate_completed_setup())
            marker = Path(folder) / "pi-home" / "setup-complete"
            self.assertEqual(marker.read_text(), "true\n")
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertFalse(updater.migrate_completed_setup())

    def test_only_successful_fixed_branch_builds_are_accepted(self):
        sha = "a" * 40
        valid = {"workflow_runs": [{"head_sha": sha, "head_branch": updater.BRANCH, "conclusion": "success", "event": "push", "head_repository": {"full_name": "impala84/roon-deck"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.toml').write_text('release_channel = "stable"')
            (root / 'pyproject.toml').write_text('[project]\nversion = "1.0.0"')
            (root / 'update-channel-initialized').touch()
            with patch.object(updater, 'APP', root), patch.object(updater, 'STATE', root), patch.object(updater, 'CONFIG', root / 'config.toml'), patch.object(updater, 'published_releases', return_value=[{'tag_name': 'v1.1.0-alpine'}]):
                reference = {'object': {'type': 'commit', 'sha': sha}}
                with patch.object(updater, "fetch_json", side_effect=[reference, valid]):
                    self.assertEqual(updater.verified_revision(), sha)
                for changes in ({"head_sha": "../bad"}, {"head_branch": "main"}, {"conclusion": "failure"}, {"event": "pull_request"}, {"head_repository": {"full_name": "other/fork"}}):
                    invalid = {"workflow_runs": [{**valid["workflow_runs"][0], **changes}]}
                    with patch.object(updater, "fetch_json", side_effect=[reference, invalid]), self.assertRaises(RuntimeError): updater.verified_revision()
                (root / 'pyproject.toml').write_text('[project]\nversion = "1.2.0"')
                with self.assertRaises(updater.NoDowngrade): updater.verified_revision()

    def test_tar_traversal_and_links_are_rejected(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("repo/link", tarfile.SYMTYPE), ("/absolute", tarfile.REGTYPE)):
            with tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "source.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    item = tarfile.TarInfo(name); item.type = kind; item.linkname = "/etc/shadow"; tar.addfile(item)
                with self.assertRaises(RuntimeError): updater.extract_source(archive, Path(folder) / "out")

    def test_safe_source_extract_and_atomic_switch_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / "source.gz"
            with tarfile.open(archive, "w:gz") as tar:
                item = tarfile.TarInfo("repo/appliance/alpine/updater.py"); item.size = 4; tar.addfile(item, io.BytesIO(b"pass"))
            source = updater.extract_source(archive, root / "out")
            self.assertTrue((source / "appliance/alpine/updater.py").exists())
            app = root / "pi-home"; old = root / "previous"; old.mkdir(); app.symlink_to(old)
            with patch.object(updater, "APP", app):
                updater.activate(source); self.assertEqual(app.resolve(), source.resolve())
                updater.activate(old); self.assertEqual(app.resolve(), old.resolve())

    def test_source_download_retries_transient_network_failures(self):
        response = type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda *args: None, "read": lambda self, size: b""})()
        with tempfile.TemporaryDirectory() as folder, patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("temporary"), response]) as urlopen, patch.object(updater.time, "sleep"), patch.object(updater, "status"):
            archive = Path(folder) / "source.tar.gz"
            updater.download_source("a" * 40, archive)
            self.assertTrue(archive.exists())
            self.assertEqual(urlopen.call_count, 2)

    def test_current_revision_does_not_download_or_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder); (app / ".source-commit").write_text("a" * 40)
            with patch.object(updater, "APP", app), patch.object(updater, "status"), patch.object(updater, "verified_revision", return_value="a" * 40), patch.object(updater, "healthy", return_value=True), patch.object(updater, "restart") as restart:
                updater.update(); restart.assert_not_called()

    def test_current_files_restart_a_stale_touchscreen(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder); (app / ".source-commit").write_text("a" * 40)
            with patch.object(updater, "APP", app), patch.object(updater, "status") as status, patch.object(updater, "verified_revision", return_value="a" * 40), patch.object(updater, "healthy", side_effect=[False, True]), patch.object(updater, "restart") as restart:
                updater.update(); restart.assert_called_once(); self.assertIn("now running", status.call_args.args[0])
