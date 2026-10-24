"""Run Lua probes in the real game and save their results.

  python work/headless/game_probe.py --run NAME --probe CONTEXT=FILE.lua [--probe ...] [--no-mods]

Launches the game (vpbench launcher), activates the benchmark mods unless --no-mods, runs each probe
in its Lua context (MainMenu, ModsSinglePlayer, ...) through the tuner, writes the returned values to
work/test-runs/NAME/probe-<n>-<file stem>.json, and quits normally. Probes that need a game in
progress use vpbench newgame instead.
"""
from pathlib import Path
import argparse, json, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/vpbench'))
sys.path.insert(0, str(ROOT / 'work/headless'))
import vpbench
from vpbench import write, utc
from db_capture import INSTALLED_DLL, sha256


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--probe', action='append', required=True, help='CONTEXT=path/to/probe.lua')
    ap.add_argument('--no-mods', action='store_true')
    ap.add_argument('--dll-sha')
    args = ap.parse_args()
    probes = []
    for item in args.probe:
        context, _, path = item.partition('=')
        probes.append((context, Path(path)))
    b = vpbench.Bench(args.run)
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
        b.launch(args.dll_sha or sha256(INSTALLED_DLL), 1800)
    try:
        for n, (context, path) in enumerate(probes, 1):
            try:
                value = b.call(context, path.read_text(encoding='utf-8'), f'probe-{n}', timeout=120)
                result = {'ok': True, 'value': value}
            except Exception as error:
                result = {'ok': False, 'error': str(error)}
            write(b.run / f'probe-{n}-{path.stem}.json', dict(utc=utc(), context=context, file=str(path), **result))
            b.log('probe', n=n, context=context, file=path.name, ok=result['ok'])
    finally:
        b.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
