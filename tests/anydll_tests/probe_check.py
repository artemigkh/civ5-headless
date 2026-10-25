#!/usr/bin/env python3
"""The fingerprint probe must never change a game: check it with any DLL.

  python tests/anydll_tests/probe_check.py --config CONFIG.json --exe EXE --out RUNS_DIR [--cases a,b] [--every 5]
                                           [--workers N] [--no-off] [--probe probes/fingerprint.lua]

CONFIG.json is invariant.py's. Every case is played three times: <case>-dense (probe on every turn), <case>-sparse
(probe every --every turns) and <case>-off (no probe; --no-off leaves it out). Checks, per case:
  - the dense and sparse runs fingerprint every expected turn, without probe errors or missing line parts;
  - dense and sparse fingerprints are identical on their common turns (sampling more often changes nothing);
  - with a DLL that writes digests (Logs/HeadlessDigest.log): the three runs' digest logs are identical.
The exit code is 0 when every check passes. Standard library only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'python'))

import invariant  # noqa: E402
from civ5headless import fingerprint  # noqa: E402


def variants(case, probe, every_file, no_off):
    out = [('dense', ['--lua-probe', str(probe)]), ('sparse', ['--lua-probe', str(every_file), '--lua-probe', str(probe)])]
    if not no_off:
        out.append(('off', []))
    return out


def check_case(runs, case, every, no_off):
    """[(ok, text)] for one case."""
    name = case['name']
    out = []
    dense, sparse, off = (runs / f'{name}-{v}' for v in ('dense', 'sparse', 'off'))
    fps = {}
    for label, run, step in (('dense', dense, 1), ('sparse', sparse, every)):
        try:
            fp = fingerprint.read(run)
        except FileNotFoundError as e:
            out.append((False, f'{label}: {e}'))
            continue
        fps[label] = fp
        turns = fp.turns()
        last = max(turns, default=-1)
        expected = [t for t in range(0, last + 1) if t % step == 0]
        missing = [t for t in expected if t not in fp.sections]
        ok = (bool(turns) and not missing and not fp.errors and not fp.incomplete
              and last >= int(case['turns']) // step * step)
        out.append((ok, f'{label}: {len(turns)} turns (last {last})'
                    + (f'; missing {missing[:8]}' if missing else '') + (f'; errors {fp.errors}' if fp.errors else '')
                    + (f'; incomplete {fp.incomplete}' if fp.incomplete else '')))
    if len(fps) == 2:
        r = fingerprint.compare(fps['dense'], fps['sparse'])
        out.append((r['identical'] and r['common'] >= 2, 'dense / sparse fingerprints: ' + fingerprint.summary(r)))
    if (dense / 'Logs' / 'HeadlessDigest.log').is_file():
        pairs = [('sparse', sparse)] + ([] if no_off else [('off', off)])
        for label, run in pairs:
            verdict = invariant.compare_case(dense, run)
            out.append((verdict.startswith('identical'), f'dense / {label} digests: {verdict}'))
    else:
        out.append((True, 'no digest log (DLL without the digest additions): fingerprints only'))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', required=True)
    ap.add_argument('--exe', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cases')
    ap.add_argument('--every', type=int, default=5, help='the sparse run fingerprints every this many turns')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--no-off', action='store_true', help='skip the run without the probe')
    ap.add_argument('--probe', default=str(HERE.parents[1] / 'probes' / 'fingerprint.lua'))
    ap.add_argument('--check-only', action='store_true', help='check the runs already in --out')
    a = ap.parse_args()
    cfg = invariant.load_config(a.config)
    cases = invariant.pick(cfg['cases'], a.cases)
    runs = Path(a.out)
    runs.mkdir(parents=True, exist_ok=True)
    every_file = runs / f'probe-every-{a.every}.lua'
    every_file.write_text(f'C5HFP_EVERY = {a.every}\n', encoding='utf-8')
    probe = Path(a.probe).resolve()
    if not a.check_only:
        jobs = []
        for case in cases:
            for label, args in variants(case, probe, every_file.resolve(), a.no_off):
                jobs.append((dict(case, name=f"{case['name']}-{label}"), args))
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures = [pool.submit(invariant.run_one, cfg, c, Path(a.exe), runs, args) for c, args in jobs]
            for f in concurrent.futures.as_completed(futures):
                name, rc, secs = f.result()
                print('%-34s rc=%d %6.1f s' % (name, rc, secs), flush=True)
    bad = 0
    for case in cases:
        for ok, text in check_case(runs, case, a.every, a.no_off):
            bad += not ok
            print('%-24s %s %s' % (case['name'], 'ok  ' if ok else 'FAIL', text))
    print('probe check: ' + ('passed' if not bad else f'{bad} failure(s)'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
