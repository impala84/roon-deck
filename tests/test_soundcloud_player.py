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
        cover = mock.patch.object(sc, "oembed_cover", return_value="https://i1.sndcdn.com/artworks-abc-t500x500.jpg"); cover.start(); self.addCleanup(cover.stop)

    def test_search_results_get_small_covers(self):
        self.assertEqual(sc.search("q")[0]["artwork"], "https://i1.sndcdn.com/artworks-abc-t200x200.jpg")

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


class StreamFormatTests(unittest.TestCase):
    def test_stream_format_and_resample(self):
        player = sc.Player()
        values = {"audio-codec-name": "aac", "audio-bitrate": 256000, "audio-params": {"samplerate": 44100}, "audio-out-params": {"samplerate": 48000}}
        player.ipc = lambda command, name: values.get(name)
        self.assertEqual(player.stream_format(), "AAC · 256 kbps · 44.1 kHz · resampled to 48 kHz")
        values["audio-out-params"] = {"samplerate": 44100}; values["audio-bitrate"] = None
        self.assertEqual(player.stream_format(), "AAC · 44.1 kHz")


if __name__ == "__main__":
    unittest.main()


class AdminBridgeTests(unittest.TestCase):
    def test_request_to_a_missing_player_is_none(self):
        from pi_bus_time_display.server import soundcloud_request
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertIsNone(soundcloud_request("/state"))


class CacheAndPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.TemporaryDirectory(); self.addCleanup(self.bin.cleanup)
        self.log = Path(self.bin.name) / "calls"
        path = Path(self.bin.name) / "yt-dlp"
        path.write_text('#!/usr/bin/env python3\nimport json,sys\nopen(%r,"a").write("x")\nprint(json.dumps({"url":"https://soundcloud.com/a/t","title":"T","uploader":"A","duration":1}))\n' % str(self.log)); path.chmod(path.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": self.bin.name + os.pathsep + os.environ["PATH"]}); patcher.start(); self.addCleanup(patcher.stop)
        sc._CACHE.clear()
        cover = mock.patch.object(sc, "oembed_cover", return_value=""); cover.start(); self.addCleanup(cover.stop)

    def test_repeat_searches_use_the_cache(self):
        sc.search("same"); sc.search("same"); sc.search("Same")
        self.assertEqual(len(self.log.read_text()), 1)

    def test_playlist_tracks_need_a_soundcloud_link(self):
        self.assertEqual(sc.tracks_of("https://soundcloud.com/a/sets/mix")[0]["title"], "T")
        self.assertRaises(ValueError, sc.tracks_of, "https://example.com/list")

    def test_api_track_links_are_accepted(self):
        self.assertTrue(sc.clean_url("https://api.soundcloud.com/tracks/123456"))


class OutputTests(unittest.TestCase):
    CARDS = """ 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 1 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 2 [sndrpihifiberry]: HifiberryDacp - snd_rpi_hifiberry_dacplus
                      snd_rpi_hifiberry_dacplus
"""

    def test_the_dac_is_preferred_over_hdmi_and_headphones(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cards"; path.write_text(self.CARDS)
            cards = sc.sound_cards(str(path))
            self.assertEqual([card["id"] for card in cards], ["vc4hdmi0", "Headphones", "sndrpihifiberry"])
            self.assertEqual(sc.best_output(cards), "alsa/hw:CARD=sndrpihifiberry,DEV=0")

    def test_no_cards_means_mpv_default(self):
        self.assertEqual(sc.best_output([]), "")

    def test_cover_sizes(self):
        self.assertEqual(sc.art_url("https://i1.sndcdn.com/artworks-x-large.jpg"), "https://i1.sndcdn.com/artworks-x-t200x200.jpg")
        self.assertEqual(sc.art_url("https://i1.sndcdn.com/artworks-x-t500x500.png", "t500x500"), "https://i1.sndcdn.com/artworks-x-t500x500.png")
        self.assertEqual(sc.art_url("http://insecure/x.jpg"), "")
