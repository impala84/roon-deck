#!/usr/bin/env python3
"""RoonDeck Backup Server: isolated rsync inboxes and server-owned archives.

Run behind a trusted LAN or HTTPS reverse proxy. SSH keys can only upload into
one device inbox; they cannot read, delete or alter the managed archive.
"""
import base64
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
import uuid

from pi_bus_time_display import __version__
from pi_bus_time_display.backup import check_backup
from pi_bus_time_display.backup_crypto import FORMAT as ENCRYPTED
from pi_bus_time_display.backup_server_client import write_private

MAX_BYTES = 40_000_000
NAME = re.compile(r'roondeck-backup-[A-Za-z0-9-]{10,70}\.json')
DEVICE = re.compile(r'[a-f0-9]{32}')
DEFAULT_POLICY = {'enabled': True, 'keep': 14, 'max_age_days': 0, 'time': '03:30', 'timezone': 'UTC',
                  'on_change': False, 'change_delay_seconds': 120, 'include_secrets': False}


def contents(reported, bundle, encrypted):
    """A short, safe summary of what a recovery point holds, for display only."""
    if isinstance(reported, dict):
        return {'settings': True, 'streamdeck': reported.get('streamdeck') is True, 'home_layout': reported.get('home_layout') is True,
                'images': reported['images'] if type(reported.get('images')) is int and 0 <= reported['images'] <= 1000 else 0,
                'credentials': reported.get('credentials') is True}
    if encrypted: return {'settings': True, 'credentials': True}
    files = bundle.get('files', {}); art = bundle.get('art', {})
    return {'settings': True, 'streamdeck': 'listening.json' in files, 'home_layout': 'home-layout.json' in files, 'images': len(art), 'credentials': False}


def policy(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULT_POLICY): raise ValueError('Invalid backup policy')
    result = {**DEFAULT_POLICY, **data}
    for key in ('enabled', 'on_change', 'include_secrets'):
        if type(result[key]) is not bool: raise ValueError('Invalid policy switch')
    for key, low, high in (('keep', 1, 365), ('max_age_days', 0, 3650), ('change_delay_seconds', 30, 86400)):
        if type(result[key]) is not int or not low <= result[key] <= high: raise ValueError(f'{key} must be between {low} and {high}')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(result['time'])): raise ValueError('Use HH:MM for backup time (UTC)')
    try: ZoneInfo(result['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError): raise ValueError('Enter a valid timezone, such as Asia/Singapore') from None
    return result


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, root, password, ssh_port=2222):
        if len(password) < 16: raise ValueError('Set ADMIN_PASSWORD to at least 16 characters')
        self.root, self.password, self.ssh_port = Path(root), password, ssh_port
        self.lock = threading.RLock()
        self.codes = {}
        self.attempts = {}
        self.root.mkdir(parents=True, exist_ok=True)
        try: self.db = json.loads((self.root / 'registry.json').read_text())
        except FileNotFoundError: self.db = {'policy': DEFAULT_POLICY.copy(), 'devices': {}}
        self.db['policy'] = policy(self.db['policy'])
        self.save()
        self.keys()

    def save(self): write_private(self.root / 'registry.json', self.db)

    def keys(self):
        lines = []
        for device, record in self.db['devices'].items():
            if not record.get('revoked'):
                lines.append(f'restrict,command="/usr/bin/rrsync -wo -no-del -munge {self.root}/incoming/{device}" {record["public_key"]}')
        target = self.root / 'authorized_keys'
        temp = self.root / '.authorized_keys'
        temp.write_text('\n'.join(lines) + '\n'); temp.chmod(0o600); os.replace(temp, target)

    def effective(self, record): return {**self.db['policy'], **record.get('policy', {})}

    def paths(self, device):
        if not DEVICE.fullmatch(device): raise ValueError('Invalid device')
        inbox, archive = self.root / 'incoming' / device, self.root / 'archives' / device
        inbox.mkdir(parents=True, exist_ok=True); archive.mkdir(parents=True, exist_ok=True)
        return inbox, archive

    def pair_code(self, device=''):
        if device and device not in self.db['devices']: raise ValueError('Unknown recovery device')
        self.codes = {k: v for k, v in self.codes.items() if v['expires'] > time.time()}
        code = secrets.token_hex(6).upper()
        self.codes[digest(code)] = {'device': device, 'expires': time.time() + 600}
        return {'code': code, 'expires_in': 600}

    def pair(self, data, address):
        now = time.time()
        self.attempts = {key: val for key, val in self.attempts.items() if val[0] > now - 600}
        stamp, count = self.attempts.get(address, (now, 0))
        if count >= 20: raise ValueError('Too many pairing attempts; wait ten minutes')
        self.attempts[address] = (stamp, count + 1)
        entry = self.codes.get(digest(''.join(str(data.get('code', '')).split()).upper()))
        if not entry or entry['expires'] < now: raise ValueError('Pairing code expired or incorrect')
        key = str(data.get('public_key', '')).split()
        if len(key) < 2 or key[0] != 'ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]{40,150}', key[1]): raise ValueError('Invalid SSH public key')
        decoded = base64.b64decode(key[1], validate=True)
        if len(decoded) != 51 or decoded[:19] != b'\0\0\0\x0bssh-ed25519\0\0\0\x20': raise ValueError('Invalid SSH key encoding')
        host_key = ' '.join((self.root / 'ssh' / 'ssh_host_ed25519_key.pub').read_text().split()[:2])
        device = entry['device'] or uuid.uuid4().hex
        record = self.db['devices'].get(device, {'backups': [], 'policy': {}, 'last_success': 0})
        token = secrets.token_urlsafe(32)
        record.update(name=str(data.get('name', '')).strip()[:80] or 'RoonDeck', public_key=' '.join(key[:2]), token=digest(token), revoked=False, last_seen=now, paired_at=now, error='', retry_after=0)
        self.paths(device)
        self.db['devices'][device] = record
        self.save(); self.keys()
        del self.codes[digest(''.join(str(data['code']).split()).upper())]
        return {'device': device, 'token': token, 'host_key': host_key, 'ssh_port': self.ssh_port}

    def authenticate(self, token):
        for device, record in self.db['devices'].items():
            if not record.get('revoked') and hmac.compare_digest(record['token'], digest(token)):
                return device, record
        raise PermissionError('Pair this device first')

    def status(self, record):
        p = self.effective(record); now = time.time()
        zone = ZoneInfo(p['timezone'])
        local_now = datetime.fromtimestamp(now, zone)
        daily = local_now.strftime('%H:%M') >= p['time'] and datetime.fromtimestamp(record['last_success'], zone).date() != local_now.date()
        changed = bool(record.get('candidate')) and record.get('candidate') != record.get('fingerprint') and now - record.get('changed_at', now) >= p['change_delay_seconds']
        encryption_changed = bool(record['backups']) and record['backups'][0]['encrypted'] != p['include_secrets']
        due = now >= record.get('retry_after', 0) and (record.get('requested', False) or (p['enabled'] and (not record['backups'] or daily or encryption_changed or (p['on_change'] and changed))))
        return {'name': record['name'], 'policy': p, 'due': due, 'backups': record['backups'], 'error': record.get('error', ''), 'last_success': record['last_success'], 'paired_at': record.get('paired_at', 0), 'requested': bool(record.get('requested', False))}

    def prune(self, device):
        record = self.db['devices'][device]; p = self.effective(record)
        records = sorted(record['backups'], key=lambda b: b['created'], reverse=True)
        keep = []
        for index, item in enumerate(records):
            expired = p['max_age_days'] and time.time() - item['created'] > p['max_age_days'] * 86400
            if index == 0 or (index < p['keep'] and not expired): keep.append(item)
            else: (self.paths(device)[1] / item['name']).unlink(missing_ok=True)
        record['backups'] = keep

    def complete(self, device, data):
        record = self.db['devices'][device]
        name = str(data.get('name', ''))
        if not NAME.fullmatch(name): raise ValueError('Invalid backup filename')
        inbox, archive = self.paths(device)
        source = inbox / name
        if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES: raise ValueError('Backup upload missing or too large')
        # rrsync has finished; open without following links even if an upload races.
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as handle: raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError('Backup too large')
        sha = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(sha, str(data.get('sha256', ''))): raise ValueError('Backup checksum mismatch; upload again')
        bundle = json.loads(raw)
        if not isinstance(bundle, dict): raise ValueError('Invalid backup')
        encrypted = bundle.get('format') == ENCRYPTED
        if encrypted:
            if bundle.get('version') != 1 or len(base64.b64decode(bundle.get('salt', ''), validate=True)) != 32 or not re.fullmatch(r'[a-f0-9]{64}', str(bundle.get('mac', ''))): raise ValueError('Invalid encrypted backup')
            base64.b64decode(bundle.get('payload', ''), validate=True)
        else:
            check_backup(bundle)
            if bundle.get('secrets') or bundle.get('includes_secrets'): raise ValueError('Credential backups must be encrypted')
        if self.effective(record)['include_secrets'] and not encrypted: raise ValueError('Server policy requires encryption')
        existing = next((b for b in record['backups'] if b['name'] == name), None)
        if existing and existing['sha256'] != sha: raise ValueError('A recovery point cannot be overwritten')
        if not existing:
            # Copy into a private archive: the upload account is confined to inbox.
            target = archive / name
            temp = archive / ('.' + name)
            with open(temp, 'wb') as handle: handle.write(raw)
            temp.chmod(0o600); os.replace(temp, target)
            record['backups'].append({'name': name, 'created': time.time(), 'size': len(raw), 'sha256': sha, 'encrypted': encrypted, 'app_version': str(data.get('app_version', ''))[:60], 'contents': contents(data.get('contents'), bundle, encrypted)})
        source.unlink(missing_ok=True)
        record.update(last_success=time.time(), last_seen=time.time(), error='', retry_after=0, requested=False, fingerprint=str(data.get('fingerprint', ''))[:64])
        self.prune(device); self.save()
        return {'ok': True}

    def backup(self, device, name):
        record = self.db['devices'][device]
        item = next((b for b in record['backups'] if b['name'] == name), None)
        if not item: raise ValueError('Backup not found')
        path = self.paths(device)[1] / name
        if path.is_symlink(): raise ValueError('Invalid backup path')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']: raise ValueError('Stored backup failed its checksum')
        return json.loads(raw)

    def cleanup(self):
        for device in self.db['devices']:
            self.prune(device)
            inbox, _ = self.paths(device)
            for path in inbox.iterdir():
                if (path.is_file() or path.is_symlink()) and time.time() - path.lstat().st_mtime > 86400: path.unlink()
        self.save()


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(60)

        def log_message(self, *args): pass  # Never log pairing codes, tokens or backup bodies.

        def reply(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(raw)

        def process(self, post=False):
            try:
                if self.path == '/favicon.svg' and not post:
                    raw = Path(__file__).with_name('favicon.svg').read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'image/svg+xml'); self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'public, max-age=3600'); self.end_headers(); self.wfile.write(raw); return
                if self.path == '/' and not post:
                    raw = Path(__file__).with_name('index.html').read_bytes().replace(b'__VERSION__', ('v' + __version__ + ' Alpine').encode())
                    self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                    self.end_headers(); self.wfile.write(raw); return
                token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                # No cookies: cross-site requests cannot acquire authentication.
                admin = self.path.startswith('/api/admin/')
                with store.lock:
                    if admin:
                        if not hmac.compare_digest(token, store.password): raise PermissionError('Sign in to the server')
                        device = record = None
                    elif self.path == '/api/pair' and post: device = record = None
                    else: device, record = store.authenticate(token)
                    data = {}
                    if post:
                        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': raise ValueError('JSON required')
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 8000: raise ValueError('Invalid request size')
                        data = json.loads(self.rfile.read(length))
                        if not isinstance(data, dict): raise ValueError('JSON object required')
                    if self.path == '/api/pair' and post: result = store.pair(data, self.client_address[0])
                    elif self.path == '/api/admin/status' and not post:
                        result = {'policy': store.db['policy'], 'devices': [{'device': d, 'revoked': r.get('revoked', False), 'last_seen': r.get('last_seen', 0), **store.status(r)} for d, r in store.db['devices'].items()]}
                    elif self.path == '/api/admin/pair-code' and post: result = store.pair_code(str(data.get('device', '')))
                    elif self.path == '/api/admin/policy' and post:
                        device = str(data.get('device', ''))
                        p = policy(data.get('policy'))
                        if device:
                            if device not in store.db['devices']: raise ValueError('Unknown device')
                            store.db['devices'][device]['policy'] = p
                        else: store.db['policy'] = p
                        store.cleanup(); result = {'ok': True}
                    elif self.path in {'/api/admin/run', '/api/admin/use-defaults'} and post:
                        device = str(data.get('device', ''))
                        if device not in store.db['devices']: raise ValueError('Unknown device')
                        record = store.db['devices'][device]
                        if self.path.endswith('/run'): record.update(requested=True, retry_after=0)
                        else: record['policy'] = {}; store.prune(device)
                        store.save(); result = {'ok': True}
                    elif self.path == '/api/admin/revoke' and post:
                        device = str(data.get('device', ''))
                        if device not in store.db['devices']: raise ValueError('Unknown device')
                        store.db['devices'][device]['revoked'] = True; store.save(); store.keys(); result = {'ok': True}
                    elif self.path == '/api/admin/delete' and post:
                        device, name = str(data.get('device', '')), str(data.get('name', ''))
                        if device not in store.db['devices']: raise ValueError('Unknown device')
                        r = store.db['devices'][device]
                        if not any(b['name'] == name for b in r['backups']): raise ValueError('Unknown backup')
                        (store.paths(device)[1] / name).unlink(missing_ok=True)
                        r['backups'] = [b for b in r['backups'] if b['name'] != name]; store.save(); result = {'ok': True}
                    elif self.path == '/api/admin/cleanup' and post: store.cleanup(); result = {'ok': True}
                    elif self.path == '/api/admin/download' and post: result = store.backup(str(data.get('device', '')), str(data.get('name', '')))
                    elif self.path == '/api/device/status' and not post: result = store.status(record)
                    elif self.path == '/api/device/heartbeat' and post:
                        fingerprint = str(data.get('fingerprint', ''))
                        if not re.fullmatch(r'[a-f0-9]{64}', fingerprint): raise ValueError('Invalid fingerprint')
                        if fingerprint != record.get('candidate'): record.update(candidate=fingerprint, changed_at=time.time())
                        record['last_seen'] = time.time(); store.save(); result = store.status(record)
                    elif self.path == '/api/device/complete' and post: result = store.complete(device, data)
                    elif self.path == '/api/device/report' and post:
                        record.update(error=str(data.get('error', ''))[:240], last_seen=time.time(), retry_after=time.time() + 3600); store.save(); result = {'ok': True}
                    elif self.path.startswith('/api/device/backup/') and not post: result = store.backup(device, self.path.rsplit('/', 1)[-1])
                    else: self.reply(404, {'error': 'Not found'}); return
                self.reply(200, result)
            except PermissionError as error: self.reply(401, {'error': str(error)})
            except (ValueError, TypeError, KeyError, OSError) as error: self.reply(400, {'error': str(error)[:200]})

        def do_GET(self): self.process()
        def do_POST(self): self.process(True)
    return Handler


def main():
    store = Store(os.getenv('DATA_DIR', '/data'), os.environ['ADMIN_PASSWORD'], int(os.getenv('SSH_PORT', '2222')))
    store.cleanup()
    server = ThreadingHTTPServer(('0.0.0.0', int(os.getenv('HTTP_PORT', '8042'))), handler(store))
    if os.getenv('TLS_CERT'):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(os.environ['TLS_CERT'], os.environ['TLS_KEY'])
        server.socket = context.wrap_socket(server.socket, server_side=True)
    def maintenance():
        while True:
            time.sleep(3600)
            with store.lock: store.cleanup()
    threading.Thread(target=maintenance, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__': main()
