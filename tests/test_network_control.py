import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_bus_time_display.network_control import NetworkControl, join_reason
from pi_bus_time_display.remote_access import atomic_json
from pi_bus_time_display.server import Config, State, make_handler

ETH_UUID = '11111111-1111-4111-8111-111111111111'
WIFI_UUID = '22222222-2222-4222-8222-222222222222'


class NetworkControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.links = {'eth0': {'kind':'ethernet','state':'connected','managed':True,'uuid':ETH_UUID},
                      'wlan0': {'kind':'wifi','state':'disconnected','managed':True,'uuid':WIFI_UUID}}
        self.radio = True
        self.manager = NetworkControl(Path(self.temp.name), self.run_system); self.manager.retry_delay = 0

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

    def test_joining_wifi_never_touches_ethernet(self):
        with patch('pi_bus_time_display.network_control.time.sleep'):
            result = self.manager.handle({'operation': 'select', 'target': 'wifi', 'ssid': 'Home', 'password': 'secret-pass'})
        self.assertTrue(result['ok'])
        self.assertEqual(self.links['eth0']['state'], 'connected')
        self.assertFalse(any(args[:3] == ['nmcli', 'radio', 'wifi'] and args[3:] == ['off'] for args in self.calls))
        self.assertFalse(any(args[:2] == ['ip', 'link'] and 'down' in args for args in self.calls))
        self.assertFalse(any(args[:3] == ['nmcli', 'device', 'set'] and args[-2:] == ['managed', 'no'] for args in self.calls))
        connect = next(args for args in self.calls if args[:5] == ['nmcli', '--wait', '20', 'device', 'wifi'])
        self.assertIn('Home', connect)

    def test_failed_join_removes_the_half_made_profile_and_restores_the_previous_wifi(self):
        self.links['wlan0']['state'] = 'connected'
        base = self.run_system
        def failing(args):
            if args[:5] == ['nmcli', '--wait', '20', 'device', 'wifi']:
                self.calls.append(args); error = ValueError('x'); error.detail = 'Error: Secrets were required, but not provided.'; raise error
            return base(args)
        self.manager.run = failing
        with patch('pi_bus_time_display.network_control.time.sleep'), self.assertRaisesRegex(ValueError, 'password was not accepted'):
            self.manager.handle({'operation': 'select', 'target': 'wifi', 'ssid': 'Cafe', 'password': 'wrong'})
        self.assertIn(['nmcli', 'connection', 'delete', 'id', 'Cafe'], self.calls)
        self.assertIn(['nmcli', '--wait', '20', 'connection', 'up', 'uuid', WIFI_UUID, 'ifname', 'wlan0'], self.calls)
        self.assertEqual(self.links['eth0']['state'], 'connected')
        self.assertNotIn('wrong', json.dumps(self.manager.status()))

    def test_invalid_names_and_missing_adapter_change_nothing(self):
        for values in ({'ssid': 'x' * 40}, {'ssid': 'a\nb'}, {'ssid': 'ok', 'password': 'p' * 200}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.manager.handle({'operation': 'select', 'target': 'wifi', **values})
        del self.links['wlan0']
        with self.assertRaisesRegex(ValueError, 'No Wi-Fi adapter'):
            self.manager.handle({'operation': 'select', 'target': 'wifi', 'ssid': 'Home'})
        self.assertFalse(any(args[:3] == ['nmcli', 'radio', 'wifi'] and len(args) > 3 for args in self.calls))

    def test_choosing_a_connection_without_a_network_name_is_a_harmless_no_op(self):
        for target in ('ethernet', 'wifi'):
            self.assertTrue(self.manager.handle({'operation': 'select', 'target': target})['ok'])
        self.assertFalse(any(args[:2] == ['nmcli', 'device'] and args[2] in {'set', 'connect', 'disconnect'} for args in self.calls))

    def test_tidy_undoes_the_old_switch_so_ethernet_and_wifi_are_both_back(self):
        self.links['eth0'].update(state='unmanaged', managed=False); self.radio = False
        self.manager.config.parent.mkdir(parents=True, exist_ok=True)
        self.manager.config.write_text('[device-roondeck-ethernet]\nmanaged=0\n')
        atomic_json(self.manager.policy, {'selected': 'wifi'})
        self.manager.recover()
        self.assertFalse(self.manager.config.exists())
        self.assertTrue(self.radio); self.assertTrue(self.links['eth0']['managed'])
        self.assertEqual(self.links['eth0']['state'], 'connected')
        self.assertNotIn('selected', json.loads(self.manager.policy.read_text()) if self.manager.policy.exists() else {})
        calls = len(self.calls); self.manager.recover()
        self.assertFalse(any(args[:3] == ['nmcli', 'radio', 'wifi'] and len(args) > 3 for args in self.calls[calls:]))

    def test_status_reports_ethernet_as_primary_when_connected(self):
        self.links['wlan0']['state'] = 'connected'
        status = self.manager.status()
        self.assertEqual(status['primary'], 'ethernet')
        self.links['eth0']['state'] = 'disconnected'
        self.assertEqual(self.manager.status()['primary'], 'wifi')

    def test_old_screens_confirming_or_restoring_are_harmless(self):
        for operation in ('confirm', 'restore'):
            self.assertTrue(self.manager.handle({'operation': operation, 'token': 'stale'})['ok'])

    def test_join_failure_reasons_are_in_plain_words(self):
        error = ValueError('x'); error.detail = 'Error: No network with SSID Home found.'
        self.assertIn('not found', join_reason(error))
        error.detail = 'Connection activation failed: IP configuration could not be reserved'
        self.assertIn('no address', join_reason(error))


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
