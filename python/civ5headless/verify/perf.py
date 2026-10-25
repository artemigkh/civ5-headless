"""Performance (plan 5.4): real game against host, host throughput, machine load, and the per-machine history.

- Wall time per turn early, mid and late: the horizon in thirds, from the cumulative seconds per turn
  (turn-times.jsonl in the host, autoplay()'s turn times in the real game).
- The host figures come from the trajectory game when it ran alone (the single-worker phase); otherwise from the
  first trajectory game that finished, and the table says how many host games ran beside it.
- Machine load: a sampler records every few seconds the busy cores, the real game's busy cores and the host games
  running, so contention shows beside every timing.
- History: <runs>/verify-history/<machine>.jsonl gets one line per suite run; the report draws the trend and warns
  when the host is slower than its recent runs with the same setup and mode.
"""
from __future__ import annotations
import json
import os
import platform
import re
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import winproc

MB = 2 ** 20


def thirds(times, horizon=None):
    """{early, mid, late, all}: seconds per turn in each third of the horizon, from {turn: cumulative seconds}."""
    if not times:
        return {}
    times = {int(t): float(s) for t, s in times.items()}
    end = max(times)
    horizon = min(horizon or end, end)
    cuts = [0, round(horizon / 3), round(2 * horizon / 3), horizon]

    def at(t):
        if t <= 0:
            return 0.0
        if t in times:
            return times[t]
        below = [k for k in times if k <= t]
        return times[max(below)] if below else 0.0

    out = {}
    for name, (a, b) in zip(('early', 'mid', 'late'), zip(cuts, cuts[1:])):
        if b > a:
            out[name] = round((at(b) - at(a)) / (b - a), 3)
    out['all'] = round(at(horizon) / horizon, 3) if horizon else None
    out['turns'] = horizon
    out['ranges'] = [[a + 1, b] for a, b in zip(cuts, cuts[1:])]
    return out


def host_figures(job):
    """Performance of one host job (a hostside.Job.to_dict() with its status): status.json, turn times, report."""
    from .hostside import turn_times
    st = job.get('status') or {}
    proc = st.get('process') or {}
    folder = Path(job['runDir']) if job.get('runDir') else None
    times = dict(turn_times(folder)) if folder else {}
    launch = None
    report = None
    for name in ('host-report.json', 'newgame-report.json'):
        p = (folder or Path('.')) / name
        if folder and p.is_file():
            try:
                report = json.loads(p.read_text(encoding='utf-8'))
                break
            except ValueError:
                pass
    if report:
        timings = report.get('timings') or report.get('timings_seconds') or {}
        total = timings.get('total') or report.get('wallSeconds')
        if 'autoplay' in timings and total:
            launch = round(total - timings['autoplay'] - timings.get('shutdown', 0), 2)
    if launch is None and st.get('hostSeconds') and st.get('wallSeconds') is not None:
        launch = round(st['hostSeconds'] - st['wallSeconds'], 2)
    return dict(source=job.get('name'), turns=job.get('endTurn'), perTurn=thirds(times, job.get('turns')),
                launchToFirstTurn=launch, autoplaySeconds=st.get('wallSeconds'), processSeconds=st.get('hostSeconds'),
                cpuSeconds=_r(proc.get('CPUSeconds')), peakWorkingSetMB=_mb(proc.get('PeakWorkingSet')),
                peakPrivateMB=_mb(proc.get('PeakPrivateBytes') or proc.get('PeakCommit')),
                meanConcurrency=job.get('meanConcurrency'), curve=sorted(times.items()))


def real_figures(real, game_name, samples=None, period=5.0):
    """Performance of one real game from real.json (see realside.py)."""
    if not real:
        return None
    game = next((g for g in real.get('games', []) if g.get('name') == game_name), None)
    if not game or not game.get('autoplay'):
        return None
    times = {int(k): float(v) for k, v in (game['autoplay'].get('turnSeconds') or {}).items()}
    per = thirds(times, game.get('turns'))
    proc = game.get('process') or real.get('process') or {}  # the game's own: taken right after its autoplay
    first = next((g for g in real.get('games', []) if g.get('start')), None)
    launch = (real.get('launch') or {}).get('seconds')
    to_first = None
    if launch is not None and first:
        to_first = round(launch + (real.get('mods') or {}).get('seconds', 0) + first['start'].get('seconds', 0), 2)
    out = dict(source=game_name, turns=game['autoplay'].get('endTurn'), perTurn=per, launchSeconds=launch,
               launchToFirstTurn=to_first, startGameSeconds=(game.get('start') or {}).get('seconds'),
               autoplaySeconds=game.get('autoplaySeconds'), cpuSeconds=_r(_pick(proc, 'CPUSeconds', 'cpuSeconds', 'cpu_seconds')),
               peakWorkingSetMB=_mb(_pick(proc, 'PeakWorkingSet', 'peakWorkingSet', 'peak_working_set')),
               peakPrivateMB=_mb(_pick(proc, 'PeakPrivateBytes', 'peakPrivateBytes', 'peak_private_bytes')),
               curve=sorted(times.items()))
    if samples and game.get('autoplayStartedAt') is not None and per.get('ranges'):
        load = {}
        start = game['autoplayStartedAt']
        for name, (a, b) in zip(('early', 'mid', 'late'), per['ranges']):
            t0, t1 = start + times.get(a - 1, 0.0), start + times.get(b, max(times.values()))
            load[name] = window(samples, t0, t1, period)
        out['load'] = load
    return out


def _pick(d, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _mb(v):
    return round(v / MB) if isinstance(v, (int, float)) and v > 0 else None


def _r(v):
    return round(v, 1) if isinstance(v, (int, float)) else None


class LoadTimeline:
    """Samples the machine every period seconds on a thread: busy cores, the real game's busy cores, host games."""

    def __init__(self, t0, hosts=None, real_state=None, period=5.0):
        self.t0, self.hosts, self.real_state, self.period = t0, hosts, real_state, period
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='load-timeline', daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.stop_event.is_set():
            meter = winproc.LoadMeter().start()
            if self.stop_event.wait(self.period):
                break
            m = meter.stop()
            hosts = self.hosts() if self.hosts else None
            self.samples.append(dict(t=round(time.monotonic() - self.t0, 1), busyCores=m['systemBusyCores'],
                                     gameBusyCores=m['gameBusyCores'], hosts=hosts,
                                     real=(self.real_state or {}).get('phase')))

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(self.period + 2)

    def window(self, t0, t1):
        return window(self.samples, t0, t1, self.period)


def window(samples, t0, t1, period=5.0):
    """Mean load over the samples whose end lies in [t0, t1 + period] (seconds since the suite started)."""
    if t0 is None or t1 is None:
        return None
    rows = [s for s in samples or [] if t0 <= s['t'] <= t1 + period]
    if not rows:
        return None
    avg = lambda k: round(sum(r[k] or 0 for r in rows) / len(rows), 2)
    return dict(busyCores=avg('busyCores'), gameBusyCores=avg('gameBusyCores'), hosts=avg('hosts'), samples=len(rows))


def throughput(phases, samples=None, period=5.0):
    """Rows for the phases that measure throughput (hostside.Phase.to_dict() dicts): workers, games, seconds, games
    and turns per hour, machine load."""
    rows = []
    for d in phases:
        if not d.get('throughput') or not d.get('completed') or not d.get('seconds'):
            continue
        row = dict(phase=d['name'], workers=d['workers'], games=d['completed'], turnsPerGame=round(d['turns'] / d['completed']),
                   seconds=round(d['seconds'], 1), gamesPerHour=round(d['gamesPerHour'], 1),
                   turnsPerHour=round(d['turnsPerHour']), meanGameSeconds=round(d['meanGameSeconds'], 1))
        if samples:
            row['load'] = window(samples, d['started'], d['finished'], period)
        rows.append(row)
    return rows


# ---- history ----

def machine():
    cpu = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            cpu = winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    except OSError:
        cpu = platform.processor()
    return dict(name=platform.node(), cpu=cpu, logicalCPUs=os.cpu_count())


def history_path(runs, name=None):
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', (name or platform.node() or 'machine')).lower()
    return Path(runs) / 'verify-history' / f'{name}.jsonl'


def load_history(path):
    out = []
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def append_history(path, entry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, separators=(',', ':')) + '\n')


def regression(history, entry, threshold=0.15, last=5):
    """Compare entry's host seconds per turn with the median of the last `last` runs of the same setup and mode.
    Returns {status, change, baseline, previous, changed: [what differs from the previous run]} or None."""
    key = (entry.get('setupKey'), entry.get('mode'))
    same = [h for h in history if (h.get('setupKey'), h.get('mode')) == key and _spt(h) is not None]
    now = _spt(entry)
    if not same or now is None:
        return None
    recent = same[-last:]
    base = statistics.median(_spt(h) for h in recent)
    change = now / base - 1 if base else None
    prev = same[-1]
    changed = [k for k in ('dllSHA256', 'modsKey', 'exeSHA256') if prev.get(k) != entry.get(k)]
    status = 'warn' if change is not None and change > threshold else 'pass'
    return dict(status=status, change=change, baseline=base, current=now, runs=len(recent), previous=prev.get('utc'),
                changed=changed)


def _spt(h):
    return ((h.get('host') or {}).get('perTurn') or {}).get('all')


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
