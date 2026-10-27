import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_bus_time_display.network_control import NetworkControl
from pi_bus_time_display.remote_access import atomic_json
from pi_bus_time_display.server import Config, State, make_handler

ETH_UUID = '11111111-1111-4111-8111-111111111111'
WIFI_UUID = '22222222-2222-4222-8222-222222222222'


class NetworkControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.calls, self.armed = [], []
        self.links = {'eth0': {'kind':'ethernet','state':'connected','managed':True,'uuid':ETH_UUID},
                      'wlan0': {'kind':'wifi','state':'disconnected','managed':True,'uuid':WIFI_UUID}}
        self.radio = True
        self.manager = NetworkControl(Path(self.temp.name), self.run_system, self.armed.append)

    def run_system(self, args):
        self.calls.append(args)
        if args == ['nmcli','-t','-f','DEVICE,TYPE,STATE','device','status']:
            return '\n'.join(f"{name}:{item['kind']}:{item['state']}" for name,item in self.links.items()) + '\nrdremote:wireguard:connected\nlo:loopback:connected'
        if args[:2] == ['nmcli','-g']:
            item = self.links[args[-1]]
            return {'GENERAL.AUTOCONNECT':'yes', 'GENERAL.NM-MANAGED':'yes' if item['managed'] else 'no', 'GENERAL.STATE':'100 (connected)' if item['state']=='connected' else '30 (disconnected)',
                    'GENERAL.CON-UUID':item['uuid'], 'IP4.ADDRESS':'192.168.1.42/24' if item['state']=='connected' else '', 'GENERAL.CONNECTION':'Home' if item['state']=='connected' else '--'}[args[2]]
        if args[:3] == ['nmcli','radio','wifi']:
            if len(args)>3:
                self.radio = args[3]=='on'
                if not self.radio: self.links['wlan0']['state']='disconnected'
            return 'enabled' if self.radio else 'disabled'
        if args[:3] == ['nmcli','device','set'] and args[-2] == 'managed':
            item=self.links[args[3]]; item['managed']=args[-1]=='yes'
            if not item['managed']: item['state']='unmanaged'
        if args[:5] == ['nmcli','--wait','20','device','connect']:
            self.links[args[-1]]['state']='connected'
        if args[:5] == ['nmcli','--wait','5','device','disconnect']:
            self.links[args[-1]]['state']='disconnected'
        if args[:5] == ['nmcli','--wait','20','device','wifi']:
            self.links['wlan0']['state']='connected'
        if args[:5] == ['nmcli','--wait','20','connection','up']:
            self.links[args[-1]]['state']='connected'
        return ''

    def prepare(self, target, **values):
        with patch('pi_bus_time_display.network_control.threading.Thread') as thread:
            result = self.manager.handle({'operation':'select','target':target,**values})
        self.assertTrue(result['queued']); self.assertEqual(self.armed,[result['token']])
        self.assertFalse(any(args[:3] == ['nmcli','radio','wifi'] and len(args)>3 for args in self.calls))
        return result['token']

    def apply(self, token, **values):
        with patch('pi_bus_time_display.network_control.time.sleep'):
            self.manager.apply(token, **values)

    def test_scan_lists_networks_strongest_first_without_duplicates(self):
        output='*:61:WPA2:Home: 5G\n :88:WPA2:Cafe\n :40:--:Open\n :30:WPA2:Cafe\n :70:WPA2:\n'
        with patch('pi_bus_time_display.network_control.subprocess.run') as run:
            run.return_value.returncode=0; run.return_value.stdout=output
            result=self.manager.handle({'operation':'scan'})
        self.assertEqual([item['ssid'] for item in result['networks']],['Home: 5G','Cafe','Open'])
        self.assertTrue(result['networks'][0]['in_use']); self.assertFalse(result['networks'][2]['secured'])
        self.assertEqual(result['networks'][1]['signal'],88)

    def test_scan_with_wifi_off_turns_it_on_for_the_scan_and_back_off(self):
        self.radio=False
        with patch('pi_bus_time_display.network_control.subprocess.run') as run, patch('pi_bus_time_display.network_control.time.sleep'):
            run.return_value.returncode=0; run.return_value.stdout=' :80:WPA2:Cafe\n'
            result=self.manager.handle({'operation':'scan'})
        self.assertEqual([item['ssid'] for item in result['networks']],['Cafe'])
        self.assertIn(['nmcli','radio','wifi','on'],self.calls); self.assertIn(['nmcli','radio','wifi','off'],self.calls)
        self.assertFalse(self.radio)

    def test_wifi_switch_persists_ethernet_off_and_only_confirm_commits(self):
        token=self.prepare('wifi'); self.apply(token)
        self.assertTrue(self.manager.pending.exists()); self.assertFalse(self.manager.policy.exists())
        self.assertFalse(self.links['eth0']['managed'])
        self.assertIn(['ip','link','set','dev','eth0','down'],self.calls)
        self.assertIn('match-device=type:ethernet\nmanaged=0', self.manager.config.read_text())
        self.manager.handle({'operation':'confirm','token':token})
        self.assertFalse(self.manager.pending.exists())
        self.assertEqual(self.manager.status()['selected'],'wifi')
        self.manager.rollback(token)
        self.assertFalse(self.links['eth0']['managed'])

    def test_ethernet_switch_turns_wifi_radio_off(self):
        self.links['wlan0']['state']='connected'
        token=self.prepare('ethernet'); self.apply(token)
        self.assertFalse(self.radio)
        self.manager.handle({'operation':'confirm','token':token})
        self.assertEqual(self.manager.status()['selected'],'ethernet')

    def test_unconfirmed_trial_restores_original_links_and_policy(self):
        token=self.prepare('wifi'); self.apply(token); self.manager.rollback(token)
        self.assertTrue(self.links['eth0']['managed']); self.assertEqual(self.links['eth0']['state'],'connected')
        self.assertEqual(self.links['wlan0']['state'],'disconnected')
        self.assertTrue(self.radio); self.assertFalse(self.manager.config.exists())
        self.assertFalse(self.manager.pending.exists()); self.assertEqual(self.manager.status()['status'],'restored')

    def test_startup_recovery_restores_an_interrupted_switch(self):
        token=self.prepare('wifi'); self.apply(token)
        recovered=NetworkControl(self.manager.root,self.run_system,self.armed.append); recovered.recover()
        self.assertEqual(self.links['eth0']['state'],'connected'); self.assertFalse(recovered.pending.exists())

    def test_failed_target_is_restored_before_old_link_is_disabled(self):
        token=self.prepare('wifi'); original=self.manager.run
        def fail(args):
            if args[:5]==['nmcli','--wait','20','device','connect']: raise ValueError('private system output')
            return original(args)
        self.manager.run=fail; self.apply(token)
        self.assertTrue(self.links['eth0']['managed']); self.assertEqual(self.links['eth0']['state'],'connected')
        self.assertNotIn(['ip','link','set','dev','eth0','down'],self.calls)
        self.assertNotIn('private system output',json.dumps(self.manager.status()))

    def test_invalid_or_missing_adapters_never_change_network(self):
        for target in ('vpn',';reboot',None,{},'wifi'):
            with self.subTest(target=target):
                if target=='wifi': del self.links['wlan0']
                with self.assertRaises(ValueError): self.manager.handle({'operation':'select','target':target})
        self.assertEqual(self.armed,[]); self.assertFalse(self.manager.pending.exists())

    def test_unavailable_watchdog_prevents_all_mutations(self):
        self.manager.arm=lambda token: (_ for _ in ()).throw(OSError('not ready'))
        with self.assertRaisesRegex(ValueError,'recovery'): self.manager.prepare('wifi')
        self.assertFalse(self.manager.pending.exists()); self.assertTrue(self.links['eth0']['managed'])

    def test_password_never_enters_journal_or_public_status(self):
        token=self.prepare('wifi',ssid='Test network',password='private-test-password')
        self.assertNotIn('private-test-password',self.manager.pending.read_text())
        self.apply(token,ssid='Test network',password='private-test-password')
        self.assertNotIn('private-test-password',json.dumps(self.manager.status()))
        self.assertEqual(self.manager.private.stat().st_mode & 0o777,0o700)
        self.assertEqual(self.manager.pending.stat().st_mode & 0o777,0o600)

    def test_recovery_does_not_raise_wifi_link_while_radio_is_off(self):
        self.radio=False
        token=self.prepare('wifi'); self.apply(token)
        original=self.manager.run
        def check(args):
            if args==['ip','link','set','dev','wlan0','up'] and not self.radio:
                raise ValueError('RF-kill prevents link up')
            return original(args)
        self.manager.run=check; self.manager.rollback(token)
        self.assertFalse(self.radio); self.assertFalse(self.manager.pending.exists())
        self.assertEqual(self.links['eth0']['state'],'connected')

    def test_failed_recovery_keeps_journal_for_retry(self):
        token=self.prepare('wifi'); self.apply(token)
        original=self.manager.run
        self.manager.run=lambda args: (_ for _ in ()).throw(ValueError('unavailable'))
        self.manager.rollback(token)
        self.assertTrue(self.manager.pending.exists())
        self.manager.run=original; self.manager.rollback(token)
        self.assertFalse(self.manager.pending.exists())

    def test_existing_ethernet_off_policy_is_restored_after_ethernet_trial(self):
        self.links['eth0'].update(managed=False,state='unmanaged')
        self.links['wlan0']['state']='connected'
        self.manager.config.parent.mkdir(parents=True,exist_ok=True)
        original_config='[device-roondeck-ethernet]\nmatch-device=type:ethernet\nmanaged=0\n'
        self.manager.config.write_text(original_config)
        atomic_json(self.manager.policy,{'selected':'wifi'})
        token=self.prepare('ethernet'); self.apply(token); self.manager.rollback(token)
        self.assertEqual(self.manager.config.read_text(),original_config)
        self.assertEqual(self.manager.status()['selected'],'wifi')
        self.assertFalse(self.links['eth0']['managed']); self.assertTrue(self.radio)

    def test_stale_or_expired_confirmation_cannot_commit(self):
        token=self.prepare('wifi'); self.apply(token)
        with self.assertRaises(ValueError): self.manager.handle({'operation':'confirm','token':'wrong'})
        record=json.loads(self.manager.pending.read_text()); record['deadline']=0; atomic_json(self.manager.pending,record)
        with self.assertRaises(ValueError): self.manager.handle({'operation':'confirm','token':token})
        self.assertFalse(self.manager.policy.exists())

    def test_stale_watchdog_cannot_revert_new_trial(self):
        token=self.prepare('wifi'); self.apply(token)
        self.manager.rollback('old-token'); self.assertTrue(self.manager.pending.exists())
        self.assertFalse(self.links['eth0']['managed'])

    def test_confirmation_checks_the_other_connection_really_is_off(self):
        token=self.prepare('wifi'); self.apply(token); self.links['eth0']['managed']=True
        with self.assertRaisesRegex(ValueError,'Ethernet is still enabled'):
            self.manager.handle({'operation':'confirm','token':token})
        self.assertFalse(self.manager.policy.exists())

    def test_bridges_vlans_and_vpn_profiles_are_never_selected_or_disabled(self):
        token=self.prepare('wifi'); self.apply(token)
        self.assertFalse(any('rdremote' in args or 'lo' in args for args in self.calls))


class NetworkHTTPTests(unittest.TestCase):
    def test_authentication_precedes_socket_calls_for_both_methods(self):
        with tempfile.TemporaryDirectory() as folder:
            handler_type=make_handler(State(Config(),Path(folder)),Path(folder)/'config',Path(folder)/'env',Path(folder)/'mode')
            for method in ('do_GET','do_POST'):
                handler=object.__new__(handler_type); handler.path='/api/admin/network'; handler.authorised=lambda:False
                with patch('pi_bus_time_display.server.accessory_request') as call:
                    getattr(handler,method)(); call.assert_not_called()

    def test_network_namespace_cannot_be_overridden_by_client(self):
        with tempfile.TemporaryDirectory() as folder:
            handler_type=make_handler(State(Config(),Path(folder)),Path(folder)/'config',Path(folder)/'env',Path(folder)/'mode')
            handler=object.__new__(handler_type); handler.path='/api/admin/network'; handler.authorised=lambda:True
            payload=json.dumps({'operation':'select','target':'wifi','action':'reboot'}).encode()
            handler.headers={'Content-Length':str(len(payload))};handler.rfile=io.BytesIO(payload);handler.send_json=lambda *args:None
            with patch('pi_bus_time_display.server.accessory_request',return_value={'ok':True}) as call:
                handler.do_POST(); self.assertEqual(call.call_args.kwargs,{'helper_action':'network_control'})
