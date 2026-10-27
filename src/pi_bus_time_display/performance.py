"""Lightweight Linux performance readings shared by the touchscreen and web GUI."""
from __future__ import annotations

from collections import deque
from pathlib import Path
import threading
import time

SAMPLES = 60
NETWORK_CEILINGS = (5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0)  # Mb/s
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
        # Tunnel, bridge and container interfaces carry the same bytes again as the physical link; count each byte once.
        if name.strip() == "lo" or name.strip().startswith(("wg", "tun", "tap", "veth", "docker", "br-", "virbr")) or len(fields) < 9: continue
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
        # A fixed set of ceilings, not the recent peak: an idle link then looks idle and a stream looks like a stream.
        peak = max(values, default=0) * 1.05
        ceiling = next((step for step in NETWORK_CEILINGS if step >= peak), peak)
        return [min(100.0, value * 100.0 / ceiling) for value in values]


def format_value(key, value, compact=False):
    if value is None: return "—"
    if key == "temp": return f"{value:.0f}°C"
    if key == "network" and compact: return f"{value:.1f}M" if value < 100 else f"{value:.0f}M"
    if key == "network": return f"{value:.1f} Mb/s" if value < 100 else f"{value:.0f} Mb/s"
    return f"{value:.0f}%"



class PerformanceHistory:
    """One bounded, process-wide history, independent of the number of web clients."""

    def __init__(self, reader=read_text, clock=time.monotonic):
        self.reader = reader
        self.clock = clock
        self.sampler = PerformanceSampler()
        self.lock = threading.Lock()
        self.last_sample = None

    def sample(self):
        with self.lock:
            now = self.clock()
            if self.last_sample is not None and now - self.last_sample < 1:
                return
            if self.last_sample is not None and now - self.last_sample > 2.5:
                self.sampler = PerformanceSampler()
            latest = self.sampler.sample(now, self.reader("/proc/stat"), self.reader("/proc/meminfo"),
                                         self.reader("/sys/class/thermal/thermal_zone0/temp"), self.reader("/proc/net/dev"))
            # Never pin an old line to "Now" after its measurement disappears.
            for key, value in latest.items():
                if value is None:
                    self.sampler.history[key].clear()
            self.last_sample = now

    def snapshot(self):
        # Also supports embedded servers and tests which do not launch main's poll thread.
        self.sample()
        with self.lock:
            history = {key: list(values) for key, values in self.sampler.history.items()}
            return {"seconds": SAMPLES, "interval_seconds": 1,
                    "latest": dict(self.sampler.latest), "history": history,
                    "available": any(value is not None for value in self.sampler.latest.values())}

    def run(self, stop):
        while not stop.is_set():
            self.sample()
            stop.wait(1)
