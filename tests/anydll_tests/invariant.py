#!/usr/bin/env python3
"""Host invariant check: the same games with two host builds (or options) must give identical digest logs.

  python tests/anydll_tests/invariant.py run --config CONFIG.json --exe EXE --out RUNS_DIR [--cases a,b] [--workers N]
                                       [--host-arg=ARG ...]
  python tests/anydll_tests/invariant.py compare BASE_DIR NEW_DIR [--cases a,b]

CONFIG.json (per machine, keep it out of the repository, for example under runs/):

  {"dll": "...CvGameCore_Expansion2.dll", "db": "...built.db", "modsDb": "...Civ5ModsDatabase.db",
   "locDb": "...Localization-Merged.db", "modsDir": null, "gameDir": null,
   "cases": [{"name": "speed-quick", "spec": "...resolved.json", "turns": 100}, ...]}

`run` plays every case into RUNS_DIR/<name> (at most --workers at once). `compare` compares Logs/HeadlessDigest.log of
each case line by line; HHENV lines may differ only in their thread id. The exit code is 0 when every case is
identical. Standard library only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import time
from pathlib import Path

THREAD = re.compile(r'\|thread=\d+')


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('dll', 'db', 'cases'):
        if key not in cfg:
            raise SystemExit('config: missing ' + key)
    return cfg


def pick(cases, names):
    if not names:
        return cases
    wanted = [n.strip() for n in names.split(',') if n.strip()]
    by_name = {c['name']: c for c in cases}
    missing = [n for n in wanted if n not in by_name]
    if missing:
        raise SystemExit('unknown case(s): ' + ', '.join(missing))
    return [by_name[n] for n in wanted]


def command(cfg, case, exe, out, host_args):
    cmd = [str(exe), 'newgame', '--spec', str(case['spec']), '--out', str(out), '--dll', str(cfg['dll']),
           '--db', str(cfg['db']), '--turns', str(case['turns'])]
    for key, opt in (('modsDb', '--mods-db'), ('locDb', '--loc-db'), ('modsDir', '--mods-dir'), ('gameDir', '--game-dir')):
        if cfg.get(key):
            cmd += [opt, str(cfg[key])]
    cmd += list(case.get('hostArgs', [])) + list(host_args)
    return cmd


def run_one(cfg, case, exe, runs, host_args):
    out = runs / case['name']
    cmd = command(cfg, case, exe, out, host_args)
    t0 = time.time()
    with (runs / (case['name'] + '.host.txt')).open('w', encoding='utf-8', errors='replace') as log:
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
    return case['name'], rc, time.time() - t0


def cmd_run(a):
    cfg = load_config(a.config)
    runs = Path(a.out)
    runs.mkdir(parents=True, exist_ok=True)
    cases = pick(cfg['cases'], a.cases)
    (runs / 'invariant-run.json').write_text(json.dumps({'exe': str(a.exe), 'hostArgs': a.host_arg, 'config': cfg},
                                                       indent=1), encoding='utf-8')
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(run_one, cfg, c, Path(a.exe), runs, a.host_arg) for c in cases]
        for f in concurrent.futures.as_completed(futures):
            name, rc, secs = f.result()
            print('%-28s rc=%d %6.1f s' % (name, rc, secs), flush=True)
            failed += rc != 0
    return 1 if failed else 0


def digest_lines(path):
    lines = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('HHENV|'):
            line = THREAD.sub('|thread=*', line)
        lines.append(line)
    return lines


def compare_case(base, new):
    a, b = base / 'Logs' / 'HeadlessDigest.log', new / 'Logs' / 'HeadlessDigest.log'
    if not a.is_file() or not b.is_file():
        return 'missing ' + (str(a) if not a.is_file() else str(b))
    la, lb = digest_lines(a), digest_lines(b)
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            fx, fy = x.split('|'), y.split('|')
            diff = [p for p, q in zip(fx, fy) if p != q]
            return 'line %d differs (%s): %s' % (i + 1, '|'.join(fx[:3]), ' '.join(diff[:6]))
    if len(la) != len(lb):
        return 'line counts differ: %d vs %d' % (len(la), len(lb))
    turns = sum(1 for x in la if x.startswith('HHDIGEST|'))
    return 'identical (%d digest lines)' % turns


def cmd_compare(a):
    base, new = Path(a.base), Path(a.new)
    names = sorted(p.name for p in base.iterdir() if (p / 'Logs' / 'HeadlessDigest.log').is_file())
    if a.cases:
        names = [n for n in names if n in set(a.cases.split(','))]
    bad = 0
    for name in names:
        verdict = compare_case(base / name, new / name)
        bad += not verdict.startswith('identical')
        print('%-28s %s' % (name, verdict))
    print('%d of %d identical' % (len(names) - bad, len(names)))
    return 1 if bad or not names else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--config', required=True)
    r.add_argument('--exe', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--cases')
    r.add_argument('--workers', type=int, default=4)
    r.add_argument('--host-arg', action='append', default=[], help='extra host option (write --host-arg=--opt)')
    c = sub.add_parser('compare')
    c.add_argument('base')
    c.add_argument('new')
    c.add_argument('--cases')
    a = ap.parse_args()
    return cmd_run(a) if a.cmd == 'run' else cmd_compare(a)


if __name__ == '__main__':
    sys.exit(main())
