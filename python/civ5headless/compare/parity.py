"""Parity of the host with real-game references (plan section 6, M5 matrix).

  c5h parity REF_RUN --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--game-dir DIR] [--exe EXE]
             [--turns N] [--name NAME] [--host-arg ARG]...
  c5h parity --matrix STATUS.json --dll DLL [...] [--only REGEX] [--workers N]
  c5h host-first MATRIX.json --dll DLL [--db DB] [--mods-db DB] [--loc-db DB] [--exe EXE] [--only REGEX] [--workers N]

parity: REF_RUN is a reference folder (a path, or a name under the runs folder) recorded in the real game:
spec-resolved.json, HeadlessDigest.log, dump-tS (load screen; S = start turn) and dump-tE. The host replays the same
spec (same seeds) for E-S turns (default) into <runs>/parity-<name>, then

  1. compares every HHDIGEST point of the two HeadlessDigest.log files (first divergent turn and sections),
  2. compares the dumps (c5h dumps) of the load screen and of the final turn (field attribution from the
     reference's *.fields.txt when it was recorded with a field-map DLL).

The DLL must be the one the reference ran (same source; a field-map build is fine). The references are recorded
with the profile's logging on, which the host copies by default (older DLLs' AI results depend on it).

Result: <run>/parity-result.json and one summary line. --matrix runs every case whose state is "done" in the status
file, --workers in parallel, and writes <runs>/parity-summary.json. Exit code 0 when every compared case is identical.

host-first: runs the host on every case of a matrix before the real game records it. Each case's spec is resolved
and played for the case's turns into <runs>/first-<prefix>-<name> (the parity command line, without a reference).
The real-game recorder then compares the live digests with these runs and stops a couple of turns after the first
difference. The DLL must be the one deployed in the real game (a field-map build of the same source is fine).
Summary: <runs>/first-<prefix>.json.

Inputs left out (--db, --mods-db, --loc-db, --game-dir, --exe) come from the configuration (c5h doctor); the game
database is --db, else the configured db, else the cached build for the configured mods and --dll.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config, dbcache
from .. import spec as gamespec
from . import digest, dumps

# The real-game probe's VICTORY call (victory.json of a game to victory), run in the host before its final dump
VICTORY_LUA = ("local ok,v=pcall(function() return Game.GetVictory() end);"
               "return {turn=Game.GetGameTurn(),winner=Game.GetWinner(),victory=ok and v or -2,state=Game.GetGameState()}")
VICTORY_KEYS = ('turn', 'winner', 'victory', 'state')


def ref_folder(ref, cfg):
    p = Path(ref)
    if not p.is_dir() and cfg.runs:
        p = cfg.runs / ref
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
    r = digest.compare(ref_log, host_log)
    return dict(common=r['common'], onlyRef=r['onlyA'], onlyHost=r['onlyB'], first=r['first'],
                firstSavedbDiffTurn=r['savedbFirstTurn'], lastRefTurn=r['lastTurnA'], lastHostTurn=r['lastTurnB'])


def compare_dump(ref_dump, host_dump):
    if not ref_dump.is_dir() or not host_dump.is_dir():
        return dict(ok=False, missing=[str(p) for p in (ref_dump, host_dump) if not p.is_dir()])
    ok, lines = dumps.compare_dumps(ref_dump, host_dump)
    summary = next((l for l in lines if l.startswith('summary:')), '')
    different = [l for l in lines if 'DIFFERENT' in l or l.startswith('    ')]
    return dict(ok=ok, summary=summary, different=different[:60])


def host_command(a, spec_path, out, turns):
    """The civ5headless.exe newgame command line for a resolved spec."""
    cmd = [str(a.exe), 'newgame', '--spec', str(spec_path), '--out', str(out), '--dll', str(Path(a.dll).resolve()),
           '--db', str(Path(a.db).resolve())]
    if a.mods_db: cmd += ['--mods-db', str(Path(a.mods_db).resolve())]
    if a.loc_db: cmd += ['--loc-db', str(Path(a.loc_db).resolve())]
    cmd += ['--game-dir', str(a.game_dir)]
    if turns: cmd += ['--turns', str(turns)]
    return cmd


def run_case(ref, a, cfg, quiet=False):
    ref = ref_folder(ref, cfg)
    out_dir = cfg.require('runs')
    name = a.name or f'parity-{ref.name}' + (f'-{a.tag}' if a.tag else '')
    first_turn, last_turn = dump_turns(ref)
    turns = a.turns if a.turns is not None else last_turn - first_turn
    run = out_dir / name
    if run.exists():
        shutil.rmtree(run)
    run.parent.mkdir(parents=True, exist_ok=True)
    cmd = host_command(a, ref / 'spec-resolved.json', run, turns)
    ref_victory = ref / 'victory.json'
    if ref_victory.exists():
        lua = out_dir / f'{name}.victory.lua'
        lua.write_text(VICTORY_LUA + '\n', encoding='utf-8')
        cmd += ['--lua-before-dump', str(lua)]
    cmd += list(a.host_arg or [])
    started = time.monotonic()
    log_path = out_dir / f'{name}.host.txt'
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
        if ref_victory.exists():
            rv = json.loads(ref_victory.read_text(encoding='utf-8'))
            hp = run / 'lua-before-dump.json'
            hv = json.loads(hp.read_text(encoding='utf-8')) if hp.exists() else None
            hv = hv if isinstance(hv, dict) else {}
            result['victory'] = dict(ref={k: rv.get(k) for k in VICTORY_KEYS}, host={k: hv.get(k) for k in VICTORY_KEYS})
            result['victory']['ok'] = result['victory']['ref'] == result['victory']['host']
            identical = identical and result['victory']['ok']
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
        if r.get('victory'):
            v = r['victory']
            s += f" | victory {'same' if v['ok'] else 'DIFFERENT'} {v['ref']}" + ('' if v['ok'] else f" host {v['host']}")
        if not r['dumpFinal']['ok']:
            s += f" | final dump: {r['dumpFinal'].get('summary') or r['dumpFinal'].get('missing')}"
    return s + f" [host {r['hostSeconds']} s, {r['turns']} turns]"


def add_host_arguments(ap, cfg):
    ap.add_argument('--dll', required=True, help='game DLL (the one the reference ran / the real game runs)')
    ap.add_argument('--db', help='game database (default: config db, else the cached build)')
    ap.add_argument('--mods-dir', default=cfg.mods_dir, help='MODS folder for the cached build (default: config mods_dir)')
    ap.add_argument('--mods-db', default=cfg.mods_db, help='default: config mods_db')
    ap.add_argument('--loc-db', default=cfg.loc_db, help='default: config loc_db')
    ap.add_argument('--game-dir', default=cfg.game_dir, help='default: config game_dir')
    ap.add_argument('--exe', default=cfg.exe, help='civ5headless.exe (default: config exe)')
    ap.add_argument('--only', help='regex on case names')


def resolve_inputs(a, cfg):
    """Fill a.exe, a.db and a.game_dir (errors name what is missing)."""
    a.exe = dbcache.find_exe(a.exe, cfg)
    if a.game_dir is None:
        cfg.require('game_dir', 'pass --game-dir')
    a.db = dbcache.database(cfg, db=a.db, mods_dir=a.mods_dir, mods_db=a.mods_db, dll=a.dll, exe=a.exe,
                            log=lambda m: print(m, file=sys.stderr))[0]


def main(argv=None, cfg=None):
    cfg = cfg or config.load()
    ap = argparse.ArgumentParser(prog='c5h parity', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ref', nargs='?', help='reference run folder, or a name under the runs folder')
    ap.add_argument('--matrix', help='status file: run every "done" case')
    add_host_arguments(ap, cfg)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--turns', type=int, help='autoplay turns to arm (default: last dump turn minus first; for a game to victory pass the count the reference armed)')
    ap.add_argument('--name', help='run folder name (default parity-<ref>[-TAG])')
    ap.add_argument('--tag', help='suffix for the run folder names and the summary file (variants of a matrix run)')
    ap.add_argument('--host-arg', action='append', help='extra host argument (repeatable; use --host-arg=--x)')
    a = ap.parse_args(argv)
    if not a.ref and not a.matrix:
        ap.error('REF_RUN or --matrix is required')
    resolve_inputs(a, cfg)
    if a.matrix:
        status = json.loads(Path(a.matrix).read_text(encoding='utf-8'))
        cases = [v['run'] for k, v in status.items() if v.get('state') == 'done' and (not a.only or re.search(a.only, k))]
        a.name = None
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
            results = list(pool.map(lambda c: run_case(c, a, cfg), cases))
        summary = dict(dll=str(Path(a.dll).resolve()), cases={r['case']: dict(status=r['status'], line=summary_line(r))
                                                                for r in results})
        (cfg.runs / (f'parity-summary-{a.tag}.json' if a.tag else 'parity-summary.json')).write_text(json.dumps(summary, indent=1), encoding='utf-8')
        n_ok = sum(r['status'] == 'identical' for r in results)
        print(f'{n_ok}/{len(results)} identical')
        return 0 if n_ok == len(results) else 1
    return 0 if run_case(a.ref, a, cfg)['status'] == 'identical' else 1


# ---- host first ----

def first_case(prefix, case, a, cfg):
    out_dir = cfg.require('runs')
    name = f'first-{prefix}-{case["name"]}'
    run = out_dir / name
    if run.exists():
        shutil.rmtree(run)
    run.parent.mkdir(parents=True, exist_ok=True)
    resolved_path = out_dir / f'{name}.resolved.json'
    resolved_path.write_text(json.dumps(gamespec.resolve(case['spec'], a.db), indent=1) + '\n', encoding='utf-8')
    cmd = host_command(a, resolved_path, run, case['turns'])
    started = time.monotonic()
    with open(out_dir / f'{name}.host.txt', 'wb') as out:
        code = subprocess.call(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    log = run / 'Logs/HeadlessDigest.log'
    turns = [k[1] for k in digest.digest_lines(log)] if log.exists() else []
    result = dict(case=case['name'], run=str(run), exitCode=code, seconds=round(time.monotonic() - started, 1),
                  digestPoints=len(turns), lastTurn=max(turns, default=None), digest=str(log) if log.exists() else None)
    print(f"{case['name']}: exit {code}, {len(turns)} digest points to T{result['lastTurn']} in {result['seconds']} s", flush=True)
    return result


def first_main(argv=None, cfg=None):
    cfg = cfg or config.load()
    ap = argparse.ArgumentParser(prog='c5h host-first', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('matrix', help='{"prefix": ..., "cases": [{"name", "turns", "spec"}]}')
    add_host_arguments(ap, cfg)
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args(argv)
    resolve_inputs(a, cfg)
    matrix = json.loads(Path(a.matrix).read_text(encoding='utf-8'))
    prefix = matrix.get('prefix', 'm')
    cases = [c for c in matrix['cases'] if not a.only or re.search(a.only, c['name'])]
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        results = list(pool.map(lambda c: first_case(prefix, c, a, cfg), cases))
    (cfg.runs / f'first-{prefix}.json').write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
    return 0 if all(r['exitCode'] == 0 for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
