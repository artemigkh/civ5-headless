"""Headless parity check of one real-game reference run (plan section 6, M5 matrix).

  python work/headless/parity_run.py REF_RUN --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--exe EXE]
         [--turns N] [--name NAME] [--host-arg ARG]...
  python work/headless/parity_run.py --matrix [STATUS.json] --dll DLL [...] [--only REGEX] [--workers N]

REF_RUN is a reference folder (work/test-runs/<name>, or just <name>) recorded by record_matrix.py / game_probe.py:
spec-resolved.json, HeadlessDigest.log, dump-tS (load screen; S = start turn) and dump-tE. The host replays the same
spec (same seeds) for E-S turns (default) into work/headless-runs/parity-<name>, then

  1. compares every HHDIGEST point of the two HeadlessDigest.log files (first divergent turn and sections),
  2. runs tools/headless/parity_t000.py on dump-t000 and on the final dump (field attribution from the
     reference's *.fields.txt when it was recorded with a field-map DLL).

The DLL must be the one the reference ran (same source; a field-map build is fine). The references are recorded
with the profile's logging on, which the host copies by default (older DLLs' AI results depend on it).

Result: <run>/parity-result.json and one summary line. --matrix runs every case whose state is "done" in the status
file (default work/test-runs/hh-m5-matrix.json), --workers in parallel, and writes
work/headless-runs/parity-summary.json. Exit code 0 when every compared case is identical.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAIN = ROOT.parents[2] if ROOT.parent.name == 'wt' else ROOT
RUNS = MAIN / 'work/test-runs'
OUT = ROOT / 'work/headless-runs'
sys.path.insert(0, str(ROOT / 'tools/headless'))
import hhdigest  # noqa: E402

DEFAULT_DB = MAIN / 'work/headless/db/mods-reference-08D19878.db'
DEFAULT_STATUS = RUNS / 'hh-m5-matrix.json'


def latest_exe():
    p = ROOT / 'work/latest-headless-build-path.txt'
    return Path(p.read_text(encoding='utf-8').strip()) / 'civ5headless.exe'


def ref_folder(ref):
    p = Path(ref)
    if not p.is_dir():
        p = RUNS / ref
    if not p.is_dir():
        raise SystemExit(f'no reference folder {ref}')
    return p.resolve()


def dump_turns(ref):
    """(first, last) game turns of the reference's dumps: the load screen (the start turn: 0, or the era's start
    turn such as 125) and the last turn. The host names its load-screen dump dump-t000 whatever the start turn."""
    turns = [int(m.group(1)) for d in ref.iterdir() if (m := re.fullmatch(r'dump-t(\d+)', d.name)) and d.is_dir()]
    return (min(turns), max(turns)) if turns else (0, 0)


def compare_digests(ref_log, host_log):
    """Per digest point: first divergent (turn, point, sections); common/only counts."""
    da, db = hhdigest.digest_lines(ref_log), hhdigest.digest_lines(host_log)
    keys = sorted(set(da) & set(db), key=lambda k: (k[1], k[0] or ''))
    first = None
    savedb = None
    for key in keys:
        fa, oa = da[key]
        fb, ob = db[key]
        diff = [n for n in oa if n not in hhdigest.META and fa.get(n) != fb.get(n)]
        diff += [n for n in ob if n not in hhdigest.META and n not in fa]
        # savedb is outside the digest total (hhdigest.EXCLUDED): reported, not a divergence
        if 'savedb' in diff and savedb is None:
            savedb = key[1]
        diff = [n for n in diff if n not in hhdigest.EXCLUDED]
        if fa['total'] != fb['total'] or diff:
            first = dict(turn=key[1], point=key[0], sections=diff)
            break
    return dict(common=len(keys), onlyRef=len(set(da) - set(db)), onlyHost=len(set(db) - set(da)), first=first,
                firstSavedbDiffTurn=savedb,
                lastRefTurn=max((k[1] for k in da), default=None), lastHostTurn=max((k[1] for k in db), default=None))


def compare_dump(ref_dump, host_dump):
    if not ref_dump.is_dir() or not host_dump.is_dir():
        return dict(ok=False, missing=[str(p) for p in (ref_dump, host_dump) if not p.is_dir()])
    proc = subprocess.run([sys.executable, str(ROOT / 'tools/headless/parity_t000.py'), str(ref_dump), str(host_dump)],
                          capture_output=True, text=True, errors='replace')
    lines = proc.stdout.splitlines()
    summary = next((l for l in lines if l.startswith('summary:')), '')
    different = [l for l in lines if 'DIFFERENT' in l or l.startswith('    ')]
    return dict(ok=proc.returncode == 0, summary=summary, different=different[:60])


def run_case(ref, a, quiet=False):
    ref = ref_folder(ref)
    name = a.name or f'parity-{ref.name}' + (f'-{a.tag}' if a.tag else '')
    first_turn, last_turn = dump_turns(ref)
    turns = a.turns if a.turns is not None else last_turn - first_turn
    run = OUT / name
    if run.exists():
        import shutil
        shutil.rmtree(run)
    run.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(a.exe or latest_exe()), 'newgame', '--spec', str(ref / 'spec-resolved.json'), '--out', str(run),
           '--dll', str(Path(a.dll).resolve()), '--db', str(Path(a.db).resolve())]
    if a.mods_db: cmd += ['--mods-db', str(Path(a.mods_db).resolve())]
    if a.loc_db: cmd += ['--loc-db', str(Path(a.loc_db).resolve())]
    if turns: cmd += ['--turns', str(turns)]
    cmd += list(a.host_arg or [])
    started = time.monotonic()
    log_path = OUT / f'{name}.host.txt'
    with open(log_path, 'wb') as out:
        code = subprocess.call(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    seconds = round(time.monotonic() - started, 1)
    result = dict(case=ref.name, ref=str(ref), run=str(run), turns=turns, exitCode=code, hostSeconds=seconds, command=cmd)
    host_log = run / 'Logs/HeadlessDigest.log'
    if code != 0 or not host_log.exists():
        result.update(status='host-failed', hostLog=str(log_path))
    else:
        result['digest'] = compare_digests(ref / 'HeadlessDigest.log', host_log)
        result['dumpT000'] = compare_dump(ref / f'dump-t{first_turn:03d}', run / 'dump-t000')
        # the reference's last dump: the target turn, or the turn a game to victory ended (the host stops there
        # too and names its final dump by that turn)
        final = f'dump-t{last_turn:03d}'
        result['dumpFinal'] = compare_dump(ref / final, run / final) if turns else result['dumpT000']
        d = result['digest']
        # a reference without digest points (0 turns: load-screen dump only) is judged on its dumps
        complete = d['lastRefTurn'] is None or (d['lastHostTurn'] is not None and d['lastHostTurn'] >= d['lastRefTurn'])
        identical = d['first'] is None and complete and result['dumpT000']['ok'] and result['dumpFinal']['ok']
        result['status'] = 'identical' if identical else 'different'
    (run / 'parity-result.json').write_text(json.dumps(result, indent=1), encoding='utf-8') if run.exists() else None
    if not quiet:
        print(summary_line(result), flush=True)
    return result


def summary_line(r):
    s = f"{r['case']}: {r['status']}"
    if r.get('digest'):
        d = r['digest']
        if d['first']:
            f = d['first']
            secs = ','.join(f['sections'])
            s += f" - first divergence turn {f['turn']} ({f['point']}): {secs[:120]}"
        else:
            s += f" - {d['common']} digest points match (ref to T{d['lastRefTurn']}, host to T{d['lastHostTurn']})"
        if not r['dumpFinal']['ok']:
            s += f" | final dump: {r['dumpFinal'].get('summary') or r['dumpFinal'].get('missing')}"
    return s + f" [host {r['hostSeconds']} s, {r['turns']} turns]"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ref', nargs='?', help='reference run folder or name under work/test-runs')
    ap.add_argument('--matrix', nargs='?', const=str(DEFAULT_STATUS), help='status file: run every "done" case')
    ap.add_argument('--only', help='regex on case names (with --matrix)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--dll', required=True, help='game DLL matching the reference (same source)')
    ap.add_argument('--db', default=str(DEFAULT_DB))
    ap.add_argument('--mods-db')
    ap.add_argument('--loc-db')
    ap.add_argument('--exe', help='civ5headless.exe (default: work/latest-headless-build-path.txt)')
    ap.add_argument('--turns', type=int, help='autoplay turns to arm (default: last dump turn minus first; for a game to victory pass the count the reference armed)')
    ap.add_argument('--name', help='run folder name (default parity-<ref>[-TAG])')
    ap.add_argument('--tag', help='suffix for the run folder names and the summary file (variants of a matrix run)')
    ap.add_argument('--host-arg', action='append', help='extra host argument (repeatable; use --host-arg=--x)')
    a = ap.parse_args()
    if a.matrix:
        status = json.loads(Path(a.matrix).read_text(encoding='utf-8'))
        cases = [v['run'] for k, v in status.items() if v.get('state') == 'done' and (not a.only or re.search(a.only, k))]
        a.name = None
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
            results = list(pool.map(lambda c: run_case(c, a), cases))
        summary = dict(dll=str(Path(a.dll).resolve()), cases={r['case']: dict(status=r['status'], line=summary_line(r))
                                                                for r in results})
        (OUT / (f'parity-summary-{a.tag}.json' if a.tag else 'parity-summary.json')).write_text(json.dumps(summary, indent=1), encoding='utf-8')
        n_ok = sum(r['status'] == 'identical' for r in results)
        print(f'{n_ok}/{len(results)} identical')
        return 0 if n_ok == len(results) else 1
    if not a.ref:
        ap.error('REF_RUN or --matrix is required')
    return 0 if run_case(a.ref, a)['status'] == 'identical' else 1


if __name__ == '__main__':
    sys.exit(main())
