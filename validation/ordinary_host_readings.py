"""Parent-side host readings for the whole of a worker's life, from launch to exit.

A failed reading is recorded as missing and never affects the run. Deadlines do not
depend on this. No filing content or runtime value passes through here.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

INTERVAL_SECONDS = 2.0


def _run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=1.5).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def read_host(parent):
    therm = _run('/usr/bin/pmset', '-g', 'therm')
    limit = lambda name: (lambda m: int(m[1]) if m else None)(re.search(name + r'\s*=\s*(\d+)', therm))
    power = _run('/usr/bin/pmset', '-g', 'batt').split('\n', 1)[0]
    worker_cpu = worker_rss = None
    for line in _run('/bin/ps', '-axo', 'ppid=,pcpu=,rss=,command=').splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4 and fields[0] == str(parent) and '_ordinary_rehearsal_worker' in fields[3]:
            worker_cpu, worker_rss = float(fields[1]), int(fields[2])
    try:
        load = round(os.getloadavg()[0], 2)
    except OSError:
        load = None
    return {'load1': load, 'cpu_speed_limit': limit('CPU_Speed_Limit'), 'cpu_scheduler_limit': limit('CPU_Scheduler_Limit'),
            'on_ac_power': 'AC Power' in power if power else None, 'worker_cpu_percent': worker_cpu, 'worker_rss_kb': worker_rss}


class HostReadings:
    def __init__(self, output, *, interval=INTERVAL_SECONDS):
        self.path, self.interval = Path(output) / 'host_readings.json', interval
        self.rows, self.stop = [], threading.Event()
        self.thread = threading.Thread(target=self._loop, name='host-readings', daemon=True)

    def _loop(self):
        parent = os.getpid()
        while True:
            try:
                self.rows.append({'offset_s': round(time.monotonic() - self.started, 3), **read_host(parent)})
            except Exception:
                self.rows.append({'offset_s': round(time.monotonic() - self.started, 3), 'unreadable': True})
            if self.stop.wait(self.interval):
                return

    def __enter__(self):
        self.started = time.monotonic()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=5)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'interval_seconds': self.interval, 'readings': list(self.rows)}, stream, sort_keys=True)
        except OSError:
            pass
        return False

    def summary(self):
        known = lambda key: [row[key] for row in self.rows if row.get(key) is not None]
        speeds, loads = known('cpu_speed_limit'), known('load1')
        return {'readings': len(self.rows), 'first_offset_s': self.rows[0]['offset_s'] if self.rows else None,
                'last_offset_s': self.rows[-1]['offset_s'] if self.rows else None,
                'min_cpu_speed_limit': min(speeds) if speeds else None, 'max_load1': max(loads) if loads else None,
                'all_on_ac_power': all(known('on_ac_power')) if known('on_ac_power') else None}
