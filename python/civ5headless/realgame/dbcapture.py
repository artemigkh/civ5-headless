"""Capture the game's databases from the real game, and check them against what the game holds in memory.

  python -m civ5headless.realgame.dbcapture --run NAME [--snapshot-only]

Launches the game (session.py), then:
  1. Main menu, no mods active: copies cache/Civ5DebugDatabase.db (the DLC snapshot: base game, expansions and DLC)
     and exports the database the game holds in memory (RealGameSession.game_database).
  2. Activates the configured mods (the activated mods of mods_db), then copies the modded Civ5DebugDatabase.db and
     exports the in-memory database again. Skipped with --snapshot-only.
  3. Quits normally and compares each copy with its in-memory export, table by table.

Results go to <runs>/NAME: dlc-debug.db, dlc-ingame.db, mods-debug.db, mods-ingame.db, db-capture.json.
`c5h snapshot` builds the DLC snapshot from the game's files without the game; dlc-debug.db is the captured
alternative (set `snapshot` in civ5headless.toml to use it), and `c5h snapshot --oracle dlc-debug.db` compares them.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, sqlite3, sys, time

from .. import config
from ..run import utc, write
from .session import RealGameSession, SessionError
from .tuner import TunerError


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''): h.update(part)
    return h.hexdigest().upper()


def wait_db_written(cache, after, label, session, timeout=300, settle=5):
    """Wait until Civ5DebugDatabase.db is newer than `after` and unchanged for settle seconds; return its mtime."""
    db = cache / 'Civ5DebugDatabase.db'
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        st = db.stat() if db.exists() else None
        sig = (st.st_mtime, st.st_size) if st else None
        if st and st.st_mtime > after and sig == last:
            session.event('debug_db_ready', phase=label, mtime=st.st_mtime, size=st.st_size)
            return st.st_mtime
        last = sig
        time.sleep(settle)
    raise TimeoutError(f'{label}: Civ5DebugDatabase.db was not rewritten')


def table_rows(conn, table):
    cols = [r[1] for r in conn.execute(f'pragma table_info("{table}")')]
    rows = conn.execute(f'select * from "{table}"').fetchall()
    return cols, sorted(rows, key=lambda r: tuple((v is None, type(v).__name__, str(v)) for v in r))


def compare(cached, ingame):
    a, b = sqlite3.connect(cached), sqlite3.connect(ingame)
    try:
        ta = {r[0] for r in a.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        tb = {r[0] for r in b.execute("select name from sqlite_master where type='table'")}
        diffs = []
        for t in sorted(ta & tb):
            ca, ra = table_rows(a, t)
            cb, rb = table_rows(b, t)
            if ca != cb or ra != rb:
                diffs.append({'table': t, 'columns_equal': ca == cb, 'rows_cached': len(ra), 'rows_ingame': len(rb)})
        return {'tables_cached': len(ta), 'tables_ingame': len(tb), 'only_cached': sorted(ta - tb),
                'only_ingame': sorted(tb - ta), 'differing': diffs}
    finally:
        a.close()
        b.close()


def capture(cfg, run, snapshot_only=False, session=None, settle=5):
    """Runs the capture into the run folder; returns the db-capture.json dict."""
    cache = cfg.require('cache_dir')
    s = session or RealGameSession(cfg, run, log=lambda m: print(f'{utc()} {m}', flush=True))
    result = {'utc': utc(), 'dll': str(cfg.dll) if cfg.dll else None}
    try:
        started = time.time()
        s.launch()
        wait_db_written(cache, started, 'dlc', s, settle=settle)
        shutil.copy2(cache / 'Civ5DebugDatabase.db', run / 'dlc-debug.db')
        s.game_database(run / 'dlc-ingame.db')
        if not snapshot_only:
            before = (cache / 'Civ5DebugDatabase.db').stat().st_mtime
            result['mods'] = s.set_mods([m.id for m in cfg.active_mods])['mods']
            wait_db_written(cache, before, 'mods', s, settle=settle)
            shutil.copy2(cache / 'Civ5DebugDatabase.db', run / 'mods-debug.db')
            s.game_database(run / 'mods-ingame.db')
    except (SessionError, TunerError, OSError) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        result['quit'] = s.quit()
    for phase in ('dlc', 'mods'):
        cached, ingame = run / f'{phase}-debug.db', run / f'{phase}-ingame.db'
        if cached.exists() and ingame.exists():
            result[phase + 'Compare'] = compare(cached, ingame)
            result[phase + 'DebugSha'] = sha256(cached)
    write(run / 'db-capture.json', result)
    return result


def main(argv=None, cfg=None):
    cfg = cfg or config.load()
    ap = argparse.ArgumentParser(prog='python -m civ5headless.realgame.dbcapture', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='run folder name below <runs>')
    ap.add_argument('--snapshot-only', action='store_true', help='only the DLC snapshot (main menu, no mods)')
    args = ap.parse_args(argv)
    run = cfg.require('runs') / args.run
    if run.exists():
        ap.error(f'{run} exists')
    result = capture(cfg, run, args.snapshot_only)
    print(json.dumps({k: (v if not isinstance(v, dict) or 'differing' not in v else
                          {'differing': len(v['differing']), 'only_cached': len(v['only_cached']), 'only_ingame': len(v['only_ingame'])})
                      for k, v in result.items()}, indent=1, default=str))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
