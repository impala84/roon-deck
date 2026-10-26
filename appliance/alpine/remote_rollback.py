"""Short-lived routing rollback watchdog, independent of the UI/setup helper."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pi_bus_time_display.remote_access import AccessoryManager, load_json


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9a-f]{32}", sys.argv[1]):
        raise SystemExit("Invalid connection trial")
    manager = AccessoryManager()
    token = sys.argv[1]
    pending = load_json(manager.pending_path, {})
    if pending.get("token") != token: return
    time.sleep(max(0, min(90, pending.get("deadline", 0) - time.time())))
    for attempt in range(3):
        try:
            manager.rollback(token)
            return
        except (OSError, ValueError):
            if attempt < 2: time.sleep(2)
    # Keep pending.json on failure so Settings still exposes recovery state.


if __name__ == "__main__": main()
