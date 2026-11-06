"""Network helper: Ethernet is always preferred, Wi-Fi is the fallback.

NetworkManager already gives wired links a better route than Wi-Fi, so both can stay up
and nothing needs switching. This module only joins Wi-Fi networks (without touching
Ethernet), scans, reports status, and tidies up after older versions that used to turn
the other connection off. Only the authenticated appliance helper calls it.
"""
import fcntl
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time

from .remote_access import atomic_json, atomic_text, load_json

INTERFACE = re.compile(r"[A-Za-z0-9_.-]{1,15}\Z")
UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
KINDS = {'ethernet': 'ethernet', 'wifi': 'wifi'}


def run_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}, timeout=25 if 'connect' in args or 'up' in args else 3 if args[:2] in (['nmcli', '-g'], ['nmcli', '-t']) or args == ['nmcli', 'radio', 'wifi'] else 5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('Network operation timed out. The previous connection will be restored.') from error
    if result.returncode:
        error = ValueError('Could not change the connection. Check the cable or saved Wi-Fi settings.')
        error.detail = (result.stderr or result.stdout or '').strip()
        raise error
    return result.stdout.strip()


def join_reason(error):
    """Plain-words reason a Wi-Fi join failed, from nmcli's own message, so the screen can say why it went back."""
    text = str(getattr(error, 'detail', '') or error)
    low = text.lower()
    if 'no network with ssid' in low or 'not found' in low: return 'The network was not found. Check the hotspot is on and visible, and try again.'
    if 'secrets were required' in low or 'password' in low or 'psk' in low or '802-1x' in low or 'auth' in low: return 'The password was not accepted.'
    if 'timeout' in low or 'timed out' in low: return 'The network did not answer in time.'
    if 'ip configuration' in low or 'dhcp' in low: return 'Connected, but the network gave no address.'
    return text.splitlines()[0][:120] if text else 'The connection could not be made.'


class NetworkControl:
    def __init__(self, root=Path('/'), run=run_command):
        self.root, self.run = Path(root), run
        self.private = self.root / 'var/lib/roondeck-network'
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.pending = self.private / 'pending.json'
        self.policy = self.private / 'selection.json'
        self.watchdog = self.private / 'watchdog.json'
        self.result = self.private / 'status.json'
        self.config = self.root / 'etc/NetworkManager/conf.d/90-roondeck-selection.conf'
        self.lock = threading.RLock()
        self.retry_delay = 3

    def safe(self, args):
        try: return self.run(args)
        except (ValueError, OSError, subprocess.TimeoutExpired): return ''

    def devices(self):
        devices = []
        for line in self.run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status']).splitlines():
            parts = line.split(':')
            if len(parts) != 3: continue
            interface, kind, state = parts
            if kind not in KINDS or not INTERFACE.fullmatch(interface): continue
            # Only physical links; leave bridges, VLANs, VPNs and loopback alone.
            managed = self.run(['nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', interface]) == 'yes'
            try:
                speed_value = (self.root / 'sys/class/net' / interface / 'speed').read_text().strip()
                speed = speed_value + ' Mb/s' if speed_value.isdigit() else ''
            except OSError: speed = ''
            signal = ''
            if kind == 'wifi' and state == 'connected':
                scan = self.safe(['nmcli', '-t', '-f', 'IN-USE,SIGNAL,RATE', 'device', 'wifi', 'list', '--rescan', 'no', 'ifname', interface])
                for entry in scan.splitlines():
                    fields = entry.split(':', 2)
                    if len(fields) == 3 and fields[0] == '*':
                        signal = fields[1] + '%' if fields[1].isdigit() else ''
                        speed = fields[2]
                        break
            devices.append({'autoconnect': self.run(['nmcli', '-g', 'GENERAL.AUTOCONNECT', 'device', 'show', interface]) == 'yes', 'signal': signal, 'speed': speed, 'interface': interface, 'kind': kind, 'state': state, 'managed': managed,
                            'connected': state == 'connected',
                            'address': self.safe(['nmcli', '-g', 'IP4.ADDRESS', 'device', 'show', interface]),
                            'name': self.safe(['nmcli', '-g', 'GENERAL.CONNECTION', 'device', 'show', interface])})
        if len(devices) > 8: raise ValueError('Too many network adapters for automatic switching.')
        return devices

    def status(self):
        pending = load_json(self.pending, {})
        result = load_json(self.result, {})
        devices = self.devices()
        primary = next((item['kind'] for item in devices if item['kind'] == 'ethernet' and item['connected']), '') or next((item['kind'] for item in devices if item['connected']), '')
        return {'ok': True, 'hostname': socket.gethostname(), 'devices': devices, 'selected': primary, 'primary': primary,
                'saved_wifi': sum(1 for line in self.safe(['nmcli', '-t', '-f', 'TYPE', 'connection', 'show']).splitlines() if line.strip() in ('802-11-wireless', 'wifi')),
                'wifi_enabled': self.run(['nmcli', 'radio', 'wifi']) == 'enabled',
                'trial': {'token': pending.get('token', ''), 'target': pending.get('target', ''),
                          'seconds': max(0, round(pending.get('deadline', 0) - time.time()))},
                'status': result.get('status', 'idle'), 'message': result.get('message', '')}

    def scan(self):
        """Nearby Wi-Fi networks, strongest first. Names only: no saved profiles or passwords are read."""
        # The Wi-Fi radio is off while Ethernet is primary. Scanning needs it on, so turn it on for the scan and put it back after.
        was_off = self.run(['nmcli', 'radio', 'wifi']) != 'enabled'
        if was_off:
            self.run(['nmcli', 'radio', 'wifi', 'on']); time.sleep(3)
        try:
            return self._scan_list()
        finally:
            if was_off: self.safe(['nmcli', 'radio', 'wifi', 'off'])

    def _scan_list(self):
        try:
            result = subprocess.run(['nmcli', '--escape', 'no', '-t', '-f', 'IN-USE,SIGNAL,SECURITY,SSID', 'device', 'wifi', 'list', '--rescan', 'yes'],
                                    capture_output=True, text=True, env={**os.environ, 'LC_ALL': 'C'}, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('Wi-Fi scan timed out.') from error
        if result.returncode: raise ValueError('Wi-Fi scan failed.')
        seen = {}
        for line in result.stdout.splitlines():
            fields = line.split(':', 3)
            if len(fields) != 4 or not fields[3] or len(fields[3].encode()) > 32: continue
            use, signal, security, ssid = fields
            entry = {'ssid': ssid, 'signal': int(signal) if signal.isdigit() else 0, 'secured': security not in ('', '--'), 'in_use': use == '*'}
            if ssid not in seen or entry['signal'] > seen[ssid]['signal'] or entry['in_use']: seen[ssid] = entry
        return {'ok': True, 'networks': sorted(seen.values(), key=lambda item: (not item['in_use'], -item['signal']))[:20], 'message': ''}

    def join_wifi(self, ssid, password=''):
        """Join a Wi-Fi network. Ethernet is left alone; a failed join puts the previous Wi-Fi connection back."""
        if not isinstance(ssid, str) or not isinstance(password, str) or not ssid or len(ssid.encode()) > 32 or len(password) > 128 or any(char in ssid + password for char in ('\x00', '\n', '\r')):
            raise ValueError('Enter a valid network name and password.')
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            devices = self.devices()
            radios = [item for item in devices if item['kind'] == 'wifi']
            if not radios: raise ValueError('No Wi-Fi adapter found.')
            radio = next((item for item in radios if item['connected']), radios[0])
            interface = radio['interface']
            previous = ''
            if radio['connected']:
                value = self.safe(['nmcli', '-g', 'GENERAL.CON-UUID', 'device', 'show', interface])
                if UUID.fullmatch(value): previous = value
            self.run(['nmcli', 'radio', 'wifi', 'on'])
            self.run(['nmcli', 'device', 'set', interface, 'managed', 'yes'])
            try:
                # The radio may have just been switched on, so give it a fresh scan before asking for the network.
                self.safe(['nmcli', 'device', 'wifi', 'rescan', 'ifname', interface]); time.sleep(3)
                args = ['nmcli', '--wait', '20', 'device', 'wifi', 'connect', ssid, 'ifname', interface]
                if password: args += ['password', password]
                try: self.run(args)
                except ValueError as error:
                    if 'no network with ssid' not in str(getattr(error, 'detail', '')).lower(): raise
                    self.safe(['nmcli', 'device', 'wifi', 'rescan', 'ifname', interface]); time.sleep(self.retry_delay + 1)
                    self.run(args)
                if not self.run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', interface]).startswith('100'):
                    raise ValueError('The network did not become ready.')
            except Exception as error:
                reason = join_reason(error)
                # A failed join leaves a half-made saved profile (often with the wrong password); remove it.
                self.safe(['nmcli', 'connection', 'delete', 'id', ssid])
                if previous: self.safe(['nmcli', '--wait', '20', 'connection', 'up', 'uuid', previous, 'ifname', interface])
                atomic_json(self.result, {'status': 'error', 'message': 'Could not join ' + ssid + ': ' + reason})
                raise ValueError('Could not join ' + ssid + ': ' + reason) from None
            atomic_json(self.result, {'status': 'ready', 'message': 'Connected to ' + ssid + '.'})
            return {'ok': True, 'message': 'Connected to ' + ssid + '.'}

    def tidy(self):
        """Undo what the old Ethernet/Wi-Fi switch did, so both links come back and Ethernet is simply preferred."""
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            legacy = self.config.exists() or bool(load_json(self.policy, {}).get('selected'))
            if not legacy: return False
            self.config.unlink(missing_ok=True)
            self.safe(['nmcli', 'general', 'reload', 'conf'])
            self.safe(['nmcli', 'radio', 'wifi', 'on'])
            for item in self.devices():
                self.safe(['nmcli', 'device', 'set', item['interface'], 'managed', 'yes'])
                self.safe(['ip', 'link', 'set', 'dev', item['interface'], 'up'])
                if item['kind'] == 'ethernet' and not item['connected']:
                    self.safe(['nmcli', '--wait', '20', 'device', 'connect', item['interface']])
            self.policy.unlink(missing_ok=True)
            return True

    def _restore(self, record, reason=''):
        errors = []
        def restore(args):
            try: self.run(args)
            except Exception: errors.append(True)
        if record['previous_config'] is None: self.config.unlink(missing_ok=True)
        else: atomic_text(self.config, record['previous_config'], 0o644)
        restore(['nmcli', 'general', 'reload', 'conf'])
        restore(['nmcli', 'radio', 'wifi', 'on' if record['wifi_enabled'] else 'off'])
        for item in record['devices']:
            restore(['nmcli', 'device', 'set', item['interface'], 'managed', 'yes' if item['managed'] else 'no'])
            if item['managed']:
                if item['kind'] == 'ethernet' or record['wifi_enabled']:
                    restore(['ip', 'link', 'set', 'dev', item['interface'], 'up'])
                if not item['connected']:
                    self.safe(['nmcli', '--wait', '5', 'device', 'disconnect', item['interface']])
                restore(['nmcli', 'device', 'set', item['interface'], 'autoconnect', 'yes' if item.get('autoconnect', True) else 'no'])
            elif item['kind'] == 'ethernet':
                restore(['ip', 'link', 'set', 'dev', item['interface'], 'down'])
        for item in record['active']:
            restore(['nmcli', '--wait', '20', 'connection', 'up', 'uuid', item['uuid'], 'ifname', item['interface']])
        if errors:
            atomic_json(self.result, {'status': 'error', 'message': 'Network recovery could not finish. Use the touchscreen or local console to check connections.'})
            # Keep the journal so helper startup can retry recovery.
            return
        atomic_json(self.policy, record['previous_policy'])
        self.pending.unlink(missing_ok=True)
        atomic_json(self.result, {'status': 'restored', 'message': ('Could not switch: ' + reason + ' The previous connection is back.') if reason else 'The previous network settings have been restored.'})

    def rollback(self, token):
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = load_json(self.pending, {})
            if record.get('token') == token: self._restore(record)

    def recover(self):
        """At startup: finish an interrupted switch from an older version, then undo its leftovers."""
        record = load_json(self.pending, {})
        if record: self.rollback(record.get('token'))
        self.tidy()

    def handle(self, data):
        operation = data.get('operation', 'status')
        if operation == 'status': return self.status()
        if operation == 'scan': return self.scan()
        if operation in ('select', 'join'):
            ssid = data.get('ssid', '')
            if ssid: return self.join_wifi(ssid, data.get('password', ''))
            # Choosing Ethernet or Wi-Fi without a network name has nothing left to switch: Ethernet is used whenever it is plugged in.
            self.tidy(); return {'ok': True}
        # Old screens may still send these; there is no longer a trial to keep or undo.
        if operation in ('restore', 'confirm'):
            record = load_json(self.pending, {})
            if record: self.rollback(record['token'])
            self.tidy(); return {'ok': True}
        raise ValueError('Unknown network operation.')
