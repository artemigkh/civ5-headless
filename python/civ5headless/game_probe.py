"""Run Lua probes in the real game and save their results.

  python work/headless/game_probe.py --run NAME --probe CONTEXT=FILE.lua [--probe ...] [--no-mods]
  python work/headless/game_probe.py --run NAME --spec SPEC.json [--turns N] --probe CONTEXT[@WHEN]=FILE.lua ...

Launches the game (vpbench launcher), activates the benchmark mods unless --no-mods, runs each probe
in its Lua context (MainMenu, ModsSinglePlayer, InGame, ...) through the tuner, writes the returned
values to work/test-runs/NAME/probe-<n>-<file stem>.json, and quits normally.

With --spec the probes can also run inside a game started from that spec (seeds pinned and the
per-turn digest on, as vpbench newgame --spec). WHEN picks the moment:
  setup  before the game starts (default without @: setup for front-end contexts, start for InGame)
  start  turn 0 after loading, before the load screen closes (game core idle)
  end    after --turns N turns of AI autoplay (the observer setup vpbench uses), game core idle
`{RUN}` in a probe is replaced by the run folder (forward slashes), e.g. for Game.DumpHeadlessState.
The headless logs (digest, runtime, trace) are copied into the run folder at the end.

--dump-from A --dump-to B has the DLL dump the state at doTurnBegin of turns A..B (field-level detail around a
divergence); the dumps are copied to <run>/HeadlessDumps. --stop-turn S quits once turn S is reached while still
arming --turns N, so a short re-record of a long game keeps the same autoplay count (it is in the digest); the @end
probes are skipped then.

--host-digest HOST_LOG compares the game's live HeadlessDigest.log with a host run of the same case (same spec,
DLL and --turns), point by point as the turns pass. A difference that matches again within --diverge-turns turns
(default 2) is recorded as a transient and the game goes on; one that persists that long writes
<run>/divergence.json and quits, so a long reference costs real-game time only up to its divergence.
--rolling-dumps K dumps every turn and keeps the last K turns plus K turns around every difference, so the run that
finds a divergence also has the field-level dumps around it (about 85 MB per Tiny dump).
"""
from pathlib import Path
import argparse, json, re, shutil, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/vpbench'))
sys.path.insert(0, str(ROOT / 'work/headless'))
sys.path.insert(0, str(ROOT / 'tools/headless'))
import vpbench, gamespec, hhdigest
from vpbench import write, utc
from db_capture import INSTALLED_DLL, sha256

ARM = ("assert(not PreGame.IsMultiplayerGame());local p=Players[0];assert(p and p:IsAlive() and not p:IsMinorCiv());"
       "Game.SetOption('GAMEOPTION_QUICK_COMBAT',true);Game.SetOption('GAMEOPTION_QUICK_MOVEMENT',true);"
       "Game.SetAIAutoPlay({turns},0);return Game.GetAIAutoPlay()")
# vpbench's TURN plus the game state (GAMESTATE_ON is 0): a game to victory ends before the autoplay count runs out.
TURN = ("return {turn=Game.GetGameTurn(),autoplay=Game.GetAIAutoPlay(),pause=Game.GetPausePlayer(),"
        "winner=Game.GetWinner(),state=Game.GetGameState()}")
VICTORY = ("local ok,v=pcall(function() return Game.GetVictory() end);"
           "return {turn=Game.GetGameTurn(),winner=Game.GetWinner(),victory=ok and v or -2,state=Game.GetGameState()}")


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--probe', action='append', default=[], help='CONTEXT[@setup|start|end]=path/to/probe.lua')
    ap.add_argument('--no-mods', action='store_true')
    ap.add_argument('--dll-sha')
    ap.add_argument('--spec', help='Start a game from this spec (work/headless/gamespec.py)')
    ap.add_argument('--turns', type=int, default=0, help='With --spec: autoplay this many turns before the @end probes '
                    '(a game that ends earlier, with a winner or a game state other than ON, stops there)')
    ap.add_argument('--max-seconds', type=int, default=10800, help='Overall cap on the autoplay (default 3 h)')
    ap.add_argument('--stall-seconds', type=int, default=900, help='Fail when no turn passes for this long (default 15 min)')
    ap.add_argument('--no-digest', dest='digest', action='store_false')
    ap.add_argument('--dump-from', type=int, help='With --spec: DLL state dumps at doTurnBegin from this turn')
    ap.add_argument('--dump-to', type=int, help='... to this turn (default: --dump-from)')
    ap.add_argument('--stop-turn', type=int, default=0, help='With --spec and --turns: quit once this turn is reached')
    ap.add_argument('--host-digest', help='With --spec and --turns: a host run\'s HeadlessDigest.log of the same case; '
                    'stop --diverge-turns turns after the first difference')
    ap.add_argument('--diverge-turns', type=int, default=2)
    ap.add_argument('--rolling-dumps', type=int, default=0, help='With --spec: dump every turn, keep the last K')
    args = ap.parse_args()
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
    dumps = vpbench.GAME_DOCS / 'Logs/HeadlessDumps'
    if args.dump_from is not None and dumps.exists():
        # Earlier runs' dumps of the same turns would be overwritten in place; keep them apart.
        dumps.rename(dumps.with_name(f'HeadlessDumps-{time.strftime("%Y%m%d-%H%M%S")}'))
    b = vpbench.Bench(args.run)
    since = time.time()
    if args.no_mods:
        dll_sha = args.dll_sha or sha256(INSTALLED_DLL)
        log = b.run.parent / (args.run + '-launch.log')
        with log.open('wb') as stream:
            code = subprocess.run([vpbench.PWSH, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'work/vpbench/vpbench-launch.ps1'),
                                   '-RunName', args.run, '-ExpectedDLLSHA', dll_sha, '-MaximumSeconds', '1800'],
                                  stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT).returncode
        if code: raise RuntimeError(f'Launch failed; see {log}')
        (b.run / 'calls').mkdir(exist_ok=True)
        b.guards = json.loads((b.run / 'watcher-manifest.json').read_text(encoding='utf-8-sig'))
        deadline = time.monotonic() + 240
        while not ({'MainMenu', 'LegalScreen', 'ModsBrowser'} & b.states()):
            if time.monotonic() >= deadline: raise TimeoutError('Main menu did not appear')
            time.sleep(2)
    else:
        # The launch guard ends the game after this many seconds: room for the autoplay cap plus setup.
        b.launch(args.dll_sha or sha256(INSTALLED_DLL), min(43200, max(3600, args.max_seconds + 900)))
    counter = [0]

    def run_probes(when):
        for context, moment, path in probes:
            if moment != when: continue
            counter[0] += 1
            n = counter[0]
            try:
                source = path.read_text(encoding='utf-8').replace('{RUN}', b.run.as_posix())
                value = b.call(context, source, f'probe-{n}', timeout=120)
                result = {'ok': True, 'value': value}
            except Exception as error:
                result = {'ok': False, 'error': str(error)}
            write(b.run / f'probe-{n}-{path.stem}.json', dict(utc=utc(), context=context, when=when, file=str(path), **result))
            b.log('probe', n=n, context=context, when=when, file=path.name, ok=result['ok'])

    try:
        run_probes('setup')
        if args.spec:
            resolved = gamespec.resolve(json.loads(Path(args.spec).read_text(encoding='utf-8')))
            write(b.run / 'spec-resolved.json', resolved)
            write(b.run / 'pregame.json', b.call('ModsSinglePlayer', gamespec.pregame_lua(resolved), 'pregame-setup'))
            seeds = resolved['seeds']
            dump_range = f"dumpfrom={args.dump_from}\ndumpto={args.dump_to}\n" if args.dump_from is not None else ''
            vpbench.HEADLESS_SEEDS.write_text(f"map={seeds['map']}\nsync={seeds['sync']}\ndigest={int(args.digest)}\nnormalise=1\n{dump_range}",
                                              encoding='ascii')
            b.call('ModsSinglePlayer', vpbench.START, 'start-game')
            b.wait_loaded()
            write(b.run / 'setup.json', b.call('InGame', vpbench.SETUP, 'setup-info'))
            b.log('seeds_pinned', **vpbench.check_seeds(resolved))
            run_probes('start')
            if args.turns > 0:
                b.call('InGame', ARM.format(turns=args.turns), 'arm-autoplay')
            b.call('LoadScreen', vpbench.CONTINUE, 'continue')
            if args.turns > 0:
                live = LiveDigest(vpbench.GAME_DOCS / 'Logs/HeadlessDigest.log', Path(args.host_digest)) if args.host_digest else None
                started = time.monotonic()
                last_turn, last_change = None, started
                early = False
                while True:
                    time.sleep(3)
                    state = b.call('InGame', TURN, 'turn', keep=False)
                    now = time.monotonic()
                    if state['turn'] != last_turn: last_turn, last_change = state['turn'], now
                    if state['winner'] >= 0 or state['state'] != 0: break
                    if state['turn'] >= args.turns and state['autoplay'] == 0: break
                    if args.stop_turn and state['turn'] >= args.stop_turn: early = True; break
                    if live:
                        live.poll()
                        if live.open and live.last_turn >= live.open['turn'] + args.diverge_turns:
                            write(b.run / 'divergence.json', dict(utc=utc(), hostDigest=args.host_digest, transients=live.transients, **live.open))
                            b.log('diverged', **live.open)
                            early = True
                            break
                    if args.rolling_dumps:
                        k, turn, runs = args.rolling_dumps, state['turn'], live.runs() if live else []
                        prune_dumps(dumps, lambda t: t > turn - k or any(a - k <= t and (u is None or t <= u + k) for a, u in runs))
                    if now - last_change >= args.stall_seconds: raise TimeoutError(f'autoplay stalled: {state}')
                    if now - started >= args.max_seconds: raise TimeoutError(f'autoplay over the time cap: {state}')
                b.log('autoplay_done', early=early, **state)
                if live:
                    time.sleep(3)
                    live.poll()
                    if live.open and not early:
                        write(b.run / 'divergence.json', dict(utc=utc(), hostDigest=args.host_digest, transients=live.transients, **live.open))
                    write(b.run / 'live-compare.json', dict(utc=utc(), hostDigest=args.host_digest, compared=live.compared,
                                                            first=live.first, open=live.open, transients=live.transients,
                                                            stoppedAt=state['turn'], early=early))
                if early: return 0
                time.sleep(3)
                write(b.run / 'victory.json', dict(utc=utc(), **b.call('InGame', VICTORY, 'victory')))
            run_probes('end')
    finally:
        b.quit()
        if args.spec and vpbench.HEADLESS_SEEDS.exists(): vpbench.HEADLESS_SEEDS.unlink()
        vpbench.collect_headless_logs(b, since)
        if args.dump_from is not None and dumps.exists():
            shutil.copytree(dumps, b.run / 'HeadlessDumps', dirs_exist_ok=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
