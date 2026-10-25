"""c5h: the civ5-headless command line (also python -m civ5headless).

  c5h [--config FILE] COMMAND [ARGS...]      c5h COMMAND -h shows a command's options

--config names the civ5headless.toml to read (default: C5H_CONFIG, ./civ5headless.toml, then the one in the
workspace); c5h doctor shows what it and discovery give.

Each command is a module's main(argv, cfg) -> exit code; cfg is the loaded config.Config. A main(argv) that takes no
configuration is called with the arguments only. The verification suite plugs in the same way: c5h verify calls
civ5headless.verify.main(argv, cfg) when that package is present.
"""
import importlib
import inspect
import sys

from . import __version__, config

# (command, module, function, summary)
COMMANDS = [
    ('doctor', 'civ5headless.doctor', 'main', 'check the setup: configuration and where it came from, game, host'),
    ('run', 'civ5headless.run', 'main', 'play one game in the host from a spec'),
    ('queue', 'civ5headless.queue', 'main', 'play many games in parallel: run, status, compare'),
    ('compare', 'civ5headless.compare.digest', 'compare_main', "compare two runs' per-turn state digests"),
    ('verify', 'civ5headless.verify', 'main', 'the verification suite (when installed)'),
    ('spec', 'civ5headless.spec', 'main', 'resolve a game spec, or print its pregame Lua'),
    ('dbbuild', 'civ5headless.dbbuild', 'main', 'build the game database for a mod set'),
    ('dbcache', 'civ5headless.dbcache', 'main', 'the cached game database for the configured mods and DLL'),
    ('snapshot', 'civ5headless.snapshot', 'main', "build the DLC snapshot (base game, expansions, DLC) from the game's files"),
    ('modsdb', 'civ5headless.modsdb', 'main', 'generate the mods registry (Civ5ModsDatabase.db) for a mod set'),
    ('dbdiff', 'civ5headless.dbdiff', 'main', 'compare two game databases'),
    ('dumps', 'civ5headless.compare.dumps', 'main', 'compare two state dumps section by section'),
    ('parity', 'civ5headless.compare.parity', 'main', 'replay a real-game reference in the host and compare'),
    ('host-first', 'civ5headless.compare.parity', 'first_main', 'run the host on every case of a matrix first'),
    ('skew', 'civ5headless.compare.skew', 'main', 'frame-count independence sweep'),
    ('digest', 'civ5headless.compare.digest', 'main', 'digest helpers: verify a dump, hash files'),
    ('fingerprint', 'civ5headless.fingerprint', 'main', 'Lua fingerprints (probes/fingerprint.lua): compare, show'),
    ('hazards', 'civ5headless.cli', 'hazards_main', 'UI hazard scan: scan, methods, known'),
]


def hazards_main(argv, cfg):
    """c5h hazards: civ5headless.hazards.main with the configured profiles folder as its default."""
    from . import hazards
    argv = list(argv)
    given = lambda opt: any(x == opt or x.startswith(opt + '=') for x in argv)
    profiles = getattr(cfg, 'profiles', None)
    if profiles and argv[:1] == ['scan'] and not given('--profiles'):
        argv += ['--profiles', str(profiles)]
    elif profiles and argv[:1] == ['known'] and not given('--known'):
        argv += ['--known', str(profiles / 'known-ui-files.json')]
    return hazards.main(argv)


def usage():
    lines = [f'c5h {__version__}: Civilization V AI autoplay without the game', '',
             'usage: c5h [--config FILE] COMMAND [ARGS...]   (c5h COMMAND -h for its options)', '', 'commands:']
    lines += [f'  {name:<12}{summary}' for name, _, _, summary in COMMANDS]
    return '\n'.join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    path = None
    while argv and argv[0].startswith('-'):
        opt = argv.pop(0)
        if opt in ('-h', '--help'):
            print(usage())
            return 0
        if opt == '--version':
            print(__version__)
            return 0
        if opt == '--config' and argv:
            path = argv.pop(0)
        elif opt.startswith('--config='):
            path = opt.split('=', 1)[1]
        else:
            print(f'c5h: unknown option {opt}\n\n{usage()}', file=sys.stderr)
            return 2
    if not argv:
        print(usage())
        return 2
    name, rest = argv[0], argv[1:]
    entry = next((c for c in COMMANDS if c[0] == name), None)
    if entry is None:
        print(f'c5h: unknown command {name}\n\n{usage()}', file=sys.stderr)
        return 2
    _, module, function, _ = entry
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as error:
        if error.name == module:
            print(f'c5h {name}: {module} is not part of this installation', file=sys.stderr)
            return 2
        raise
    try:
        cfg = config.load(path)
    except config.ConfigError as error:
        if name != 'doctor':
            print(f'c5h: configuration error: {error}', file=sys.stderr)
            return 2
        cfg = error  # doctor reports it
    entry_point = getattr(mod, function)
    takes_config = len(inspect.signature(entry_point).parameters) > 1
    try:
        return (entry_point(rest, cfg) if takes_config else entry_point(rest)) or 0
    except config.ConfigError as error:
        print(f'c5h {name}: {error}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
