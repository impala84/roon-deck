"""Detached recovery for an unconfirmed physical-network switch."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from pi_bus_time_display.network_control import NetworkControl
from pi_bus_time_display.remote_access import load_json, atomic_json

if __name__ == '__main__':
    manager = NetworkControl()
    record = load_json(manager.pending, {})
    if len(sys.argv) == 2 and record.get('token') == sys.argv[1]:
        atomic_json(manager.watchdog, {'token': sys.argv[1]})
        time.sleep(max(0, record['deadline'] - time.time()))
        manager.rollback(sys.argv[1])
