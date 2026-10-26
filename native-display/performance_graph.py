"""Live system performance graph for the 10-inch Settings page.

CPU, memory, temperature and network are sampled once a second while the graph is on screen and drawn as the last
60 seconds. The four chips above the graph show the latest value; tapping one shows or hides its line.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from native_common import FamilyIcon
from gi.repository import GLib, Gtk, Pango

SAMPLES = 60
SERIES = (
    ("cpu", "CPU", (.30, .65, 1.0)),
    ("memory", "Memory", (.60, .41, .98)),
    ("temp", "Temp", (1.0, .65, .30)),
    ("network", "Network", (.25, .85, .62)),
)


def parse_cpu_times(text):
    """(busy, total) jiffies from the first line of /proc/stat, or None."""
    try:
        values = [int(value) for value in text.splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values) - idle, sum(values)
    except (IndexError, ValueError):
        return None


def cpu_percent(previous, current):
    if not previous or not current or current[1] <= previous[1]: return None
    return max(0.0, min(100.0, (current[0] - previous[0]) * 100.0 / (current[1] - previous[1])))


def memory_percent(text):
    try:
        values = {line.split(":")[0]: int(line.split()[1]) for line in text.splitlines() if ":" in line and len(line.split()) > 1}
        total, available = values["MemTotal"], values["MemAvailable"]
        return max(0.0, min(100.0, (total - available) * 100.0 / total)) if total else None
    except (KeyError, ValueError, IndexError):
        return None


def network_bytes(text):
    """Received plus sent bytes on every interface except loopback, from /proc/net/dev."""
    total = 0
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        fields = rest.split()
        if name.strip() == "lo" or len(fields) < 9: continue
        try: total += int(fields[0]) + int(fields[8])
        except ValueError: continue
    return total


def read_text(path):
    try: return Path(path).read_text(encoding="ascii", errors="replace")
    except OSError: return ""


class PerformanceSampler:
    """Keeps the last SAMPLES readings of each series; values are plotted as 0-100."""

    def __init__(self):
        self.history = {key: deque(maxlen=SAMPLES) for key, _name, _colour in SERIES}
        self.latest = {key: None for key, _name, _colour in SERIES}
        self.previous_cpu = None; self.previous_network = None; self.previous_time = None
        self.network_rates = deque(maxlen=SAMPLES)

    def sample(self, now, stat_text, meminfo_text, temperature_text, network_text):
        cpu_now = parse_cpu_times(stat_text)
        cpu = cpu_percent(self.previous_cpu, cpu_now); self.previous_cpu = cpu_now
        memory = memory_percent(meminfo_text)
        try: temperature = int(temperature_text.strip()) / 1000.0
        except ValueError: temperature = None
        counted = network_bytes(network_text) if network_text else None
        rate = None
        if counted is not None and self.previous_network is not None and self.previous_time is not None and now > self.previous_time:
            rate = max(0.0, (counted - self.previous_network) * 8 / 1_000_000 / (now - self.previous_time))
        self.previous_network = counted; self.previous_time = now
        self.latest = {"cpu": cpu, "memory": memory, "temp": temperature, "network": rate}
        if cpu is not None: self.history["cpu"].append(cpu)
        if memory is not None: self.history["memory"].append(memory)
        if temperature is not None: self.history["temp"].append(max(0.0, min(100.0, temperature)))
        if rate is not None:
            self.network_rates.append(rate)
            self.history["network"].append(rate)
        return self.latest

    def plotted(self, key):
        """The points to draw, 0-100. Network has no fixed ceiling, so it is scaled to its recent peak."""
        values = list(self.history[key])
        if key != "network": return values
        ceiling = max(5.0, max(values, default=0) * 1.2)
        return [min(100.0, value * 100.0 / ceiling) for value in values]


def format_value(key, value, compact=False):
    if value is None: return "—"
    if key == "temp": return f"{value:.0f}°C"
    if key == "network" and compact: return f"{value:.1f}M" if value < 100 else f"{value:.0f}M"
    if key == "network": return f"{value:.1f} Mb/s" if value < 100 else f"{value:.0f} Mb/s"
    return f"{value:.0f}%"


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
        note = Gtk.Label(label="Last 60 seconds"); note.add_css_class("perf-note"); header.append(note)
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
        self.connect("map", self.start); self.connect("unmap", self.stop)

    def set_compact(self, compact):
        """Seven-inch landscape: a shorter graph and tighter card so it fits beside the other controls."""
        self.compact = compact
        self.area.set_size_request(-1, 100 if compact else 470); self.area.set_vexpand(compact)
        self.set_vexpand(compact); self.set_spacing(8 if compact else 14)
        short = {"cpu": "CPU", "memory": "Mem", "temp": "Temp", "network": "Net"}
        for key, name, _colour in SERIES:
            self.chip_names[key].set_text(short[key] if compact else name)
            self.chip_checks[key].set_visible(not compact)
        (self.add_css_class if compact else self.remove_css_class)("compact")

    def toggle(self, key):
        self.enabled[key] = not self.enabled[key]
        (self.chips[key].remove_css_class if self.enabled[key] else self.chips[key].add_css_class)("off")
        self.chip_checks[key].set_opacity(1 if self.enabled[key] else 0)
        self.area.queue_draw()

    def start(self, *_):
        self.tick()
        if self.timer is None: self.timer = GLib.timeout_add(1000, self.tick)

    def stop(self, *_):
        if self.timer is not None: GLib.source_remove(self.timer); self.timer = None
        # The next visit starts a clean 60 seconds rather than joining samples from minutes ago.
        self.sampler = PerformanceSampler()

    def tick(self):
        latest = self.sampler.sample(GLib.get_monotonic_time() / 1_000_000, read_text("/proc/stat"), read_text("/proc/meminfo"),
                                     read_text("/sys/class/thermal/thermal_zone0/temp"), read_text("/proc/net/dev"))
        for key, _name, _colour in SERIES: self.chip_values[key].set_text(format_value(key, latest.get(key), self.compact))
        self.area.queue_draw()
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
