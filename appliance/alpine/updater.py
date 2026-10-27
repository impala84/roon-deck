#!/usr/bin/env python3
"""Alpine application updates: verified revisions, staged and reversible.

No kernel/APK upgrades, no setup re-run, and no user-supplied download URLs.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import time
import sys
import tomllib
import urllib.error
import urllib.request

APP = Path("/opt/pi-home")
STATE = Path("/var/lib/pi-home")
REPO = "https://api.github.com/repos/impala84/roon-deck"
BRANCH = "alpine-beta"
DISPLAY_REVISION = Path("/run/pi-home/display-source-commit")
MANAGED_RELEASE = re.compile(r"[0-9a-f]{40}-[0-9]+")
UPDATE_RESERVE_BYTES = 96_000_000
MIN_STAGE_BYTES = 160_000_000
sys.path.insert(0, str(APP / "src"))
from pi_bus_time_display.releases import github_json, published_releases, select_release
CONFIG = Path("/etc/pi-home/config.toml")


class NoDowngrade(RuntimeError):
    pass


def status(message):
    temporary = STATE / ".alpine-update-status"
    temporary.write_text(message + "\n"); temporary.chmod(0o644)
    temporary.replace(STATE / "update-status")
    print(message, flush=True)


def run(args, timeout=300):
    # Keep dependency output in a private local log, never in HTTP responses.
    # Streaming to disk also shows progress while pip/npm are still running.
    log = STATE / "update.log"
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(f"\n{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} Starting {Path(args[0]).name}\n"); file.flush()
        try:
            result = subprocess.run(args, stdout=file, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            file.write("Step timed out\n"); file.flush()
            raise RuntimeError("Application preparation timed out; see the private update log")
        file.write(f"Step finished with exit status {result.returncode}\n")
    if result.returncode: raise RuntimeError("Application preparation or service restart failed; see the private update log")


def fetch_json(url):
    # Shared with the release list: unchanged answers are re-validated for free and a rate-limited network says so.
    return github_json(url, timeout=30)


def wait_for_clock(timeout=45):
    """Do not start TLS while a Pi without an RTC still thinks it is 1970."""
    if time.gmtime().tm_year >= 2024:
        return
    status("Update · Waiting for network time…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if time.gmtime().tm_year >= 2024:
            return
        time.sleep(1)
    raise RuntimeError("The Pi clock is not ready. Check network time and try again; current application unchanged")


def managed_release(path, releases):
    return (
        path.parent == releases
        and not path.is_symlink()
        and path.is_dir()
        and (path.name == "initial-image" or MANAGED_RELEASE.fullmatch(path.name))
    )


def prune_releases(releases, preserve=()):
    """Remove only updater-owned, inactive releases from the exact release root."""
    preserved = {Path(path).resolve() for path in preserve}
    for path in releases.iterdir():
        if managed_release(path, releases) and path.resolve() not in preserved:
            shutil.rmtree(path)


def tree_disk_usage(path):
    """Allocated bytes used by one release tree, without following symlinks."""
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            candidate = Path(root) / name
            try:
                stat = candidate.lstat()
            except OSError:
                continue
            total += stat.st_blocks * 512
    return total


def required_stage_space(current):
    # A new tree is normally close to the current release's allocated size.
    # Add a bounded reserve for the source archive, extraction and package
    # growth instead of rejecting every update below an arbitrary 400 MB.
    return max(MIN_STAGE_BYTES, tree_disk_usage(current) + UPDATE_RESERVE_BYTES)


def verified_revision():
    configuration = tomllib.loads(CONFIG.read_text())
    channel = configuration.get("release_channel", "stable") if (STATE / "update-channel-initialized").exists() else "beta"
    installed = tomllib.loads((APP / "pyproject.toml").read_text())["project"]["version"]
    selected = select_release(published_releases(), channel, installed, "alpine")
    if selected["status"] == "ahead":
        raise NoDowngrade(selected["message"])
    if selected["status"] == "unavailable":
        raise RuntimeError(selected["message"])
    reference = fetch_json(REPO + "/git/ref/tags/" + selected["tag"]).get("object", {})
    if reference.get("type") == "tag" and re.fullmatch(r"[0-9a-f]{40}", reference.get("sha", "")):
        reference = fetch_json(REPO + "/git/tags/" + reference["sha"]).get("object", {})
    sha = reference.get("sha", "")
    if reference.get("type") != "commit" or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Invalid Alpine release revision")
    # Beta is the physical-development channel: the user explicitly accepts
    # an exact published prerelease tag and performs the hardware acceptance
    # check. Stable remains gated by the complete Alpine verification job.
    if channel == "beta":
        return sha
    result = fetch_json(REPO + "/actions/workflows/alpine-image.yml/runs?branch=" + BRANCH + "&head_sha=" + sha + "&status=success&per_page=100")
    runs = result.get("workflow_runs", [])
    runs = [build for build in runs if build.get("head_sha") == sha]
    if not runs: raise RuntimeError("No verified Alpine build is available")
    build = runs[0]
    if build.get("head_branch") != BRANCH or build.get("conclusion") != "success" or build.get("event") not in {"push", "workflow_dispatch"} or build.get("head_repository", {}).get("full_name") != "impala84/roon-deck" or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Invalid verified build response")
    return sha


def extract_source(archive, destination):
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 10000: raise RuntimeError("Too many source files")
        if sum(item.size for item in members) > 100_000_000: raise RuntimeError("Source package is too large")
        for item in members:
            parts = Path(item.name).parts
            if not parts or item.name.startswith("/") or ".." in parts or not (item.isfile() or item.isdir()):
                raise RuntimeError("Unsafe source package")
        tar.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not (roots[0] / "appliance/alpine/updater.py").is_file():
        raise RuntimeError("Not an Alpine-compatible application package")
    return roots[0]


def download_source(sha, archive, attempts=3):
    url = "https://codeload.github.com/impala84/roon-deck/tar.gz/" + sha
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as file:
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > 30_000_000: raise RuntimeError("Source download is too large")
                    file.write(chunk)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            try: archive.unlink()
            except FileNotFoundError: pass
            if attempt < attempts:
                status(f"Update · Source download interrupted; retrying ({attempt + 1}/{attempts})…")
                time.sleep(2)
    detail = getattr(last_error, "reason", last_error)
    raise RuntimeError(f"Could not download the verified application files after {attempts} attempts: {detail}") from last_error


def activate(target):
    temporary = APP.with_name(".pi-home-next")
    if temporary.is_symlink(): temporary.unlink()
    temporary.symlink_to(target)
    temporary.replace(APP)


def migrate_completed_setup():
    """Give pre-marker installations the root-readable boot completion flag."""
    marker = STATE / "setup-complete"
    if marker.exists(): return False
    legacy = STATE.with_name("pi-home-setup") / "progress.json"
    try:
        complete = bool(json.loads(legacy.read_text(encoding="utf-8")).get("complete"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if not complete: return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text("true\n", encoding="ascii"); temporary.chmod(0o600); temporary.replace(marker)
    return True


def healthy(expected_sha=None):
    for _ in range(30):
        try:
            for url in ("http://127.0.0.1:8765/api/status", "http://127.0.0.1:8766/api/state"):
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status != 200: raise OSError("Not ready")
            if expected_sha:
                with urllib.request.urlopen("http://127.0.0.1:8766/api/build", timeout=2) as response:
                    if response.status != 200 or json.load(response).get("revision") != expected_sha:
                        raise OSError("Roon controller is not running the staged revision")
            run(["rc-service", "pi-home-display", "status"], timeout=10)
            if expected_sha:
                if not DISPLAY_REVISION.exists() or DISPLAY_REVISION.read_text().strip() != expected_sha:
                    raise OSError("Touchscreen is not running the staged revision")
            return True
        except (OSError, RuntimeError, subprocess.TimeoutExpired): time.sleep(1)
    return False


def restart():
    # OpenRC otherwise cycles dependent services during each backend restart.
    # Hold the display stopped until every backend has restarted so Cage/seatd
    # cannot race a second display start for the service/DRM locks.
    run(["rc-service", "--nodeps", "pi-home-display", "stop"], timeout=45)
    # Cage can leave seatd's DRM session connected briefly after OpenRC reports
    # the supervised display stopped. A new Cage then receives a broken pipe
    # and respawns forever without ever publishing its source revision.
    run(["rc-service", "--nodeps", "seatd", "restart"], timeout=45)
    for service in ("pi-home-setup", "pi-home-api", "pi-home-roon"):
        run(["rc-service", "--nodeps", service, "restart"], timeout=45)
    if Path("/etc/runlevels/default/roondeck-dial").exists() and (APP / "src/pi_bus_time_display/surface_dial.py").is_file():
        run(["rc-service", "--nodeps", "roondeck-dial", "restart"], timeout=45)
    if Path("/etc/runlevels/default/roondeck-discovery").exists() and (APP / "src/pi_bus_time_display/sood_relay.py").is_file():
        run(["rc-service", "--nodeps", "roondeck-discovery", "restart"], timeout=45)
    try: DISPLAY_REVISION.unlink()
    except FileNotFoundError: pass
    run(["rc-service", "--nodeps", "pi-home-display", "start"], timeout=45)


def update():
    # The helper may have inherited /opt/pi-home as its working directory.
    # Move away before pruning an inactive release so child installers never
    # inherit a deleted current-working-directory inode.
    os.chdir("/")
    wait_for_clock()
    status("Update · Checking published Alpine releases…")
    try:
        sha = verified_revision()
    except NoDowngrade as error:
        status("Update unchanged. " + str(error)); return
    if (APP / ".source-commit").exists() and (APP / ".source-commit").read_text().strip() == sha:
        if healthy(sha):
            status("Update unchanged. Latest Alpine release is installed and running."); return
        status("Update files are current · Restarting the stale touchscreen…")
        restart()
        if not healthy(sha): raise RuntimeError("Current files are installed but the touchscreen could not be restarted on that revision")
        status("Touchscreen repaired. Alpine " + sha[:7] + " is now running."); return
    releases = Path("/opt/pi-home-releases"); releases.mkdir(exist_ok=True, mode=0o755)
    # A 1.7 GB appliance cannot retain a full Python/npm tree for every update.
    # The live release is the rollback copy while the next one is staged.
    current = APP.resolve()
    status("Update · Reclaiming old update space…")
    prune_releases(releases, {current})
    required = required_stage_space(current)
    available = shutil.disk_usage(releases).free
    if available < required:
        raise RuntimeError(f"Not enough free space to stage this update ({required // 1_000_000} MB required, {available // 1_000_000} MB available); current application unchanged")
    target = releases / (sha + "-" + str(time.time_ns()))
    try:
        # Stage dependencies while the existing app remains running.
        with tempfile.TemporaryDirectory(prefix="pi-home-source-") as folder:
            temporary = Path(folder); archive = temporary / "source.tar.gz"
            status("Update · Downloading verified application files…")
            download_source(sha, archive)
            try:
                source = extract_source(archive, temporary / "unpacked")
            except (tarfile.TarError, OSError) as error:
                raise RuntimeError(f"Downloaded application package could not be unpacked: {error}") from error
            source.rename(target)
        (target / ".source-commit").write_text(sha + "\n")
        status("Update · Creating Python environment…")
        run(["python3", "-m", "venv", "--system-site-packages", str(target / ".venv")])
        status("Update · Installing RoonDeck Python package…")
        run([str(target / ".venv/bin/pip"), "install", "--no-build-isolation", "--no-deps", str(target)])
        status("Update · Downloading Roon dependencies…")
        run(["npm", "--prefix", str(target / "roon-controller"), "ci", "--omit=dev", "--no-audit", "--no-fund"])
        status("Update · Checking prepared application…")
        run([str(target / ".venv/bin/python"), "-c", "import gi; gi.require_version('Gtk', '4.0'); gi.require_foreign('cairo'); from pi_bus_time_display import __version__"])
        for path in ("native-display/roondeck_native.py", "scripts/pi-bus-cage-launch", "appliance/alpine/display-session"):
            (target / path).chmod(0o755)
    except Exception:
        if target.exists() and managed_release(target, releases):
            shutil.rmtree(target)
        raise
    previous = APP.resolve()
    if not APP.is_symlink():
        previous = releases / "initial-image"
        if previous.exists(): raise RuntimeError("Initial image backup already exists; repair required")
        APP.rename(previous)
    try:
        activate(target)
        migrate_completed_setup()
        shutil.copyfile(target / "appliance/alpine/display-launch", "/usr/local/bin/pi-home-display-launch")
        Path("/usr/local/bin/pi-home-display-launch").chmod(0o755)
        status("Update · Restarting and checking RoonDeck…")
        restart()
        if not healthy(sha): raise RuntimeError("New application did not become healthy or the touchscreen kept running old files")
    except Exception as failure:
        activate(previous)
        shutil.copyfile(previous / "appliance/alpine/display-launch", "/usr/local/bin/pi-home-display-launch")
        Path("/usr/local/bin/pi-home-display-launch").chmod(0o755)
        restart()
        previous_sha = (previous / ".source-commit").read_text().strip() if (previous / ".source-commit").exists() else None
        if not healthy(previous_sha): raise RuntimeError("Update failed; previous files restored but services need attention")
        if target.exists() and managed_release(target, releases):
            shutil.rmtree(target)
        raise RuntimeError("Update failed; previous working application restored: " + str(failure)) from failure
    # Cleanup is deliberately outside activation/rollback. Failure to reclaim an
    # old inactive tree must never roll back an already healthy new release.
    try: prune_releases(releases, {target})
    except OSError: pass
    status("Update installed. Alpine " + sha[:7] + "; settings and pairing preserved.")


def check():
    """Check the selected channel without downloading or installing an update."""
    os.chdir("/")
    wait_for_clock()
    try:
        sha = verified_revision()
    except NoDowngrade:
        return
    installed = (APP / ".source-commit").read_text().strip() if (APP / ".source-commit").exists() else ""
    if installed != sha:
        status("Update available. Open Settings → System → Software to install the latest Alpine release.")


def main():
    if os.geteuid() != 0: raise SystemExit("Run with sudo")
    with open("/run/pi-home-update.lock", "a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        try: check() if "--check" in sys.argv[1:] else update()
        except Exception as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, ssl.SSLCertVerificationError):
                message = "HTTPS certificate check failed. Check the Pi clock and network time sync; existing installation retained"
            else:
                if isinstance(error, RuntimeError): message = str(error)
                else:
                    code = getattr(error, "code", None)
                    detail = f"HTTP {code}" if code else str(getattr(error, "reason", error))[:80] or type(error).__name__
                    message = f"Download or application preparation failed ({detail}); existing installation retained"
            status("Failed: " + message)
            raise SystemExit(1)


if __name__ == "__main__": main()
