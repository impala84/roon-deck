"""SoundCloud player for the Pi: yt-dlp finds tracks, mpv plays them on the Pi's own audio output.

This is a small local service (127.0.0.1:8767) used by the touchscreen. It is not connected to Roon. The Pi's DAC can only
play one thing at a time, so SoundCloud and Roon take turns: starting a track pauses the Roon zone, and when Roon starts
playing again this service stops.

Only the standard library is used. yt-dlp and mpv are installed on the appliance from the web admin (SoundCloud tab).
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", int(os.getenv("ROONDECK_SOUNDCLOUD_PORT", "8767"))
ROON = os.getenv("ROONDECK_ROON_URL", "http://127.0.0.1:8766")
STATE_DIR = Path(os.getenv("PI_HOME_STATE_DIR", "/var/lib/pi-home"))
IPC_SOCKET = os.getenv("ROONDECK_SOUNDCLOUD_IPC", "/tmp/roondeck-soundcloud-mpv.sock")
TRACK_URL = re.compile(r"^https://(?:www\.|m\.|on\.|api\.|api-v2\.)?soundcloud\.com/[A-Za-z0-9_./~%?=&-]{1,300}$")
PARK_SECONDS = 8
PROFILE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
KINDS = {"tracks": "tracks", "likes": "likes", "reposts": "reposts", "playlists": "sets"}


def clean_query(value) -> str:
    query = " ".join(str(value or "").split())
    if not 1 <= len(query) <= 120: raise ValueError("Enter something to search for.")
    return query


def clean_url(value) -> str:
    url = str(value or "").strip()
    if not TRACK_URL.fullmatch(url): raise ValueError("That is not a SoundCloud link.")
    return url


def clean_profile(value) -> str:
    name = str(value or "").strip().strip("/").rsplit("/", 1)[-1]
    if not PROFILE.fullmatch(name): raise ValueError("Enter a SoundCloud profile name, such as the part after soundcloud.com/.")
    return name


ART_SIZE = re.compile(r"-(?:large|small|badge|tiny|crop|original|t\d+x\d+)(\.[A-Za-z]+)$")


def art_url(url, size="t200x200") -> str:
    """SoundCloud cover links carry their size in the name; pick a small one for lists and a big one for Now Playing."""
    url = str(url or "")
    if not url.startswith("https://"): return ""
    return ART_SIZE.sub("-%s\\1" % size, url, count=1)


_COVERS: dict = {}


def oembed_cover(url) -> str:
    """SoundCloud's public oEmbed answer carries a cover even when yt-dlp's quick listing has none."""
    if url in _COVERS: return _COVERS[url]
    cover = ""
    try:
        request = urllib.request.Request("https://soundcloud.com/oembed?format=json&url=" + urllib.parse.quote(url, safe=""), headers={"User-Agent": "RoonDeck"})
        with urllib.request.urlopen(request, timeout=5) as response: cover = str(json.loads(response.read(200_000)).get("thumbnail_url") or "")
    except (OSError, ValueError): pass
    if len(_COVERS) > 2000: _COVERS.clear()
    _COVERS[url] = cover
    return cover


def add_covers(items, budget=6.0):
    """Give every listed track a small cover, in parallel, without holding the list up for long."""
    missing = [item for item in items if not item.get("artwork")]
    if not missing: return items
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(oembed_cover, item["url"]): item for item in missing}
        done, _ = concurrent.futures.wait(futures, timeout=budget)
        for future in done:
            try: futures[future]["artwork"] = art_url(future.result())
            except Exception: pass
    return items


def parse_entries(output: str) -> list[dict]:
    """Turn yt-dlp's flat listing (one JSON object per line, or one playlist object) into track dictionaries."""
    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"): continue
        try: item = json.loads(line)
        except ValueError: continue
        found = item.get("entries") if isinstance(item.get("entries"), list) else [item]
        for entry in found:
            if not isinstance(entry, dict): continue
            url = str(entry.get("webpage_url") or entry.get("url") or "")
            if not TRACK_URL.fullmatch(url): continue
            thumbs = entry.get("thumbnails") or []
            art = str(entry.get("thumbnail") or (thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else "") or "")
            entries.append({"url": url, "title": str(entry.get("title") or "Untitled")[:200],
                            "artist": str(entry.get("uploader") or entry.get("channel") or "")[:120],
                            "duration": int(entry.get("duration") or 0), "artwork": art_url(art)})
    return entries


_CACHE: dict = {}
CACHE_SECONDS = 600


def run_ytdlp(arguments: list[str], timeout: int = 40, cache_key=None) -> list[dict]:
    """Run yt-dlp. Answers are kept for ten minutes, and if SoundCloud fails the last good answer is still shown."""
    now = time.monotonic()
    cached = _CACHE.get(cache_key) if cache_key else None
    if cached and now - cached[0] < CACHE_SECONDS: return cached[1]
    try:
        entries = _run_ytdlp(arguments, timeout)
    except RuntimeError:
        if cached: return cached[1]
        raise
    if cache_key and entries: _CACHE[cache_key] = (now, entries)
    return entries


def _run_ytdlp(arguments: list[str], timeout: int) -> list[dict]:
    try:
        result = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", "--ignore-errors", *arguments],
                                capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error: raise RuntimeError("yt-dlp is not installed.") from error
    except subprocess.TimeoutExpired as error: raise RuntimeError("SoundCloud took too long to answer.") from error
    entries = parse_entries(result.stdout)
    if result.returncode != 0:
        print("yt-dlp exit %s: %s" % (result.returncode, (result.stderr or "").strip()[-400:]), flush=True)   # appears in the service's log
    if not entries and result.returncode != 0: raise RuntimeError("SoundCloud could not be reached. If this keeps happening yt-dlp may need updating.")
    return entries


def search(query, limit=20) -> list[dict]:
    query = clean_query(query); count = max(1, min(int(limit), 30))
    return add_covers(run_ytdlp(["--", "scsearch%d:%s" % (count, query)], cache_key=("search", query.lower(), count)))


_CLIENT = {"id": "", "at": 0.0}
API = "https://api-v2.soundcloud.com"


def fetch_text(url, limit=3_000_000, timeout=12):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) RoonDeck", "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response: return response.read(limit).decode("utf-8", "replace")


def client_id():
    """The public client id SoundCloud's own web player uses, found in its scripts (yt-dlp does the same). Kept for an hour."""
    if _CLIENT["id"] and time.monotonic() - _CLIENT["at"] < 3600: return _CLIENT["id"]
    page = fetch_text("https://soundcloud.com/", 2_000_000)
    for source in reversed(re.findall(r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', page)):
        try: found = re.search(r'client_id\s*[:=]\s*"([A-Za-z0-9]{32})"', fetch_text(source))
        except OSError: continue
        if found:
            _CLIENT["id"] = found.group(1); _CLIENT["at"] = time.monotonic(); return _CLIENT["id"]
    raise RuntimeError("SoundCloud's web player could not be read.")


def api_get(path, **params):
    query = urllib.parse.urlencode({**params, "client_id": client_id()})
    try: return json.loads(fetch_text(API + path + "?" + query, 4_000_000))
    except urllib.error.HTTPError as error:
        if error.code == 401: _CLIENT["id"] = ""   # the id was rotated: look it up again next time
        raise


def tracks_from_api(collection, wrapper="track") -> list[dict]:
    items = []
    for entry in collection or []:
        track = entry.get(wrapper) if isinstance(entry, dict) and isinstance(entry.get(wrapper), dict) else entry
        if not isinstance(track, dict): continue
        url = str(track.get("permalink_url") or "")
        if not TRACK_URL.fullmatch(url) or track.get("kind", "track") != "track": continue
        user = track.get("user") if isinstance(track.get("user"), dict) else {}
        art = str(track.get("artwork_url") or user.get("avatar_url") or "")
        items.append({"url": url, "title": str(track.get("title") or "Untitled")[:200], "artist": str(user.get("username") or "")[:120],
                      "duration": int((track.get("full_duration") or track.get("duration") or 0) / 1000), "artwork": art_url(art)})
    return items


def likes_via_api(name, count) -> list[dict]:
    try:
        user = api_get("/resolve", url="https://soundcloud.com/" + name)
        data = api_get("/users/%d/likes" % int(user["id"]), limit=count)
    except urllib.error.HTTPError as error:
        raise RuntimeError("There is no SoundCloud profile called “%s”. Use the part of your profile link after soundcloud.com/." % name if error.code == 404 else "SoundCloud refused the request (%s)." % error.code) from error
    except (OSError, ValueError, KeyError, TypeError) as error: raise RuntimeError("SoundCloud could not be reached.") from error
    return tracks_from_api(data.get("collection"))


def browse(profile, kind="likes", limit=50) -> list[dict]:
    if kind not in KINDS: raise ValueError("Choose tracks, likes, reposts or playlists.")
    name = clean_profile(profile); count = max(1, min(int(limit), 100))
    if kind == "likes":
        key = ("browse", name, kind, count); cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS: return cached[1]
        try: items = likes_via_api(name, count)
        except RuntimeError as error:
            print("SoundCloud likes via the API failed (%s); trying yt-dlp." % error, flush=True)
            if "no SoundCloud profile" in str(error): raise
        else:
            if items: _CACHE[key] = (time.monotonic(), items)
            return add_covers(items)
    return add_covers(run_ytdlp(["--playlist-end", str(count), "--", "https://soundcloud.com/%s/%s" % (name, KINDS[kind])], timeout=60, cache_key=("browse", name, kind, count)))


def tracks_of(url, limit=100) -> list[dict]:
    """The tracks inside a playlist (or any SoundCloud link that lists tracks)."""
    url = clean_url(url)
    return add_covers(run_ytdlp(["--playlist-end", str(max(1, min(int(limit), 200))), "--", url], timeout=60, cache_key=("tracks", url)))


def roon_get(path):
    with urllib.request.urlopen(ROON + path, timeout=1.5) as response: return json.loads(response.read(1_000_000) or b"{}")


def roon_playing() -> bool:
    try: return ((roon_get("/api/state").get("zone") or {}).get("state")) == "playing"
    except (OSError, ValueError): return False


def pause_roon():
    """Free the DAC before SoundCloud starts. Failure to reach Roon is not an error: it may simply not be running."""
    try:
        request = urllib.request.Request(ROON + "/api/control", data=json.dumps({"action": "pause"}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=2).read()
    except (OSError, ValueError): pass


def sound_cards(path="/proc/asound/cards"):
    """The Pi's sound cards as mpv device names. Roon Bridge and the audio board pick a card by hand; mpv's default is
    often HDMI, which is silent on a DAC, so SoundCloud chooses the DAC (a HAT or USB card) unless told otherwise."""
    try: lines = Path(path).read_text().splitlines()
    except OSError: return []
    cards = []
    for line in lines:
        match = re.match(r"^\s*(\d+)\s+\[([^\]]+?)\s*\]:\s*(.*)$", line)
        if match: cards.append({"index": int(match.group(1)), "id": match.group(2), "kind": match.group(3).strip(), "name": match.group(3).strip()})
        elif cards and line.strip(): cards[-1]["name"] = line.strip()
    for card in cards:
        text = (card["id"] + " " + card["kind"] + " " + card["name"]).lower()
        card["rank"] = 0 if "hdmi" in text else 1 if "headphones" in text or "bcm2835" in text else -1 if "loopback" in text or "dummy" in text else 2
        card["device"] = "alsa/hw:CARD=%s,DEV=0" % card["id"]   # straight to the DAC: no ALSA mixing or resampling in between
    return cards


def best_output(cards=None):
    cards = sound_cards() if cards is None else cards
    usable = [card for card in cards if card["rank"] >= 0]
    return max(usable, key=lambda card: (card["rank"], -card["index"]))["device"] if usable else ""


class Player:
    def __init__(self):
        self.lock = threading.RLock(); self.queue: list[dict] = []; self.index = -1
        self.process = None; self.generation = 0; self.paused = False; self.error = ""
        self.device = ""; self.profile = ""; self.shared_output = False; self.started = 0.0; self.parked = None; self.pause_token = 0; self.load_settings()

    # ---- settings ------------------------------------------------------------------------------------------------
    def load_settings(self):
        try: data = json.loads((STATE_DIR / "soundcloud.json").read_text())
        except (OSError, ValueError): data = {}
        self.profile = data.get("profile", "") if PROFILE.fullmatch(str(data.get("profile", ""))) else ""
        self.device = str(data.get("audio_device", ""))[:80] if re.fullmatch(r"[A-Za-z0-9_:=,./-]{0,80}", str(data.get("audio_device", ""))) else ""

    def save_settings(self, profile=None, audio_device=None):
        with self.lock:
            if profile is not None: self.profile = clean_profile(profile) if str(profile).strip() else ""
            if audio_device is not None:
                if not re.fullmatch(r"[A-Za-z0-9_:=,./-]{0,80}", str(audio_device)): raise ValueError("That audio device name is not valid.")
                self.device = str(audio_device)
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "soundcloud.json").write_text(json.dumps({"profile": self.profile, "audio_device": self.device}))

    # ---- mpv -----------------------------------------------------------------------------------------------------
    def ipc(self, *command):
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(1.0); client.connect(IPC_SOCKET)
                client.sendall((json.dumps({"command": list(command)}) + "\n").encode())
                buffer = b""
                while b"\n" not in buffer:
                    chunk = client.recv(4096)
                    if not chunk: break
                    buffer += chunk
            for line in buffer.splitlines():
                reply = json.loads(line)
                if "error" in reply: return reply.get("data") if reply["error"] == "success" else None
        except (OSError, ValueError): return None
        return None

    def stop_process(self):
        process, self.process = self.process, None
        self.generation += 1
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(2)
            except subprocess.TimeoutExpired: process.kill()

    def spawn(self, url, start=0):
        # Bit-perfect as far as SoundCloud allows: ALSA output at full software volume (the DAC or amp sets the level),
        # no replay gain or normalising, and the best audio stream SoundCloud offers.
        command = ["mpv", "--no-video", "--no-terminal", "--audio-display=no", "--idle=no", "--msg-level=all=warn", "--input-ipc-server=" + IPC_SOCKET,
                   "--ao=alsa", "--volume=100", "--volume-max=100", "--replaygain=no", "--audio-normalize-downmix=no", "--ytdl-format=bestaudio/best"]
        device = self.device or best_output()
        if device and self.shared_output: device = device.replace("alsa/hw:", "alsa/plughw:")   # the DAC refused the direct format
        if device: command.append("--audio-device=" + device)
        self.started = time.monotonic()
        print("SoundCloud playing on %s: %s" % (device or "mpv's default output", url), flush=True)
        if start > 0: command.append("--start=%d" % int(start))
        command += ["--", url]
        try: Path(IPC_SOCKET).unlink(missing_ok=True)
        except OSError: pass
        return subprocess.Popen(command, stdout=subprocess.DEVNULL)   # mpv's warnings (a busy or missing device) go to the service log

    def watch(self, process, generation):
        code = process.wait()
        with self.lock:
            if generation != self.generation: return   # we stopped or replaced it ourselves
            self.process = None
            if code == 0 and self.index + 1 < len(self.queue): self.play_index(self.index + 1)
            elif code != 0:
                device = self.device or best_output()
                if "alsa/hw:" in device and not self.shared_output and time.monotonic() - self.started < 6:
                    self.shared_output = True; print("The DAC refused a direct stream; falling back to ALSA's converting output.", flush=True); self.play_index(self.index); return
                self.error = "That track could not be played."; self.paused = False

    # ---- transport -----------------------------------------------------------------------------------------------
    def play(self, items, index=0):
        with self.lock:
            tracks = [{**item, "url": clean_url(item.get("url"))} for item in (items or [])][:200]
            if not tracks: raise ValueError("Nothing to play.")
            self.queue = tracks; self.play_index(max(0, min(int(index), len(tracks) - 1)))

    def fill_artwork(self, index):
        """A larger cover for the Now Playing screen."""
        try:
            item = self.queue[index]; cover = oembed_cover(item["url"])
            if cover: item["cover"] = art_url(cover, "t500x500")
        except (IndexError, KeyError): pass

    def play_index(self, index, start=0):
        with self.lock:
            self.stop_process(); self.index = index; self.error = ""; self.paused = False; self.parked = None
            pause_roon()
            try: process = self.spawn(self.queue[index]["url"], start)
            except FileNotFoundError: self.error = "mpv is not installed."; return
            self.process = process
            threading.Thread(target=self.fill_artwork, args=(index,), daemon=True).start()
            threading.Thread(target=self.watch, args=(process, self.generation), daemon=True).start()

    def running(self): return bool(self.process and self.process.poll() is None)

    def pause(self, value=None):
        with self.lock:
            if self.parked is not None:   # waiting with the DAC released: pressing play carries on where it stopped
                if value is None or not value:
                    parked, self.parked = self.parked, None; self.play_index(parked["index"], parked["position"])
                return
            if not self.running(): return
            self.paused = (not self.paused) if value is None else bool(value)
            self.ipc("set_property", "pause", self.paused); self.pause_token += 1
            if not self.paused: pause_roon()
            else: threading.Timer(PARK_SECONDS, self.park_if_still_paused, args=(self.pause_token,)).start()

    def park_if_still_paused(self, token):
        with self.lock:
            if token == self.pause_token and self.running() and self.paused: self.park()

    def park(self):
        """Let go of the DAC but remember the track and position. A paused mpv still holds an ALSA device, which would
        leave Roon without sound, so a paused or interrupted track waits as a bookmark and restarts from it on play."""
        with self.lock:
            if not self.running() or not 0 <= self.index < len(self.queue): return
            position = self.ipc("get_property", "time-pos")
            self.parked = {"index": self.index, "position": int(position or 0)}; self.stop_process(); self.paused = True

    def step(self, amount):
        with self.lock:
            target = self.index + amount
            if 0 <= target < len(self.queue): self.play_index(target)

    def stop(self):
        with self.lock: self.stop_process(); self.paused = False; self.parked = None

    def skip(self, seconds):
        """Jump backwards or forwards by a fixed amount, handy for finding your place in a long mix."""
        seconds = max(-600, min(600, int(float(seconds))))
        with self.lock:
            if self.parked is not None: self.parked["position"] = max(0, self.parked["position"] + seconds)
            elif self.running(): self.ipc("seek", seconds, "relative")

    def seek(self, position):
        with self.lock:
            if self.parked is not None: self.parked["position"] = max(0, int(float(position)))
            elif self.running(): self.ipc("set_property", "time-pos", max(0, float(position)))

    def stream_format(self):
        """What is really playing, e.g. "AAC · 256 kbps · 44.1 kHz": the codec and rate mpv decoded and the rate it sent to the DAC."""
        codec = self.ipc("get_property", "audio-codec-name"); bitrate = self.ipc("get_property", "audio-bitrate")
        if not isinstance(bitrate, (int, float)) or bitrate <= 0:   # streamed (HLS) audio reports its rate on the track instead
            for entry in self.ipc("get_property", "track-list") or []:
                if isinstance(entry, dict) and entry.get("type") == "audio" and entry.get("selected"): bitrate = entry.get("hls-bitrate") or entry.get("demux-bitrate"); break
        source = self.ipc("get_property", "audio-params") or {}; out = self.ipc("get_property", "audio-out-params") or {}
        parts = []
        if codec: parts.append(str(codec).upper())
        if isinstance(bitrate, (int, float)) and bitrate > 0: parts.append("%d kbps" % round(bitrate / 1000 if bitrate >= 1000 else bitrate))
        rate = source.get("samplerate") if isinstance(source, dict) else None
        if rate: parts.append("%g kHz" % (rate / 1000))
        if isinstance(out, dict) and rate and out.get("samplerate") and out["samplerate"] != rate: parts.append("resampled to %g kHz" % (out["samplerate"] / 1000))
        return " · ".join(parts)

    def state(self):
        with self.lock:
            running = self.running(); track = self.queue[self.index] if running and 0 <= self.index < len(self.queue) else None
            position = duration = None; stream = ""
            if not running and self.parked is not None and 0 <= self.parked["index"] < len(self.queue):
                track = self.queue[self.parked["index"]]
                return {"active": True, "paused": True, "parked": True, "track": track, "index": self.parked["index"], "queue": len(self.queue),
                        "position": self.parked["position"], "duration": int(track.get("duration") or 0), "error": self.error, "profile": self.profile,
                        "audio_device": self.device, "audio_chosen": self.device or best_output(), "stream": "", "direct": False}
            if running:
                position = self.ipc("get_property", "time-pos"); duration = self.ipc("get_property", "duration"); stream = self.stream_format()
            return {"active": running, "paused": self.paused if running else False, "track": track, "index": self.index if running else -1,
                    "queue": len(self.queue), "position": int(position or 0), "duration": int(duration or (track or {}).get("duration") or 0),
                    "error": self.error, "profile": self.profile, "audio_device": self.device, "audio_chosen": self.device or best_output(), "stream": stream, "direct": "alsa/hw:" in (self.device or best_output()) and not self.shared_output}

    def yield_to_roon(self):
        """Roon started playing: the DAC belongs to it now."""
        while True:
            time.sleep(2)
            if self.running() and roon_playing(): self.park()   # keep the track and position, free the DAC


player = Player()


class Handler(BaseHTTPRequestHandler):
    server_version = "RoonDeckSoundCloud"

    def log_message(self, *_): pass

    def send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/state": return self.send(200, player.state())
        if self.path == "/outputs": return self.send(200, {"outputs": sound_cards(), "chosen": player.device or best_output()})
        self.send(404, {"error": "Not found"})

    def do_POST(self):
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 200_000)
            data = json.loads(self.rfile.read(length) or b"{}")
            path = self.path
            if path == "/search": return self.send(200, {"items": search(data.get("query"), data.get("limit", 20))})
            if path == "/browse": return self.send(200, {"items": browse(data.get("profile") or player.profile, data.get("kind", "likes"), data.get("limit", 50))})
            if path == "/tracks": return self.send(200, {"items": tracks_of(data.get("url"))})
            if path == "/play": player.play(data.get("items"), data.get("index", 0))
            elif path == "/pause": player.pause(data.get("paused"))
            elif path == "/next": player.step(1)
            elif path == "/previous": player.step(-1)
            elif path == "/stop": player.stop()
            elif path == "/seek": player.seek(data.get("position", 0))
            elif path == "/skip": player.skip(data.get("seconds", 0))
            elif path == "/settings": player.save_settings(data.get("profile"), data.get("audio_device"))
            else: return self.send(404, {"error": "Not found"})
            self.send(200, {"ok": True, **player.state()})
        except (ValueError, TypeError) as error: self.send(400, {"error": str(error)})
        except RuntimeError as error: self.send(502, {"error": str(error)})


def main():
    threading.Thread(target=player.yield_to_roon, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
