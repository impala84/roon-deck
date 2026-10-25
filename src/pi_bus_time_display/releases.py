"""Published GitHub releases are the single authority for update channels.

Also executable with system Python before the installed package is upgraded.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
import tomllib
import urllib.request
from functools import total_ordering
from pathlib import Path

REPOSITORY = "impala84/roon-deck"
VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")


@total_ordering
class SemVer:
    def __init__(self, value: str):
        match = VERSION.fullmatch(value)
        if not match:
            raise ValueError("Invalid semantic version")
        self.core = tuple(int(match[i]) for i in (1, 2, 3))
        self.pre = tuple(match[4].split(".")) if match[4] else ()
        if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in self.pre):
            raise ValueError("Invalid numeric prerelease identifier")

    def __eq__(self, other):
        return isinstance(other, SemVer) and (self.core, self.pre) == (other.core, other.pre)

    def __lt__(self, other):
        if self.core != other.core:
            return self.core < other.core
        if not self.pre or not other.pre:
            return bool(self.pre) and not other.pre
        for left, right in zip(self.pre, other.pre):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.pre) < len(other.pre)


def select_release(releases: list, channel: str, installed: str, distribution: str = "rpi") -> dict:
    if channel not in {"stable", "beta"}:
        raise ValueError("Release channel must be stable or beta")
    if distribution not in {"rpi", "alpine"}:
        raise ValueError("Unknown release distribution")
    current = SemVer(installed)
    candidates = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft"):
            continue
        tag = release.get("tag_name", "")
        # Only normal v-prefixed release tags may reach the updater.
        if not isinstance(tag, str) or not tag.startswith("v"):
            continue
        alpine = tag.endswith("-alpine")
        # Alpine appliances accept "-alpine" tags and, from beta.87, plain tags;
        # the pre-Alpine "rpi" distribution still only sees plain tags.
        if distribution == "rpi" and alpine:
            continue
        version_tag = tag[:-7] if alpine else tag
        try:
            version = SemVer(version_tag)
        except ValueError:
            continue
        if channel == "stable" and (version.pre or release.get("prerelease")):
            continue
        candidates.append((version, tag))
    if not candidates:
        return {"installed_version": installed, "release_channel": channel, "latest_version": None, "update_available": False, "status": "unavailable", "message": "No published release is available for this channel."}
    latest, tag = max(candidates, key=lambda entry: entry[0])
    available = latest > current
    status = "available" if available else "ahead" if latest < current else "current"
    message = "Update available." if available else "Installed version is newer than this channel; no downgrade will be performed." if status == "ahead" else "Up to date."
    return {"installed_version": installed, "release_channel": channel, "latest_version": (tag[:-7] if tag.endswith("-alpine") else tag)[1:], "tag": tag, "update_available": available, "status": status, "message": message}


def published_releases() -> list:
    releases = []
    for page in range(1, 6):
        request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100&page={page}", headers={"Accept": "application/vnd.github+json", "User-Agent": "RoonDeck-Updater"})
        with urllib.request.urlopen(request, timeout=8) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Invalid release catalogue")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise ValueError("Release catalogue exceeds the supported page limit")


class ReleaseChecker:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = {}
        self.checked_at = 0.0

    def check(self, channel: str, installed: str, refresh: bool = False, distribution: str = "rpi") -> dict:
        with self.lock:
            key = (channel, installed, distribution)
            if not refresh and getattr(self, "cache_key", None) == key and time.monotonic() - self.checked_at < 300:
                return dict(self.cached)
            try:
                result = select_release(published_releases(), channel, installed, distribution)
            except (OSError, ValueError):
                result = {"installed_version": installed, "release_channel": channel, "latest_version": None, "update_available": False, "status": "unavailable", "message": "Could not check GitHub releases. Try again later."}
            self.cached = result
            self.cache_key = key
            self.checked_at = time.monotonic()
            return dict(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--installed", required=True)
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text()) if args.config.exists() else {}
    result = select_release(published_releases(), config.get("release_channel", "stable"), args.installed)
    if result["status"] == "unavailable":
        raise SystemExit(result["message"])
    print(result["tag"] if result["update_available"] else "")


if __name__ == "__main__":
    main()
