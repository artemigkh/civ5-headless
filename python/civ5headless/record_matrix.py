"""Record real-game references for the headless parity matrix (plan section 6, M5).

  python work/headless/record_matrix.py MATRIX.json [--only REGEX] [--limit N] [--retry-failed]

MATRIX.json is {"prefix": "hh-m5", "cases": [{"name": ..., "turns": N, "spec": {...gamespec...}}, ...]}.
Each case runs work/headless/game_probe.py --spec (seeds pinned, digest on, autoplay armed before the load
screen closes) into work/test-runs/<prefix>-<name>, with state dumps at the load screen and after the last
turn. The deployed DLL is used as is; its SHA-256 is recorded per case.

Status: work/test-runs/<prefix>-matrix.json (one entry per case: state, run, dllSha, seconds, utc). The
recorder is resumable: finished cases are skipped, failed ones only with --retry-failed. Stop it between
cases by creating work/test-runs/<prefix>-matrix.stop (checked before each case).
"""
from pathlib import Path
import argparse, json, re, subprocess, sys, time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/headless'))
from db_capture import INSTALLED_DLL, sha256

PROBES = ROOT / 'work/headless/probes'


def utc(): return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix')
    ap.add_argument('--only', help='Regex on case names')
    ap.add_argument('--limit', type=int, default=0, help='Record at most this many cases')
    ap.add_argument('--retry-failed', action='store_true')
    args = ap.parse_args()
    matrix = json.loads(Path(args.matrix).read_text(encoding='utf-8'))
    prefix = matrix.get('prefix', 'hh-m5')
    runs = ROOT / 'work/test-runs'
    status_path = runs / f'{prefix}-matrix.json'
    stop_path = runs / f'{prefix}-matrix.stop'
    status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}

    def save():
        status_path.write_text(json.dumps(status, indent=1) + '\n', encoding='utf-8')

    for case in matrix['cases']:
        status.setdefault(case['name'], {'state': 'pending', 'turns': case['turns']})
    save()
    done = 0
    for case in matrix['cases']:
        name = case['name']
        entry = status[name]
        if args.only and not re.search(args.only, name): continue
        if entry['state'] == 'done' or (entry['state'] == 'failed' and not args.retry_failed): continue
        if args.limit and done >= args.limit: break
        if stop_path.exists():
            print('stop file found; stopping', flush=True)
            break
        run = f'{prefix}-{name}'
        spec_path = runs / f'{run}.spec.json'
        spec_path.write_text(json.dumps(case['spec'], indent=1) + '\n', encoding='utf-8')
        dll_sha = sha256(INSTALLED_DLL)
        command = [sys.executable, str(ROOT / 'work/headless/game_probe.py'), '--run', run, '--dll-sha', dll_sha,
                   '--spec', str(spec_path), '--turns', str(case['turns']),
                   '--probe', f'InGame@start={PROBES / "dump-state.lua"}', '--probe', f'InGame@end={PROBES / "dump-state.lua"}']
        entry.update(state='running', run=run, dllSha=dll_sha, utc=utc())
        save()
        print(f'{utc()} {name}: {case["turns"]} turns', flush=True)
        started = time.monotonic()
        with (runs / f'{run}.out').open('wb') as out:
            code = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        last = (runs / f'{run}.out').read_text(encoding='utf-8', errors='replace').rstrip().splitlines()[-1:]
        quit_ok = bool(last) and '"action": "quit"' in last[0] and ('"gameExited": true' in last[0] or '"killed": true' in last[0])
        entry.update(state='done' if code == 0 and quit_ok else 'failed', exitCode=code, seconds=round(time.monotonic() - started, 1), utc=utc())
        save()
        print(f'{utc()} {name}: {entry["state"]} in {entry["seconds"]} s', flush=True)
        done += 1
    counts = {}
    for e in status.values(): counts[e['state']] = counts.get(e['state'], 0) + 1
    print('status:', counts, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
