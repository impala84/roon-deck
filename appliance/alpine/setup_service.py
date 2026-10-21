"""Local-only, bounded first-boot actions. Never expose this helper over HTTP."""
import json
import fcntl
import os
import platform
import posixpath
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import socket
import struct
import subprocess
import threading
import tempfile
import tarfile
import urllib.request
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SOCKET = "/run/pi-home-setup.sock"
PROFILES = {"auto": "", "original": "vc4-kms-dsi-7inch", "touch2-5": "vc4-kms-dsi-ili9881-5inch", "touch2-7": "vc4-kms-dsi-ili9881-7inch", "touch2-10": "vc4-kms-dsi-ili79600-10-1inch"}
ROON_BRIDGE_URL = "https://download.roonlabs.net/builds/RoonBridge_linuxarmv8.tar.bz2"
UPDATE_CHECK_CRON = "0 3 * * * /usr/bin/python3 /opt/pi-home/appliance/alpine/updater.py --check"


def ensure_daily_update_check(root=Path("/")):
    """Install one quiet 03:00 release check without disturbing other jobs."""
    path = Path(root) / "etc/crontabs/root"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if "pi-home/appliance/alpine/updater.py --check" not in line]
    lines.append(UPDATE_CHECK_CRON)
    atomic(path, "\n".join(lines) + "\n", 0o600)


def configure_netdata_lightweight(root, enabled):
    """Manage the lightweight profile; preserve Cloud, alerts and storage."""
    if type(enabled) is not bool:
        raise ValueError("Choose a supported Netdata monitoring mode.")
    root = Path(root)
    directory = root / ("opt/netdata/etc/netdata" if (root / "opt/netdata/bin/netdata").is_file() else "etc/netdata")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "netdata.conf"
    text = read(path) if path.exists() else ""
    backup = directory / "netdata.conf.pi-home-backup"
    if not backup.exists(): atomic(backup, text, 0o640)
    settings = [("ml", "enabled", "no" if enabled else "auto"), ("db", "update every", "3" if enabled else "1")]
    original_plugins = re.search(r"(?ms)^\[plugins\][^\n]*\n(.*?)(?=^\[|\Z)", read(backup))
    for key in ("netflow", "otel", "scripts.d", "nfacct", "network-viewer", "debugfs", "apps", "go.d"):
        previous = re.search(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(.*)$", original_plugins.group(1)) if original_plugins else None
        value = ("yes" if key in {"apps", "go.d"} else "no") if enabled else (previous.group(1) if previous else None)
        settings.append(("plugins", key, value))
    for section, key, value in settings:
        pattern = rf"(?ms)^\[{section}\][^\n]*\n(.*?)(?=^\[|\Z)"
        match = re.search(pattern, text)
        setting = f"    {key} = {value}\n" if value is not None else ""
        if match:
            body = re.sub(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*\n?", "", match.group(1))
            text = text[:match.start(1)] + body.rstrip() + "\n" + setting + text[match.end(1):]
        elif value is not None:
            text = text.rstrip() + f"\n\n[{section}]\n" + setting
    atomic(path, text, 0o644)
    (root / "var/lib/pi-home").mkdir(parents=True, exist_ok=True)
    atomic(root / "var/lib/pi-home/netdata-lightweight", "yes\n" if enabled else "no\n")


def orientation_transform(profile, orientation, mounting="standard"):
    """Translate the user-facing viewport orientation into panel rotation."""
    if orientation not in {"landscape", "portrait"}:
        raise ValueError("Choose Landscape or Portrait.")
    if mounting not in {"standard", "inverted"}:
        raise ValueError("Choose Standard or 180° rotation.")
    native_portrait = profile.startswith("touch2-")
    if orientation == "portrait":
        base = "normal" if native_portrait else "90"
    else:
        base = "90" if native_portrait else "normal"
    return base if mounting == "standard" else {"normal": "180", "90": "270"}[base]


def display_orientation(profile, rotation):
    native_portrait = profile.startswith("touch2-")
    portrait = rotation in ({"normal", "180"} if native_portrait else {"90", "270"})
    return "portrait" if portrait else "landscape"


def display_mounting(rotation):
    return "inverted" if rotation in {"180", "270"} else "standard"


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as file:
        return file.read()


def atomic(path, text, mode=0o644):
    path = Path(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8))
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "w") as file:
        file.write(text)
        file.flush(); os.fsync(file.fileno())
    if path.exists() and not path.is_symlink():
        owner = path.stat()
        os.chown(temporary, owner.st_uid, owner.st_gid)
    temporary.replace(path)


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        # Never return subprocess output: Wi-Fi/password commands may echo secrets.
        raise ValueError("Could not apply that setting. Check it and try again.")
    return result.stdout.strip()


def validate_username(username):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{2,31}", username):
        raise ValueError("Use 3–32 lowercase letters, numbers, hyphens or underscores; start with a letter.")


def set_login_credentials(username, password, root=Path("/"), run=command):
    """Create/enable one recovery account and set its password without PAM policy.

    Alpine's interactive BusyBox ``passwd`` applies a strength check. BusyBox
    ``chpasswd`` is present in the appliance image and deliberately accepts the
    owner's chosen password. The password travels only over stdin and is never
    written to progress or command output.
    """
    validate_username(username); validate_password(password)
    root = Path(root)
    passwd_file = root / "etc/passwd"
    accounts = {line.split(":", 1)[0] for line in read(passwd_file).splitlines()} if passwd_file.exists() else set()
    if username not in accounts:
        run(["adduser", "-D", "-h", f"/home/{username}", username])
        run(["addgroup", username, "wheel"])
    result = subprocess.run(["chpasswd"], input=username + ":" + password + "\n", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=15)
    if result.returncode: raise ValueError("Could not set the device password. Please retry.")
    ssh = root / "etc/ssh/sshd_config.d/pi-home.conf"
    if ssh.parent.exists():
        atomic(ssh, "PermitRootLogin no\nPasswordAuthentication yes\nPermitEmptyPasswords no\nAllowUsers " + username + "\n", 0o600)


def validate_password(password):
    if not 8 <= len(password) <= 128 or any(c in password for c in "\r\n\x00"):
        raise ValueError("Choose a password of 8–128 characters.")
    if password != password.strip().strip("'\""):
        raise ValueError("Do not start or end the password with spaces or quotation marks.")


def parse_netdata_connection_command(value):
    """Extract credentials from Netdata's generated command without running it."""
    value = str(value or "").strip()
    if not 20 <= len(value) <= 16_384 or "\x00" in value:
        raise ValueError("Paste the complete connection command from Netdata Cloud.")
    if "https://get.netdata.cloud/kickstart.sh" not in value:
        raise ValueError("Use the official Netdata Cloud connection command.")
    try:
        words = shlex.split(value)
    except ValueError as error:
        raise ValueError("The Netdata Cloud command could not be read. Copy it again in full.") from error
    options = {}
    for index, word in enumerate(words):
        for name in ("claim-token", "claim-rooms", "claim-url"):
            flag = "--" + name
            if word == flag and index + 1 < len(words): options[name] = words[index + 1]
            elif word.startswith(flag + "="): options[name] = word[len(flag) + 1:]
    token = str(options.get("claim-token", "")).strip()
    rooms = str(options.get("claim-rooms", "")).strip()
    url = str(options.get("claim-url", "https://app.netdata.cloud")).strip().rstrip("/")
    if not 8 <= len(token) <= 512 or any(character.isspace() or ord(character) < 33 for character in token):
        raise ValueError("The pasted command does not contain a valid claim token.")
    room_values = [room.strip() for room in rooms.split(",") if room.strip()]
    if any(not re.fullmatch(r"[A-Za-z0-9._:-]{4,128}", room) for room in room_values):
        raise ValueError("The pasted command contains an invalid Netdata Room ID.")
    if url != "https://app.netdata.cloud":
        raise ValueError("Only the official Netdata Cloud service is supported.")
    return token, ",".join(room_values), url


def claim_netdata(root, token, rooms, url="https://app.netdata.cloud"):
    """Configure the installed Agent using Netdata's supported claim file."""
    root = Path(root)
    claim = root / "etc/netdata/claim.conf"; claim.parent.mkdir(parents=True, exist_ok=True)
    room_line = "    rooms = " + rooms + "\n" if rooms else ""
    atomic(claim, "[global]\n    url = " + url + "\n    token = " + token + "\n" + room_line + "    insecure = no\n", 0o640)
    try:
        netdata = __import__("grp").getgrnam("netdata")
        os.chown(claim, 0, netdata.gr_gid)
    except KeyError:
        pass


def run_netdata_claim_helper(root, token, rooms, url="https://app.netdata.cloud"):
    """Claim Alpine's packaged Agent with its bundled helper.

    Older packaged Agents do not consume claim.conf on restart. Never execute
    the pasted Cloud command; pass only previously validated values to this
    fixed local executable.
    """
    helper = Path(root) / "usr/sbin/netdata-claim.sh"
    if not helper.is_file(): return False
    arguments = [str(helper), f"-token={token}", f"-url={url}", "-daemon-not-running"]
    if rooms: arguments.append(f"-rooms={rooms}")
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True, timeout=90)
    # A previous interrupted claim may have registered the machine GUID
    # remotely without retaining its local identity. Retry that one case with
    # a fresh node ID while preserving Netdata's stable machine GUID.
    if result.returncode == 13:
        arguments.append(f"-id={uuid.uuid4()}")
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, timeout=90)
    errors = {
        1: "The installed Netdata claim helper did not understand this request.",
        2: "Netdata could not create its private Cloud identity files.",
        3: "The installed Netdata Agent is missing a Cloud dependency.",
        4: "Netdata could not reach Netdata Cloud. Check the network and clock.",
        5: "Netdata could not notify its local Agent about the Cloud connection.",
        6: "Netdata refused the account used to create its Cloud identity.",
        7: "Netdata Cloud returned an unexpected response.",
        8: "Netdata Cloud rejected the generated node identity.",
        9: "Netdata Cloud rejected this device name.",
        10: "Netdata Cloud rejected the Room ID in the connection command.",
        11: "Netdata Cloud rejected the Agent's public key.",
        12: "The Netdata Cloud claim token is expired or invalid. Generate a new command.",
        13: "This Netdata node identity is already registered in Cloud.",
        14: "Netdata Cloud is still processing this claim. Try again shortly.",
        15: "Netdata Cloud encountered an internal error.",
        16: "Netdata Cloud timed out while processing the claim.",
        17: "Netdata Cloud is temporarily unavailable.",
        18: "Netdata could not generate a unique node identity.",
    }
    if result.returncode:
        raise ValueError(errors.get(result.returncode, "Netdata Cloud connection failed for an unknown reason."))
    return True


def ensure_roon_bridge_service(root):
    root = Path(root)
    start = root / "opt/RoonBridge/start.sh"
    if not start.is_file():
        raise ValueError("Roon Bridge is not installed on this appliance.")
    service = root / "etc/init.d/roonbridge"
    if not service.exists():
        service.parent.mkdir(parents=True, exist_ok=True)
        atomic(service, """#!/sbin/openrc-run
description=\"Roon Bridge audio endpoint\"
supervisor=supervise-daemon
command=/opt/RoonBridge/start.sh
directory=/opt/RoonBridge
respawn_delay=5
respawn_max=0
output_log=/var/log/pi-home/roonbridge.log
error_log=/var/log/pi-home/roonbridge-error.log
export ROON_DATAROOT=/var/roon
export ROON_ID_DIR=/var/roon
depend() { need localmount; after networkmanager; }
""", 0o755)
    return service


def configure_airplay(root, name="RoonDeck"):
    """Write the small, owned Shairport Sync configuration used by RoonDeck."""
    root = Path(root)
    name = str(name).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._'-]{0,49}", name):
        raise ValueError("Use 1–50 letters, numbers, spaces, dots, hyphens or apostrophes for the AirPlay name.")
    if not (root / "usr/bin/shairport-sync").is_file():
        raise ValueError("AirPlay is not installed on this appliance.")
    atomic(root / "etc/shairport-sync.conf", f'''general = {{
    name = "{name}";
    output_backend = "alsa";
}};

alsa = {{
    output_device = "default";
}};
''', 0o644)
    state = root / "var/lib/pi-home"
    state.mkdir(parents=True, exist_ok=True)
    atomic(state / "airplay-name", name + "\n")
    return name


def ensure_netdata_service(root):
    """Adopt Alpine's package or Netdata's official /opt installation."""
    root = Path(root)
    service = root / "etc/init.d/netdata"
    static_agent = root / "opt/netdata/bin/netdata"
    packaged_agent = root / "usr/sbin/netdata"
    if not static_agent.is_file() and not packaged_agent.is_file():
        raise ValueError("Netdata is not installed on this appliance.")
    service.parent.mkdir(parents=True, exist_ok=True)
    if static_agent.is_file():
        managed = """#!/sbin/openrc-run
description="Netdata monitoring agent"
supervisor=supervise-daemon
command=/opt/netdata/bin/netdata
command_args="-D"
respawn_delay=5
respawn_max=0
output_log=/var/log/pi-home/netdata.log
error_log=/var/log/pi-home/netdata-error.log
depend() { need localmount; after networkmanager; }
"""
        if not service.exists() or service.read_text(errors="replace") != managed:
            backup = service.parent / "netdata.pi-home-package-backup"
            if service.exists() and not backup.exists(): shutil.copyfile(service, backup)
            atomic(service, managed, 0o755)
    return service


def display_power(root, powered, brightness_percent=100):
    """Control the backlight without disabling the DSI touch controller."""
    brightness_percent = int(brightness_percent)
    if not 10 <= brightness_percent <= 100: raise ValueError("Brightness must be between 10 and 100.")
    devices = sorted((Path(root) / "sys/class/backlight").glob("*"))
    devices = [device for device in devices if (device / "brightness").exists() or (device / "bl_power").exists()]
    if not devices: raise ValueError("No display backlight control was found.")
    for device in devices:
        brightness = device / "brightness"; power = device / "bl_power"
        if powered:
            if power.exists(): power.write_text("0", encoding="ascii")
            if brightness.exists():
                maximum = int((device / "max_brightness").read_text(encoding="ascii")) if (device / "max_brightness").exists() else 255
                brightness.write_text(str(max(1, round(maximum * brightness_percent / 100))), encoding="ascii")
        elif brightness.exists():
            # Brightness zero switches the backlight off while leaving Goodix
            # alive, so the next contact can still wake the application.
            brightness.write_text("0", encoding="ascii")
        elif power.exists():
            power.write_text("4", encoding="ascii")


def install_clock_support(root=Path("/"), run=command, now=None):
    """Migrate existing appliances as well as newly built images."""
    root = Path(root)
    source = Path(__file__).with_name("init.d") / "pi-home-clock"
    service = root / "etc/init.d/pi-home-clock"
    service.parent.mkdir(parents=True, exist_ok=True)
    if not service.exists() or service.read_bytes() != source.read_bytes():
        shutil.copyfile(source, service)
        service.chmod(0o755)
    hwclock = root / "etc/runlevels/boot/hwclock"
    if hwclock.is_symlink():
        hwclock.unlink()
    run(["rc-update", "add", "pi-home-clock", "boot"])

    chrony = root / "etc/chrony/chrony.conf"
    if chrony.is_file():
        lines = []
        for line in chrony.read_text().splitlines():
            if re.match(r"^\s*makestep\s", line):
                continue
            if re.match(r"^\s*(?:pool|server)\s", line) and not re.search(r"(?:^|\s)iburst(?:\s|$)", line):
                line += " iburst"
            lines.append(line)
        lines.append("makestep 0.1 -1")
        updated = "\n".join(lines) + "\n"
        if chrony.read_text() != updated:
            atomic(chrony, updated)

    epoch = int(now if now is not None else __import__("time").time())
    if epoch >= 1704067200:
        seed = root / "var/lib/pi-home/clock-seed"
        seed.parent.mkdir(parents=True, exist_ok=True)
        atomic(seed, str(epoch) + "\n")


def update_locked(root=Path("/")):
    """Observe the updater's process lock, including across helper restarts."""
    path = Path(root) / "run/pi-home-update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
    return False


class Setup:
    def __init__(self, root=Path("/"), run=command, roon=None, login_credentials=set_login_credentials):
        self.root = Path(root); self.run = run; self.roon = roon or self.roon_state
        self.login_credentials = login_credentials
        self.tools_lock = threading.Lock()
        self.netdata_install_lock = threading.Lock()
        self.roon_install_lock = threading.Lock()
        self.airplay_install_lock = threading.Lock()
        self.software_lock = threading.Lock()
        self.update_process = None
        self.progress = self.root / "var/lib/pi-home-setup/progress.json"
        self.progress.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def roon_state(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8766/api/state", timeout=3) as response:
                return json.load(response)
        except (OSError, ValueError):
            return {"connected": False, "zones": []}

    def saved(self):
        return json.loads(read(self.progress)) if self.progress.exists() else {}

    def save(self, state):
        atomic(self.progress, json.dumps(state), 0o600)

    def setting(self, key, value):
        path = self.root / "etc/pi-home/config.toml"
        text = read(path)
        replacement = f"{key} = {json.dumps(value)}"
        text, count = re.subn(rf"^{key}\s*=.*$", lambda _: replacement, text, flags=re.M)
        if count != 1: raise ValueError("Configuration needs repair before setup can continue.")
        atomic(path, text, 0o640)

    def connected(self):
        output = self.run(["nmcli", "-t", "-f", "STATE", "device"])
        return any(line == "connected" for line in output.splitlines())

    def install_official_netdata(self, token="", rooms="", claim_url="https://app.netdata.cloud"):
        """Replace the Alpine Agent only after an explicit UI request.

        The pasted shell is never run. We fetch the one fixed HTTPS endpoint
        and reconstruct only the validated claim arguments.
        """
        status = self.root / "var/lib/pi-home/netdata-operation-status"
        installer = None
        migrated_package = False
        try:
            request = urllib.request.Request("https://get.netdata.cloud/kickstart.sh", headers={"User-Agent": "Pi-Home-Netdata-Installer"})
            with urllib.request.urlopen(request, timeout=45) as response, tempfile.NamedTemporaryFile(prefix="pi-home-netdata-", delete=False) as output:
                installer = Path(output.name)
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > 5_000_000: raise ValueError("The official Netdata installer was unexpectedly large.")
                    output.write(chunk)
            installer.chmod(0o700)
            packaged_agent = self.root / "usr/sbin/netdata"
            static_agent = self.root / "opt/netdata/bin/netdata"
            if packaged_agent.is_file() and not static_agent.is_file():
                # Netdata's kickstart installer deliberately refuses to replace
                # distribution-packaged installs. Older RoonDeck images shipped
                # Alpine's package, so remove it only after the new installer
                # has downloaded successfully. apk retains /etc configuration.
                atomic(status, "Replacing the older Alpine Netdata package…\n")
                subprocess.run(["rc-service", "netdata", "stop"], capture_output=True, check=False, timeout=30)
                self.run(["apk", "del", "netdata"])
                migrated_package = True
            atomic(status, "Installing the latest official stable Netdata Agent…\n")
            arguments = ["/bin/bash", str(installer), "--non-interactive", "--release-channel", "stable", "--static-only", "--auto-update"]
            if static_agent.is_file(): arguments.append("--reinstall")
            if token: arguments.extend(["--claim-token", token, "--claim-url", claim_url])
            if rooms: arguments.extend(["--claim-rooms", rooms])
            environment = {**os.environ, "DISABLE_TELEMETRY": "1"}
            result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment, timeout=900)
            if result.returncode: raise ValueError("The official Netdata installer rejected this installation or connection command.")
            ensure_netdata_service(self.root)
            preference = self.root / "var/lib/pi-home/netdata-lightweight"
            lightweight = not preference.exists() or read(preference).strip() != "no"
            configure_netdata_lightweight(self.root, lightweight)
            # The installer may have started an Agent outside OpenRC.
            subprocess.run(["rc-service", "netdata", "stop"], capture_output=True, check=False, timeout=30)
            subprocess.run(["/opt/netdata/bin/netdatacli", "shutdown-agent"], capture_output=True, check=False, timeout=30)
            self.run(["rc-service", "netdata", "start"])
            self.run(["rc-update", "add", "netdata", "default"])
            self.run(["rc-update", "add", "crond", "default"])
            self.run(["rc-service", "crond", "start"])
            # Restart under the managed service to apply the selected profile.
            atomic(status, "Official Netdata Agent installed. " + ("Checking Cloud connection…\n" if token else "Connect to Netdata Cloud from Settings when ready.\n"))
        except Exception as error:
            if migrated_package and not (self.root / "opt/netdata/bin/netdata").is_file():
                try:
                    self.run(["apk", "add", "--no-cache", "netdata"])
                    self.run(["rc-update", "add", "netdata", "default"])
                    self.run(["rc-service", "netdata", "start"])
                except Exception:
                    pass
            message = str(error) if isinstance(error, ValueError) else "The official Netdata installation failed. Check the network and try again."
            atomic(status, "Failed: " + message + "\n")
        finally:
            if installer is not None:
                installer.unlink(missing_ok=True)
            self.netdata_install_lock.release()

    def install_roon_bridge(self):
        """Install Roon's official ARM64 payload without its non-Alpine wrapper."""
        status = self.root / "var/lib/pi-home/roonbridge-install-status"
        work = self.root / "var/tmp/pi-home-roonbridge-install"
        archive = work / "RoonBridge.tar.bz2"
        extracted = work / "RoonBridge"
        destination = self.root / "opt/RoonBridge"
        try:
            if platform.machine() not in {"aarch64", "arm64"}:
                raise ValueError("Roon Bridge is available here only on a 64-bit ARM Raspberry Pi.")
            if destination.exists():
                raise ValueError("Roon Bridge is already installed.")
            atomic(status, "Installing Roon Bridge compatibility libraries…\n")
            self.run(["apk", "add", "--no-cache", "gcompat", "libstdc++", "icu-libs", "alsa-lib", "bzip2"])
            if work.exists(): shutil.rmtree(work)
            work.mkdir(parents=True, mode=0o700)
            request = urllib.request.Request(ROON_BRIDGE_URL, headers={"User-Agent": "Pi-Home-RoonBridge-Installer"})
            atomic(status, "Downloading the official Roon Bridge package…\n")
            total = 0
            with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 1_000_000_000: raise ValueError("The official Roon Bridge package was unexpectedly large.")
                    output.write(chunk)
            atomic(status, "Validating the official Roon Bridge package…\n")
            with tarfile.open(archive, "r:bz2") as package:
                members = package.getmembers()
                if not members or sum(member.size for member in members) > 1_500_000_000:
                    raise ValueError("The official Roon Bridge package is invalid.")
                for member in members:
                    name = posixpath.normpath(member.name)
                    if name != "RoonBridge" and not name.startswith("RoonBridge/"):
                        raise ValueError("The official Roon Bridge package contains an unsafe path.")
                    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                        raise ValueError("The official Roon Bridge package contains an unsupported file.")
                    if member.issym() or member.islnk():
                        target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname))
                        if target != "RoonBridge" and not target.startswith("RoonBridge/"):
                            raise ValueError("The official Roon Bridge package contains an unsafe link.")
                package.extractall(work)
            required = (extracted / "start.sh", extracted / "check.sh", extracted / "Bridge/RoonBridge.exe")
            if not all(path.is_file() for path in required):
                raise ValueError("The official Roon Bridge package is incomplete.")
            self.run([str(extracted / "check.sh")])
            destination.parent.mkdir(parents=True, exist_ok=True)
            extracted.replace(destination)
            ensure_roon_bridge_service(self.root)
            self.run(["rc-update", "add", "roonbridge", "default"])
            self.run(["rc-service", "roonbridge", "start"])
            atomic(status, "Roon Bridge installed and running. Enable this endpoint in Roon → Settings → Audio.\n")
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else "Roon Bridge installation failed. Check the network and try again."
            atomic(status, "Failed: " + message + "\n")
        finally:
            if work.exists(): shutil.rmtree(work)
            self.roon_install_lock.release()

    def install_airplay(self):
        """Install Alpine's maintained classic AirPlay receiver and enable it."""
        status = self.root / "var/lib/pi-home/airplay-install-status"
        status.parent.mkdir(parents=True, exist_ok=True)
        try:
            if (self.root / "usr/bin/shairport-sync").is_file():
                raise ValueError("AirPlay is already installed.")
            atomic(status, "Installing the Alpine Shairport Sync package…\n")
            self.run(["apk", "add", "--no-cache", "shairport-sync", "shairport-sync-openrc"])
            configure_airplay(self.root)
            self.run(["rc-update", "add", "shairport-sync", "default"])
            self.run(["rc-service", "shairport-sync", "start"])
            atomic(status, "AirPlay installed and running. Choose RoonDeck from the AirPlay menu on an Apple device.\n")
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else "AirPlay installation failed. Check the network and try again."
            atomic(status, "Failed: " + message + "\n")
        finally:
            self.airplay_install_lock.release()

    def install_setup_software(self, choices):
        """Install optional services serially; persist choices, never credentials."""
        try:
            for name, installer, lock, status_name, present in (
                ("roon_bridge", self.install_roon_bridge, self.roon_install_lock, "roonbridge-install-status", "opt/RoonBridge/start.sh"),
                ("airplay", self.install_airplay, self.airplay_install_lock, "airplay-install-status", "usr/bin/shairport-sync"),
                ("netdata", self.install_official_netdata, self.netdata_install_lock, "netdata-operation-status", "opt/netdata/bin/netdata"),
            ):
                if not choices.get(name, False) or (self.root / present).is_file(): continue
                labels = {"roon_bridge": "Roon Bridge…", "airplay": "AirPlay…", "netdata": "Netdata…"}
                state = self.saved(); state["software_status"] = "Installing " + labels[name]; self.save(state)
                lock.acquire(); installer()
                status = read(self.root / "var/lib/pi-home" / status_name).strip()
                if status.startswith("Failed:"): raise ValueError(status)
            state = self.saved(); state.update(software=True, software_status="Selected software is ready."); self.save(state)
        except Exception:
            state = self.saved(); state.update(software=False, software_status="Installation could not finish. Check the network and retry, or continue without optional software."); self.save(state)
        finally:
            self.software_lock.release()

    def handle(self, data):
        state = self.saved(); action = data.get("action")
        if action == "status":
            if state.get("software_status", "").startswith("Installing") and not self.software_lock.locked():
                state.update(software=False, software_status="Installation was interrupted. Retry to continue."); self.save(state)
            try: connected = self.connected()
            except (ValueError, subprocess.TimeoutExpired): connected = False
            return {"ok": True, "progress": state, "software_busy": self.software_lock.locked(), "connected": connected, "roon": self.roon()}
        if self.software_lock.locked():
            raise ValueError("Wait for the selected software installation to finish.")
        if action == "software":
            if state.get("complete"): raise ValueError("Setup is already complete.")
            if not state.get("network"): raise ValueError("Connect to your network first.")
            choices = {name: data.get(name, False) for name in ("roon_bridge", "airplay", "netdata")}
            if any(type(value) is not bool for value in choices.values()): raise ValueError("Choose supported software options.")
            lightweight = data.get("netdata_lightweight", True)
            if type(lightweight) is not bool: raise ValueError("Choose a supported Netdata monitoring mode.")
            (self.root / "var/lib/pi-home").mkdir(parents=True, exist_ok=True)
            atomic(self.root / "var/lib/pi-home/netdata-lightweight", "yes\n" if lightweight else "no\n")
            choices["netdata_lightweight"] = lightweight
            selected = choices["roon_bridge"] or choices["airplay"] or choices["netdata"]
            state.update(software_choices=choices, software=not selected, software_status="Installing selected software…" if selected else "Optional software skipped.")
            self.save(state)
            if selected:
                self.software_lock.acquire()
                threading.Thread(target=self.install_setup_software, args=(choices,), daemon=True).start()
            return {"ok": True, "progress": state}
        if action == "update":
            if not state.get("complete"): raise ValueError("Finish setup before updating.")
            if (self.update_process is not None and self.update_process.poll() is None) or update_locked(self.root):
                return {"ok": True, "queued": False}
            atomic(self.root / "var/lib/pi-home/update-status", "Update · Queued…\n")
            self.update_process = subprocess.Popen(["/usr/bin/python3", "/opt/pi-home/appliance/alpine/updater.py"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "queued": True}
        if action == "install_tools":
            if not state.get("complete"): raise ValueError("Finish setup before installing tools.")
            if not self.tools_lock.acquire(blocking=False):
                return {"ok": True, "queued": False}
            atomic(self.root / "var/lib/pi-home/tools-status", "Installing system tools…\n")
            threading.Thread(target=self.install_tools, daemon=True).start()
            return {"ok": True, "queued": True}
        if action in {"display_on", "display_off", "set_brightness"}:
            if not state.get("complete"): raise ValueError("Finish setup before controlling the display.")
            display_power(self.root, action != "display_off", data.get("brightness", 100))
            return {"ok": True, "powered": action != "display_off"}
        if action == "set_display":
            if not state.get("complete"): raise ValueError("Finish setup before changing the display.")
            profile = str(data.get("profile", "")); orientation = str(data.get("orientation", "")); mounting = str(data.get("mounting", "standard"))
            if profile not in PROFILES or profile == "auto": raise ValueError("Choose a supported display.")
            if not (self.root / f"boot/overlays/{PROFILES[profile]}.dtbo").is_file(): raise ValueError("Display driver is missing from this image.")
            rotation = orientation_transform(profile, orientation, mounting)
            config = self.root / "etc/pi-home"
            previous_profile = read(config / "display-profile").strip() if (config / "display-profile").exists() else "original"
            atomic(config / "display-profile", profile + "\n")
            atomic(config / "display-transform", rotation + "\n")
            atomic(config / "display-orientation", orientation + "\n")
            atomic(config / "display-mounting", mounting + "\n")
            state.update(profile=profile, rotation=rotation, display_orientation=orientation, display_mounting=mounting); self.save(state)
            if previous_profile != profile:
                boot = self.root / "boot/config.txt"; text = read(boot)
                text = re.sub(r"\n?# BEGIN PI HOME SETUP\n.*?# END PI HOME SETUP\n?", "\n", text, flags=re.S)
                if not Path(str(boot) + ".setup-backup").exists(): atomic(Path(str(boot) + ".setup-backup"), text)
                text = re.sub(r"^display_auto_detect=.*$", "display_auto_detect=0", text, flags=re.M)
                overlay = PROFILES[profile]
                text += f"\n# BEGIN PI HOME SETUP\n[all]\ndtoverlay={overlay}\n# END PI HOME SETUP\n"
                atomic(boot, text)
                try:
                    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
                    atomic(self.root / "var/lib/pi-home/reboot-required-boot-id", boot_id + "\n")
                except OSError: pass
            # Apply Display explicitly includes a reboot: boot overlays, Cage
            # output transform and libinput calibration then start together.
            # Delay until after the HTTP response reaches the touchscreen.
            threading.Timer(2, lambda: self.run(["/sbin/reboot"])).start()
            return {"ok": True, "orientation": orientation, "mounting": mounting, "rotation": rotation, "reboot_required": True}
        if action == "netdata_lightweight":
            if not state.get("complete"): raise ValueError("Finish setup first.")
            if not (self.root / "opt/netdata/bin/netdata").is_file() and not (self.root / "usr/sbin/netdata").is_file(): raise ValueError("Netdata is not installed.")
            configure_netdata_lightweight(self.root, data.get("enabled"))
            ensure_netdata_service(self.root)
            running = subprocess.run(["rc-service", "netdata", "status"], capture_output=True, check=False, timeout=10).returncode == 0
            if running: self.run(["rc-service", "netdata", "restart"])
            return {"ok": True}
        if action in {"netdata_enable", "netdata_disable"}:
            if not state.get("complete"): raise ValueError("Finish setup before changing services.")
            ensure_netdata_service(self.root)
            if action == "netdata_enable":
                self.run(["rc-update", "add", "netdata", "default"])
                running = False
                try:
                    with urllib.request.urlopen("http://127.0.0.1:19999/api/v1/info", timeout=.8): running = True
                except OSError: pass
                if not running: self.run(["rc-service", "netdata", "start"])
            else:
                self.run(["rc-service", "netdata", "stop"])
                cli = self.root / "opt/netdata/bin/netdatacli"
                if cli.is_file():
                    subprocess.run([str(cli), "shutdown-agent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                self.run(["rc-update", "del", "netdata", "default"])
            return {"ok": True}
        if action in {"roon_start", "roon_stop", "roon_restart"}:
            if not state.get("complete"): raise ValueError("Finish setup before changing services.")
            ensure_roon_bridge_service(self.root)
            if action == "roon_start":
                self.run(["rc-update", "add", "roonbridge", "default"])
                self.run(["rc-service", "roonbridge", "start"])
            elif action == "roon_stop":
                self.run(["rc-service", "roonbridge", "stop"])
                self.run(["rc-update", "del", "roonbridge", "default"])
            else:
                self.run(["rc-service", "roonbridge", "restart"])
            return {"ok": True}
        if action in {"airplay_start", "airplay_stop", "airplay_restart", "airplay_configure"}:
            if not state.get("complete"): raise ValueError("Finish setup before changing services.")
            if not (self.root / "usr/bin/shairport-sync").is_file(): raise ValueError("AirPlay is not installed on this appliance.")
            if action == "airplay_configure":
                name = configure_airplay(self.root, data.get("name", ""))
                self.run(["rc-service", "shairport-sync", "restart"])
                return {"ok": True, "name": name}
            if action == "airplay_start":
                self.run(["rc-update", "add", "shairport-sync", "default"])
                self.run(["rc-service", "shairport-sync", "start"])
            elif action == "airplay_stop":
                self.run(["rc-service", "shairport-sync", "stop"])
                self.run(["rc-update", "del", "shairport-sync", "default"])
            else:
                self.run(["rc-service", "shairport-sync", "restart"])
            return {"ok": True}
        if action == "roon_install":
            if not state.get("complete"): raise ValueError("Finish setup before installing Roon Bridge.")
            if (self.root / "opt/RoonBridge/start.sh").is_file(): raise ValueError("Roon Bridge is already installed.")
            if not self.roon_install_lock.acquire(blocking=False): return {"ok": True, "queued": False}
            status = self.root / "var/lib/pi-home/roonbridge-install-status"; status.parent.mkdir(parents=True, exist_ok=True)
            atomic(status, "Roon Bridge installation queued…\n")
            threading.Thread(target=self.install_roon_bridge, daemon=True).start()
            return {"ok": True, "queued": True}
        if action == "airplay_install":
            if not state.get("complete"): raise ValueError("Finish setup before installing AirPlay.")
            if (self.root / "usr/bin/shairport-sync").is_file(): raise ValueError("AirPlay is already installed.")
            if not self.airplay_install_lock.acquire(blocking=False): return {"ok": True, "queued": False}
            status = self.root / "var/lib/pi-home/airplay-install-status"; status.parent.mkdir(parents=True, exist_ok=True)
            atomic(status, "AirPlay installation queued…\n")
            threading.Thread(target=self.install_airplay, daemon=True).start()
            return {"ok": True, "queued": True}
        if action in {"netdata_claim", "netdata_claim_command", "netdata_disconnect"}:
            if not state.get("complete"): raise ValueError("Finish setup before changing Netdata Cloud.")
            if not (self.root / "etc/init.d/netdata").is_file(): raise ValueError("Netdata is not installed.")
            if action == "netdata_claim_command":
                token, rooms, claim_url = parse_netdata_connection_command(data.get("command"))
                room_values = rooms.split(",") if rooms else []
            elif action == "netdata_claim":
                token = str(data.get("token", "")).strip(); rooms = str(data.get("rooms", "")).strip()
                claim_url = "https://app.netdata.cloud"
                if not 8 <= len(token) <= 512 or any(character.isspace() or ord(character) < 33 for character in token):
                    raise ValueError("Enter the claim token shown by Netdata Cloud.")
                room_values = [value.strip() for value in rooms.split(",") if value.strip()]
                if any(not re.fullmatch(r"[A-Za-z0-9._:-]{4,128}", value) for value in room_values):
                    raise ValueError("Enter valid Netdata Room IDs, separated by commas.")
            operation_status = self.root / "var/lib/pi-home/netdata-operation-status"
            operation_status.parent.mkdir(parents=True, exist_ok=True)
            atomic(operation_status, "Applying Netdata Cloud connection settings…\n")
            if action in {"netdata_claim", "netdata_claim_command"}:
                packages = []
                if not (self.root / "usr/bin/openssl").is_file(): packages.append("openssl")
                if not any((self.root / path).exists() for path in ("usr/bin/curl", "usr/bin/wget")): packages.append("curl")
                if packages:
                    atomic(operation_status, "Installing Netdata Cloud connection support…\n")
                    self.run(["apk", "add", "--no-cache", *packages])
            self.run(["rc-service", "netdata", "stop"])
            try:
                if action == "netdata_disconnect":
                    claim = self.root / "etc/netdata/claim.conf"
                    if claim.exists() and not claim.is_symlink(): claim.unlink()
                cloud = self.root / "var/lib/netdata/cloud.d"
                if cloud.exists():
                    if cloud.is_symlink() or not cloud.is_dir(): raise ValueError("Netdata Cloud identity needs manual repair.")
                    shutil.rmtree(cloud)
                if action in {"netdata_claim", "netdata_claim_command"}:
                    joined_rooms = ",".join(room_values)
                    claim_netdata(self.root, token, joined_rooms, claim_url)
                    run_netdata_claim_helper(self.root, token, joined_rooms, claim_url)
            except Exception:
                # Claim failure must not leave local monitoring unavailable.
                self.run(["rc-service", "netdata", "start"])
                atomic(operation_status, "Netdata Cloud connection failed. The local Agent is still running.\n")
                raise
            self.run(["rc-update", "add", "netdata", "default"])
            self.run(["rc-service", "netdata", "start"])
            atomic(operation_status, "Netdata Cloud settings applied. Waiting for the Agent to connect…\n")
            return {"ok": True}
        if action in {"netdata_install", "netdata_official_install"}:
            if not state.get("complete"): raise ValueError("Finish setup before installing Netdata.")
            token, rooms, claim_url = ("", "", "https://app.netdata.cloud") if action == "netdata_install" else parse_netdata_connection_command(data.get("command"))
            if not (self.root / "usr/bin/curl").is_file():
                operation_status = self.root / "var/lib/pi-home/netdata-operation-status"
                operation_status.parent.mkdir(parents=True, exist_ok=True)
                atomic(operation_status, "Installing curl for the official Netdata installer…\n")
                self.run(["apk", "add", "--no-cache", "curl", "ca-certificates"])
            if not self.netdata_install_lock.acquire(blocking=False):
                return {"ok": True, "queued": False}
            operation_status = self.root / "var/lib/pi-home/netdata-operation-status"
            operation_status.parent.mkdir(parents=True, exist_ok=True)
            atomic(operation_status, "Downloading the official Netdata installer…\n")
            threading.Thread(target=self.install_official_netdata, args=(token, rooms, claim_url), daemon=True).start()
            return {"ok": True, "queued": True}
        if action == "device_credentials":
            if not state.get("complete"): raise ValueError("Finish setup before changing device access.")
            username = str(data.get("username", "")).strip(); password = str(data.get("password", ""))
            validate_username(username); validate_password(password)
            if password != data.get("confirmation"): raise ValueError("The two passwords do not match.")
            previous = str(state.get("username", "admin"))
            self.login_credentials(username, password, self.root, self.run)
            if previous != username:
                # Retain the account/home for recovery, but remove its login
                # credential so changing the appliance username does not leave
                # an unnoticed second local account behind.
                self.run(["passwd", "-l", previous])
            env = self.root / "etc/pi-home/secrets.env"
            text = re.sub(r"^ADMIN_USERNAME=.*$", lambda _: "ADMIN_USERNAME=" + username, read(env), flags=re.M)
            text = re.sub(r"^ADMIN_PASSWORD=.*$", lambda _: "ADMIN_PASSWORD=" + password, text, flags=re.M)
            atomic(env, text, 0o600)
            state["username"] = username; self.save(state)
            self.run(["rc-service", "sshd", "restart"])
            threading.Timer(1, lambda: self.run(["rc-service", "pi-home-api", "restart"])).start()
            return {"ok": True}
        if action == "reboot" and (state.get("complete") or state.get("orientation")):
            threading.Timer(2, lambda: self.run(["/sbin/reboot"])).start()
            return {"ok": True}
        # Authenticated web settings reuse only these validated network/name
        # actions after onboarding; other wizard steps stay locked.
        if state.get("complete") and action not in {"set_hostname", "set_wifi"}: raise ValueError("Setup is already complete.")
        if action in {"set_hostname", "set_wifi"}:
            if not state.get("complete"): raise ValueError("Finish setup before changing network settings.")
            action = {"set_hostname": "name", "set_wifi": "wifi"}[action]
        if action == "name":
            name = str(data.get("hostname", "")).lower()
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
                raise ValueError("Use 1–63 letters, numbers or hyphens; no spaces or edge hyphens.")
            self.run(["hostname", name]); atomic(self.root / "etc/hostname", name + "\n")
            self.run(["rc-service", "avahi-daemon", "restart"])
            state["hostname"] = name
        elif action == "wifi":
            ssid = str(data.get("ssid", "")); password = str(data.get("password", ""))
            if not ssid or len(ssid.encode()) > 32 or any(c in ssid + password for c in "\x00\r\n") or len(password) > 128:
                raise ValueError("Enter a valid Wi-Fi name and password.")
            args = ["nmcli", "--wait", "30", "device", "wifi", "connect", ssid]
            if password: args += ["password", password]
            self.run(args)
            if not self.connected(): raise ValueError("Wi-Fi is not connected yet. Please try again.")
            profile = self.run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", "wlan0"]).strip()
            if profile and profile != "--":
                self.run(["nmcli", "connection", "modify", profile, "802-11-wireless.powersave", "2"])
            state["network"] = True
        elif action == "network":
            if not self.connected(): raise ValueError("Connect Ethernet or Wi-Fi first.")
            state["network"] = True
        elif action == "roon":
            zone = str(data.get("zone", ""))
            if not data.get("skip"):
                if zone not in [z.get("name") for z in self.roon().get("zones", [])]:
                    raise ValueError("Authorise RoonDeck in Roon, refresh, then choose an available zone.")
            else: zone = ""
            self.setting("roon_zone_name", zone); state["roon"] = True; state["zone"] = zone
        elif action in {"orientation", "display"}:
            profile = data.get("profile"); rotation = data.get("rotation")
            if not isinstance(profile, str) or not isinstance(rotation, str) or profile not in PROFILES or rotation not in {"normal", "90", "180", "270"}:
                raise ValueError("Choose a supported display and orientation.")
            theme = data.get("theme", "roon"); timezone = data.get("timezone", "UTC")
            if theme not in ("roon", "fresh-mint") or not isinstance(timezone, str): raise ValueError("Choose a supported theme and timezone.")
            try: ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError): raise ValueError("Enter an IANA timezone, such as Europe/London or Asia/Singapore.")
            boot = self.root / "boot/config.txt"
            text = read(boot)
            text = re.sub(r"\n?# BEGIN PI HOME SETUP\n.*?# END PI HOME SETUP\n?", "\n", text, flags=re.S)
            if not Path(str(boot) + ".setup-backup").exists(): atomic(Path(str(boot) + ".setup-backup"), text)
            text = re.sub(r"^display_auto_detect=.*$", "display_auto_detect=" + ("1" if profile == "auto" else "0"), text, flags=re.M)
            overlay = PROFILES[profile]
            if overlay:
                if not (self.root / f"boot/overlays/{overlay}.dtbo").is_file(): raise ValueError("Display driver is missing from this image.")
                # Direct libinput calibration owns touch rotation. Do not add
                # kernel swaps/inversions or WL_OUTPUT mapping on top of it.
                text += f"\n# BEGIN PI HOME SETUP\n[all]\ndtoverlay={overlay}\n# END PI HOME SETUP\n"
            atomic(boot, text)
            config = self.root / "etc/pi-home"
            atomic(config / "display-profile", profile); atomic(config / "display-transform", rotation)
            atomic(config / "display-orientation", display_orientation(profile, rotation))
            state.update(orientation=True, profile=profile, rotation=rotation, display_orientation=display_orientation(profile, rotation))
            if action == "display":
                self.setting("display_theme", theme); self.setting("timezone", timezone)
                state.update(display=True, theme=theme, timezone=timezone)
        elif action == "finish":
            if not all(state.get(key) for key in ("hostname", "network", "roon", "display")):
                raise ValueError("Complete the setup steps first.")
            password = str(data.get("password", ""))
            username = str(data.get("username", "admin")).strip()
            validate_username(username)
            validate_password(password)
            if password != data.get("confirmation"):
                raise ValueError("The two passwords do not match. Please enter them again.")
            env = self.root / "etc/pi-home/secrets.env"
            text = re.sub(r"^ADMIN_USERNAME=.*$", lambda _: "ADMIN_USERNAME=" + username, read(env), flags=re.M)
            text = re.sub(r"^ADMIN_PASSWORD=.*$", lambda _: "ADMIN_PASSWORD=" + password, text, flags=re.M)
            atomic(env, text, 0o600)
            self.login_credentials(username, password, self.root, self.run)
            if data.get("ssh", True):
                self.run(["rc-update", "add", "sshd", "default"])
                self.run(["rc-service", "sshd", "start"])
            else:
                self.run(["rc-update", "del", "sshd", "default"])
                self.run(["rc-service", "sshd", "stop"])
            state["ssh"] = bool(data.get("ssh", True)); state["username"] = username
            self.run(["rc-service", "pi-home-api", "restart"])
            state["complete"] = True
        else: raise ValueError("Unknown setup action.")
        self.save(state)
        return {"ok": True, "progress": state}


    def install_tools(self):
        path = self.root / "var/lib/pi-home/tools-status"
        try:
            # Fixed allowlist only: never accept package names from HTTP clients.
            result = subprocess.run(["apk", "add", "--no-cache", "grim", "procps", "curl", "ca-certificates", "chrony", "chrony-openrc"], capture_output=True, text=True, timeout=240)
            if result.returncode: raise ValueError("Installation failed. Check the network, clock and free disk space, then retry.")
            self.run(["rc-update", "add", "chronyd", "default"])
            self.run(["rc-service", "chronyd", "start"])
            launcher = self.root / "usr/local/bin/pi-home-display-launch"
            shutil.copyfile(Path(__file__).with_name("display-launch"), launcher)
            launcher.chmod(0o755)
            atomic(path, "System tools installed. Storage, downloads, diagnostics and time sync are ready.\n")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            atomic(path, "Installation failed. Check the network, clock and free disk space, then retry.\n")
        finally:
            self.tools_lock.release()


def serve():
    install_clock_support()
    ensure_daily_update_check()
    app = Setup()
    if Path("/opt/netdata/bin/netdata").is_file():
        ensure_netdata_service(Path("/"))
        app.run(["rc-update", "add", "netdata", "default"])
    uid = pwd.getpwnam("morningbus").pw_uid
    path = Path(SOCKET)
    if path.exists():
        if not path.is_socket(): raise RuntimeError("Unexpected setup socket path")
        path.unlink()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(SOCKET); os.chmod(SOCKET, 0o600); os.chown(SOCKET, uid, -1); server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if peer[1] != uid: continue
                try:
                    message = connection.makefile("rb").readline(4097)
                    if len(message) > 4096: raise ValueError("Setup request is too large.")
                    data = json.loads(message)
                    if not isinstance(data, dict): raise ValueError("Invalid setup request.")
                    result = app.handle(data)
                except ValueError as error:
                    result = {"ok": False, "error": str(error)}
                except (TypeError, OSError, subprocess.TimeoutExpired):
                    result = {"ok": False, "error": "Could not apply this step. Check your settings and connection, then try again."}
                connection.sendall((json.dumps(result) + "\n").encode())


if __name__ == "__main__": serve()
