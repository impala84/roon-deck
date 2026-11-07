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
NAME = re.compile(r"roondeck-backup-\d{4}-\d{2}-\d{2}(?:-\d{4})?\.json")
DEFAULT = {"enabled": False, "url": "", "folder": "RoonDeck", "username": "", "verify_tls": True, "keep": 14, "time": "03:30"}


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
        if not target["enabled"]: continue
        now = time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        if today == last_day or time.strftime("%H:%M", now) < target["time"] or time.time() < retry_after: continue
        try:
            name = run_backup(target, os.getenv(SECRET, ""), config_path, state_dir, env_path, version)
            write_status(state_dir / "backup-status.json", True, f"Saved {name}"); last_day = today
        except (ValueError, OSError) as error:
            write_status(state_dir / "backup-status.json", False, str(error)); retry_after = time.time() + 3600
