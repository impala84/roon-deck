"""Exclusive Ethernet/Wi-Fi selection with a root-owned rollback journal.

Only the authenticated appliance helper calls this module. No profiles or
credentials are read. A detached watchdog restores the previous links unless
an administrator confirms the trial from the new connection.
"""
import fcntl
import os
from pathlib import Path
import re
import secrets
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
    def __init__(self, root=Path('/'), run=run_command, arm=None):
        self.root, self.run = Path(root), run
        self.private = self.root / 'var/lib/roondeck-network'
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.pending = self.private / 'pending.json'
        self.policy = self.private / 'selection.json'
        self.watchdog = self.private / 'watchdog.json'
        self.result = self.private / 'status.json'
        self.config = self.root / 'etc/NetworkManager/conf.d/90-roondeck-selection.conf'
        self.lock = threading.RLock()
        self.arm = arm or self.arm_watchdog

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
        saved = load_json(self.policy, {})
        result = load_json(self.result, {})
        return {'ok': True, 'hostname': socket.gethostname(), 'devices': self.devices(), 'selected': saved.get('selected', ''),
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

    def arm_watchdog(self, token):
        process = subprocess.Popen(['/usr/bin/python3', '/opt/pi-home/appliance/alpine/network_rollback.py', token],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None: break
            if load_json(self.watchdog, {}).get('token') == token: return
            time.sleep(.05)
        process.terminate()
        process.wait(timeout=2)
        raise ValueError('Network recovery did not become ready.')

    def prepare(self, target, ssid='', password=''):
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not isinstance(target, str) or target not in KINDS: raise ValueError('Choose Ethernet or Wi-Fi.')
            if not isinstance(ssid, str) or not isinstance(password, str) or len(ssid.encode()) > 32 or len(password) > 128 or any(char in ssid + password for char in ('\x00', '\n', '\r')):
                raise ValueError('Enter a valid network name and password.')
            if target != 'wifi' and (ssid or password): raise ValueError('Wi-Fi credentials can only be used with Wi-Fi.')
            if self.pending.exists(): raise ValueError('Confirm or restore the current network trial first.')
            devices = self.devices()
            choices = [item for item in devices if item['kind'] == target]
            if not choices: raise ValueError('No Ethernet adapter found.' if target == 'ethernet' else 'No Wi-Fi adapter found.')
            chosen = next((item for item in choices if item['connected']), choices[0])
            active = []
            for item in devices:
                if item['connected']:
                    value = self.run(['nmcli', '-g', 'GENERAL.CON-UUID', 'device', 'show', item['interface']])
                    if not UUID.fullmatch(value): raise ValueError('Could not record the current connection safely.')
                    active.append({'interface': item['interface'], 'uuid': value})
            token = secrets.token_hex(16)
            record = {'token': token, 'target': target, 'interface': chosen['interface'], 'deadline': time.time() + 90,
                      'devices': devices, 'active': active, 'wifi_enabled': self.run(['nmcli', 'radio', 'wifi']) == 'enabled',
                      'previous_config': self.config.read_text() if self.config.exists() else None,
                      'previous_policy': load_json(self.policy, {})}
            atomic_json(self.pending, record)
            try: self.arm(token)
            except Exception:
                self.pending.unlink(missing_ok=True)
                raise ValueError('Could not start network recovery. No connection was changed.')
            atomic_json(self.result, {'status': 'switching', 'message': 'Switching connection. Reopen this page using the device name or new IP address, then confirm within 90 seconds.'})
            try:
                threading.Thread(target=self.apply, args=(token, ssid, password), daemon=True).start()
            except Exception:
                self.pending.unlink(missing_ok=True)
                raise ValueError('Could not start the network switch. No connection was changed.')
            return {'ok': True, 'queued': True, 'token': token}

    def apply(self, token, ssid='', password=''):
        # Give the HTTP response time to leave the old interface.
        time.sleep(1)
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = load_json(self.pending, {})
            if record.get('token') != token: return
            try:
                target, interface = record['target'], record['interface']
                wired = [item['interface'] for item in record['devices'] if item['kind'] == 'ethernet']
                if target == 'ethernet':
                    self.config.unlink(missing_ok=True)
                    self.run(['nmcli', 'general', 'reload', 'conf'])
                    self.run(['nmcli', 'device', 'set', interface, 'managed', 'yes'])
                    self.run(['ip', 'link', 'set', 'dev', interface, 'up'])
                else:
                    self.run(['nmcli', 'radio', 'wifi', 'on'])
                    self.run(['nmcli', 'device', 'set', interface, 'managed', 'yes'])
                if target == 'wifi' and ssid:
                    # The radio may have just been switched on, so give it a fresh scan before asking for the network.
                    self.safe(['nmcli', 'device', 'wifi', 'rescan', 'ifname', interface]); time.sleep(3)
                    args = ['nmcli', '--wait', '20', 'device', 'wifi', 'connect', ssid, 'ifname', interface]
                    if password: args += ['password', password]
                    try: self.run(args)
                    except ValueError as error:
                        if 'no network with ssid' not in str(getattr(error, 'detail', '')).lower(): raise
                        self.safe(['nmcli', 'device', 'wifi', 'rescan', 'ifname', interface]); time.sleep(4)
                        self.run(args)
                else:
                    self.run(['nmcli', '--wait', '20', 'device', 'connect', interface])
                state = self.run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', interface])
                if not state.startswith('100'): raise ValueError('The selected connection did not become ready.')
                if target == 'ethernet':
                    self.run(['nmcli', 'radio', 'wifi', 'off'])
                else:
                    # NetworkManager 1.52 has no persistent `device managed`
                    # CLI option. Its device config persists this explicit choice.
                    content = '[device-roondeck-ethernet]\nmatch-device=type:ethernet\nmanaged=0\n'
                    atomic_text(self.config, content, 0o644)
                    self.run(['nmcli', 'general', 'reload', 'conf'])
                    for name in wired:
                        self.run(['nmcli', 'device', 'set', name, 'managed', 'no'])
                        self.run(['ip', 'link', 'set', 'dev', name, 'down'])
                atomic_json(self.result, {'status': 'trial', 'message': 'Confirm this connection within 90 seconds. The other connection is off.'})
            except Exception as error:
                reason = join_reason(error) if target == 'wifi' and ssid else ''
                if reason:
                    # A failed join leaves a half-made saved profile (often with the wrong password); remove it.
                    self.safe(['nmcli', 'connection', 'delete', 'id', ssid])
                self._restore(record, reason)

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
        atomic_json(self.result, {'status': 'restored', 'message': ('Could not join: ' + reason + ' The previous connection is back.') if reason else 'The previous network settings have been restored.'})

    def rollback(self, token):
        with self.lock, (self.private / 'transaction.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = load_json(self.pending, {})
            if record.get('token') == token: self._restore(record)

    def recover(self):
        record = load_json(self.pending, {})
        if record: self.rollback(record.get('token'))

    def handle(self, data):
        operation = data.get('operation', 'status')
        if operation == 'status': return self.status()
        if operation == 'scan': return self.scan()
        if operation == 'select': return self.prepare(data.get('target'), data.get('ssid', ''), data.get('password', ''))
        if operation == 'restore':
            record = load_json(self.pending, {})
            if not record: raise ValueError('There is no connection trial to restore.')
            self.rollback(record['token']); return {'ok': True}
        if operation == 'confirm':
            with self.lock, (self.private / 'transaction.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                record = load_json(self.pending, {})
                if not record or not secrets.compare_digest(str(data.get('token', '')), record['token']) or time.time() >= record['deadline']:
                    raise ValueError('This connection trial has expired. Wait for the previous connection to return.')
                if load_json(self.result, {}).get('status') != 'trial': raise ValueError('Wait for the connection switch to finish.')
                if not self.run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', record['interface']]).startswith('100'):
                    raise ValueError('The selected connection is no longer connected.')
                devices = self.devices()
                if record['target'] == 'ethernet' and self.run(['nmcli', 'radio', 'wifi']) != 'disabled':
                    raise ValueError('Wi-Fi is still enabled. Restore the previous connection and retry.')
                if record['target'] == 'wifi' and any(item['kind'] == 'ethernet' and (item['managed'] or item['connected']) for item in devices):
                    raise ValueError('Ethernet is still enabled. Restore the previous connection and retry.')
                if time.time() >= record['deadline']:
                    raise ValueError('This connection trial expired while checking. The previous connection will return.')
                atomic_json(self.policy, {'selected': record['target']})
                self.pending.unlink(missing_ok=True)
                atomic_json(self.result, {'status': 'ready', 'message': 'Connection saved. The other connection remains off, including after restart.'})
                return {'ok': True}
        raise ValueError('Unknown network operation.')
