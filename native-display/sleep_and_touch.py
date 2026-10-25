"""Screen sleep and wake, touch wake-up and cursor hiding."""
from __future__ import annotations

from native_common import BUS, post_json
from pathlib import Path
import os
import select
import struct
import threading
import time
from gi.repository import GLib, Gdk


class SleepAndTouchMixin:
    def sleep_gesture_pressed(self, _gesture, _count, _x, _y):
        if time.monotonic() - self.sleep_entered_at >= .45: self.wake("sleep gesture")

    def touchscreen_devices(self):
        devices = []
        for event_path in sorted(Path("/sys/class/input").glob("event*")):
            try: name = (event_path / "device/name").read_text(encoding="utf-8").strip().lower()
            except OSError: continue
            if any(token in name for token in ("touchscreen", "touch display", "raspberrypi-ts", "dsi touch", "ft5406", "edt-ft", "goodix")):
                device = Path("/dev/input") / event_path.name
                if device.exists(): devices.append((device, name))
        return devices

    def touchscreen_wake_worker(self):
        event_struct = struct.Struct("llHHI")
        while True:
            handles = []
            try:
                for device, name in self.touchscreen_devices():
                    try:
                        handle = os.open(device, os.O_RDONLY | os.O_NONBLOCK); handles.append((handle, name))
                    except OSError: continue
                if not handles:
                    time.sleep(5); continue
                print("RoonDeck low-level wake listening on " + ", ".join(name for _, name in handles), flush=True)
                while True:
                    readable, _, _ = select.select([handle for handle, _ in handles], [], [], 30)
                    for handle in readable:
                        try: packet = os.read(handle, event_struct.size * 32)
                        except OSError: continue
                        for offset in range(0, len(packet) - event_struct.size + 1, event_struct.size):
                            _sec, _usec, event_type, code, value = event_struct.unpack_from(packet, offset)
                            # Goodix panels can announce a new contact as
                            # BTN_TOUCH or as an MT tracking id. Accept either
                            # real contact start, but ignore coordinate motion.
                            button_touch = event_type == 1 and code == 330 and value == 1
                            tracking_start = event_type == 3 and code == 57 and value != 0xFFFFFFFF
                            if button_touch or tracking_start:
                                event_at = _sec + (_usec / 1_000_000)
                                now = time.monotonic()
                                # input_event normally uses CLOCK_MONOTONIC. If
                                # a driver reports wall time instead, use the
                                # observation time rather than comparing unlike
                                # clocks.
                                contact_at = event_at if abs(event_at - now) < 3600 else now
                                GLib.idle_add(self.low_level_touch_wake, contact_at)
            finally:
                for handle, _name in handles:
                    try: os.close(handle)
                    except OSError: pass
            time.sleep(1)

    def low_level_touch_wake(self, contact_at=None):
        # Raw contact starts are the most reliable activity signal on DSI
        # panels: GTK may turn a drag into scrolling without emitting a button
        # press. Record every contact so inactivity is measured from the last
        # touch, not from the time the panel originally woke.
        self.last_interaction = max(self.last_interaction, contact_at or time.monotonic())
        if (hasattr(self, "stack") and self.stack.get_visible_child_name() == "roon"
                and (self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
                     or (hasattr(self, "detail_takeover") and self.detail_takeover.get_visible()))):
            self.browse_last_interaction = self.last_interaction
        # The low-level event from the gesture which pressed Sleep may reach
        # GTK after the screen has already gone dark. It is not a wake gesture.
        # Compare when contact actually began, not when this idle callback ran.
        if contact_at is not None and contact_at <= self.sleep_entered_at:
            return False
        if self.inactivity_sleeping or (self.stack.get_visible_child_name() == "sleep" and time.monotonic() - self.sleep_entered_at >= .45): self.wake("Linux touchscreen event")
        return False

    def note_activity(self, _controller, event):
        if event is None: return False
        # Legacy controllers also receive pointer motion, enter/leave and window
        # events. A powered-down panel can consume the beginning of the first
        # contact, so accept its release as a wake gesture as well.
        event_type = event.get_event_type()
        if event_type in {Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN}:
            # Remember where the finger landed (window coordinates) so action menus open beside the tapped row.
            try:
                position = event.get_position()
                if position[0] is not False and len(position) >= 3: self.last_tap_point = (position[-2], position[-1])
            except (AttributeError, TypeError, ValueError): pass
        if event_type in {Gdk.EventType.ENTER_NOTIFY, Gdk.EventType.MOTION_NOTIFY, Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN}:
            # A pointer entering or moving re-asserts the compositor's cursor; blank it on the surface too.
            try: self.window.get_surface().set_cursor(Gdk.Cursor.new_from_name("none", None))
            except (AttributeError, TypeError, GLib.Error): pass
        contact_started = event_type in {Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.KEY_PRESS}
        contact_finished = event_type in {Gdk.EventType.BUTTON_RELEASE, Gdk.EventType.TOUCH_END}
        if not contact_started and not contact_finished:
            return False
        self.last_interaction = time.monotonic()
        if (self.stack.get_visible_child_name() == "roon"
                and (self.roon_views.get_visible_child_name() in {"discover", "browse", "search"}
                     or (hasattr(self, "detail_takeover") and self.detail_takeover.get_visible()))):
            self.browse_last_interaction = self.last_interaction
        if self.inactivity_sleeping:
            source = getattr(event_type, "value_nick", str(event_type))
            self.inactivity_sleeping = False; print(f"RoonDeck waking after touchscreen {source}", flush=True); self.set_screen_power(True, force=True); self.stack.set_visible_child_name(self.last_mode or "bus")
        elif self.stack.get_visible_child_name() == "sleep" and time.monotonic() - self.sleep_entered_at >= .45:
            self.wake(getattr(event_type, "value_nick", str(event_type)))
        return False

    def prepare_sleep_wake(self):
        # Ignore only the short tail of the gesture that pressed Sleep. Using a
        # timestamp avoids depending on a delayed GLib arming callback, which
        # could leave manual sleep permanently unable to accept a wake touch.
        self.sleep_entered_at = time.monotonic()

    def sleep(self, *_):
        self.inactivity_sleeping = False; self.settings_open = False
        self.manual_sleep_pending = True; self.manual_sleep_started_at = time.monotonic()
        self.prepare_sleep_wake(); self.stack.set_visible_child_name("sleep")
        self.set_screen_power(bool(self.settings_data.get("sleep_show_clock", False)))
        print("RoonDeck manual sleep requested", flush=True)
        threading.Thread(target=self.request_manual_sleep, daemon=True).start()

    def request_manual_sleep(self):
        for attempt in range(3):
            if post_json(BUS + "/api/admin/display-mode", {"mode": "sleep"}):
                GLib.idle_add(self.start_poll)
                return
            if attempt < 2: time.sleep(.35)
        GLib.idle_add(self.manual_sleep_failed)

    def manual_sleep_failed(self):
        if self.manual_sleep_pending:
            self.manual_sleep_pending = False
            print("RoonDeck manual sleep request failed after three attempts", flush=True)
            self.set_screen_power(True, force=True)
            self.stack.set_visible_child_name(self.last_mode or "bus")
        return False

    def wake(self, *_):
        now = time.monotonic()
        source = _[0] if _ else "input"
        self.manual_sleep_pending = False; self.sleep_entered_at = 0.0; self.last_interaction = now; self.inactivity_sleeping = False; print(f"RoonDeck waking after fresh touchscreen {source}", flush=True); self.set_screen_power(True, force=True); self.stack.set_visible_child_name(self.last_mode or "bus")
        threading.Thread(target=post_json, args=(BUS + "/api/device/wake", {"view": self.last_mode or "bus"}), daemon=True).start()

    def hide_widget_cursor(self, widget):
        widget.set_cursor_from_name("none")
        child = widget.get_first_child()
        while child:
            self.hide_widget_cursor(child)
            child = child.get_next_sibling()

    def hide_native_cursor(self, widget):
        """Hide the cursor on a newly-mapped popover's separate native surface."""
        self.hide_widget_cursor(widget)
        try:
            native = widget.get_native()
            surface = native.get_surface() if native else None
            if surface: surface.set_cursor(Gdk.Cursor.new_from_name("none", None))
        except (AttributeError, TypeError, GLib.Error):
            pass
        return False

    def hide_touch_cursor(self):
        # Child widgets and newly-created popover surfaces can override the
        # window cursor. Include every current descendant on each pass.
        self.hide_widget_cursor(self.window)
        return True
