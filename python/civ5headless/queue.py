"""Parallel runner for headless games: a resumable queue of hhbench runs with N workers.

  python work/headless/runner.py run QUEUE.json [--workers N] [--affinity p-first|none] [--retry-failed]
  python work/headless/runner.py status QUEUE.json        # job table and totals (also written as QUEUE.summary.json)
  python work/headless/runner.py compare QUEUE.json       # samerun per seed pair, abcompare over the batch

QUEUE.json:

  {"out": "work/test-runs/ab1",            # run folders: <out>/<job name> (relative to the repository root)
   "workers": 8, "affinity": "p-first",
   "defaults": {"spec": "work/headless/specs/continents-standard.json", "turns": 100,
                "modsDir": "...MODS", "modsDb": "...Civ5ModsDatabase.db", "dll": "...CvGameCore_Expansion2.dll",
                "diagnostics": 0, "checkpointEvery": 1, "maxSeconds": 7200, "stallSeconds": 900,
                "maxMemoryMB": 3500, "prune": true, "hostArgs": []},
   "variants": {"A": {"dll": "a.dll", "abRole": "baseline"}, "B": {"dll": "b.dll", "abRole": "test"}},
   "seeds": [[1001, 2002], [1003, 2004]],   # [map, sync]; jobs = seeds x variants, named <variant>-m<map>-s<sync>
   "jobs": [{"name": "extra", "turns": 250}]}  # optional explicit jobs (defaults apply)

Job keys: spec, turns, dll, db (a built database; otherwise built once per (mods input, DLL) and cached),
modsDir, modsDb, exe, gameDir, seeds {map, sync}, diagnostics, improvedMask, abRole, checkpointEvery,
maxSeconds, stallSeconds, maxMemoryMB, prune, hostArgs, lowPriority (default true).

State: QUEUE.state.json (next to the queue). A restart skips completed runs (status.json completed), re-queues
interrupted ones (their folder is kept as <name>-rN) and leaves failed ones failed unless --retry-failed.
Pause: create QUEUE.stop; workers take no new job, running games finish. Ctrl-C kills the running games
(job objects) and marks them interrupted, so the next start re-queues them.
Workers: worker k is pinned to the k-th physical core, P-cores (both hyperthreads) first, then E-cores
(--affinity none: no pinning). Games run below normal priority unless lowPriority is false.
"""
from pathlib import Path
import argparse, collections, copy, json, os, subprocess, sys, threading, time
from datetime import datetime, timezone
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import dbcache, hhbench, winproc  # noqa: E402

DEFAULTS = dict(turns=100, diagnostics=0, checkpointEvery=1, maxSeconds=7200, stallSeconds=900, maxMemoryMB=3500,
                prune=True, hostArgs=[])
PATH_KEYS = ('spec', 'dll', 'db', 'modsDir', 'modsDb', 'exe')


def utc(): return datetime.now(timezone.utc).isoformat()


def rel(base, value):
    return str((base / value).resolve()) if value and not Path(value).is_absolute() else value


def expand(queue, qpath):
    """The job list: explicit jobs plus seeds x variants, each merged over the defaults."""
    base = ROOT
    defaults = dict(DEFAULTS, **queue.get('defaults', {}))
    jobs = []
    variants = queue.get('variants') or {}
    for seed in queue.get('seeds') or []:
        m, s = (seed['map'], seed['sync']) if isinstance(seed, dict) else seed
        for vname, v in (variants.items() if variants else [('run', {})]):
            jobs.append(dict(defaults, **v, name=f'{vname}-m{m}-s{s}', variant=vname, seeds=dict(map=m, sync=s)))
    for j in queue.get('jobs') or []:
        jobs.append(dict(defaults, **j))
    names = [j['name'] for j in jobs]
    dup = [n for n, c in collections.Counter(names).items() if c > 1]
    if dup:
        raise SystemExit(f'duplicate job names: {dup}')
    for j in jobs:
        for k in PATH_KEYS:
            if j.get(k):
                j[k] = rel(base, j[k])
        if not j.get('spec') or not j.get('dll'):
            raise SystemExit(f"job {j['name']}: spec and dll are required")
        if not j.get('db') and not (j.get('modsDir') and j.get('modsDb')):
            raise SystemExit(f"job {j['name']}: db, or modsDir and modsDb, is required")
    return jobs


class Queue:
    def __init__(self, qpath):
        self.qpath = Path(qpath).resolve()
        self.queue = json.loads(self.qpath.read_text(encoding='utf-8'))
        self.out = Path(rel(ROOT, self.queue.get('out') or f'work/test-runs/{self.qpath.stem}'))
        self.jobs = expand(self.queue, self.qpath)
        self.state_path = self.qpath.with_suffix('.state.json')
        self.stop_path = self.qpath.with_suffix('.stop')
        self.log_path = self.qpath.with_suffix('.log')
        self.lock = threading.Lock()
        self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.is_file() else {}
        self.state.setdefault('jobs', {})

    def save(self):
        tmp = self.state_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.state, indent=1) + '\n', encoding='utf-8')
        os.replace(tmp, self.state_path)

    def log(self, message):
        line = f'{utc()} {message}'
        with self.lock:
            with self.log_path.open('a', encoding='utf-8') as f:
                f.write(line + '\n')
        print(line, flush=True)

    def run_dir(self, job):
        return self.out / job['name']

    def status(self, job):
        return hhbench.read(self.run_dir(job) / 'status.json') or {}


def job_args(job, folder, db, affinity):
    return SimpleNamespace(run=None, run_dir=str(folder), spec=job['spec'], target_turn=int(job['turns']), dll=job['dll'], db=str(db),
                           mods_dir=job.get('modsDir'), mods_db=job.get('modsDb'), exe=job.get('exe'), game_dir=job.get('gameDir'),
                           diagnostics=int(job.get('diagnostics') or 0), improved_mask=job.get('improvedMask'), ab_role=job.get('abRole'),
                           checkpoint_every=int(job.get('checkpointEvery') or 1), stall_seconds=job.get('stallSeconds'),
                           max_memory_mb=job.get('maxMemoryMB') or None, affinity=affinity, prune=bool(job.get('prune')),
                           poll=1.0, host_arg=list(job.get('hostArgs') or []), maximum_seconds=job.get('maxSeconds'),
                           seeds=job.get('seeds'), low_priority=bool(job.get('lowPriority', True)))


def prepare(q, retry_failed):
    """Classify every job; move interrupted (and, with retry_failed, failed) attempts aside. Returns pending jobs."""
    pending = []
    for job in q.jobs:
        st = q.state['jobs'].setdefault(job['name'], dict(state='pending', attempts=0))
        status = q.status(job)
        folder = q.run_dir(job)
        if status.get('state') == 'completed':
            st['state'] = 'completed'
            continue
        if folder.exists():
            again = st.get('state') in ('running', 'interrupted', 'pending') or (retry_failed and st.get('state') == 'failed')
            if not again:
                st['state'] = 'failed'
                continue
            n = 2
            while folder.with_name(f'{folder.name}-r{n}').exists():
                n += 1
            folder.rename(folder.with_name(f'{folder.name}-r{n}'))
            st.setdefault('previous', []).append(dict(folder=f'{folder.name}-r{n}', state=st.get('state'), error=st.get('error')))
        st['state'] = 'pending'
        pending.append(job)
    q.save()
    return pending


def databases(q, jobs):
    """Build (or find) the database of every job: once per (mods input, DLL) through dbcache."""
    out = {}
    for job in jobs:
        if job.get('db'):
            out[job['name']] = job['db']
            continue
        key = (job['modsDir'], job['modsDb'], job['dll'], job.get('exe'))
        if key not in out:
            t = time.monotonic()
            db, inputs, k = dbcache.get_db(job['modsDir'], job['modsDb'], job['dll'], job.get('exe'), log=q.log)
            out[key] = str(db)
            q.log(f'database {k} for {Path(job["dll"]).parent.name}/{Path(job["dll"]).name}: {db} ({time.monotonic() - t:.1f} s)')
        out[job['name']] = out[key]
    return out


def run(args):
    q = Queue(args.queue)
    q.out.mkdir(parents=True, exist_ok=True)
    workers = args.workers or int(q.queue.get('workers', 8))
    mode = args.affinity or q.queue.get('affinity', 'p-first')
    masks = winproc.worker_affinities(workers, mode)
    pending = prepare(q, args.retry_failed)
    q.log(f'queue {q.qpath.name}: {len(q.jobs)} jobs, {len(pending)} to run, {workers} workers, affinity {mode}')
    if not pending:
        return summary(q)
    dbs = databases(q, pending)
    todo = collections.deque(pending)
    started = time.monotonic()
    previous = (q.state.get('queue') or {}).get('seconds') or 0  # batch time of earlier sessions (resume)
    q.state['queue'] = dict(state='running', started=utc(), workers=workers, affinity=mode, seconds=previous)
    q.save()
    stopping = threading.Event()

    def worker(slot):
        while not stopping.is_set():
            with q.lock:
                if q.stop_path.exists() or not todo:
                    return
                job = todo.popleft()
                st = q.state['jobs'][job['name']]
                st.update(state='running', worker=slot, started=utc(), attempts=st.get('attempts', 0) + 1,
                          affinity=hex(masks[slot]) if masks[slot] else None)
                q.save()
            q.log(f"[w{slot}] start {job['name']} ({job['turns']} turns, {Path(job['dll']).parent.name})")
            t = time.monotonic()
            try:
                code = hhbench.newgame(job_args(job, q.run_dir(job), dbs[job['name']], masks[slot]), quiet=True)
            except KeyboardInterrupt:
                code = None
            except BaseException as error:  # noqa: BLE001
                code = 1
                q.log(f"[w{slot}] {job['name']}: {type(error).__name__}: {error}")
            status = q.status(job)
            proc = status.get('process') or {}
            with q.lock:
                st = q.state['jobs'][job['name']]
                if stopping.is_set() and status.get('state') != 'completed':
                    st.update(state='interrupted', finished=utc())
                else:
                    st.update(state='completed' if code == 0 and status.get('state') == 'completed' else 'failed', finished=utc(),
                              seconds=round(time.monotonic() - t, 1), wallSeconds=status.get('wallSeconds'), endTurn=status.get('endTurn'),
                              peakWorkingSetMB=round((proc.get('PeakWorkingSet') or 0) / 2 ** 20), cpuSeconds=round(proc.get('CPUSeconds') or 0, 1),
                              error=status.get('error'))
                q.save()
            q.log(f"[w{slot}] {st['state']} {job['name']}: {status.get('endTurn')} turns, autoplay {status.get('wallSeconds')} s, "
                  f"host {status.get('hostSeconds')} s, peak {round((proc.get('PeakWorkingSet') or 0) / 2 ** 20)} MB"
                  + (f", error {status.get('error')}" if status.get('error') else ''))

    meter = winproc.LoadMeter().start()
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    for th in threads:
        th.start()
        time.sleep(0.2)  # stagger the database copies and map generation a little
    try:
        while any(th.is_alive() for th in threads):
            for th in threads:
                th.join(timeout=0.5)
    except KeyboardInterrupt:
        stopping.set()
        q.log('interrupted: the running games are killed with their job objects; restart to resume')
        raise
    finally:
        with q.lock:
            q.state['queue']['background'] = meter.stop()
            q.state['queue'].update(state='stopped' if (q.stop_path.exists() or stopping.is_set()) else 'finished', finished=utc(),
                                    seconds=round(previous + time.monotonic() - started, 1))
            q.save()
    return summary(q)


def summary(q, batch_seconds=None):
    rows = []
    for job in q.jobs:
        s = q.status(job)
        st = q.state['jobs'].get(job['name'], {})
        proc = s.get('process') or {}
        rows.append(dict(name=job['name'], variant=job.get('variant'), state=s.get('state') or st.get('state', 'pending'),
                         turns=s.get('endTurn'), endReason=s.get('endReason'), wallSeconds=s.get('wallSeconds'),
                         secondsPerTurn=s.get('secondsPerTurn'), hostSeconds=s.get('hostSeconds'),
                         cpuSeconds=round(proc.get('CPUSeconds') or 0, 1) or None,
                         peakWorkingSetMB=round((proc.get('PeakWorkingSet') or 0) / 2 ** 20) or None,
                         peakCommitMB=round((proc.get('PeakCommit') or 0) / 2 ** 20) or None,
                         worker=st.get('worker'), error=s.get('error') or st.get('error')))
    done = [r for r in rows if r['state'] == 'completed']
    totals = dict(jobs=len(rows), completed=len(done), failed=sum(r['state'] == 'failed' for r in rows),
                  pending=sum(r['state'] not in ('completed', 'failed') for r in rows),
                  gameTurns=sum(r['turns'] or 0 for r in done), hostSeconds=round(sum(r['hostSeconds'] or 0 for r in done), 1))
    qs = q.state.get('queue') or {}
    batch = batch_seconds or qs.get('seconds')
    if batch:
        totals.update(batchSeconds=round(batch, 1), gameTurnsPerHour=round(totals['gameTurns'] * 3600 / batch))
    if qs.get('background'):
        bg = dict(qs['background'])
        hosts = sum(r['cpuSeconds'] or 0 for r in done)
        bg['otherBusyCores'] = round(bg['systemBusyCores'] - hosts / max(bg['seconds'], 1e-6), 2)
        totals['background'] = bg  # last session; otherBusyCores = everything but the hosts (real game, OS, ...)
    print(f"{'job':<28}{'state':<11}{'turns':>6}{'autoplay s':>11}{'s/turn':>8}{'host s':>8}{'CPU s':>8}{'peak MB':>8}  end")
    for r in rows:
        print(f"{r['name']:<28}{r['state']:<11}{r['turns'] or '':>6}{r['wallSeconds'] or '':>11}{r['secondsPerTurn'] or '':>8}"
              f"{r['hostSeconds'] or '':>8}{r['cpuSeconds'] or '':>8}{r['peakWorkingSetMB'] or '':>8}  {r['endReason'] or ''}"
              + (f"  {r['error']}" if r['error'] else ''))
    print('totals: ' + json.dumps(totals))
    hhbench.write(q.qpath.with_suffix('.summary.json'), dict(utc=utc(), out=str(q.out), totals=totals, jobs=rows))
    return 0 if totals['failed'] == 0 and totals['pending'] == 0 else 1


def compare(args):
    """samerun.py for each seed's variant pair, then abcompare.py and compare.py over the completed runs."""
    q = Queue(args.queue)
    done = [j for j in q.jobs if q.status(j).get('state') == 'completed']
    tools = ROOT / 'work/vpbench'
    by_seed = collections.defaultdict(list)
    for j in done:
        by_seed[json.dumps(j.get('seeds'), sort_keys=True)].append(j)
    if (tools / 'samerun.py').is_file():
        for seed, js in by_seed.items():
            for other in js[1:]:
                print(f"\nsamerun {js[0]['name']} {other['name']}:", flush=True)
                subprocess.run([sys.executable, '-B', str(tools / 'samerun.py'), str(q.run_dir(js[0])), str(q.run_dir(other))])
    turns = sorted({int(j['turns']) for j in done})
    if (tools / 'abcompare.py').is_file() and done:
        marks = [t for t in (50, 100, 150, 200, 250) if t <= max(turns)]
        print('\nabcompare:', flush=True)
        subprocess.run([sys.executable, '-B', str(tools / 'abcompare.py')] + [str(q.run_dir(j)) for j in done]
                       + ['--turns', ','.join(map(str, marks)), '--json', str(q.qpath.with_suffix('.abcompare.json'))])
    if args.compare_runs and done:
        print('\ncompare:', flush=True)
        subprocess.run([sys.executable, '-B', str(tools / 'compare.py')] + [str(q.run_dir(j)) for j in done[:args.compare_runs]])
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run'); r.add_argument('queue')
    r.add_argument('--workers', type=int); r.add_argument('--affinity', choices=['p-first', 'none'])
    r.add_argument('--retry-failed', action='store_true')
    s = sub.add_parser('status'); s.add_argument('queue')
    c = sub.add_parser('compare'); c.add_argument('queue')
    c.add_argument('--compare-runs', type=int, default=4, help='also print compare.py for the first N runs (0: no)')
    a = p.parse_args()
    if a.command == 'run':
        return run(a)
    if a.command == 'status':
        return summary(Queue(a.queue))
    return compare(a)


if __name__ == '__main__':
    sys.exit(main())
