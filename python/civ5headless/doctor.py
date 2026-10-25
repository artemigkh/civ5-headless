"""c5h doctor: the configuration, where each value came from, and what is missing for host games.

  c5h doctor [--json]

Prints every configuration value with its source (file, discovery, environment, default, unset), the activated mods,
then checks: Python, the game folder (the Firaxis DLLs and ICU data the host loads), the DLL, the mods and
localization databases, the host exe, and a game database (db, or a snapshot for the database cache). Exit code 1
when a check fails. Not yet checked (milestone 2): config.ini (EnableTuner, LoggingEnabled), the toolchain build, the
real game's mods.
"""
import argparse
import json
import sys

from . import config

FIRAXIS_DLLS = ('CvGameDatabaseWin32Final Release.dll', 'CvLocalizationWin32Final Release.dll', 'lua51_Win32.dll')


def checks(cfg):
    """[(status, what, detail)]; status ok, warn or FAIL."""
    out = []
    v = sys.version_info
    out.append(('ok' if v >= (3, 11) else 'FAIL', 'Python', f'{sys.version.split()[0]} ({sys.executable})'
                + ('' if v >= (3, 11) else '; 3.11 or newer is needed')))

    def path_check(key, kind, why, severity='FAIL'):
        p = getattr(cfg, key)
        if p is None:
            out.append((severity, key, f'not set ({why}): ' + cfg.sources[key].note))
            return False
        exists = p.is_dir() if kind == 'dir' else p.is_file()
        out.append(('ok' if exists else severity, key, str(p) + ('' if exists else f' does not exist ({why})')))
        return exists

    if path_check('game_dir', 'dir', 'the host loads the Firaxis DLLs from it'):
        missing = [n for n in FIRAXIS_DLLS + ('Locale/icudt44l.dat',) if not (cfg.game_dir / n).is_file()]
        out.append(('FAIL' if missing else 'ok', 'game files',
                    'missing ' + ', '.join(missing) if missing else 'Firaxis database, localization and Lua DLLs, ICU data'))
    path_check('dll', 'file', 'the game DLL to run')
    path_check('mods_dir', 'dir', 'the mods the host loads', 'warn')
    path_check('mods_db', 'file', 'the activated mods', 'warn')
    path_check('loc_db', 'file', "the game's text; written by the game at its first start", 'FAIL')
    path_check('exe', 'file', 'build it: python tools/build_host.py')
    if cfg.db:
        path_check('db', 'file', 'the game database used as is')
    elif cfg.snapshot:
        path_check('snapshot', 'file', 'the database builder starts from it')
    else:
        out.append(('warn', 'game database', 'neither db nor snapshot is set: games need --db, or a snapshot so the '
                    'database can be built from the mods (set one in civ5headless.toml)'))
    if cfg.mods_db and cfg.mods_db.is_file():
        out.append(('ok' if cfg.active_mods else 'warn', 'active mods',
                    f'{len(cfg.active_mods)} activated in {cfg.mods_db.name}' if cfg.active_mods else
                    'none activated (the game lists none while it sits in the mods browser; pin a copy taken in a '
                    'modded session, or use --mod with c5h dbbuild)'))
    for note in cfg.notes:
        out.append(('warn', 'configuration', note))
    return out


def main(argv=None, cfg=None):
    ap = argparse.ArgumentParser(prog='c5h doctor', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true', help='print the configuration and the checks as JSON')
    a = ap.parse_args(argv)
    if isinstance(cfg, Exception):
        print(f'configuration error: {cfg}')
        return 1
    cfg = cfg or config.load()
    results = checks(cfg)
    if a.json:
        print(json.dumps(dict(cfg.to_dict(), checks=[dict(status=s, what=w, detail=d) for s, w, d in results]), indent=1))
        return 1 if any(s == 'FAIL' for s, _, _ in results) else 0
    print(f'config file: {cfg.file}' if cfg.file else
          f'config file: none ({config.FILE_NAME} in the current folder or the workspace, or C5H_CONFIG); all values below are discovered or defaults')
    print()
    width = max(len(k) for k in config.KEYS)
    for key, value, source, note in cfg.rows():
        print(f'  {key:<{width}}  {source:<11}  {value if value else "-"}' + (f'  ({note})' if note else ''))
    if cfg.active_mods:
        print(f'\nactive mods ({cfg.mods_db}):')
        for m in cfg.active_mods:
            print(f'  {m.name or "?"} v{m.version}  {m.id}')
    print('\nchecks:')
    for status, what, detail in results:
        print(f'  {status:<5} {what}: {detail}')
    failed = sum(s == 'FAIL' for s, _, _ in results)
    print(f'\n{failed} check(s) failed' if failed else '\nready for host games')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
