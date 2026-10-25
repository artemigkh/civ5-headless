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
"""
from pathlib import Path
import argparse, json, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/vpbench'))
sys.path.insert(0, str(ROOT / 'work/headless'))
import vpbench, gamespec
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
    args = ap.parse_args()
    probes = []
    for item in args.probe:
        target, _, path = item.partition('=')
        context, _, when = target.partition('@')
        when = when or ('start' if context == 'InGame' else 'setup')
        if when not in ('setup', 'start', 'end') or (when != 'setup' and not args.spec):
            ap.error(f'bad probe moment: {item}')
        probes.append((context, when, Path(path)))
    if args.no_mods and args.spec: ap.error('--spec needs the mods')
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
            vpbench.HEADLESS_SEEDS.write_text(f"map={seeds['map']}\nsync={seeds['sync']}\ndigest={int(args.digest)}\nnormalise=1\n", encoding='ascii')
            b.call('ModsSinglePlayer', vpbench.START, 'start-game')
            b.wait_loaded()
            write(b.run / 'setup.json', b.call('InGame', vpbench.SETUP, 'setup-info'))
            b.log('seeds_pinned', **vpbench.check_seeds(resolved))
            run_probes('start')
            if args.turns > 0:
                b.call('InGame', ARM.format(turns=args.turns), 'arm-autoplay')
            b.call('LoadScreen', vpbench.CONTINUE, 'continue')
            if args.turns > 0:
                started = time.monotonic()
                last_turn, last_change = None, started
                while True:
                    time.sleep(3)
                    state = b.call('InGame', TURN, 'turn', keep=False)
                    now = time.monotonic()
                    if state['turn'] != last_turn: last_turn, last_change = state['turn'], now
                    if state['winner'] >= 0 or state['state'] != 0: break
                    if state['turn'] >= args.turns and state['autoplay'] == 0: break
                    if now - last_change >= args.stall_seconds: raise TimeoutError(f'autoplay stalled: {state}')
                    if now - started >= args.max_seconds: raise TimeoutError(f'autoplay over the time cap: {state}')
                b.log('autoplay_done', **state)
                time.sleep(3)
                write(b.run / 'victory.json', dict(utc=utc(), **b.call('InGame', VICTORY, 'victory')))
            run_probes('end')
    finally:
        b.quit()
        if args.spec and vpbench.HEADLESS_SEEDS.exists(): vpbench.HEADLESS_SEEDS.unlink()
        vpbench.collect_headless_logs(b, since)
    return 0


if __name__ == '__main__':
    sys.exit(main())
