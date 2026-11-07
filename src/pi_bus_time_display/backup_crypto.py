"""Optional AES-256-CBC encryption with PBKDF2 and encrypt-then-MAC.

The recovery password never leaves the Pi. Authenticate before decrypting.
OpenSSL is already part of the appliance; no new Python dependency is needed.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess

FORMAT = 'roondeck-encrypted-backup'
ITERATIONS = 200_000
MAX_BYTES = 40_000_000


def _cipher(payload, password, salt, decrypt=False):
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS, 64)
    env = {**os.environ, 'ROONDECK_CIPHER_PASSWORD': key[:32].hex()}
    try:
        result = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', str(ITERATIONS),
                                 '-pass', 'env:ROONDECK_CIPHER_PASSWORD', '-d' if decrypt else '-e'],
                                input=payload, capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('OpenSSL is required for encrypted backups') from None
    if result.returncode: raise ValueError('Could not decrypt the backup' if decrypt else 'Could not encrypt the backup')
    return result.stdout, key[32:]


def encrypt(bundle, password):
    if not 12 <= len(password) <= 1000: raise ValueError('Use a recovery password of 12 to 1000 characters')
    salt = secrets.token_bytes(32)
    payload, mac_key = _cipher(json.dumps(bundle).encode(), password, salt)
    return {'format': FORMAT, 'version': 1, 'salt': base64.b64encode(salt).decode(),
            'payload': base64.b64encode(payload).decode(),
            'mac': hmac.new(mac_key, b'roondeck-encrypted-backup-v1\0' + salt + payload, 'sha256').hexdigest()}


def decrypt(bundle, password):
    try:
        if bundle['format'] != FORMAT or bundle['version'] != 1 or not 12 <= len(password) <= 1000: raise ValueError()
        salt = base64.b64decode(bundle['salt'], validate=True)
        payload = base64.b64decode(bundle['payload'], validate=True)
        if len(salt) != 32 or len(payload) > MAX_BYTES: raise ValueError()
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS, 64)
        expected = hmac.new(key[32:], b'roondeck-encrypted-backup-v1\0' + salt + payload, 'sha256').hexdigest()
        if not hmac.compare_digest(expected, bundle['mac']): raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Wrong recovery password or damaged encrypted backup') from None
    raw, _ = _cipher(payload, password, salt, True)
    return json.loads(raw)
