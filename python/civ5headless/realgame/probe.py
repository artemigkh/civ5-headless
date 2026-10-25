"""Run Lua probes in the real game and save their results (on the real-game session, session.py).

  python -m civ5headless.realgame.probe --run NAME --probe CONTEXT=FILE.lua [--probe ...] [--no-mods]
  python -m civ5headless.realgame.probe --run NAME --spec SPEC.json [--turns N] --probe CONTEXT[@WHEN]=FILE.lua ...

Launches the game, activates the configured mods (the activated mods of mods_db) unless --no-mods, runs each probe
in its Lua context (MainMenu, ModsSinglePlayer, InGame, ...) through the tuner, writes the returned values to
<runs>/NAME/probe-<n>-<file stem>.json, and quits normally.

With --spec the probes can also run inside a game started from that spec, its seeds pinned through config.ini
before the launch. WHEN picks the moment:
  setup  before the game starts (default without @: setup for front-end contexts, start for InGame)
  start  turn 0 after loading, before the load screen closes (game core idle)
  end    after --turns N turns of AI autoplay (the observer setup the host uses), game core idle
`{RUN}` in a probe is replaced by the run folder (forward slashes), e.g. for Game.DumpHeadlessState.
The game's logs written during the run are copied into the run folder at the end.

DLLs with the optional digest additions (docs/dll-additions.md) read HeadlessSeeds.txt in the game's cache folder at
the next new game; the run writes it with digest=1 (--no-digest: 0) and the dump range, and removes it afterwards.
Other DLLs ignore it. --dump-from A --dump-to B has such a DLL dump the state at doTurnBegin of turns A..B; the dumps
are copied to <run>/HeadlessDumps. --stop-turn S quits once turn S is reached while still arming --turns N, so a short
re-record of a long game keeps the same autoplay count (it is in the digest); the @end probes are skipped then.

--host-digest HOST_LOG compares the game's live HeadlessDigest.log with a host run of the same case (same spec,
DLL and --turns), point by point as the turns pass. A difference that matches again within --diverge-turns turns
(default 2) is recorded as a transient and the game goes on; one that persists that long writes
<run>/divergence.json and quits, so a long reference costs real-game time only up to its divergence.
--rolling-dumps K dumps every turn and keeps the last K turns plus K turns around every difference, so the run that
finds a divergence also has the field-level dumps around it (about 85 MB per Tiny dump).

Exit code 0 when everything ran and the game exited.
"""
from pathlib import Path
import argparse, json, re, shutil, sys, time

from .. import config
from .. import spec as gamespec
from ..compare import digest as hhdigest
from ..run import utc, write
from .session import VICTORY, RealGameSession, SessionError
from .tuner import TunerError


def prune_dumps(dumps, keep):
    """Delete the DLL's doTurnBegin dumps of the turns keep(turn) rejects (the one being written is the newest: kept)."""
    if not dumps.exists(): return
    for d in dumps.iterdir():
        m = re.fullmatch(r'doTurnBegin-t(\d+)', d.name)
        if m and not keep(int(m.group(1))): shutil.rmtree(d, ignore_errors=True)


class LiveDigest:
    """Reads the game's HeadlessDigest.log as it grows and compares each new point with a host run's log.

    open: the first point of the current run of differences (None while the points match); a run that matches
    again goes to transients with the turn it matched again (until)."""

    def __init__(self, live_path, host_path):
        self.live_path, self.offset, self.pending = live_path, 0, b''
        self.host = hhdigest.digest_lines(host_path)
        self.compared = 0
        self.last_turn = -1
        self.first = None
        self.open = None
        self.transients = []

    def runs(self):
        """(first turn, last turn or None while open) of every run of differences so far."""
        return [(t['turn'], t['until']) for t in self.transients] + ([(self.open['turn'], None)] if self.open else [])

    def poll(self):
        """Compare the points logged since the last poll; returns the open run of differences, if any."""
        if not self.live_path.exists(): return self.open
        with self.live_path.open('rb') as f:
            f.seek(self.offset)
            data = f.read()
        self.offset += len(data)
        data = self.pending + data
        lines = data.split(b'\n')
        self.pending = lines.pop()  # incomplete last line
        for raw in lines:
            line = raw.decode('utf-8', 'replace').rstrip('\r')
            if not line.startswith('HHDIGEST|'): continue
            _, fields, order = hhdigest.parse_line(line)
            key = (fields.get('point'), int(fields['turn']))
            if key not in self.host: continue
            self.compared += 1
            self.last_turn = key[1]
            host_fields, host_order = self.host[key]
            names = [n for n in order + [n for n in host_order if n not in fields] if n not in hhdigest.META]
            sections = [n for n in names if fields.get(n) != host_fields.get(n) and n not in hhdigest.EXCLUDED]
            if fields['total'] != host_fields['total'] or sections:
                difference = dict(turn=key[1], point=key[0], sections=sections, compared=self.compared)
                self.first = self.first or difference
                self.open = self.open or difference
            elif self.open:
                self.transients.append(dict(self.open, until=key[1]))
                self.open = None
        return self.open


def main(argv=None, cfg=None):
    cfg = cfg or config.load()
    ap = argparse.ArgumentParser(prog='python -m civ5headless.realgame.probe', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='run folder name below <runs>')
    ap.add_argument('--probe', action='append', default=[], help='CONTEXT[@setup|start|end]=path/to/probe.lua')
    ap.add_argument('--no-mods', action='store_true')
    ap.add_argument('--spec', help='Start a game from this spec (spec.py)')
    ap.add_argument('--turns', type=int, default=0, help='With --spec: autoplay this many turns before the @end probes '
                    '(a game that ends earlier, with a winner or a game state other than ON, stops there)')
    ap.add_argument('--max-seconds', type=int, default=10800, help='Overall cap on the autoplay (default 3 h)')
    ap.add_argument('--stall-seconds', type=int, default=900, help='Fail when no turn passes for this long (default 15 min)')
    ap.add_argument('--no-digest', dest='digest', action='store_false', help='HeadlessSeeds.txt with digest=0')
    ap.add_argument('--dump-from', type=int, help='With --spec: DLL state dumps at doTurnBegin from this turn')
    ap.add_argument('--dump-to', type=int, help='... to this turn (default: --dump-from)')
    ap.add_argument('--stop-turn', type=int, default=0, help='With --spec and --turns: quit once this turn is reached')
    ap.add_argument('--host-digest', help='With --spec and --turns: a host run\'s HeadlessDigest.log of the same case; '
                    'stop --diverge-turns turns after the first difference')
    ap.add_argument('--diverge-turns', type=int, default=2)
    ap.add_argument('--rolling-dumps', type=int, default=0, help='With --spec: dump every turn, keep the last K')
    ap.add_argument('--no-cpu-guard', dest='cpu_guard', action='store_false')
    args = ap.parse_args(argv)
    if args.rolling_dumps and args.dump_from is None: args.dump_from, args.dump_to = 0, 100000
    if args.host_digest and not (args.spec and args.turns > 0 and args.digest): ap.error('--host-digest needs --spec, --turns and the digest')
    if args.dump_from is not None and args.dump_to is None: args.dump_to = args.dump_from
    probes = []
    for item in args.probe:
        target, _, path = item.partition('=')
        context, _, when = target.partition('@')
        when = when or ('start' if context == 'InGame' else 'setup')
        if when not in ('setup', 'start', 'end') or (when != 'setup' and not args.spec):
            ap.error(f'bad probe moment: {item}')
        probes.append((context, when, Path(path)))
    if args.no_mods and args.spec: ap.error('--spec needs the mods')
    if (args.dump_from is not None or args.stop_turn) and not args.spec: ap.error('--dump-from and --stop-turn need --spec')
    run = cfg.require('runs') / args.run
    if run.exists(): ap.error(f'{run} exists')
    resolved = None
    if args.spec:
        from .. import dbcache
        resolved = gamespec.resolve(json.loads(Path(args.spec).read_text(encoding='utf-8')),
                                    dbcache.database(cfg, log=lambda m: print(m, file=sys.stderr))[0])
    logs = cfg.require('user_dir') / 'Logs'
    dumps = logs / 'HeadlessDumps'
    if args.dump_from is not None and dumps.exists():
        # Earlier runs' dumps of the same turns would be overwritten in place; keep them apart.
        dumps.rename(dumps.with_name(f'HeadlessDumps-{time.strftime("%Y%m%d-%H%M%S")}'))
    headless_seeds = cfg.require('cache_dir') / 'HeadlessSeeds.txt'
    s = RealGameSession(cfg, run, cpu_guard=args.cpu_guard, stall_seconds=args.stall_seconds, poll=3.0,
                        log=lambda m: print(f'{utc()} {m}', flush=True))
    counter = [0]
    ok = True

    def run_probes(when):
        nonlocal ok
        for context, moment, path in probes:
            if moment != when: continue
            counter[0] += 1
            n = counter[0]
            try:
                source = path.read_text(encoding='utf-8-sig').replace('{RUN}', run.as_posix())
                result = {'ok': True, 'value': s.call(context, source, f'probe-{n}')}
            except (SessionError, TunerError) as error:
                result = {'ok': False, 'error': str(error)}
                ok = False
            write(run / f'probe-{n}-{path.stem}.json', dict(utc=utc(), context=context, when=when, file=str(path), **result))
            s.event('probe', n=n, context=context, when=when, file=path.name, ok=result['ok'])

    quit_info = {}
    try:
        if resolved:
            write(run / 'spec-resolved.json', resolved)
            s.launch(resolved['seeds']['map'], resolved['seeds']['sync'])
        else:
            s.launch()
        if not args.no_mods:
            s.set_mods([m.id for m in cfg.active_mods])
        run_probes('setup')
        if resolved:
            dump_range = f"dumpfrom={args.dump_from}\ndumpto={args.dump_to}\n" if args.dump_from is not None else ''
            headless_seeds.write_text(f"digest={int(args.digest)}\nnormalise=1\n{dump_range}", encoding='ascii')
            write(run / 'setup.json', s.start_game(resolved))
            run_probes('start')
            if args.turns > 0:
                live = LiveDigest(logs / 'HeadlessDigest.log', Path(args.host_digest)) if args.host_digest else None
                early = [False]

                def on_poll(state):
                    if args.stop_turn and state['turn'] >= args.stop_turn:
                        early[0] = True
                    if live:
                        live.poll()
                        if live.open and live.last_turn >= live.open['turn'] + args.diverge_turns:
                            write(run / 'divergence.json', dict(utc=utc(), hostDigest=args.host_digest, transients=live.transients, **live.open))
                            s.event('diverged', **live.open)
                            early[0] = True
                    if args.rolling_dumps:
                        k, turn, runs = args.rolling_dumps, state['turn'], live.runs() if live else []
                        prune_dumps(dumps, lambda t: t > turn - k or any(a - k <= t and (u is None or t <= u + k) for a, u in runs))
                    return early[0]
                played = s.autoplay(args.turns, max_seconds=args.max_seconds, on_poll=on_poll)
                write(run / 'autoplay.json', played)
                if played['endReason'] in ('max_seconds', 'stalled'):
                    raise SessionError(f"autoplay ended early: {played['endReason']} at turn {played['endTurn']}")
                if live:
                    time.sleep(3)
                    live.poll()
                    if live.open and not early[0]:
                        write(run / 'divergence.json', dict(utc=utc(), hostDigest=args.host_digest, transients=live.transients, **live.open))
                    write(run / 'live-compare.json', dict(utc=utc(), hostDigest=args.host_digest, compared=live.compared,
                                                          first=live.first, open=live.open, transients=live.transients,
                                                          stoppedAt=played['endTurn'], early=early[0]))
                if not early[0]:
                    time.sleep(3)
                    write(run / 'victory.json', dict(utc=utc(), **s.call('InGame', VICTORY, 'victory')))
                    run_probes('end')
            else:
                run_probes('end')
    except (SessionError, TunerError, OSError) as error:
        ok = False
        write(run / 'error.json', dict(utc=utc(), error=f'{type(error).__name__}: {error}'))
        print(f'{utc()} failed: {error}', file=sys.stderr)
    finally:
        quit_info = s.quit()
        headless_seeds.unlink(missing_ok=True)  # never pin a later, unrelated game
        s.collect_logs(run)
        if args.dump_from is not None and dumps.exists():
            shutil.copytree(dumps, run / 'HeadlessDumps', dirs_exist_ok=True)
        write(run / 'process.json', s.process_stats())
    return 0 if ok and quit_info.get('exited') else 1


if __name__ == '__main__':
    sys.exit(main())
