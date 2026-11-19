"""SoundCloud player for the Pi: yt-dlp finds tracks, mpv plays them on the Pi's own audio output.

This is a small local service (127.0.0.1:8767) used by the touchscreen. It is not connected to Roon. The Pi's DAC can only
play one thing at a time, so SoundCloud and Roon take turns: starting a track pauses the Roon zone, and when Roon starts
playing again this service stops.

Only the standard library is used. yt-dlp and mpv are installed on the appliance from the web admin (SoundCloud tab).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", int(os.getenv("ROONDECK_SOUNDCLOUD_PORT", "8767"))
ROON = os.getenv("ROONDECK_ROON_URL", "http://127.0.0.1:8766")
STATE_DIR = Path(os.getenv("PI_HOME_STATE_DIR", "/var/lib/pi-home"))
IPC_SOCKET = os.getenv("ROONDECK_SOUNDCLOUD_IPC", "/tmp/roondeck-soundcloud-mpv.sock")
TRACK_URL = re.compile(r"^https://(?:www\.|m\.|on\.)?soundcloud\.com/[A-Za-z0-9_./~%?=&-]{1,300}$")
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
                            "duration": int(entry.get("duration") or 0), "artwork": art if art.startswith("https://") else ""})
    return entries


def run_ytdlp(arguments: list[str], timeout: int = 40) -> list[dict]:
    try:
        result = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", "--ignore-errors", *arguments],
                                capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error: raise RuntimeError("yt-dlp is not installed.") from error
    except subprocess.TimeoutExpired as error: raise RuntimeError("SoundCloud took too long to answer.") from error
    entries = parse_entries(result.stdout)
    if not entries and result.returncode != 0: raise RuntimeError("SoundCloud could not be reached. If this keeps happening yt-dlp may need updating.")
    return entries


def search(query, limit=20) -> list[dict]:
    return run_ytdlp(["--", "scsearch%d:%s" % (max(1, min(int(limit), 30)), clean_query(query))])


def browse(profile, kind="likes", limit=50) -> list[dict]:
    if kind not in KINDS: raise ValueError("Choose tracks, likes, reposts or playlists.")
    return run_ytdlp(["--playlist-end", str(max(1, min(int(limit), 100))), "--", "https://soundcloud.com/%s/%s" % (clean_profile(profile), KINDS[kind])], timeout=60)


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


class Player:
    def __init__(self):
        self.lock = threading.RLock(); self.queue: list[dict] = []; self.index = -1
        self.process = None; self.generation = 0; self.paused = False; self.error = ""
        self.device = ""; self.profile = ""; self.load_settings()

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

    def spawn(self, url):
        command = ["mpv", "--no-video", "--no-terminal", "--audio-display=no", "--idle=no", "--really-quiet", "--input-ipc-server=" + IPC_SOCKET]
        if self.device: command.append("--audio-device=" + self.device)
        command += ["--", url]
        try: Path(IPC_SOCKET).unlink(missing_ok=True)
        except OSError: pass
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def watch(self, process, generation):
        code = process.wait()
        with self.lock:
            if generation != self.generation: return   # we stopped or replaced it ourselves
            self.process = None
            if code == 0 and self.index + 1 < len(self.queue): self.play_index(self.index + 1)
            elif code != 0: self.error = "That track could not be played."; self.paused = False

    # ---- transport -----------------------------------------------------------------------------------------------
    def play(self, items, index=0):
        with self.lock:
            tracks = [{**item, "url": clean_url(item.get("url"))} for item in (items or [])][:200]
            if not tracks: raise ValueError("Nothing to play.")
            self.queue = tracks; self.play_index(max(0, min(int(index), len(tracks) - 1)))

    def play_index(self, index):
        with self.lock:
            self.stop_process(); self.index = index; self.error = ""; self.paused = False
            pause_roon()
            try: process = self.spawn(self.queue[index]["url"])
            except FileNotFoundError: self.error = "mpv is not installed."; return
            self.process = process
            threading.Thread(target=self.watch, args=(process, self.generation), daemon=True).start()

    def running(self): return bool(self.process and self.process.poll() is None)

    def pause(self, value=None):
        with self.lock:
            if not self.running(): return
            self.paused = (not self.paused) if value is None else bool(value)
            self.ipc("set_property", "pause", self.paused)
            if not self.paused: pause_roon()

    def step(self, amount):
        with self.lock:
            target = self.index + amount
            if 0 <= target < len(self.queue): self.play_index(target)

    def stop(self):
        with self.lock: self.stop_process(); self.paused = False

    def seek(self, position):
        with self.lock:
            if self.running(): self.ipc("set_property", "time-pos", max(0, float(position)))

    def state(self):
        with self.lock:
            running = self.running(); track = self.queue[self.index] if running and 0 <= self.index < len(self.queue) else None
            position = duration = None
            if running:
                position = self.ipc("get_property", "time-pos"); duration = self.ipc("get_property", "duration")
            return {"active": running, "paused": self.paused if running else False, "track": track, "index": self.index if running else -1,
                    "queue": len(self.queue), "position": int(position or 0), "duration": int(duration or (track or {}).get("duration") or 0),
                    "error": self.error, "profile": self.profile, "audio_device": self.device}

    def yield_to_roon(self):
        """Roon started playing: the DAC belongs to it now."""
        while True:
            time.sleep(2)
            if self.running() and not self.paused and roon_playing(): self.stop()


player = Player()


class Handler(BaseHTTPRequestHandler):
    server_version = "RoonDeckSoundCloud"

    def log_message(self, *_): pass

    def send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/state": return self.send(200, player.state())
        self.send(404, {"error": "Not found"})

    def do_POST(self):
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 200_000)
            data = json.loads(self.rfile.read(length) or b"{}")
            path = self.path
            if path == "/search": return self.send(200, {"items": search(data.get("query"), data.get("limit", 20))})
            if path == "/browse": return self.send(200, {"items": browse(data.get("profile") or player.profile, data.get("kind", "likes"), data.get("limit", 50))})
            if path == "/play": player.play(data.get("items"), data.get("index", 0))
            elif path == "/pause": player.pause(data.get("paused"))
            elif path == "/next": player.step(1)
            elif path == "/previous": player.step(-1)
            elif path == "/stop": player.stop()
            elif path == "/seek": player.seek(data.get("position", 0))
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
