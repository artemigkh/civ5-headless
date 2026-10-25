"""Test edits for the database builder (plan M4 acceptance), checked later against game launches.

  python tools/dbbuild_test_edits.py --input DIR [--edits xmlrow,sqlupdate,newtable,sqlerror]
                                     [--scratch DIR] [--oracle GAME.db] [--baseline GAME.db] [--dll DLL]
  python tools/dbbuild_test_edits.py --apply-to MODS [--edits ...]   # edit a MODS folder in place
  python tools/dbbuild_test_edits.py --revert MODS                   # undo --apply-to

Development tool for Vox Populi mod sets (the edits name VP and CP files). Default mode copies a pinned builder
input (DIR with MODS/ and Civ5ModsDatabase.db) to a scratch folder (default <runs>/dbbuild-test-edits),
applies the edits there, builds the database with c5h dbbuild and prints the values each
edit should produce. The edits only change existing UpdateDatabase files (no modinfo change):

  xmlrow     VP Units/NewUnits.xml: UNIT_HEAVY_SKIRMISHER PortraitIndex 10 -> 47 (a changed XML row)
  sqlupdate  VP Text/en_US/WorldMap/TerrainTextChanges.sql: + UPDATE Units SET Combat = Combat + 3 for UNIT_WARRIOR (8 -> 11)
  newtable   CP StackingFormations.sql: + CREATE TABLE HeadlessBuilderTest with 3 rows (one copied from Units)
  sqlerror   VP Units/UnitChanges.sql: + a statement on a missing table, then UPDATE UNIT_SCOUT Cost + 7.
             The builder (Firaxis ExecuteMultiple) stops at the error, so Scout Cost stays 90; a game
             launch shows whether the engine does the same (the one error semantic the oracle could
             not check, because the current mods have no SQL errors).

Checking against the game (with the game free):
  1. --apply-to "<Documents>\\My Games\\Sid Meier's Civilization 5\\MODS" (backs up each file as
     *.hhtest-orig), launch the game with the benchmark mods active, copy cache\\Civ5DebugDatabase.db
     (realgame/dbcapture.py), then --revert.
  2. Build from the same edited files: copy the deployed MODS (.modinfo/.xml/.sql/.lua) and
     Civ5ModsDatabase.db as a new pinned input, and run this script with --input on the unedited
     copy plus --oracle GAME.db, or run c5h dbbuild on the edited copy with --oracle.
  3. dbdiff prints identical when the builder matches; the printed checks name the rows to inspect.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))  # the package, from this checkout
from civ5headless import config, dbbuild  # noqa: E402

VP = '(2) Vox Populi'
CP = '(1) Community Patch'
BACKUP = '.hhtest-orig'

EDITS = {
    'xmlrow': {
        'file': (VP, 'Database Changes/Units/NewUnits.xml'),
        'regex': (r'(<Type>UNIT_HEAVY_SKIRMISHER</Type>.*?<PortraitIndex>)10(</PortraitIndex>)', r'\g<1>47\g<2>'),
        'check': ("SELECT PortraitIndex FROM Units WHERE Type = 'UNIT_HEAVY_SKIRMISHER'", 47, 10),
    },
    'sqlupdate': {
        # VP's last SQL file before Triggers.sql: later files set Combat again (UnitChanges.sql is too early).
        'file': (VP, 'Database Changes/Text/en_US/WorldMap/TerrainTextChanges.sql'),
        'append': "-- headless builder test edit (sqlupdate)\nUPDATE Units SET Combat = Combat + 3 WHERE Type = 'UNIT_WARRIOR';\n",
        'check': ("SELECT Combat FROM Units WHERE Type = 'UNIT_WARRIOR'", 11, 8),
    },
    'newtable': {
        'file': (CP, 'Database Changes/StackingFormations.sql'),
        'append': ("-- headless builder test edit (newtable)\n"
                   "CREATE TABLE HeadlessBuilderTest(Type TEXT PRIMARY KEY, Value INTEGER NOT NULL DEFAULT 0, Note TEXT);\n"
                   "INSERT INTO HeadlessBuilderTest(Type, Value, Note) VALUES('HBT_ONE', 1, 'first');\n"
                   "INSERT INTO HeadlessBuilderTest(Type, Value) VALUES('HBT_TWO', 2);\n"
                   "INSERT INTO HeadlessBuilderTest(Type, Value, Note) SELECT 'HBT_' || Type, Cost, Class FROM Units WHERE Type = 'UNIT_SETTLER';\n"),
        'check': ("SELECT COUNT(*) FROM HeadlessBuilderTest", 3, None),
    },
    'sqlerror': {
        'file': (VP, 'Database Changes/Units/UnitChanges.sql'),
        'append': ("-- headless builder test edit (sqlerror): the statement after the error shows whether loading stops\n"
                   "INSERT INTO HeadlessBuilderMissingTable(Type) VALUES('X');\n"
                   "UPDATE Units SET Cost = Cost + 7 WHERE Type = 'UNIT_SCOUT';\n"),
        'check': ("SELECT Cost FROM Units WHERE Type = 'UNIT_SCOUT'", 90, 90),
    },
}
ORDER = ['xmlrow', 'sqlupdate', 'newtable', 'sqlerror']


def apply_edits(mods: Path, names, backup=False):
    for name in names:
        e = EDITS[name]
        path = mods / e['file'][0] / e['file'][1]
        raw = path.read_bytes()
        crlf = b'\r\n' in raw
        text = raw.decode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
        if backup and not (path.with_name(path.name + BACKUP)).exists():
            shutil.copy2(path, path.with_name(path.name + BACKUP))
        if 'regex' in e:
            new, n = re.subn(e['regex'][0], e['regex'][1], text, count=1, flags=re.S)
            if n != 1:
                raise SystemExit(f'{name}: pattern not found in {path}')
        else:
            add = e['append'].replace('\n', '\r\n') if crlf else e['append']
            sep = '' if text.endswith('\n') else ('\r\n' if crlf else '\n')
            new = text + sep + add
        data = new.encode('utf-8')
        if raw.startswith(b'\xef\xbb\xbf'):
            data = b'\xef\xbb\xbf' + data
        path.write_bytes(data)
        print(f'edited {path} ({name})')


def revert(mods: Path):
    n = 0
    for p in mods.rglob('*' + BACKUP):
        target = p.with_name(p.name[:-len(BACKUP)])
        shutil.move(str(p), str(target))
        print('restored', target)
        n += 1
    print(f'{n} file(s) restored')


def copy_input(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src / 'MODS', dst / 'MODS')
    shutil.copy2(src / 'Civ5ModsDatabase.db', dst / 'Civ5ModsDatabase.db')


def main(argv=None):
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', type=Path, help='pinned builder input (MODS\\, Civ5ModsDatabase.db)')
    ap.add_argument('--scratch', type=Path, default=cfg.runs / 'dbbuild-test-edits' if cfg.runs else None)
    ap.add_argument('--edits', default=','.join(ORDER))
    ap.add_argument('--oracle', type=Path, help='game database captured with the same edits')
    ap.add_argument('--baseline', type=Path, help='game database without the edits (for the before values)')
    ap.add_argument('--dll', type=Path, default=cfg.dll, help='game DLL for post-processing (default: config dll)')
    ap.add_argument('--apply-to', type=Path, help='apply the edits to this MODS folder in place (with backups)')
    ap.add_argument('--revert', type=Path, help='restore the backups below this MODS folder')
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.edits.split(',') if n.strip()]
    for n in names:
        if n not in EDITS:
            raise SystemExit(f'unknown edit {n}; choose from {", ".join(ORDER)}')
    if a.revert:
        revert(a.revert)
        return 0
    if a.apply_to:
        apply_edits(a.apply_to, names, backup=True)
        print(f'revert with: python tools/{Path(__file__).name} --revert "{a.apply_to}"')
        return 0
    if not a.input:
        ap.error('--input DIR (a pinned builder input) is required')

    scratch = a.scratch.resolve()
    copy_input(a.input, scratch / 'input')
    apply_edits(scratch / 'input/MODS', names)
    out = scratch / 'built.db'
    args = ['--mods-dir', str(scratch / 'input/MODS'), '--mods-db', str(scratch / 'input/Civ5ModsDatabase.db'),
            '--out', str(out), '--dll', str(a.dll)]
    if a.oracle:
        args += ['--oracle', str(a.oracle)]
    rc = dbbuild.main(args, cfg)
    con = sqlite3.connect(out)
    base = sqlite3.connect(a.baseline.resolve().as_uri() + '?mode=ro', uri=True) if a.baseline and a.baseline.is_file() else None
    ok = True
    print('checks (built database):')
    for n in names:
        sql, expected, before = EDITS[n]['check']
        got = con.execute(sql).fetchone()[0]
        was = None
        if base is not None:
            try:
                was = base.execute(sql).fetchone()[0]
            except sqlite3.Error:
                was = '(no table)'
        good = got == expected
        ok &= good
        print(f'  {n:10s} {"ok  " if good else "FAIL"} {sql}: {got} (expected {expected}; unedited game database {was})')
    if a.oracle:
        game = sqlite3.connect(a.oracle.resolve().as_uri() + '?mode=ro', uri=True)
        print('checks (game database):')
        for n in names:
            sql = EDITS[n]['check'][0]
            try:
                print(f'  {n:10s} {sql}: {game.execute(sql).fetchone()[0]}')
            except sqlite3.Error as exc:
                print(f'  {n:10s} {sql}: {exc}')
    return 0 if ok and rc == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
