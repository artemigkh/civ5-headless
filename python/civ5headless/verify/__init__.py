"""c5h verify: how accurately a headless game represents a real Civ V autoplay game, for your DLL, mods and maps;
and how fast and lean the host is against the real game (docs/verification.md).

  c5h verify [--quick | --full | --host-only] [--budget MIN] [--out DIR] [--strict]
             [--turns N] [--spec FILE] [--map SCRIPT] [--size WORLDSIZE_X] [--players N] [--city-states N]
             [--seeds MAP SYNC] [--ensemble N] [--ensemble-seed SYNC] [--workers N] [--reference-workers N]
             [--no-single-phase] [--frame-skew K] [--heap-perturb SEED] [--setups FILE | --no-setups]
             [--standard-turns N] [--victory-games N] [--host-arg ARG]... [--affinity p-first|none]
             [--dll DLL] [--db DB] [--mod ID[:VERSION]... | --no-mods]
  c5h verify --analyse DIR [--self-test [--foreign RUN]... [--shift 0.05]] [--no-history]

Modes (plan section 5.5):
  --quick       the default, about 20-25 minutes: the real game launches once, plays 4 seeded setups to turn 0 and
                a Tiny game of 150 turns; beside it the host plays the same games, the A/A, frame-skew, heap-
                perturbation and probe-off references, and an ensemble of 32 Tiny games
  --full        about 45-55 minutes: adds a real A/A of the Tiny game, a Standard game of 60 turns on both sides, a
                larger ensemble (64) and host Tiny games to victory
  --host-only   about 5 minutes, no real game (CI): host references, throughput and a small ensemble; the
                statistics then score the host trajectory game against the ensemble (a self-test)

Every option has a [verify] key in civ5headless.toml (verify/settings.py; [verify.quick], [verify.full] and
[verify.host-only] apply to one mode). --analyse re-runs the checks and the report on a finished run folder;
--self-test adds the statistics self-test (held-out ensemble games, shifted metrics, --foreign games from another
setup).

Output: <runs>/verify-<mode>-<date>-<time>/ with report.html (one self-contained page) and verify.json.
History: <runs>/verify-history/<machine>.jsonl, one line per run.

Exit codes: 0 passed (warnings allowed), 1 a check failed (or warned, with --strict), 2 usage or configuration
error, 3 incomplete: the host or the real trajectory game did not run, so there is no verdict.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .. import config

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_INCOMPLETE = 0, 1, 2, 3


def parser():
    ap = argparse.ArgumentParser(prog='c5h verify', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    m = ap.add_mutually_exclusive_group()
    m.add_argument('--quick', dest='mode', action='store_const', const='quick', help='the default mode')
    m.add_argument('--full', dest='mode', action='store_const', const='full')
    m.add_argument('--host-only', dest='mode', action='store_const', const='host-only')
    ap.add_argument('--budget', type=float, dest='budget_minutes', help='time budget in minutes (the mode default otherwise)')
    ap.add_argument('--out', help='run folder (default <runs>/verify-<mode>-<date>-<time>)')
    ap.add_argument('--strict', action='store_true', default=None, help='warnings make the exit code 1')
    ap.add_argument('--turns', type=int, help='trajectory and ensemble horizon (default 150)')
    ap.add_argument('--spec', help='game spec of the trajectory and ensemble game (default: Tiny Continents)')
    ap.add_argument('--map', help='map script of the trajectory game, e.g. Assets/Maps/Pangaea.lua')
    ap.add_argument('--size', help='world size, e.g. WORLDSIZE_SMALL')
    ap.add_argument('--players', type=int, help='major civs')
    ap.add_argument('--city-states', type=int)
    ap.add_argument('--seeds', type=int, nargs=2, metavar=('MAP', 'SYNC'), help='seeds of the trajectory game')
    ap.add_argument('--ensemble', type=int, help='host ensemble games')
    ap.add_argument('--ensemble-seed', type=int, help='first sync seed of the ensemble')
    ap.add_argument('--workers', type=int, help='host games at once (ensemble phase)')
    ap.add_argument('--reference-workers', type=int, help='host references at once (default 4)')
    ap.add_argument('--no-single-phase', dest='single_phase', action='store_false', default=None,
                    help='do not play the trajectory game alone first')
    ap.add_argument('--frame-skew', type=int, help='K of the frame-skew reference (default 7)')
    ap.add_argument('--heap-perturb', type=int, help='seed of the heap-perturbation reference')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--setups', help='JSON file: a list of game specs for the turn-0 checks')
    g.add_argument('--no-setups', action='store_true', help='skip the turn-0 setups')
    ap.add_argument('--standard-turns', type=int, help='full: Standard game length (0: none)')
    ap.add_argument('--victory-games', type=int, help='full: host Tiny games to victory')
    ap.add_argument('--host-arg', action='append', dest='host_args', help='extra civ5headless.exe argument (repeatable)')
    ap.add_argument('--affinity', choices=['p-first', 'none'], help='host worker pinning')
    ap.add_argument('--dll', help='game DLL for the host (default: the configuration)')
    ap.add_argument('--db', help='built game database for the host (default: the configuration or the cache)')
    mm = ap.add_mutually_exclusive_group()
    mm.add_argument('--mod', action='append', dest='mods', metavar='ID[:VERSION]',
                    help='an activated mod (repeatable): the mod set, instead of the configuration')
    mm.add_argument('--no-mods', action='store_true', default=None, help='no mods (host, database and real game)')
    ap.add_argument('--analyse', '--analyze', metavar='DIR', help='checks and report again from a finished run folder')
    ap.add_argument('--no-history', action='store_true', help='--analyse: do not append to the history file')
    ap.add_argument('--self-test', action='store_true', help='also run the statistics self-test on the ensemble')
    ap.add_argument('--foreign', action='append', default=[], metavar='RUN',
                    help='--self-test: a game from another setup (a host run folder), which the checks should reject')
    ap.add_argument('--shift', type=float, default=0.05, help='--self-test: relative shift of the negative controls')
    return ap


def overrides(a):
    o = {k: getattr(a, k) for k in ('budget_minutes', 'out', 'strict', 'turns', 'spec', 'map', 'size', 'players',
                                     'city_states', 'ensemble', 'ensemble_seed', 'workers', 'reference_workers',
                                     'single_phase', 'frame_skew', 'heap_perturb', 'setups', 'standard_turns',
                                     'victory_games', 'host_args', 'affinity', 'dll', 'db', 'mods', 'no_mods')}
    if a.seeds:
        o['seeds'] = list(a.seeds)
    if a.no_setups:
        o['setups'] = []
    return o


def main(argv=None, cfg=None):
    a = parser().parse_args(argv)
    if isinstance(cfg, Exception):
        print(f'c5h verify: configuration error: {cfg}', file=sys.stderr)
        return EXIT_USAGE
    cfg = cfg or config.load()
    from . import settings as settings_mod, suite
    try:
        mode = a.mode or 'quick'
        if a.analyse:
            plan = suite.host_run.read(Path(a.analyse) / 'plan.json') or {}
            if not plan.get('settings'):
                raise ValueError(f'{a.analyse} has no plan.json (not a c5h verify run folder)')
            mode = a.mode or plan.get('mode') or mode
            table = {k: v for k, v in plan['settings'].items() if k != 'mode'}
            s = settings_mod.build(mode, table, overrides(a))
        else:
            s = settings_mod.build(mode, cfg.raw.get('verify') or {}, overrides(a))
    except (settings_mod.SettingsError, OSError, ValueError) as error:
        print(f'c5h verify: {error}', file=sys.stderr)
        return EXIT_USAGE
    if a.analyse:
        doc = suite.analyse(Path(a.analyse), cfg, s, history=not a.no_history, self_test=a.self_test,
                            foreign=a.foreign, shift=a.shift)
        print(f"verdict {doc['verdict']} (exit {doc['exitCode']}): {doc['headline']}")
        print(f"report: {Path(a.analyse) / 'report.html'}")
        return doc['exitCode']
    doc = suite.run(cfg, s, self_test=a.self_test)
    return doc['exitCode']
