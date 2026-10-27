"""Live system performance graph for the 10-inch Settings page.

CPU, memory, temperature and network are sampled once a second while the graph is on screen and drawn as the last
60 seconds. The four chips above the graph show the latest value; tapping one shows or hides its line.
"""
from __future__ import annotations


from native_common import BUS, FamilyIcon, get_json
import threading
from gi.repository import GLib, Gtk, Pango

from pi_bus_time_display.performance import (
    NETWORK_CEILINGS, SAMPLES, SERIES, parse_cpu_times, cpu_percent, memory_percent,
    network_bytes, read_text, PerformanceSampler, format_value,
)


def curve(cr, points):
    """Smooth line through the points (Catmull-Rom converted to Beziers)."""
    cr.move_to(*points[0])
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]; p1 = points[index]; p2 = points[index + 1]; p3 = points[min(len(points) - 1, index + 2)]
        cr.curve_to(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                    p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1])


class PerformanceGraph(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add_css_class("perf-card"); self.set_vexpand(False); self.set_valign(Gtk.Align.START); self.set_hexpand(True)
        self.sampler = PerformanceSampler(); self.enabled = {key: True for key, _name, _colour in SERIES}; self.timer = None
        header = Gtk.Box(spacing=12)
        title = Gtk.Label(label="SYSTEM PERFORMANCE"); title.add_css_class("eyebrow"); title.set_xalign(0); title.set_hexpand(True); header.append(title)
        self.roon_status = Gtk.Label(label=""); self.roon_status.add_css_class("perf-note"); self.roon_status.add_css_class("perf-roon"); self.roon_status.set_visible(False); header.append(self.roon_status)
        note = Gtk.Label(label="Last 60 seconds"); note.add_css_class("perf-note"); header.append(note)
        self.short_values = False
        self.append(header)
        chips = Gtk.Box(spacing=12); chips.set_homogeneous(True); self.chips = {}; self.chip_values = {}; self.chip_checks = {}; self.chip_names = {}; self.compact = False
        for key, name, _colour in SERIES:
            chip = Gtk.Button(); chip.add_css_class("perf-chip"); chip.add_css_class(f"perf-{key}"); chip.set_focusable(False)
            row = Gtk.Box(spacing=8)
            check = FamilyIcon("check", 24); check.add_css_class("perf-check"); row.append(check)
            label = Gtk.Label(label=name); label.add_css_class("perf-chip-name"); label.set_xalign(0); row.append(label)
            value = Gtk.Label(label="—"); value.add_css_class("perf-chip-value"); value.set_xalign(1); value.set_hexpand(True); value.set_ellipsize(Pango.EllipsizeMode.END); row.append(value)
            chip.set_child(row); chip.connect("clicked", lambda _button, series=key: self.toggle(series))
            self.chips[key] = chip; self.chip_names[key] = label; self.chip_values[key] = value; self.chip_checks[key] = check; chips.append(chip)
        self.append(chips)
        self.area = Gtk.DrawingArea(); self.area.set_hexpand(True); self.area.set_vexpand(False); self.area.set_size_request(-1, 470)
        self.area.set_draw_func(self.draw); self.append(self.area)
        # Stacked mode (10-inch portrait): one card per measurement instead of four lines sharing one chart.
        self.stacked = False; self.panel_areas = {}; self.panel_values = {}; self.panel_ranges = {}
        self.panels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.panels.set_vexpand(True); self.panels.set_homogeneous(True); self.panels.set_visible(False)
        for key, name, colour in SERIES:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); card.add_css_class("perf-panel"); card.set_vexpand(True)
            head = Gtk.Box(spacing=12); hex_colour = "#%02x%02x%02x" % tuple(round(c * 255) for c in colour)
            title = Gtk.Label(); title.set_markup(f'<span foreground="{hex_colour}" weight="bold">{name.upper()}</span>'); title.add_css_class("perf-panel-title"); title.set_xalign(0); title.set_hexpand(True); head.append(title)
            value = Gtk.Label(label="—"); value.add_css_class("perf-panel-value"); head.append(value)
            area = Gtk.DrawingArea(); area.set_hexpand(True); area.set_vexpand(True); area.set_size_request(-1, 40)
            area.set_draw_func(lambda _a, cr, w, h, series=key: self.draw_panel(cr, w, h, series))
            card.append(head); card.append(area); self.panels.append(card)
            self.panel_areas[key] = area; self.panel_values[key] = value
        self.append(self.panels)
        self.axis = Gtk.Box(); self.axis.add_css_class("perf-axis"); self.axis.set_visible(False)
        for text, align in (("60s ago", Gtk.Align.START), ("30s", Gtk.Align.CENTER), ("Now", Gtk.Align.END)):
            tick = Gtk.Label(label=text); tick.add_css_class("perf-note"); tick.set_hexpand(True); tick.set_halign(align); self.axis.append(tick)
        self.append(self.axis)
        self.connect("map", self.start); self.connect("unmap", self.stop)

    def set_compact(self, compact):
        """Seven-inch landscape: a shorter graph and tighter card so it fits beside the other controls."""
        self.compact = compact
        (self.add_css_class if compact else self.remove_css_class)("compact")
        self.area.set_size_request(-1, 100 if compact else 470); self.area.set_vexpand(compact)
        for check in self.chip_checks.values(): check.set_visible(not compact)
        self.set_vexpand(compact); self.set_valign(Gtk.Align.FILL if compact else Gtk.Align.START); self.set_spacing(10 if compact else 14)

    def set_stacked(self, stacked):
        self.stacked = stacked
        self.chips[SERIES[0][0]].get_parent().set_visible(not stacked)
        self.area.set_visible(not stacked); self.panels.set_visible(stacked); self.axis.set_visible(stacked)
        self.set_vexpand(True); self.set_valign(Gtk.Align.FILL)

    def redraw(self):
        self.area.queue_draw()
        for area in self.panel_areas.values(): area.queue_draw()

    def draw_panel(self, cr, width, height, key):
        values = self.sampler.plotted(key)
        colour = next(item[2] for item in SERIES if item[0] == key)
        cr.set_line_width(1); cr.set_dash([6, 6]); cr.set_source_rgba(1, 1, 1, .12)
        cr.move_to(0, height / 2); cr.line_to(width, height / 2); cr.stroke(); cr.set_dash([])
        if len(values) < 2: return
        pad = 4; step = width / (SAMPLES - 1); count = len(values)
        points = [(width - (count - 1 - index) * step, height - pad - value / 100 * (height - 2 * pad)) for index, value in enumerate(values)]
        cr.save(); cr.rectangle(0, 0, width, height); cr.clip()
        curve(cr, points); cr.line_to(points[-1][0], height); cr.line_to(points[0][0], height); cr.close_path(); cr.set_source_rgba(*colour, .14); cr.fill()
        curve(cr, points); cr.set_source_rgb(*colour); cr.set_line_width(2.4); cr.set_line_join(1); cr.set_line_cap(1); cr.stroke()
        cr.restore()

    def toggle(self, key):
        self.enabled[key] = not self.enabled[key]
        (self.chips[key].remove_css_class if self.enabled[key] else self.chips[key].add_css_class)("off")
        self.chip_checks[key].set_opacity(1 if self.enabled[key] else 0)
        self.area.queue_draw()

    def set_roon_status(self, connected):
        self.roon_status.set_visible(True); self.roon_status.set_text("Roon connected" if connected else "Roon not connected")
        (self.roon_status.add_css_class if connected else self.roon_status.remove_css_class)("on")

    def preload(self):
        """The server already holds the last 60 seconds; draw that at once instead of building it from scratch."""
        def work():
            data = get_json(BUS + "/api/admin/performance", timeout=2)
            if isinstance(data, dict): GLib.idle_add(self.apply_history, data)
        threading.Thread(target=work, daemon=True).start()

    def apply_history(self, data):
        history = data.get("history") or {}
        for key, values in self.sampler.history.items():
            received = history.get(key)
            if isinstance(received, list) and len(received) > len(values):
                values.clear(); values.extend(float(item) for item in received[-SAMPLES:] if isinstance(item, (int, float)))
        self.redraw()
        return False

    def start(self, *_):
        self.preload(); self.tick()
        if self.timer is None: self.timer = GLib.timeout_add(1000, self.tick)

    def stop(self, *_):
        if self.timer is not None: GLib.source_remove(self.timer); self.timer = None
        # The next visit starts a clean 60 seconds rather than joining samples from minutes ago.
        self.sampler = PerformanceSampler()

    def tick(self):
        latest = self.sampler.sample(GLib.get_monotonic_time() / 1_000_000, read_text("/proc/stat"), read_text("/proc/meminfo"),
                                     read_text("/sys/class/thermal/thermal_zone0/temp"), read_text("/proc/net/dev"))
        for key, _name, _colour in SERIES: self.chip_values[key].set_text(format_value(key, latest.get(key), self.compact or self.short_values))
        for key, _name, _colour in SERIES:
            text = format_value(key, latest.get(key))
            if key == "network":
                peak = max(self.sampler.history["network"], default=0) * 1.05
                text += f"  ·  0–{next((step for step in NETWORK_CEILINGS if step >= peak), peak):g} Mb/s"
            self.panel_values[key].set_text(text)
        self.redraw()
        return True

    def draw(self, _area, cr, width, height):
        size = max(15, min(22, round(height / 14)))
        cr.select_font_face("Inter"); cr.set_font_size(size)
        left, right, top, bottom = size * 3.2, width - 8, 8, height - size * 1.9
        if right <= left + 20 or bottom <= top + 20: return
        cr.set_line_width(1); cr.set_dash([6, 6])
        for percent in (0, 25, 50, 75, 100):
            y = bottom - percent / 100 * (bottom - top)
            cr.set_source_rgba(1, 1, 1, .14); cr.move_to(left, y); cr.line_to(right, y); cr.stroke()
            label = f"{percent}%"; extents = cr.text_extents(label)
            cr.set_source_rgba(1, 1, 1, .62); cr.move_to(left - 10 - extents.x_advance, y + size * .35); cr.show_text(label)
        cr.set_dash([])
        for text, anchor in (("60s ago", 0), ("30s", .5), ("Now", 1)):
            extents = cr.text_extents(text)
            cr.set_source_rgba(1, 1, 1, .62); cr.move_to(left + anchor * (right - left) - anchor * extents.x_advance, height - size * .45); cr.show_text(text)
        cr.save(); cr.rectangle(left, top - 3, right - left, bottom - top + 6); cr.clip()
        step = (right - left) / (SAMPLES - 1)
        for key, _name, colour in SERIES:
            if not self.enabled[key]: continue
            values = self.sampler.plotted(key)
            if len(values) < 2: continue
            count = len(values)
            points = [(right - (count - 1 - index) * step, bottom - value / 100 * (bottom - top)) for index, value in enumerate(values)]
            curve(cr, points); cr.line_to(points[-1][0], bottom); cr.line_to(points[0][0], bottom); cr.close_path()
            cr.set_source_rgba(*colour, .14); cr.fill()
            curve(cr, points); cr.set_source_rgb(*colour); cr.set_line_width(2); cr.set_line_join(1); cr.set_line_cap(1); cr.stroke()
        cr.restore()
