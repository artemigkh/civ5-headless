"""Record real-game references for the headless parity matrix (plan section 6, M5).

  python -m civ5headless.realgame.record MATRIX.json [--only REGEX] [--limit N] [--retry-failed]
         [--host-digest TEMPLATE [--require-host] [--diverge-turns K]]

MATRIX.json is {"prefix": "hh-m5", "cases": [{"name": ..., "turns": N, "spec": {...spec...}}, ...]}.
Each case runs realgame/probe.py --spec (its own game launch, seeds pinned through config.ini, digest on,
autoplay armed before the load screen closes) into <runs>/<prefix>-<name>, with state dumps at the load screen and
after the last turn. The configured DLL is used as is; its SHA-256 is recorded per case.

Status: <runs>/<prefix>-matrix.json (one entry per case: state, run, dllSha, seconds, utc). The
recorder is resumable: finished cases are skipped, failed ones only with --retry-failed. Stop it between
cases by creating <runs>/<prefix>-matrix.stop (checked before each case).

To save real-game time, run the host on each case first (c5h host-first: same spec, DLL and turns) and pass
--host-digest with a path template such as "first-{run}/Logs/HeadlessDigest.log" (relative to the runs folder;
{run} = <prefix>-<name>, {name} =
the case name): the probe then compares the live digests with that log and quits K turns after the first
difference (divergence.json, live-compare.json in the run). Cases without a host log run in full, or are skipped
with --require-host. --rolling-dumps K also keeps the DLL's per-turn dumps around the divergence (<run>/HeadlessDumps).
"""
from pathlib import Path
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

from .. import config
from .dbcapture import sha256

PACKAGE_PARENT = Path(__file__).resolve().parents[2]


def utc(): return datetime.now(timezone.utc).isoformat()


def main(argv=None, cfg=None):
    cfg = cfg or config.load()
    ap = argparse.ArgumentParser(prog='python -m civ5headless.realgame.record', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix')
    ap.add_argument('--only', help='Regex on case names')
    ap.add_argument('--limit', type=int, default=0, help='Record at most this many cases')
    ap.add_argument('--retry-failed', action='store_true')
    ap.add_argument('--host-digest', help='Path template of a host run\'s HeadlessDigest.log per case ({run}, {name})')
    ap.add_argument('--require-host', action='store_true', help='Skip cases without a host digest')
    ap.add_argument('--diverge-turns', type=int, default=2)
    ap.add_argument('--rolling-dumps', type=int, default=0, help='Dump every turn, keep the last K (around a divergence)')
    args = ap.parse_args(argv)
    probes = config.System().repository()
    if probes is None:
        raise SystemExit('realgame.record needs the repository checkout (its probes/ folder)')
    probes = probes / 'probes'
    installed_dll = cfg.require('dll')
    matrix = json.loads(Path(args.matrix).read_text(encoding='utf-8'))
    prefix = matrix.get('prefix', 'hh-m5')
    runs = cfg.require('runs')
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
        host_digest = Path(args.host_digest.format(run=run, name=name)) if args.host_digest else None
        if host_digest and not host_digest.is_absolute(): host_digest = runs / host_digest
        if host_digest and not host_digest.exists():
            if args.require_host:
                print(f'{utc()} {name}: no host digest {host_digest}; skipped', flush=True)
                continue
            host_digest = None
        spec_path = runs / f'{run}.spec.json'
        spec_path.write_text(json.dumps(case['spec'], indent=1) + '\n', encoding='utf-8')
        dll_sha = sha256(installed_dll)
        command = [sys.executable, '-m', 'civ5headless.realgame.probe', '--run', run,
                   '--spec', str(spec_path), '--turns', str(case['turns']),
                   '--probe', f'InGame@start={probes / "dump-state.lua"}', '--probe', f'InGame@end={probes / "dump-state.lua"}']
        if host_digest: command += ['--host-digest', str(host_digest), '--diverge-turns', str(args.diverge_turns)]
        if args.rolling_dumps: command += ['--rolling-dumps', str(args.rolling_dumps)]
        entry.update(state='running', run=run, dllSha=dll_sha, utc=utc(), hostDigest=str(host_digest) if host_digest else None)
        save()
        print(f'{utc()} {name}: {case["turns"]} turns', flush=True)
        started = time.monotonic()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(PACKAGE_PARENT)] + [p for p in [os.environ.get('PYTHONPATH')] if p]))
        if cfg.file:
            env['C5H_CONFIG'] = str(cfg.file)
        with (runs / f'{run}.out').open('wb') as out:
            code = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env).returncode
        entry.update(state='done' if code == 0 else 'failed', exitCode=code, seconds=round(time.monotonic() - started, 1), utc=utc())
        save()
        print(f'{utc()} {name}: {entry["state"]} in {entry["seconds"]} s', flush=True)
        done += 1
    counts = {}
    for e in status.values(): counts[e['state']] = counts.get(e['state'], 0) + 1
    print('status:', counts, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
