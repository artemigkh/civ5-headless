"""Run the headless host on every case of a matrix before the real game records it (host-first parity).

  python work/headless/host_first.py MATRIX.json --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--exe EXE]
         [--only REGEX] [--workers N]

Each case's spec is resolved (work/headless/gamespec.py, as game_probe.py does) and played by civ5headless.exe for the
case's turns into work/headless-runs/first-<prefix>-<name> (the parity_run.py command line, without a reference).
Then record the real game with

  python work/headless/record_matrix.py MATRIX.json --require-host \\
         --host-digest "work/headless-runs/first-{run}/Logs/HeadlessDigest.log"

so each real-game run stops a couple of turns after its first difference from the host. The DLL must be the one
deployed in the real game (a field-map build of the same source is fine). Summary: work/headless-runs/first-<prefix>.json.
"""
import argparse, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'work/headless-runs'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'tools/headless'))
import gamespec, hhdigest  # noqa: E402

DEFAULT_DB = ROOT / 'work/headless/db/mods-reference-08D19878.db'


def latest_exe():
    return Path((ROOT / 'work/latest-headless-build-path.txt').read_text(encoding='utf-8').strip()) / 'civ5headless.exe'


def run_case(prefix, case, a):
    name = f'first-{prefix}-{case["name"]}'
    run = OUT / name
    if run.exists():
        import shutil
        shutil.rmtree(run)
    run.parent.mkdir(parents=True, exist_ok=True)
    resolved_path = OUT / f'{name}.resolved.json'
    resolved_path.write_text(json.dumps(gamespec.resolve(case['spec']), indent=1) + '\n', encoding='utf-8')
    cmd = [str(Path(a.exe).resolve() if a.exe else latest_exe()), 'newgame', '--spec', str(resolved_path), '--out', str(run),
           '--dll', str(Path(a.dll).resolve()), '--db', str(Path(a.db).resolve()), '--turns', str(case['turns'])]
    if a.mods_db: cmd += ['--mods-db', str(Path(a.mods_db).resolve())]
    if a.loc_db: cmd += ['--loc-db', str(Path(a.loc_db).resolve())]
    started = time.monotonic()
    with open(OUT / f'{name}.host.txt', 'wb') as out:
        code = subprocess.call(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    log = run / 'Logs/HeadlessDigest.log'
    turns = [k[1] for k in hhdigest.digest_lines(log)] if log.exists() else []
    result = dict(case=case['name'], run=str(run), exitCode=code, seconds=round(time.monotonic() - started, 1),
                  digestPoints=len(turns), lastTurn=max(turns, default=None), digest=str(log) if log.exists() else None)
    print(f"{case['name']}: exit {code}, {len(turns)} digest points to T{result['lastTurn']} in {result['seconds']} s", flush=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix')
    ap.add_argument('--dll', required=True)
    ap.add_argument('--db', default=str(DEFAULT_DB))
    ap.add_argument('--mods-db')
    ap.add_argument('--loc-db')
    ap.add_argument('--exe', help='civ5headless.exe (default: work/latest-headless-build-path.txt)')
    ap.add_argument('--only', help='Regex on case names')
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args()
    matrix = json.loads(Path(a.matrix).read_text(encoding='utf-8'))
    prefix = matrix.get('prefix', 'hh-m5')
    cases = [c for c in matrix['cases'] if not a.only or re.search(a.only, c['name'])]
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        results = list(pool.map(lambda c: run_case(prefix, c, a), cases))
    (OUT / f'first-{prefix}.json').write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return 0 if all(r['exitCode'] == 0 for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
