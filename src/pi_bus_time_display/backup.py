"""Backup and restore of RoonDeck settings as one downloadable file."""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
import tomllib
from pathlib import Path

from .config import load_config
from .home_layout import validate_layout
from .listening import validate_settings

FORMAT = "roondeck-backup"
ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,78}\.png")
SECRET_KEYS = ("LTA_ACCOUNT_KEY", "HOME_ASSISTANT_TOKEN", "OPENOBSERVE_PASSWORD", "BACKUP_WEBDAV_PASSWORD", "GOOGLE_BACKUP_CLIENT_SECRET", "GOOGLE_BACKUP_REFRESH_TOKEN")
MAX_ART = 200
MAX_ART_BYTES = 1_500_000
PNG = b"\x89PNG\r\n\x1a\n"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip()
    return values


def build_backup(config_path: Path, state_dir: Path, env_path: Path, version: str, include_secrets: bool = False) -> dict:
    files: dict[str, str] = {}
    for name in ("listening.json", "home-layout.json"):
        target = state_dir / name
        if target.is_file():
            files[name] = target.read_text(encoding="utf-8")
    art: dict[str, str] = {}
    folder = state_dir / "deck-art"
    if folder.is_dir():
        for item in sorted(folder.glob("*.png"))[:MAX_ART]:
            if item.is_file() and ART_NAME.fullmatch(item.name) and item.stat().st_size <= MAX_ART_BYTES:
                art[item.name] = base64.b64encode(item.read_bytes()).decode("ascii")
    bundle = {"format": FORMAT, "version": 1, "app_version": version,
              "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "config": config_path.read_text(encoding="utf-8") if config_path.is_file() else "",
              "files": files, "art": art, "includes_secrets": bool(include_secrets)}
    if include_secrets:
        env = _read_env(env_path)
        bundle["secrets"] = {key: env[key] for key in SECRET_KEYS if env.get(key)}
    return bundle


def check_backup(bundle) -> dict:
    """Validate everything before anything on disk is touched. Returns the checked parts."""
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT or bundle.get("version") != 1:
        raise ValueError("That is not a RoonDeck backup file")
    config = bundle.get("config", "")
    if not isinstance(config, str) or len(config) > 100_000:
        raise ValueError("The backup's settings are not valid")
    if config:
        tomllib.loads(config)
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "config.toml"
            probe.write_text(config, encoding="utf-8")
            load_config(probe)
    files = bundle.get("files", {})
    if not isinstance(files, dict) or set(files) - {"listening.json", "home-layout.json"}:
        raise ValueError("The backup contains unexpected files")
    parsed = {}
    for name, text in files.items():
        if not isinstance(text, str) or len(text) > 300_000: raise ValueError(f"{name} is not valid")
        data = json.loads(text)
        if name == "listening.json": validate_settings(data)
        else: validate_layout(data)
        parsed[name] = text
    art = bundle.get("art", {})
    if not isinstance(art, dict) or len(art) > MAX_ART: raise ValueError("The backup has too many images")
    images = {}
    for name, encoded in art.items():
        if not isinstance(name, str) or not ART_NAME.fullmatch(name) or not isinstance(encoded, str): raise ValueError("The backup has an invalid image name")
        raw = base64.b64decode(encoded, validate=True)
        if not raw.startswith(PNG) or len(raw) > MAX_ART_BYTES: raise ValueError(f"Image {name} is not a valid PNG")
        images[name] = raw
    secrets = bundle.get("secrets", {})
    if not isinstance(secrets, dict) or set(secrets) - set(SECRET_KEYS) or any(not isinstance(v, str) or "\n" in v or "\r" in v or len(v) > 4000 for v in secrets.values()):
        raise ValueError("The backup's saved passwords are not valid")
    return {"config": config, "files": parsed, "art": images, "secrets": secrets}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".restore-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle: handle.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def restore_backup(checked: dict, config_path: Path, state_dir: Path) -> None:
    if checked["config"]: _write(config_path, checked["config"].encode("utf-8"))
    for name, text in checked["files"].items(): _write(state_dir / name, text.encode("utf-8"))
    for name, raw in checked["art"].items(): _write(state_dir / "deck-art" / name, raw)
