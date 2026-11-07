"""Optional RoonDeck Backup Server client. Policies and retention live on server."""
import hashlib
import base64
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tempfile
import time
import threading
from functools import wraps
import urllib.error
import urllib.parse
import urllib.request

from .backup import build_backup, check_backup
from . import backup_crypto

MAX_BYTES = 40_000_000
LOCK = threading.RLock()


def serialised(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK: return fn(*args, **kwargs)
    return wrapped


def _parts_fingerprint(parts):
    result = hashlib.sha256()
    for name, content_hash in sorted(parts):
        result.update(name.encode() + b'\0' + content_hash)
    return result.hexdigest()


def fingerprint(config_path, state_dir, env_path, version):
    # Hash one file at a time; do not allocate the full base64 artwork bundle on
    # every heartbeat, particularly on a 1 GB Pi.
    from .backup import ART_NAME, MAX_ART, MAX_ART_BYTES
    paths = [('config', config_path), *[(name, state_dir / name) for name in ('listening.json', 'home-layout.json')]]
    art = state_dir / 'deck-art'
    if art.is_dir():
        paths += [('art/' + p.name, p) for p in sorted(art.glob('*.png'))[:MAX_ART]
                  if ART_NAME.fullmatch(p.name) and p.is_file() and p.stat().st_size <= MAX_ART_BYTES]
    parts = [('config', hashlib.sha256(b'').digest())] if not config_path.is_file() else []
    for name, path in paths:
        if path.is_file(): parts.append((name, hashlib.sha256(path.read_bytes()).digest()))
    return _parts_fingerprint(parts)


def bundle_fingerprint(bundle):
    parts = [('config', hashlib.sha256(bundle['config'].encode()).digest())]
    parts += [(name, hashlib.sha256(text.encode()).digest()) for name, text in bundle['files'].items()]
    parts += [('art/' + name, hashlib.sha256(base64.b64decode(text)).digest()) for name, text in bundle['art'].items()]
    return _parts_fingerprint(parts)


def write_private(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.backup-')
    try:
        with os.fdopen(fd, 'w') as handle: json.dump(data, handle)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def connection(state_dir):
    try: return json.loads((state_dir / 'backup-server.json').read_text())
    except (OSError, ValueError): return {}


def server_url(url):
    text = str(url).strip().rstrip('/')
    if text and '://' not in text: text = 'http://' + text
    parts = urllib.parse.urlsplit(text)
    try: port = parts.port
    except ValueError: port = None
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {'', '/'}:
        raise ValueError('Enter the server address, such as synology.local:8042')
    netloc = parts.netloc if port or parts.scheme == 'https' else parts.netloc + ':8042'
    return urllib.parse.urlunsplit((parts.scheme, netloc, '', '', ''))


def request(conn, path, data=None):
    headers = {'Authorization': 'Bearer ' + conn.get('token', ''), 'Content-Type': 'application/json'}
    req = urllib.request.Request(conn['url'] + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as reply:
            raw = reply.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES: raise ValueError('The backup exceeds the size limit')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ValueError('Server refused the request. Check pairing and the selected backup.') from error
    except (OSError, urllib.error.URLError) as error:
        raise ValueError('Could not reach RoonDeck Backup Server') from error


@serialised
def pair(state_dir, url, code, name):
    from .remote_backup import ensure_ssh_key
    url = server_url(url)
    result = request({'url': url}, '/api/pair', {'code': ''.join(str(code).split()), 'name': str(name).strip()[:80] or socket.gethostname(), 'public_key': ensure_ssh_key(state_dir)})
    device, key, port = result.get('device', ''), result.get('host_key', ''), result.get('ssh_port')
    if not re.fullmatch(r'[a-f0-9]{32}', device) or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+', key) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid server pairing response')
    host = urllib.parse.urlsplit(url).hostname
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,250}', host): raise ValueError('Use a DNS name or IPv4 address for the backup server')
    conn = {'url': url, 'device': device, 'token': result['token'], 'host': host, 'ssh_port': port}
    known = state_dir / 'backup-ssh' / 'server_known_hosts'
    known.write_text(f'[{host}]:{port} {key}\n' if port != 22 else f'{host} {key}\n'); known.chmod(0o600)
    write_private(state_dir / 'backup-server.json', conn)
    return {'paired': True, 'device': device}


def status(state_dir):
    conn = connection(state_dir)
    if not conn: return {'paired': False}
    result = request(conn, '/api/device/status')
    result.update(paired=True, url=conn['url'], device=conn['device'], encryption_password_set=(state_dir / 'backup-recovery-password.json').is_file())
    return result


def set_password(state_dir, password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1000: raise ValueError('Use a recovery password of 12 to 1000 characters')
    write_private(state_dir / 'backup-recovery-password.json', {'password': password})


def upload(conn, state_dir, payload, filename):
    from .remote_backup import ssh_key_path
    with tempfile.TemporaryDirectory(prefix='roondeck-upload-') as folder:
        source = Path(folder) / filename
        source.write_bytes(payload); source.chmod(0o600)
        ssh = shlex.join(['ssh', '-i', str(ssh_key_path(state_dir)), '-p', str(conn['ssh_port']), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={state_dir / "backup-ssh" / "server_known_hosts"}'])
        try:
            result = subprocess.run(['rsync', '-rt', '--no-links', '--chmod=F600,D700', '-e', ssh, str(source), f'backup@{conn["host"]}:/'], capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired): raise ValueError('Could not upload through rsync. Check rsync and SSH are installed.') from None
        if result.returncode: raise ValueError('rsync upload failed. Check pairing and the server SSH port.')


@serialised
def run(state_dir, config_path, env_path, version):
    conn = connection(state_dir)
    if not conn: raise ValueError('Pair with RoonDeck Backup Server first')
    policy = request(conn, '/api/device/status')['policy']
    password = ''
    if policy['include_secrets']:
        try: password = json.loads((state_dir / 'backup-recovery-password.json').read_text())['password']
        except (OSError, ValueError, KeyError): raise ValueError('Set a recovery password on this Pi before enabling encrypted credential backups') from None
    bundle = build_backup(config_path, state_dir, env_path, version, bool(password))
    snapshot_fingerprint = bundle_fingerprint(bundle)
    contents = {'streamdeck': 'listening.json' in bundle['files'], 'home_layout': 'home-layout.json' in bundle['files'], 'images': len(bundle['art']), 'credentials': bool(password)}
    if password: bundle = backup_crypto.encrypt(bundle, password)
    payload = json.dumps(bundle).encode()
    if len(payload) > MAX_BYTES: raise ValueError('Backup exceeds the 40 MB limit')
    name = 'roondeck-backup-' + time.strftime('%Y-%m-%d-%H%M%S', time.gmtime()) + '-' + os.urandom(4).hex() + '.json'
    upload(conn, state_dir, payload, name)
    request(conn, '/api/device/complete', {'name': name, 'sha256': hashlib.sha256(payload).hexdigest(), 'app_version': version, 'fingerprint': snapshot_fingerprint, 'contents': contents})
    write_private(state_dir / 'backup-server-status.json', {'ok': True, 'message': name, 'time': time.time()})
    return name


def restore(state_dir, name, password=''):
    if not re.fullmatch(r'roondeck-backup-[A-Za-z0-9-]+\.json', str(name)): raise ValueError('Invalid backup name')
    bundle = request(connection(state_dir), '/api/device/backup/' + name)
    if bundle.get('format') == backup_crypto.FORMAT:
        if not password:
            try: password = json.loads((state_dir / 'backup-recovery-password.json').read_text())['password']
            except (OSError, ValueError, KeyError): raise ValueError('Enter the recovery password for this backup') from None
        bundle = backup_crypto.decrypt(bundle, password)
    return check_backup(bundle)


def schedule(state_dir, config_path, env_path, version, stop):
    while not stop.wait(30):
        conn = connection(state_dir)
        if not conn: continue
        try:
            result = request(conn, '/api/device/heartbeat', {'fingerprint': fingerprint(config_path, state_dir, env_path, version)})
            if result['due']:
                name = run(state_dir, config_path, env_path, version)
                write_private(state_dir / 'backup-server-status.json', {'ok': True, 'message': name, 'time': time.time()})
        except (ValueError, OSError, KeyError) as error:
            write_private(state_dir / 'backup-server-status.json', {'ok': False, 'message': str(error)[:240], 'time': time.time()})
            try: request(conn, '/api/device/report', {'error': str(error)[:240]})
            except ValueError: pass
