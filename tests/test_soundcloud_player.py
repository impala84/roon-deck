import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pi_bus_time_display import soundcloud_player as sc

FAKE_YTDLP = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
target = args[-1]
if target.startswith("scsearch"):
    for n in range(2):
        print(json.dumps({"url": "https://soundcloud.com/artist/track-%d" % n, "title": "Track %d" % n, "uploader": "Artist", "duration": 100 + n}))
else:
    print(json.dumps({"entries": [{"url": "https://soundcloud.com/a/liked", "title": "Liked", "uploader": "A", "duration": 5}, {"url": "javascript:alert(1)", "title": "bad"}]}))
"""


class SoundCloudTests(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.TemporaryDirectory(); self.addCleanup(self.bin.cleanup)
        path = Path(self.bin.name) / "yt-dlp"; path.write_text(FAKE_YTDLP); path.chmod(path.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": self.bin.name + os.pathsep + os.environ["PATH"]}); patcher.start(); self.addCleanup(patcher.stop)

    def test_search_parses_tracks(self):
        items = sc.search("  some   query ")
        self.assertEqual([item["title"] for item in items], ["Track 0", "Track 1"])
        self.assertEqual(items[0]["url"], "https://soundcloud.com/artist/track-0")

    def test_browse_keeps_only_soundcloud_links(self):
        items = sc.browse("https://soundcloud.com/someone/", "likes")
        self.assertEqual([item["title"] for item in items], ["Liked"])

    def test_inputs_are_validated(self):
        for bad in ("", "x" * 121): self.assertRaises(ValueError, sc.clean_query, bad)
        for bad in ("http://soundcloud.com/a/b", "https://evil.example/soundcloud.com/a", "file:///etc/passwd", ""): self.assertRaises(ValueError, sc.clean_url, bad)
        self.assertEqual(sc.clean_profile("https://soundcloud.com/some_one-1"), "some_one-1")
        self.assertRaises(ValueError, sc.clean_profile, "bad name;rm")
        self.assertRaises(ValueError, sc.browse, "someone", "everything")

    def test_play_pauses_roon_and_tracks_state(self):
        player = sc.Player()
        spawned = []
        import threading
        class Proc:
            def __init__(self): self.ended = threading.Event()
            def poll(self): return 15 if self.ended.is_set() else None
            def wait(self, timeout=None): self.ended.wait(timeout); return 15
            def terminate(self): self.ended.set()
            def kill(self): self.ended.set()
        with mock.patch.object(sc, "pause_roon") as pause, mock.patch.object(player, "spawn", side_effect=lambda url: spawned.append(url) or Proc()), mock.patch.object(player, "ipc", return_value=None):
            player.play([{"url": "https://soundcloud.com/a/one", "title": "One"}, {"url": "https://soundcloud.com/a/two", "title": "Two"}], 1)
            self.assertEqual(spawned, ["https://soundcloud.com/a/two"]); pause.assert_called()
            state = player.state(); self.assertTrue(state["active"]); self.assertEqual(state["track"]["title"], "Two"); self.assertEqual(state["index"], 1)
            player.pause(); self.assertTrue(player.state()["paused"])
            player.step(-1); self.assertEqual(spawned[-1], "https://soundcloud.com/a/one")
            player.stop(); self.assertFalse(player.state()["active"])

    def test_play_rejects_non_soundcloud_urls(self):
        self.assertRaises(ValueError, sc.Player().play, [{"url": "https://example.com/a.mp3"}])

    def test_finished_track_advances_the_queue(self):
        player = sc.Player(); player.queue = [{"url": "https://soundcloud.com/a/one"}, {"url": "https://soundcloud.com/a/two"}]; player.index = 0
        player.generation = 3
        class Done:
            def wait(self): return 0
        with mock.patch.object(player, "play_index") as play: player.watch(Done(), 3)
        play.assert_called_once_with(1)
        with mock.patch.object(player, "play_index") as play: player.watch(Done(), 2)   # a replaced track must not advance
        play.assert_not_called()

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(sc, "STATE_DIR", Path(folder)):
            player = sc.Player(); player.save_settings(profile="my-name", audio_device="alsa/default")
            again = sc.Player(); self.assertEqual((again.profile, again.device), ("my-name", "alsa/default"))
            self.assertRaises(ValueError, player.save_settings, audio_device="x;y")


if __name__ == "__main__":
    unittest.main()


class AdminBridgeTests(unittest.TestCase):
    def test_request_to_a_missing_player_is_none(self):
        from pi_bus_time_display.server import soundcloud_request
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertIsNone(soundcloud_request("/state"))
