"""Frame-count independence sweep: play each case with and without --frame-skew and compare the digests.

  c5h skew [MATRIX.json ...] --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--game-dir DIR] [--exe EXE]
           [--only REGEX] [--min-turns N] [--skews 2,7] [--workers N] [--tag TAG]
           [--case NAME=SPEC.json:TURNS ...] [--host-arg=ARG ...] [--resolved-from DIR]
  c5h skew --recompare TAG     (compare an existing sweep's digests again)

civ5headless.exe --frame-skew K runs one extra CvGame::update before every K-th one, so the turn slice (+1 per
update) advances differently while the game is the same. Any digest difference between K=0 and K>0 is a result that
depends on the engine's frame count (a cache keyed on the turn slice that a recomputation would not give, an AI
step that waits a number of slices, ...); the real game's frame count is not the host's, so each such dependence is
a host/real divergence waiting to happen. Runs go to <runs>/skew-<tag>-<case>-k<K>; the summary to
<runs>/skew-<tag>.json. Each result line is printed as soon as both runs of a pair are done. Inputs left out come
from the configuration, as for c5h parity.
"""
import argparse, json, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import config
from .. import spec as gamespec
from . import digest
from .parity import add_host_arguments, host_command, resolve_inputs


def first_difference(a, b):
    r = digest.compare(a, b)
    if r['identical']:
        return dict(identical=True, common=r['common'], onlyBase=r['onlyA'], onlySkew=r['onlyB'])
    # A transient difference (later points identical again, e.g. UI-timing state such as a dismissed notification)
    # is reported apart from one that persists (a changed game).
    f = r['first']
    return dict(identical=False, turn=f['turn'], point=f['point'], sections=f['sections'], common=r['common'],
                differingPoints=len(r['differing']), differingTurns=sorted(r['differing']),
                sectionsAll=sorted({n for s in r['differing'].values() for n in s}), lastPointIdentical=r['lastPointIdentical'])


def run(case, k, a, out_dir):
    name = f'skew-{a.tag}-{case["name"]}-k{k}'
    out = out_dir / name
    if out.exists():
        shutil.rmtree(out)
    cmd = host_command(a, case['specPath'], out, case['turns'])
    if k: cmd += ['--frame-skew', str(k)]
    cmd += a.host_arg
    started = time.monotonic()
    with open(out_dir / f'{name}.host.txt', 'wb') as f:
        code = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return case['name'], k, dict(exitCode=code, seconds=round(time.monotonic() - started, 1), digest=str(out / 'Logs/HeadlessDigest.log'))


def recompare(tag, out_dir):
    """Compare the digests of an existing sweep's runs again (skew-TAG-<case>-k<K>), without playing anything."""
    runs = {}
    for d in out_dir.glob(f'skew-{tag}-*-k*'):
        m = re.fullmatch(rf'skew-{re.escape(tag)}-(.+)-k(\d+)', d.name)
        if m and d.is_dir() and (d / 'Logs/HeadlessDigest.log').exists():
            runs[(m.group(1), int(m.group(2)))] = d / 'Logs/HeadlessDigest.log'
    ok = True
    for (case, k) in sorted(runs):
        if k and (case, 0) in runs:
            res = first_difference(runs[(case, 0)], runs[(case, k)])
            ok &= res['identical']
            print(f"{case} k={k}: " + (f"identical on {res['common']} points" if res['identical'] else
                  f"turns {res['differingTurns']} sections {', '.join(res['sectionsAll'])}"
                  f" ({'identical again at the end' if res['lastPointIdentical'] else 'still different at the end'})"))
    return 0 if ok else 1


def main(argv=None, cfg=None):
    cfg = cfg or config.load()
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == '--recompare':
        return recompare(argv[1], cfg.require('runs'))
    ap = argparse.ArgumentParser(prog='c5h skew', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix', nargs='*')
    add_host_arguments(ap, cfg)
    ap.add_argument('--min-turns', type=int, default=0, help='Skip cases shorter than this')
    ap.add_argument('--skews', default='2,7')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--tag', default='sweep')
    ap.add_argument('--case', action='append', default=[], help='NAME=RESOLVED_SPEC.json:TURNS (already resolved)')
    ap.add_argument('--host-arg', action='append', default=[])
    ap.add_argument('--resolved-from', help='Folder with first-<prefix>-<case>.resolved.json (c5h host-first) to reuse, '
                    'so the seeds are those of the recorded games')
    a = ap.parse_args(argv)
    resolve_inputs(a, cfg)
    out_dir = cfg.require('runs')
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for m in a.matrix:
        matrix = json.loads(Path(m).read_text(encoding='utf-8'))
        prefix = matrix.get('prefix', 'm')
        for c in matrix['cases']:
            name = f'{prefix}-{c["name"]}'
            spec = out_dir / f'skew-{a.tag}-{name}.resolved.json'
            known = Path(a.resolved_from) / f'first-{name}.resolved.json' if a.resolved_from else None
            if known and known.exists():
                spec.write_text(known.read_text(encoding='utf-8'), encoding='utf-8')
            else:
                spec.write_text(json.dumps(gamespec.resolve(c['spec'], a.db), indent=1) + '\n', encoding='utf-8')
            cases.append(dict(name=name, specPath=spec, turns=c['turns']))
    for c in a.case:
        name, rest = c.split('=', 1)
        spec, turns = rest.rsplit(':', 1)
        cases.append(dict(name=name, specPath=Path(spec), turns=int(turns)))
    cases = [c for c in cases if c['turns'] >= a.min_turns and (not a.only or re.search(a.only, c['name']))]
    skews = [int(s) for s in a.skews.split(',') if s.strip()]
    runs, results, lock = {}, [], threading.Lock()
    summary_path = out_dir / f'skew-{a.tag}.json'
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        # base runs first, so the pairs complete early
        futures = [pool.submit(run, c, 0, a, out_dir) for c in cases]
        futures += [pool.submit(run, c, k, a, out_dir) for k in skews for c in cases]
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
                            text = (f"DIFFERENT from turn {res['turn']} ({res['point']}): {', '.join(res['sections'])};"
                                    f" {res['differingPoints']} points differ, sections {', '.join(res['sectionsAll'])},"
                                    f" {'identical again at the end' if res['lastPointIdentical'] else 'still different at the end'}")
                        print(f"{n} k={kk}: {text} (exit {res['baseExit']}/{res['skewExit']})", flush=True)
                        summary_path.write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return 0 if all(r.get('identical') for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
