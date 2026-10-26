"""Optional appliance accessories. Called only by the authenticated root helper.

WireGuard secrets stay in root-owned NetworkManager profiles. Never execute
wg-quick hooks or return command output on failure.
"""
from __future__ import annotations

import base64
import configparser
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

PROFILE = "roondeck-remote"
INTERFACE = "rdremote"
ADDRESS = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\Z")
DEFAULT_DIAL = {"enabled": False, "address": "", "target": "selected", "output_id": "", "sensitivity": "normal",
                "acceleration": False, "maximum_volume": None, "single": "playpause", "double": "next", "long": "mute"}
ACTIONS = {"status", "install", "features_save", "vpn_import", "vpn_connect", "vpn_confirm", "vpn_disconnect", "diagnostics",
           "bluetooth_scan", "bluetooth_pair", "bluetooth_connect", "bluetooth_disconnect", "bluetooth_forget", "dial_save"}


def run_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=50)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("The system operation is unavailable or timed out.") from exc
    if result.returncode:
        raise ValueError("The system operation failed. Check the connection and try again.")
    # bluetoothctl may return zero even when its operation failed.
    if args[0] == "bluetoothctl" and "No default controller" in result.stdout:
        raise ValueError("The Bluetooth adapter is unavailable. Check the Pi Bluetooth radio and firmware.")
    if args[0] == "bluetoothctl" and re.search(r"failed|not available", result.stdout, re.I):
        raise ValueError("Bluetooth operation failed. Put the Dial in pairing mode and retry.")
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout).strip()


def atomic_json(path, data, mode=0o600):
    atomic_text(path, json.dumps(data) + "\n", mode)


def atomic_text(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".roondeck-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def load_json(path, default):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def boolean(data, key, default=False):
    value = data.get(key, default)
    if type(value) is not bool: raise ValueError("Choose an enabled or disabled setting.")
    return value


def host(value):
    value = str(value).strip()
    if not value: return ""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if len(value) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
            raise ValueError("Enter an IP address or hostname.")
        return value


def key(value):
    try:
        if len(base64.b64decode(value, validate=True)) == 32: return value
    except (ValueError, TypeError):
        pass
    raise ValueError("The WireGuard profile contains an invalid key.")


def parse_profile(text, mode="full", subnets=""):
    if not isinstance(text, str) or len(text.encode()) > 16384 or "\x00" in text:
        raise ValueError("Choose a WireGuard configuration smaller than 16 KB.")
    if mode not in {"full", "split"}: raise ValueError("Choose Full Tunnel or Split Tunnel.")
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(text)
    except configparser.Error as exc:
        raise ValueError("Invalid WireGuard configuration. This beta supports one Interface and one Peer.") from exc
    if set(config.sections()) != {"Interface", "Peer"} or config.defaults():
        raise ValueError("The profile must contain exactly one Interface and one Peer.")
    interface, peer = config["Interface"], config["Peer"]
    if set(interface) - {"privatekey", "address", "dns", "mtu", "listenport"} or set(peer) - {"publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive"}:
        raise ValueError("Profile hooks and custom routing commands are not supported. Import a plain UniFi client profile.")
    try:
        addresses = [ipaddress.ip_interface(x.strip()) for x in interface["address"].split(",")]
        if not addresses or len(addresses) > 8: raise ValueError()
        dns = [str(ipaddress.ip_address(x.strip())) for x in interface.get("dns", "").split(",") if x.strip()]
        routes = [str(ipaddress.ip_network(x.strip(), strict=False)) for x in (subnets if mode == "split" else peer["allowedips"]).split(",") if x.strip()]
        if not routes or len(routes) > 32: raise ValueError()
        if mode == "split" and any(ipaddress.ip_network(x).prefixlen == 0 for x in routes): raise ValueError()
        if mode == "full" and not any(ipaddress.ip_network(x).prefixlen == 0 for x in routes):
            raise ValueError("Full Tunnel requires an AllowedIPs default route in the imported profile.")
        endpoint = peer["endpoint"].strip()
        endpoint_host, port = endpoint.rsplit(":", 1)
        if not host(endpoint_host.strip("[]")) or not 1 <= int(port) <= 65535: raise ValueError()
        if "\n" in endpoint or "\r" in endpoint: raise ValueError()
        mtu = int(interface.get("mtu", "1420"))
        listen = int(interface.get("listenport", "0"))
        keepalive = int(peer.get("persistentkeepalive", "25"))
        if not 1280 <= mtu <= 9000 or not 0 <= listen <= 65535 or not 0 <= keepalive <= 65535: raise ValueError()
        result = {"private_key": key(interface["privatekey"].strip()), "public_key": key(peer["publickey"].strip()),
                  "preshared_key": key(peer["presharedkey"].strip()) if peer.get("presharedkey") else "",
                  "addresses": [str(x) for x in addresses], "dns": dns, "routes": routes,
                  "endpoint": endpoint, "mtu": mtu, "listen": listen, "keepalive": keepalive}
    except (KeyError, ValueError, TypeError) as exc:
        # Never echo profile text or an exception containing a key.
        raise ValueError("Check the profile keys, addresses, endpoint, routing mode and destination subnets.") from exc
    return result


def keyfile(profile, identifier):
    sections = [f"[connection]\nid={PROFILE}\nuuid={identifier}\ntype=wireguard\ninterface-name={INTERFACE}\nautoconnect=false\nautoconnect-retries=0\n",
                f"[wireguard]\nprivate-key={profile['private_key']}\nprivate-key-flags=0\nmtu={profile['mtu']}\nlisten-port={profile['listen']}\npeer-routes=true\n",
                f"[wireguard-peer.{profile['public_key']}]\nendpoint={profile['endpoint']}\nallowed-ips={';'.join(profile['routes'])};\npersistent-keepalive={profile['keepalive']}\n"]
    if profile["preshared_key"]: sections[-1] += f"preshared-key={profile['preshared_key']}\npreshared-key-flags=0\n"
    for version in (4, 6):
        addresses = [x for x in profile["addresses"] if ipaddress.ip_interface(x).version == version]
        dns = [x for x in profile["dns"] if ipaddress.ip_address(x).version == version]
        section = f"[ipv{version}]\nmethod={'manual' if addresses else 'disabled'}\n"
        section += "".join(f"address{i}={address}\n" for i, address in enumerate(addresses, 1))
        if dns: section += "dns=" + ";".join(dns) + ";\nignore-auto-dns=true\n"
        if not any(ipaddress.ip_network(x).version == version and ipaddress.ip_network(x).prefixlen == 0 for x in profile["routes"]):
            section += "never-default=true\n"
        sections.append(section)
    return "\n".join(sections)


def dial_config(data):
    if not isinstance(data, dict): raise ValueError("Invalid Dial configuration.")
    result = {name: data.get(name, default) for name, default in DEFAULT_DIAL.items()}
    result["enabled"] = boolean(data, "enabled")
    result["acceleration"] = boolean(data, "acceleration")
    address = str(result["address"]).upper()
    if address and not ADDRESS.fullmatch(address): raise ValueError("Choose a paired Surface Dial.")
    if result["enabled"] and not address: raise ValueError("Pair and select a Surface Dial first.")
    result["address"] = address
    if result["target"] not in {"selected", "output"}: raise ValueError("Choose the selected zone or a specific Roon output.")
    if not isinstance(result["output_id"], str) or len(result["output_id"]) > 128: raise ValueError("Invalid Roon output.")
    if result["target"] == "output" and not result["output_id"]: raise ValueError("Choose the local Roon Bridge output.")
    if result["sensitivity"] not in {"fine", "normal", "fast"}: raise ValueError("Choose Fine, Normal or Fast sensitivity.")
    for name in ("single", "double", "long"):
        if result[name] not in {"none", "playpause", "next", "previous", "mute"}: raise ValueError("Unknown Dial action.")
    limit = result["maximum_volume"]
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (float, int)) or not math.isfinite(limit) or not -150 <= limit <= 100):
        raise ValueError("Maximum volume must be a number in the Roon output's volume units, or blank.")
    return result


class AccessoryManager:
    def __init__(self, root=Path("/"), run=run_command, arm=None):
        self.root, self.run = Path(root), run
        self.private = self.root / "var/lib/roondeck-remote"
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.meta_path = self.private / "settings.json"
        self.features_path = self.private / "features.json"
        self.visible_features_path = self.root / "var/lib/pi-home/accessory-features.json"
        self.pending_path = self.private / "pending.json"
        self.profile_path = self.root / f"etc/NetworkManager/system-connections/{PROFILE}.nmconnection"
        self.dial_path = self.root / "var/lib/pi-home/accessories.json"
        self.lock = threading.RLock()
        self.arm = arm or self.arm_rollback

    def safe(self, args):
        try: return self.run(args)
        except (ValueError, OSError, subprocess.TimeoutExpired): return ""

    def arm_rollback(self, token):
        subprocess.Popen([sys.executable, "/opt/pi-home/appliance/alpine/remote_rollback.py", token],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)

    def disconnect(self):
        try:
            self.run(["nmcli", "connection", "modify", PROFILE, "connection.autoconnect", "no"])
        except (ValueError, OSError, subprocess.TimeoutExpired):
            # Preserve safe boot behaviour even if NetworkManager itself died.
            if self.profile_path.exists():
                text = self.profile_path.read_text()
                text, count = re.subn(r"^autoconnect=.*$", "autoconnect=false", text, flags=re.M)
                if not count: text = text.replace("[connection]", "[connection]\nautoconnect=false", 1)
                atomic_text(self.profile_path, text)
                self.safe(["nmcli", "connection", "load", str(self.profile_path)])
        try:
            self.run(["nmcli", "--wait", "10", "connection", "down", PROFILE])
        except (ValueError, OSError, subprocess.TimeoutExpired):
            # A not-active profile is already safe. If NetworkManager cannot
            # remove our active interface, remove only that owned interface.
            if (self.root / "sys/class/net" / INTERFACE).exists():
                self.run(["ip", "link", "delete", "dev", INTERFACE])

    def rollback(self, token):
        with self.lock, (self.private / "transaction.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending = load_json(self.pending_path, {})
            if pending.get("token") != token: return
            self.disconnect()
            self.pending_path.unlink(missing_ok=True)

    def devices(self):
        output = self.safe(["bluetoothctl", "devices"])
        devices = []
        for line in output.splitlines():
            match = re.fullmatch(r"Device ((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (.+)", line.strip())
            if not match or "surface dial" not in match[2].lower(): continue
            address = match[1].upper()
            info = self.safe(["bluetoothctl", "info", address])
            battery = re.search(r"Battery Percentage:.*?\((\d+)\)", info)
            devices.append({"address": address, "name": "Surface Dial", "connected": "Connected: yes" in info,
                            "paired": "Paired: yes" in info, "battery": int(battery[1]) if battery else None})
            if len(devices) >= 8: break
        return devices

    def status(self):
        meta = load_json(self.meta_path, {})
        features = load_json(self.features_path, {})
        pending = load_json(self.pending_path, {})
        handshake = self.safe(["wg", "show", INTERFACE, "latest-handshakes"]) if features.get("vpn") else ""
        dates = [int(x.split()[-1]) for x in handshake.splitlines() if x.split() and x.split()[-1].isdigit()]
        newest = max(dates, default=0)
        active = features.get("vpn") is True and self.safe(["nmcli", "-g", "GENERAL.STATE", "device", "show", INTERFACE]).startswith("100")
        transfer = self.safe(["wg", "show", INTERFACE, "transfer"]) if features.get("vpn") else ""
        counters = [x.split() for x in transfer.splitlines() if len(x.split()) == 3 and all(y.isdigit() for y in x.split()[1:])]
        try: dial = dial_config(load_json(self.dial_path, DEFAULT_DIAL))
        except ValueError: dial = dict(DEFAULT_DIAL)
        return {"ok": True, "features": {name: features.get(name) is True for name in ("vpn", "dial")},
                "installed": (self.root / "usr/bin/bluetoothctl").exists() and (self.root / "usr/bin/wg").exists(),
                "bluetooth_adapter": bool(self.safe(["bluetoothctl", "list"])) if features.get("dial") else False,
                "vpn": {"configured": self.profile_path.exists(), "active": active,
                        "status": "Connected" if active and newest and time.time() - newest < 180 else "Connecting" if active else "Disconnected",
                        "address": self.safe(["nmcli", "-g", "IP4.ADDRESS,IP6.ADDRESS", "device", "show", INTERFACE]) if active else "",
                        "endpoint": meta.get("endpoint", ""), "mode": meta.get("mode", "full"), "subnets": meta.get("subnets", ""),
                        "auto_connect": meta.get("auto_connect", False), "home_server": meta.get("home_server", ""), "home_gateway": meta.get("home_gateway", ""),
                        "handshake_age": max(0, round(time.time() - newest)) if newest else None,
                        "received": sum(int(x[1]) for x in counters), "sent": sum(int(x[2]) for x in counters),
                        "pending_token": pending.get("token", ""), "confirm_seconds": max(0, round(pending.get("deadline", 0) - time.time()))},
                "dial": dial, "devices": self.devices() if features.get("dial") else [],
                "dial_status": str(load_json(self.root / "var/lib/pi-home/dial-status.json", {}).get("message", "Not running"))[:200],
                "haptics_supported": False}

    def handle(self, data):
        with self.lock:
            # Bluetooth discovery/package installation and status reads must
            # never delay the independent routing rollback watchdog.
            if str(data.get("operation", "status")).startswith("vpn_"):
                with (self.private / "transaction.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    return self._handle(data)
            return self._handle(data)

    def _handle(self, data):
        with self.lock:
            action = data.get("operation", "status")
            if action not in ACTIONS: raise ValueError("Unknown accessory operation.")
            if action == "status": return self.status()
            if action == "features_save":
                values = data.get("features", {})
                if not isinstance(values, dict): raise ValueError("Choose supported optional features.")
                features = {name: boolean(values, name) for name in ("vpn", "dial")}
                if not features["vpn"]:
                    if self.profile_path.exists(): self.disconnect()
                    self.pending_path.unlink(missing_ok=True)
                if not features["dial"]:
                    try: config = dial_config(load_json(self.dial_path, DEFAULT_DIAL))
                    except ValueError: config = dict(DEFAULT_DIAL)
                    config["enabled"] = False
                    atomic_json(self.dial_path, dial_config(config), 0o644)
                    self.safe(["rc-service", "roondeck-dial", "stop"])
                    self.safe(["rc-update", "del", "roondeck-dial", "default"])
                # Only the backend enables support. The readable copy is for
                # touchscreen visibility; operations enforce the root copy.
                atomic_json(self.features_path, features)
                atomic_json(self.visible_features_path, features, 0o644)
                return {"ok": True}
            if action == "install":
                self.run(["apk", "add", "--no-cache", "bluez", "bluez-openrc", "linux-firmware-brcm", "wireguard-tools-wg"])
                source = Path(__file__).resolve().parents[2] / "appliance/alpine/init.d/roondeck-dial"
                # Installed Python modules live in the venv; service templates
                # always come from the active application, including upgrades.
                if not source.is_file(): source = self.root / "opt/pi-home/appliance/alpine/init.d/roondeck-dial"
                atomic_text(self.root / "etc/init.d/roondeck-dial", source.read_text(), 0o755)
                # No pairing, Dial service, VPN, or Roon Bridge changes here.
                return {"ok": True}
            features = load_json(self.features_path, {})
            feature = "vpn" if action.startswith("vpn_") or action == "diagnostics" else "dial"
            if features.get(feature) is not True:
                raise ValueError("Enable this feature in web Settings first.")
            if action == "vpn_import":
                if self.pending_path.exists() or self.status()["vpn"]["active"]: raise ValueError("Disconnect Remote Access before replacing its profile.")
                mode = data.get("mode", "full")
                profile = parse_profile(data.get("profile"), mode, str(data.get("subnets", "")))
                meta = {"mode": mode, "subnets": ", ".join(profile["routes"]) if mode == "split" else "",
                        "endpoint": profile["endpoint"], "auto_connect": boolean(data, "auto_connect"),
                        "home_server": host(data.get("home_server", "")), "home_gateway": host(data.get("home_gateway", ""))}
                atomic_text(self.profile_path, keyfile(profile, str(uuid.uuid4())))
                self.run(["nmcli", "connection", "load", str(self.profile_path)])
                atomic_json(self.meta_path, meta)
                return {"ok": True}
            if action == "vpn_connect":
                if not self.profile_path.exists(): raise ValueError("Import a WireGuard profile first.")
                if self.pending_path.exists(): raise ValueError("Confirm or disconnect the current trial first.")
                self.run(["nmcli", "connection", "modify", PROFILE, "connection.autoconnect", "no"])
                token = secrets.token_hex(16)
                atomic_json(self.pending_path, {"token": token, "deadline": time.time() + 90})
                try:
                    self.arm(token)
                    self.run(["nmcli", "--wait", "20", "connection", "up", PROFILE])
                except Exception:
                    self.disconnect()
                    self.pending_path.unlink(missing_ok=True)
                    raise ValueError("Remote Access could not connect; the trial has been cancelled.") from None
                return {"ok": True, "pending_token": token, "confirm_seconds": 90}
            if action == "vpn_confirm":
                pending = load_json(self.pending_path, {})
                token = str(data.get("token", ""))
                if not pending or not secrets.compare_digest(token, pending.get("token", "")) or time.time() >= pending.get("deadline", 0):
                    raise ValueError("The connection trial expired. Connect again.")
                if not self.status()["vpn"]["active"]: raise ValueError("Remote Access is not connected.")
                auto = load_json(self.meta_path, {}).get("auto_connect", False)
                self.run(["nmcli", "connection", "modify", PROFILE, "connection.autoconnect", "yes" if auto else "no"])
                self.pending_path.unlink(missing_ok=True)
                return {"ok": True}
            if action == "vpn_disconnect":
                if self.profile_path.exists():
                    self.disconnect()
                self.pending_path.unlink(missing_ok=True)
                return {"ok": True}
            if action == "diagnostics":
                meta = load_json(self.meta_path, {})
                result = {name: bool(self.safe(["ping", "-c", "1", "-W", "2", value])) if value else None
                          for name, value in (("home_server_reachable", host(meta.get("home_server", ""))), ("home_gateway_reachable", host(meta.get("home_gateway", ""))))}
                result["roon_bridge_running"] = bool(self.safe(["rc-service", "roonbridge", "status"]))
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8766/api/state", timeout=2) as response: roon = json.load(response)
                    result["roon_connected"] = bool(roon.get("connected"))
                except (OSError, ValueError): result["roon_connected"] = False
                return {"ok": True, "diagnostics": result, "note": "Tunnel connectivity does not prove Roon Bridge discovery or audio playback."}
            if action == "bluetooth_scan":
                self.run(["rc-service", "bluetooth", "start"])
                self.run(["bluetoothctl", "power", "on"])
                self.run(["bluetoothctl", "--timeout", "8", "scan", "on"])
                return {"ok": True, "devices": self.devices()}
            if action.startswith("bluetooth_"):
                address = str(data.get("address", "")).upper()
                if not ADDRESS.fullmatch(address) or address not in {x["address"] for x in self.devices()}: raise ValueError("Choose a discovered Surface Dial.")
                if action == "bluetooth_pair":
                    self.run(["bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "30", "pair", address])
                    self.run(["bluetoothctl", "trust", address])
                    self.run(["bluetoothctl", "connect", address])
                    self.run(["rc-update", "add", "bluetooth", "default"])
                else:
                    verb = {"bluetooth_connect": "connect", "bluetooth_disconnect": "disconnect", "bluetooth_forget": "remove"}[action]
                    self.run(["bluetoothctl", verb, address])
                if action in {"bluetooth_disconnect", "bluetooth_forget"}:
                    config = load_json(self.dial_path, DEFAULT_DIAL)
                    if config.get("address") == address:
                        config["enabled"] = False
                        if action == "bluetooth_forget": config["address"] = ""
                        atomic_json(self.dial_path, config, 0o644)
                        self.safe(["rc-service", "roondeck-dial", "stop"])
                        self.safe(["rc-update", "del", "roondeck-dial", "default"])
                return {"ok": True}
            if action == "dial_save":
                config = dial_config(data.get("config", {}))
                if config["enabled"] and config["address"] not in {x["address"] for x in self.devices() if x["paired"]}:
                    raise ValueError("Pair the selected Dial before enabling controls.")
                atomic_json(self.dial_path, config, 0o644)
                if config["enabled"]:
                    self.run(["rc-update", "add", "bluetooth", "default"])
                    self.run(["rc-update", "add", "roondeck-dial", "default"])
                    self.run(["rc-service", "roondeck-dial", "restart"])
                else:
                    self.safe(["rc-service", "roondeck-dial", "stop"])
                    self.safe(["rc-update", "del", "roondeck-dial", "default"])
                return {"ok": True}
