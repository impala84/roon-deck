"""Real Alpine NetworkManager parsing, radio persistence, watchdog and HTTP.

Run only in a disposable --network none container. No physical adapter is
present and no Pi hardware/network acceptance is implied.
"""
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from pi_bus_time_display.network_control import NetworkControl
from pi_bus_time_display.remote_access import atomic_json, atomic_text


def main():
    assert Path('/etc/alpine-release').is_file() and os.geteuid() == 0, 'Disposable Alpine container only'
    processes = []
    with tempfile.TemporaryFile(mode='w+') as log:
        try:
            Path('/run/dbus').mkdir(parents=True,exist_ok=True)
            subprocess.run(['dbus-daemon','--system','--fork'],check=True)
            def start_nm():
                process=subprocess.Popen(['NetworkManager','--no-daemon'],stdout=log,stderr=log)
                processes.append(process)
                for _ in range(100):
                    result=subprocess.run(['nmcli','general','status'],capture_output=True,text=True,timeout=2)
                    if result.returncode == 0: return process
                    time.sleep(.05)
                raise AssertionError('NetworkManager did not start')
            nm=start_nm()
            manager=NetworkControl()
            manager.run(['nmcli','-g','GENERAL.AUTOCONNECT,GENERAL.NM-MANAGED,GENERAL.CON-UUID','device','show','lo'])
            assert manager.devices() == [], 'Run with --network none; no physical network devices should be present'
            atomic_text(manager.config,'[device-roondeck-ethernet]\nmatch-device=type:ethernet\nmanaged=0\n',0o644)
            configuration=subprocess.check_output(['NetworkManager','--print-config'],text=True)
            assert '[device-roondeck-ethernet]' in configuration and 'match-device=type:ethernet' in configuration and 'managed=0' in configuration
            manager.run(['nmcli','radio','wifi','off'])
            nm.terminate(); nm.wait(timeout=5); processes.remove(nm)
            start_nm()
            assert manager.run(['nmcli','radio','wifi']) == 'disabled', 'Wi-Fi off did not persist across NetworkManager restart'
            token='network-smoke-watchdog'
            atomic_json(manager.pending,{'token':token,'target':'ethernet','interface':'unused','deadline':time.time()+2,
                        'devices':[],'active':[],'wifi_enabled':True,'previous_config':None,'previous_policy':{}})
            manager.arm_watchdog(token)
            for _ in range(100):
                if not manager.pending.exists(): break
                time.sleep(.05)
            assert not manager.pending.exists(), 'Detached watchdog did not roll back the expired journal'
            assert manager.run(['nmcli','radio','wifi']) == 'enabled'
            progress=Path('/var/lib/pi-home-setup/progress.json');progress.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            atomic_json(progress,{'complete':True})
            helper=subprocess.Popen(['python3','/opt/pi-home/appliance/alpine/setup_service.py'],stdout=log,stderr=log)
            processes.append(helper)
            for _ in range(100):
                if helper.poll() is not None: raise AssertionError('Root helper did not start')
                if Path('/run/pi-home-setup.sock').exists(): break
                time.sleep(.05)
            account=pwd.getpwnam('morningbus')
            api=subprocess.Popen(['/opt/pi-home/.venv/bin/pi-home','--simulate','--config','/etc/pi-home/config.toml','--env','/etc/pi-home/secrets.env','--state-dir','/var/lib/pi-home','--host','127.0.0.1'],
                                  user=account.pw_uid,group=account.pw_gid,env={**os.environ,'PI_HOME_APPLIANCE_PLATFORM':'alpine-prototype'},stdout=log,stderr=log)
            processes.append(api)
            url='http://127.0.0.1:8765/api/admin/network'
            for attempt in range(100):
                try:
                    with urllib.request.urlopen(url,timeout=4) as response: status=json.load(response)
                    break
                except urllib.error.URLError:
                    if attempt == 99: raise
                    time.sleep(.05)
            assert status['ok'] and status['devices'] == []
            request=urllib.request.Request(url,data=b'{"operation":"select","target":"ethernet"}',headers={'Content-Type':'application/json'})
            try:
                urllib.request.urlopen(request,timeout=4)
                raise AssertionError('Selecting a missing adapter should fail')
            except urllib.error.HTTPError as error:
                assert error.code == 400 and 'No Ethernet adapter' in json.load(error)['error']
            assert not manager.pending.exists(), 'Invalid selection created a trial'
            print('Network smoke: real configuration parser, persisted Wi-Fi radio off, detached watchdog recovery and unprivileged HTTP/root socket passed in an isolated container; no physical links tested.')
        except Exception:
            log.seek(0); print(log.read()[-4000:]); raise
        finally:
            for process in reversed(processes): process.terminate()
            for process in reversed(processes): process.wait(timeout=5)


if __name__ == '__main__': main()
