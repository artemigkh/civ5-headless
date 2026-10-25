"""Frame-count independence sweep: play each case with and without --frame-skew and compare the digests.

  python work/headless/skew_sweep.py [MATRIX.json ...] --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--exe EXE]
         [--only REGEX] [--min-turns N] [--skews 2,7] [--workers N] [--tag TAG]
         [--case NAME=SPEC.json:TURNS ...] [--host-arg=ARG ...]

civ5headless.exe --frame-skew K runs one extra CvGame::update before every K-th one, so the turn slice (+1 per
update) advances differently while the game is the same. Any digest difference between K=0 and K>0 is a result that
depends on the engine's frame count (a cache keyed on the turn slice that a recomputation would not give, an AI
step that waits a number of slices, ...); the real game's frame count is not the host's, so each such dependence is
a host/real divergence waiting to happen. Runs go to work/headless-runs/skew-<tag>-<case>-k<K>; the summary to
work/headless-runs/skew-<tag>.json. Each result line is printed as soon as both runs of a pair are done.
"""
import argparse, json, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'work/headless-runs'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'tools/headless'))
import gamespec, hhdigest  # noqa: E402

DEFAULT_DB = ROOT / 'work/headless/db/mods-reference-08D19878.db'
META = hhdigest.META


def latest_exe():
    return Path((ROOT / 'work/latest-headless-build-path.txt').read_text(encoding='utf-8').strip()) / 'civ5headless.exe'


def first_difference(a, b):
    da, db = hhdigest.digest_lines(a), hhdigest.digest_lines(b)
    keys = sorted(set(da) & set(db), key=lambda k: (k[1], k[0] or ''))
    for key in keys:
        fa, oa = da[key]
        fb, ob = db[key]
        if fa['total'] != fb['total'] or any(fa.get(n) != fb.get(n) for n in set(oa) | set(ob) if n not in META):
            diff = [n for n in oa if n not in META and fa.get(n) != fb.get(n)]
            diff += [n for n in ob if n not in META and n not in fa]
            return dict(identical=False, turn=key[1], point=key[0], sections=diff, common=len(keys))
    return dict(identical=True, common=len(keys), onlyBase=len(set(da) - set(db)), onlySkew=len(set(db) - set(da)))


def run(case, k, a):
    name = f'skew-{a.tag}-{case["name"]}-k{k}'
    out = OUT / name
    if out.exists():
        shutil.rmtree(out)
    cmd = [str(Path(a.exe).resolve() if a.exe else latest_exe()), 'newgame', '--spec', str(case['specPath']), '--out', str(out),
           '--dll', str(Path(a.dll).resolve()), '--db', str(Path(a.db).resolve()), '--turns', str(case['turns'])]
    if a.mods_db: cmd += ['--mods-db', str(Path(a.mods_db).resolve())]
    if a.loc_db: cmd += ['--loc-db', str(Path(a.loc_db).resolve())]
    if k: cmd += ['--frame-skew', str(k)]
    cmd += a.host_arg
    started = time.monotonic()
    with open(OUT / f'{name}.host.txt', 'wb') as f:
        code = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return case['name'], k, dict(exitCode=code, seconds=round(time.monotonic() - started, 1), digest=str(out / 'Logs/HeadlessDigest.log'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix', nargs='*')
    ap.add_argument('--dll', required=True)
    ap.add_argument('--db', default=str(DEFAULT_DB))
    ap.add_argument('--mods-db')
    ap.add_argument('--loc-db')
    ap.add_argument('--exe')
    ap.add_argument('--only', help='Regex on case names')
    ap.add_argument('--min-turns', type=int, default=0, help='Skip cases shorter than this')
    ap.add_argument('--skews', default='2,7')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--tag', default='sweep')
    ap.add_argument('--case', action='append', default=[], help='NAME=RESOLVED_SPEC.json:TURNS (already resolved)')
    ap.add_argument('--host-arg', action='append', default=[])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for m in a.matrix:
        matrix = json.loads(Path(m).read_text(encoding='utf-8'))
        prefix = matrix.get('prefix', 'm')
        for c in matrix['cases']:
            name = f'{prefix}-{c["name"]}'
            spec = OUT / f'skew-{a.tag}-{name}.resolved.json'
            spec.write_text(json.dumps(gamespec.resolve(c['spec']), indent=1) + '\n', encoding='utf-8')
            cases.append(dict(name=name, specPath=spec, turns=c['turns']))
    for c in a.case:
        name, rest = c.split('=', 1)
        spec, turns = rest.rsplit(':', 1)
        cases.append(dict(name=name, specPath=Path(spec), turns=int(turns)))
    cases = [c for c in cases if c['turns'] >= a.min_turns and (not a.only or re.search(a.only, c['name']))]
    skews = [int(s) for s in a.skews.split(',') if s.strip()]
    runs, results, lock = {}, [], threading.Lock()
    summary_path = OUT / f'skew-{a.tag}.json'
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        # base runs first, so the pairs complete early
        futures = [pool.submit(run, c, 0, a) for c in cases]
        futures += [pool.submit(run, c, k, a) for k in skews for c in cases]
        for fut in as_completed(futures):
            name, k, r = fut.result()
            with lock:
                runs[(name, k)] = r
                pairs = [(name, k)] if k else [(name, kk) for kk in skews]
                for (n, kk) in pairs:
                    if (n, 0) in runs and (n, kk) in runs:
                        base, sk = runs[(n, 0)], runs[(n, kk)]
                        res = dict(case=n, skew=kk, baseExit=base['exitCode'], skewExit=sk['exitCode'],
                                   seconds=[base['seconds'], sk['seconds']])
                        if Path(base['digest']).exists() and Path(sk['digest']).exists():
                            res.update(first_difference(base['digest'], sk['digest']))
                        else:
                            res['identical'] = None
                        results.append(res)
                        if res.get('identical'):
                            text = f"identical on {res['common']} points"
                        elif res.get('identical') is None:
                            text = 'missing digest'
                        else:
                            text = f"DIFFERENT from turn {res['turn']} ({res['point']}): {', '.join(res['sections'])}"
                        print(f"{n} k={kk}: {text} (exit {res['baseExit']}/{res['skewExit']})", flush=True)
                        summary_path.write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return 0 if all(r.get('identical') for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
