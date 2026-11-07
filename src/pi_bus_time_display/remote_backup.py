"""Scheduled backups to a WebDAV folder (for example a Synology NAS)."""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .backup import build_backup

SECRET = "BACKUP_WEBDAV_PASSWORD"
GOOGLE_SECRET = "GOOGLE_BACKUP_CLIENT_SECRET"
GOOGLE_TOKEN = "GOOGLE_BACKUP_REFRESH_TOKEN"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.file"
NAME = re.compile(r"roondeck-backup-\d{4}-\d{2}-\d{2}(?:-\d{4})?\.json")
DEFAULT = {"google_enabled": False, "google_client_id": "", "google_folder": "RoonDeck", "enabled": False, "url": "", "folder": "RoonDeck", "username": "", "verify_tls": True, "keep": 14, "time": "03:30"}


def load_target(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULT, **{key: data[key] for key in DEFAULT if key in data}}


def validate_target(data) -> dict:
    if not isinstance(data, dict): raise ValueError("Backup settings must be an object")
    target = {**DEFAULT, **{key: data[key] for key in DEFAULT if key in data}}
    target["enabled"] = target["enabled"] is True
    target["google_enabled"] = target["google_enabled"] is True
    target["google_client_id"] = str(target["google_client_id"]).strip()[:200]
    target["google_folder"] = str(target["google_folder"]).strip() or "RoonDeck"
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,60}", target["google_folder"]): raise ValueError("Use letters, numbers, spaces, dots and dashes for the Google Drive folder")
    if target["google_enabled"] and not re.fullmatch(r"[A-Za-z0-9._-]+\.apps\.googleusercontent\.com", target["google_client_id"]): raise ValueError("Enter the Google client ID, which ends in .apps.googleusercontent.com")
    target["verify_tls"] = target["verify_tls"] is not False
    url = str(target["url"]).strip().rstrip("/")
    if target["enabled"] or url:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.query or parts.fragment:
            raise ValueError("Enter the WebDAV address, for example http://synology.local:5005")
    target["url"] = url
    folder = str(target["folder"]).strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,60}(?:/[A-Za-z0-9 ._-]{1,60}){0,3}", folder or "x") or ".." in folder.split("/"):
        raise ValueError("Use letters, numbers, spaces, dots, dashes and slashes for the folder")
    target["folder"] = folder or "RoonDeck"
    target["username"] = str(target["username"]).strip()[:100]
    if target["enabled"] and not target["username"]: raise ValueError("Enter the NAS username")
    if type(target["keep"]) is not int or not 1 <= target["keep"] <= 60: raise ValueError("Keep between 1 and 60 backups")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(target["time"])): raise ValueError("Use HH:MM for the backup time")
    return target


def save_target(path: Path, data) -> dict:
    target = validate_target(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".backup-target-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle: json.dump(target, handle)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return target


class WebDav:
    def __init__(self, target: dict, password: str):
        self.base = target["url"].rstrip("/") + "/" + "/".join(urllib.parse.quote(part) for part in target["folder"].split("/"))
        self.root = target["url"].rstrip("/")
        token = base64.b64encode(f'{target["username"]}:{password}'.encode()).decode()
        self.headers = {"Authorization": "Basic " + token}
        self.context = None
        if target["url"].startswith("https") and not target["verify_tls"]:
            self.context = ssl.create_default_context(); self.context.check_hostname = False; self.context.verify_mode = ssl.CERT_NONE

    def request(self, method, url, body=None, headers=None):
        request = urllib.request.Request(url, data=body, method=method, headers={**self.headers, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=30, context=self.context) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def ensure_folder(self, folder: str):
        url = self.root
        for part in folder.split("/"):
            url += "/" + urllib.parse.quote(part)
            status, _ = self.request("MKCOL", url)
            if status in (401, 403) : raise ValueError("The NAS refused the username or password" if status == 401 else "The NAS does not allow creating that folder")
            if status not in (201, 301, 405): raise ValueError(f"The NAS could not create the folder (error {status})")

    def put(self, name: str, data: bytes):
        status, _ = self.request("PUT", f"{self.base}/{name}", data, {"Content-Type": "application/json"})
        if status == 401: raise ValueError("The NAS refused the username or password")
        if status not in (200, 201, 204): raise ValueError(f"The NAS did not accept the file (error {status})")

    def names(self) -> list[str]:
        status, body = self.request("PROPFIND", self.base + "/", None, {"Depth": "1", "Content-Type": "application/xml"})
        if status not in (200, 207): return []
        found = []
        for node in ET.fromstring(body).iter("{DAV:}href"):
            name = urllib.parse.unquote(node.text or "").rstrip("/").rsplit("/", 1)[-1]
            if NAME.fullmatch(name): found.append(name)
        return sorted(found)

    def delete(self, name: str):
        self.request("DELETE", f"{self.base}/{urllib.parse.quote(name)}")


def run_backup(target: dict, password: str, config_path: Path, state_dir: Path, env_path: Path, version: str, now=None) -> str:
    """Upload one backup and delete the oldest beyond the keep limit. Returns the file name."""
    if not target["url"]: raise ValueError("Enter the NAS address first")
    if not password: raise ValueError("Enter the NAS password")
    stamp = time.strftime("%Y-%m-%d-%H%M", now or time.localtime())
    name = f"roondeck-backup-{stamp}.json"
    payload = json.dumps(build_backup(config_path, state_dir, env_path, version, False)).encode()
    try:
        client = WebDav(target, password)
        client.ensure_folder(target["folder"])
        client.put(name, payload)
        existing = client.names()
        for old in existing[:-target["keep"]]:
            if old != name: client.delete(old)
    except (OSError, urllib.error.URLError, ET.ParseError) as error:
        raise ValueError(f"Could not reach the NAS: {getattr(error, 'reason', error)}") from None
    return name


def write_status(path: Path, ok: bool, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ok": ok, "message": message, "time": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")


def schedule(state_dir: Path, config_path: Path, env_path: Path, version: str, stop) -> None:
    """Background loop: back up once a day at the chosen time, retrying hourly after a failure."""
    last_day, retry_after = "", 0.0
    while not stop.wait(30):
        target = load_target(state_dir / "backup-target.json")
        if not (target["enabled"] or target["google_enabled"]): continue
        now = time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        if today == last_day or time.strftime("%H:%M", now) < target["time"] or time.time() < retry_after: continue
        saved, errors = run_all(target, state_dir, config_path, env_path, version)
        write_status(state_dir / "backup-status.json", not errors, "; ".join(saved + errors))
        if errors: retry_after = time.time() + 3600
        else: last_day = today


def _http(method, url, headers=None, body=None):
    """Plain HTTPS request returning (status, parsed JSON or {})."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    try: return status, json.loads(raw or b"{}")
    except ValueError: return status, {}


def _form(data: dict) -> bytes:
    return urllib.parse.urlencode(data).encode()


def google_start(client_id: str) -> dict:
    status, data = _http("POST", "https://oauth2.googleapis.com/device/code", {"Content-Type": "application/x-www-form-urlencoded"}, _form({"client_id": client_id, "scope": GOOGLE_SCOPE}))
    if status != 200 or "device_code" not in data:
        raise ValueError("Google did not accept that client ID. Create it as a TV and Limited Input client." if data.get("error") else "Could not reach Google")
    return data


def google_poll(client_id: str, client_secret: str, device_code: str) -> str:
    """Returns the refresh token, '' while waiting. Raises ValueError if refused or expired."""
    status, data = _http("POST", "https://oauth2.googleapis.com/token", {"Content-Type": "application/x-www-form-urlencoded"},
                         _form({"client_id": client_id, "client_secret": client_secret, "device_code": device_code, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}))
    if data.get("refresh_token"): return data["refresh_token"]
    if data.get("error") in {"authorization_pending", "slow_down"}: return ""
    raise ValueError("Google sign-in was refused or timed out. Start again." if data.get("error") in {"access_denied", "expired_token"} else "Google did not accept the client ID and secret")


class Drive:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        status, data = _http("POST", "https://oauth2.googleapis.com/token", {"Content-Type": "application/x-www-form-urlencoded"},
                             _form({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}))
        if "access_token" not in data: raise ValueError("Google Drive sign-in has expired. Connect Google Drive again.")
        self.auth = {"Authorization": "Bearer " + data["access_token"]}

    def call(self, method, url, body=None, content_type="application/json"):
        headers = {**self.auth, **({"Content-Type": content_type} if body is not None else {})}
        status, data = _http(method, url, headers, body)
        if status == 401: raise ValueError("Google Drive refused the sign-in. Connect Google Drive again.")
        if status >= 400: raise ValueError(f"Google Drive error {status}")
        return data

    def folder(self, name: str) -> str:
        query = urllib.parse.quote(f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false")
        found = self.call("GET", f"https://www.googleapis.com/drive/v3/files?q={query}&fields=files(id)&pageSize=1").get("files", [])
        if found: return found[0]["id"]
        return self.call("POST", "https://www.googleapis.com/drive/v3/files?fields=id", json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder"}).encode())["id"]

    def upload(self, folder_id: str, name: str, data: bytes):
        boundary = "roondeck" + str(int(time.time() * 1000))
        meta = json.dumps({"name": name, "parents": [folder_id]})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n").encode() + data + f"\r\n--{boundary}--".encode()
        self.call("POST", "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", body, f"multipart/related; boundary={boundary}")

    def names(self, folder_id: str) -> list[tuple[str, str]]:
        query = urllib.parse.quote(f"'{folder_id}' in parents and trashed=false")
        files = self.call("GET", f"https://www.googleapis.com/drive/v3/files?q={query}&fields=files(id,name)&pageSize=200").get("files", [])
        return sorted((item["name"], item["id"]) for item in files if NAME.fullmatch(item.get("name", "")))


def run_google(target: dict, client_secret: str, refresh_token: str, config_path: Path, state_dir: Path, env_path: Path, version: str, now=None) -> str:
    if not refresh_token: raise ValueError("Connect Google Drive first")
    name = f"roondeck-backup-{time.strftime('%Y-%m-%d-%H%M', now or time.localtime())}.json"
    payload = json.dumps(build_backup(config_path, state_dir, env_path, version, False)).encode()
    try:
        drive = Drive(target["google_client_id"], client_secret, refresh_token)
        folder_id = drive.folder(target["google_folder"])
        drive.upload(folder_id, name, payload)
        for old, file_id in drive.names(folder_id)[:-target["keep"]]:
            if old != name: drive.call("DELETE", f"https://www.googleapis.com/drive/v3/files/{file_id}")
    except (OSError, urllib.error.URLError) as error:
        raise ValueError(f"Could not reach Google Drive: {getattr(error, 'reason', error)}") from None
    return name


def run_all(target: dict, state_dir: Path, config_path: Path, env_path: Path, version: str, which=None) -> tuple[list[str], list[str]]:
    """Run each wanted destination. Returns (saved messages, error messages)."""
    saved, errors = [], []
    if which in (None, "synology") and (target["enabled"] or which == "synology"):
        try: saved.append("Synology: " + run_backup(target, os.getenv(SECRET, ""), config_path, state_dir, env_path, version))
        except ValueError as error: errors.append(f"Synology: {error}")
    if which in (None, "google") and (target["google_enabled"] or which == "google"):
        try: saved.append("Google Drive: " + run_google(target, os.getenv(GOOGLE_SECRET, ""), os.getenv(GOOGLE_TOKEN, ""), config_path, state_dir, env_path, version))
        except ValueError as error: errors.append(f"Google Drive: {error}")
    return saved, errors
