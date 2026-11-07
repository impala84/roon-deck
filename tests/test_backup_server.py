"""Managed backup lifecycle, isolation, retention and authenticated encryption."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from pi_bus_time_display import backup_server_client as client, backup_crypto
from pi_bus_time_display.backup import build_backup, restore_backup

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backup_server', ROOT / 'backup-server/server.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
PASSWORD = 'test-server-password-unique'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.data = self.root / 'data'; (self.data / 'ssh').mkdir(parents=True)
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.data / 'ssh/ssh_host_ed25519_key')], check=True)
        self.store = module.Store(self.data, PASSWORD)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), module.handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.admin = {'url': self.url, 'token': PASSWORD}
        self.config = self.root / 'config.toml'; self.config.write_text('bus_stop_code = "12345"\n')
        self.env = self.root / 'env'; self.env.write_text('HOME_ASSISTANT_TOKEN=private-token\nADMIN_PASSWORD=excluded\n')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def paired(self, name='Lounge', old=''):
        state = self.root / (name.replace(' ', '-') + os.urandom(3).hex()); state.mkdir()
        code = client.request(self.admin, '/api/admin/pair-code', {'device': old})['code']
        client.pair(state, self.url, code, name)
        return state, client.connection(state), code

    def upload(self, conn, state, raw, name):
        (self.store.paths(conn['device'])[0] / name).write_bytes(raw)


class ManagedBackups(Fixture):
    def test_lifecycle_and_recovery_rekey_preserve_archive(self):
        state, conn, code = self.paired()
        with patch.object(client, 'upload', self.upload): name = client.run(state, self.config, self.env, '1.2')
        result = client.status(state)
        self.assertEqual(result['policy']['keep'], 14); self.assertEqual(len(result['backups']), 1)
        checked = client.restore(state, name)
        restore_backup(checked, self.root / 'restored.toml', self.root / 'restored-state')
        self.assertEqual((self.root / 'restored.toml').read_text(), self.config.read_text())
        new_state, new_conn, _ = self.paired('Replacement', conn['device'])
        self.assertEqual(new_conn['device'], conn['device'])
        self.assertEqual(len(client.status(new_state)['backups']), 1)
        with self.assertRaises(ValueError): client.request(conn, '/api/device/status')
        with self.assertRaises(ValueError): client.pair(state, self.url, code, 'Reuse')
        self.assertNotIn(conn['token'], (self.data / 'registry.json').read_text())
        self.assertEqual((new_state / 'backup-server.json').stat().st_mode & 0o777, 0o600)

    def test_device_isolation_checksums_and_retention_on_server(self):
        one, first, _ = self.paired('One'); two, second, _ = self.paired('Two')
        client.request(self.admin, '/api/admin/policy', {'policy': {**module.DEFAULT_POLICY, 'keep': 2}})
        with patch.object(client, 'upload', self.upload):
            names = [client.run(one, self.config, self.env, '1') for _ in range(3)]
            other = client.run(two, self.config, self.env, '1')
        self.assertEqual(len(client.status(one)['backups']), 2)
        with self.assertRaises(ValueError): client.restore(two, names[-1])
        with self.assertRaises(ValueError): client.restore(one, '../registry.json')
        self.assertTrue((self.store.paths(second['device'])[1] / other).is_file())
        (self.store.paths(first['device'])[1] / names[-1]).write_text('{}')
        with self.assertRaises(ValueError): client.restore(one, names[-1])
        self.assertIn('-no-del', (self.data / 'authorized_keys').read_text())
        client.request(self.admin, '/api/admin/policy', {'device': first['device'], 'policy': {**module.DEFAULT_POLICY, 'keep': 1}})
        self.assertEqual(len(client.status(one)['backups']), 1)
        self.assertEqual(len(client.status(two)['backups']), 1)

    def test_reject_incomplete_and_plaintext_credentials(self):
        state, conn, _ = self.paired()
        name = 'roondeck-backup-2026-11-07-123456-abcd1234.json'
        for bundle in ({'bad': True}, build_backup(self.config, state, self.env, '1', True)):
            raw = json.dumps(bundle).encode(); self.upload(conn, state, raw, name)
            with self.assertRaises(ValueError): client.request(conn, '/api/device/complete', {'name': name, 'sha256': hashlib.sha256(raw).hexdigest()})
        raw = json.dumps(build_backup(self.config, state, self.env, '1')).encode(); self.upload(conn, state, raw, name)
        with self.assertRaises(ValueError): client.request(conn, '/api/device/complete', {'name': name, 'sha256': '0' * 64})
        self.assertEqual(client.status(state)['backups'], [])
        # Symlinks can never turn arbitrary files into recovery points.
        path = self.store.paths(conn['device'])[0] / name; path.unlink(); path.symlink_to(self.config)
        with self.assertRaises(ValueError): client.request(conn, '/api/device/complete', {'name': name, 'sha256': '0' * 64})

    def test_encrypted_backup_requires_password_and_authenticates_restore(self):
        state, conn, _ = self.paired()
        client.request(self.admin, '/api/admin/policy', {'policy': {**module.DEFAULT_POLICY, 'include_secrets': True}})
        with self.assertRaisesRegex(ValueError, 'recovery password'): client.run(state, self.config, self.env, '1')
        client.set_password(state, 'independent-recovery-password')
        with patch.object(client, 'upload', self.upload): name = client.run(state, self.config, self.env, '1')
        raw = (self.store.paths(conn['device'])[1] / name).read_text()
        self.assertNotIn('private-token', raw)
        self.assertEqual(client.restore(state, name, 'independent-recovery-password')['secrets'], {'HOME_ASSISTANT_TOKEN': 'private-token'})
        with self.assertRaises(ValueError): client.restore(state, name, 'wrong-password-long-enough')
        envelope = json.loads(raw); envelope['mac'] = '0' * 64
        with self.assertRaises(ValueError): backup_crypto.decrypt(envelope, 'independent-recovery-password')

    def test_heartbeat_policy_persistence_failure_backoff_and_auth(self):
        state, conn, _ = self.paired()
        self.assertTrue(client.status(state)['due'])
        with patch.object(client, 'upload', self.upload): client.run(state, self.config, self.env, '1')
        before = client.fingerprint(self.config, state, self.env, '1')
        result = client.request(conn, '/api/device/heartbeat', {'fingerprint': before})
        self.assertFalse(result['due'])
        self.config.write_text('bus_stop_code = "54321"\n')
        after = client.fingerprint(self.config, state, self.env, '1')
        self.assertNotEqual(before, after)
        self.assertFalse(client.request(conn, '/api/device/heartbeat', {'fingerprint': after})['due'])
        record = self.store.db['devices'][conn['device']]; record['changed_at'] -= 121
        self.assertTrue(client.status(state)['due'])
        client.request(conn, '/api/device/report', {'error': 'NAS full'})
        self.assertFalse(client.status(state)['due'])
        restored = module.Store(self.data, PASSWORD)
        self.assertEqual(restored.db['devices'][conn['device']]['error'], 'NAS full')
        with self.assertRaises(ValueError): client.request(conn, '/api/admin/status')
        client.request(self.admin, '/api/admin/revoke', {'device': conn['device']})
        with self.assertRaises(ValueError): client.status(state)
        self.assertNotIn(record['public_key'], (self.data / 'authorized_keys').read_text())

    def test_server_requests_and_defaults_are_authoritative(self):
        state, conn, _ = self.paired()
        client.request(self.admin, '/api/admin/policy', {'policy': {**module.DEFAULT_POLICY, 'enabled': False, 'keep': 5}})
        self.assertFalse(client.status(state)['due'])
        client.request(self.admin, '/api/admin/run', {'device': conn['device']})
        self.assertTrue(client.status(state)['due'])
        with patch.object(client, 'upload', self.upload): client.run(state, self.config, self.env, '1')
        self.assertFalse(client.status(state)['due'])
        client.request(self.admin, '/api/admin/policy', {'device': conn['device'], 'policy': {**module.DEFAULT_POLICY, 'keep': 1}})
        self.assertEqual(client.status(state)['policy']['keep'], 1)
        client.request(self.admin, '/api/admin/use-defaults', {'device': conn['device']})
        self.assertEqual(client.status(state)['policy']['keep'], 5)

    def test_pi_http_endpoints_pair_backup_restore_and_disconnect(self):
        from pi_bus_time_display.server import State, make_handler
        from pi_bus_time_display.config import load_config
        state_dir = self.root / 'pi-state'; state_dir.mkdir()
        state = State(load_config(self.config), state_dir)
        pi = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state, self.config, self.env, state_dir / 'mode'))
        thread = threading.Thread(target=pi.serve_forever, daemon=True); thread.start()
        conn = {'url': f'http://127.0.0.1:{pi.server_port}'}
        try:
            code = client.request(self.admin, '/api/admin/pair-code', {})['code']
            client.request(conn, '/api/admin/backup-server/pair', {'url': self.url, 'code': code, 'name': 'HTTP Pi'})
            with patch.object(client, 'upload', self.upload):
                name = client.request(conn, '/api/admin/backup-server/run', {})['name']
            self.config.write_text('bus_stop_code = "54321"\n')
            client.request(conn, '/api/admin/backup-server/restore', {'name': name})
            self.assertIn('12345', self.config.read_text())
            self.assertIn('54321', json.loads((state_dir / 'before-server-restore.json').read_text())['config'])
            self.assertIn('12345', state.config.bus_stop_code)
            encrypted = backup_crypto.encrypt(build_backup(self.config, state_dir, self.env, '1'), 'test-recovery-password')
            self.config.write_text('bus_stop_code = "67890"\n')
            with self.assertRaises(ValueError): client.request(conn, '/api/admin/restore', {'encrypted': encrypted, 'password': 'wrong-recovery-password'})
            self.assertIn('67890', self.config.read_text())
            client.request(conn, '/api/admin/restore', {'encrypted': encrypted, 'password': 'test-recovery-password'})
            self.assertIn('12345', self.config.read_text())
            client.request(conn, '/api/admin/backup-server/disconnect', {})
            self.assertFalse(client.request(conn, '/api/admin/backup-server')['paired'])
        finally:
            pi.shutdown(); pi.server_close(); thread.join()

    def test_scheduler_follows_server_policy(self):
        state, conn, _ = self.paired()
        class Stop:
            calls = 0
            def wait(self, seconds):
                self.calls += 1
                return self.calls > 1
        with patch.object(client, 'upload', self.upload):
            client.schedule(state, self.config, self.env, 'scheduled', Stop())
        self.assertEqual(len(client.status(state)['backups']), 1)
        self.assertEqual(self.store.db['devices'][conn['device']]['fingerprint'], client.fingerprint(self.config, state, self.env, 'scheduled'))

    def test_policy_and_url_bounds(self):
        for bad in ({'keep': 0}, {'keep': 400}, {'enabled': 'yes'}, {'time': '25:00'}, {'unexpected': 1}, {'timezone': 'Not/AZone'}):
            with self.assertRaises(ValueError): module.policy(bad)
        for bad in ('ftp://nas', 'http://u:p@nas', 'http://nas/path', 'http://nas#fragment'):
            with self.assertRaises(ValueError): client.server_url(bad)


@unittest.skipUnless(os.getenv('ROONDECK_TEST_SSH') == '1' and os.geteuid() == 0, 'Opt-in real SSH test on disposable Linux host')
class RealSSH(Fixture):
    # Inherit the lifecycle checks too, then exercise a real OpenSSH/rrsync
    # connection. Root is used only in the disposable test daemon; production
    # explicitly forbids root and allows the unprivileged backup account.
    def test_real_rsync_forced_command_and_archive_isolation(self):
        import socket
        with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        self.store.ssh_port = port
        state, conn, _ = self.paired()
        ssh_conf = self.root / 'sshd_config'
        ssh_conf.write_text(f'''Port {port}
ListenAddress 127.0.0.1
HostKey {self.data}/ssh/ssh_host_ed25519_key
PidFile {self.root}/sshd.pid
AuthorizedKeysFile {self.data}/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin forced-commands-only
StrictModes no
UsePAM no
LogLevel ERROR
''')
        Path('/run/sshd').mkdir(exist_ok=True)
        daemon = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(ssh_conf)], stderr=subprocess.PIPE)
        original = subprocess.run
        def as_root(command, **kwargs):
            command = [arg.replace('backup@127.0.0.1:', 'root@127.0.0.1:') if isinstance(arg, str) else arg for arg in command]
            result = original(command, **kwargs)
            return result
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1): break
                except OSError: time.sleep(.05)
            with patch.object(client.subprocess, 'run', as_root):
                name = client.run(state, self.config, self.env, '1')
            self.assertEqual(len(client.status(state)['backups']), 1)
            self.assertEqual(client.restore(state, name)['config'], self.config.read_text())
            # Direct shell commands and cross-directory writes are rejected by rrsync.
            ssh = ['ssh', '-i', str(state / 'backup-ssh/id_ed25519'), '-p', str(port), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={state}/backup-ssh/server_known_hosts', 'root@127.0.0.1']
            denied = original(ssh + ['cat /etc/passwd'], capture_output=True, timeout=20)
            self.assertNotEqual(denied.returncode, 0)
            local = self.root / 'attack'; local.write_text('bad')
            transport = __import__('shlex').join(ssh[:-1])
            denied = original(['rsync', '-rt', '-e', transport, str(local), 'root@127.0.0.1:../../archives/evil'], capture_output=True, timeout=20)
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((self.data / 'archives/evil').exists())
        finally:
            daemon.terminate(); _, errors = daemon.communicate(timeout=5)
            if errors and b'Operation not permitted' in errors: self.skipTest('Host does not permit OpenSSH privilege separation')


@unittest.skipUnless(__import__('shutil').which('rsync') and __import__('shutil').which('rrsync'), 'rsync/rrsync required')
class RealRsync(Fixture):
    def test_real_upload_restricted_paths_and_no_deletion(self):
        state, conn, _ = self.paired()
        inbox, archive = self.store.paths(conn['device'])
        tools = self.root / 'tools'; tools.mkdir()
        shim = tools / 'ssh'
        shim.write_text("#!/usr/bin/env python3\nimport os,sys,shlex\na=sys.argv[1:]\ni=a.index('rsync')\nos.environ['SSH_ORIGINAL_COMMAND']=shlex.join(a[i:])\nos.execv('/usr/bin/rrsync',['rrsync','-wo','-no-del','-munge',os.environ['TEST_INBOX']])\n")
        shim.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(tools) + ':' + os.environ['PATH'], 'TEST_INBOX': str(inbox)}):
            name = client.run(state, self.config, self.env, 'real-rsync')
            self.assertEqual(client.restore(state, name)['config'], self.config.read_text())
            self.assertEqual(list(inbox.iterdir()), [])
            source = self.root / 'attack'; source.write_text('bad')
            for flags, destination in [([], '../../archives/evil'), (['--delete'], '/'), (['--remove-source-files'], '/')]:
                result = subprocess.run(['rsync', '-rt', *flags, '-e', 'ssh', str(source), 'backup@127.0.0.1:' + destination], capture_output=True, timeout=20)
                self.assertNotEqual(result.returncode, 0, result.stderr)
            # The same forced command cannot be used to download files.
            result = subprocess.run(['rsync', '-rt', '-e', 'ssh', 'backup@127.0.0.1:/', str(self.root / 'stolen')], capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((archive / name).is_file())
