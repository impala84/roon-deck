from __future__ import annotations

import base64
import json
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote, urlsplit

from . import __version__
from .config import Config


class OpenObserveLogger:
    """A bounded, non-blocking OpenObserve event sender."""

    def __init__(self, config: Callable[[], Config], *, max_queue: int = 128):
        self._config = config
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="openobserve", daemon=True)
        self._thread.start()

    def enabled(self) -> bool:
        config = self._config()
        return bool(config.openobserve_enabled and config.openobserve_url)

    def emit(self, event: str, *, level: str = "info", **fields: object) -> bool:
        if not self.enabled():
            return False
        record = self._record(event, level, fields)
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(record)
                return True
            except (queue.Empty, queue.Full):
                return False

    def test(self) -> None:
        self._post([self._record("openobserve.test", "info", {"source": "web_settings"})])

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _record(self, event: str, level: str, fields: dict[str, object]) -> dict:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "service": "roondeck",
            "version": __version__,
            "host": socket.gethostname(),
            "level": str(level),
            "event": str(event),
        }
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[str(key)] = value
        return record

    def _run(self) -> None:
        pending: list[dict] = []
        retry_seconds = 1.0
        while not self._stop.is_set():
            if not self.enabled():
                pending.clear()
                self._stop.wait(1)
                continue
            if not pending:
                try:
                    pending.append(self._queue.get(timeout=1))
                except queue.Empty:
                    continue
                deadline = time.monotonic() + 0.6
                while len(pending) < 20 and time.monotonic() < deadline:
                    try:
                        pending.append(self._queue.get_nowait())
                    except queue.Empty:
                        self._stop.wait(0.05)
            try:
                self._post(pending)
                pending.clear()
                retry_seconds = 1.0
            except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError):
                self._stop.wait(retry_seconds)
                retry_seconds = min(30.0, retry_seconds * 2)

    def _post(self, records: list[dict]) -> None:
        config = self._config()
        endpoint = openobserve_endpoint(config)
        username = config.openobserve_username.strip()
        password = os.getenv("OPENOBSERVE_PASSWORD", "")
        if not username or not password:
            raise ValueError("OpenObserve username or password is missing")
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(records, separators=(",", ":")).encode(),
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            if not 200 <= response.status < 300:
                raise OSError(f"OpenObserve returned HTTP {response.status}")


def openobserve_endpoint(config: Config) -> str:
    base = config.openobserve_url.strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OpenObserve address must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError("Put OpenObserve credentials in their separate fields")
    org = quote(config.openobserve_org.strip(), safe="")
    stream = quote(config.openobserve_stream.strip(), safe="")
    if not org or not stream:
        raise ValueError("OpenObserve organisation and stream are required")
    return f"{base}/api/{org}/{stream}/_json"
