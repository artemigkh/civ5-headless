"""Check the builder's map script registration against the game's own rows for base and DLC scripts.

  python work/headless/dbbuild_check_mapscripts.py [--snapshot DLC.db] [--exe civ5headless.exe]

Empties MapScripts, MapScriptOptions and MapScriptOptionPossibleValues in a copy of the DLC
snapshot, re-registers every map script the snapshot lists (base game and DLC, game Lua only) with
`civ5headless.exe builddb`, and compares the three tables with the snapshot. Prints identical
when the builder's GetMapScriptInfo rules (defaults, value tables, Folder) match the engine's on
the 35 base/DLC scripts, independent of the mods' scripts the oracle covers.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_db  # noqa: E402
import dbdiff  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--snapshot', type=Path, default=build_db.DEFAULT_SNAPSHOT)
    ap.add_argument('--game-dir', type=Path, default=build_db.DEFAULT_GAME)
    ap.add_argument('--exe', type=Path)
    ap.add_argument('--run', type=Path, default=build_db.ROOT / 'work/headless-builds/check-mapscripts')
    a = ap.parse_args(argv)
    run = a.run.resolve()
    run.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(a.snapshot.resolve().as_uri() + '?mode=ro', uri=True)
    names = [r[0] for r in con.execute('SELECT FileName FROM MapScripts ORDER BY rowid')]
    con.close()
    clear = run / 'clear.sql'
    clear.write_text('DELETE FROM MapScriptOptionPossibleValues;\nDELETE FROM MapScriptOptions;\nDELETE FROM MapScripts;\n',
                     encoding='utf-8')
    plan = [f'snapshot\t{a.snapshot.resolve()}', f'sql\t{clear}']
    plan += [f'mapscript\t{a.game_dir / n}\t{n}' for n in names]
    plan += [f'vfs\t{k}\t{v}' for k, v in sorted(build_db.build_vfs(a.game_dir, [], set()).items())]
    (run / 'plan.txt').write_text('\n'.join(plan) + '\n', encoding='utf-8')
    exe = (a.exe or build_db.latest_exe()).resolve()
    out = run / 'out.db'
    proc = subprocess.run([str(exe), 'builddb', '--game-dir', str(a.game_dir), '--plan', str(run / 'plan.txt'),
                           '--out', str(out), '--run', str(run / 'build')], capture_output=True, text=True, errors='replace')
    for line in proc.stdout.splitlines():
        if 'FAILED' in line:
            print(line)
    d = dbdiff.diff(a.snapshot, out, show=3)
    for t in d['tables_differ']:
        print(t['table'], 'missing', t.get('missing_count'), 'extra', t.get('extra_count'))
        for r in t.get('missing', []):
            print('   missing', r)
        for r in t.get('extra', []):
            print('   extra  ', r)
    print(f'{len(names)} map scripts:', 'identical' if d['identical'] else 'DIFFERENT')
    return 0 if d['identical'] and proc.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
