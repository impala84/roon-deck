"""Optional per-device RGB gains; no profile means the original GTK rendering."""
import json
import math
from pathlib import Path
import sys

PROFILE = Path('/etc/pi-home/display-white-balance.json')
IDENTITY = (1.0, 1.0, 1.0)
_balanced_window_type = None


def read_gains(path=PROFILE):
    try:
        with Path(path).open('rb') as file:
            data = file.read(4097)
        if len(data) > 4096:
            raise ValueError('Profile too large')
        profile = json.loads(data)
        gains = profile['rgb_gains']
        if not isinstance(gains, list) or len(gains) != 3:
            raise ValueError('Three RGB gains required')
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0.1 <= value <= 1.0 for value in gains):
            raise ValueError('RGB gains must be finite values from 0.1 to 1.0')
        return tuple(float(value) for value in gains)
    except FileNotFoundError:
        return IDENTITY
    except (OSError, ValueError, KeyError, TypeError):
        print('RoonDeck: invalid/unreadable display white-balance profile; using original colours', file=sys.stderr)
        return IDENTITY


def gain_matrix(gains):
    r, g, b = gains
    return [r, 0, 0, 0, 0, g, 0, 0, 0, 0, b, 0, 0, 0, 0, 1]


def create_display_window(*, application=None, gains=None):
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Graphene', '1.0')
    from gi.repository import Gtk, Graphene
    gains = read_gains() if gains is None else gains
    if gains == IDENTITY:
        return Gtk.ApplicationWindow(application=application)

    global _balanced_window_type
    if _balanced_window_type is None:
        class WhiteBalancedWindow(Gtk.ApplicationWindow):
            def __init__(self, application, gains):
                super().__init__(application=application)
                self.balance_matrix = Graphene.Matrix()
                self.balance_matrix.init_from_float(gain_matrix(gains))
                self.balance_offset = Graphene.Vec4()
                self.balance_offset.init(0, 0, 0, 0)

            def do_snapshot(self, snapshot):
                snapshot.push_color_matrix(self.balance_matrix, self.balance_offset)
                Gtk.ApplicationWindow.do_snapshot(self, snapshot)
                snapshot.pop()
        _balanced_window_type = WhiteBalancedWindow

    print('RoonDeck: display white-balance RGB gains ' + ', '.join(f'{gain:.4f}' for gain in gains), flush=True)
    return _balanced_window_type(application, gains)
