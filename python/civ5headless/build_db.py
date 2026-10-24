"""Build the modded game database without the game (headless host, plan section 4.5, M4).

  python work/headless/build_db.py --mods-dir MODS [--mods-db Civ5ModsDatabase.db] [--mod ID[:VER]]...
                                   --out BUILT.db [--snapshot DLC.db] [--path-as DIR] [--oracle REF.db]

Steps:
  1. Read every .modinfo below --mods-dir. The activated mods are the --mod arguments, or the
     rows with Activated = 1 in --mods-db (in its RowID order).
  2. Order them: a mod comes after the active mods it depends on or references; otherwise the
     given order is kept (the registry's RowID order, which matches the game's observed order).
  3. DLC the active mods block (<Blocks><Dlc>) is taken out of the snapshot: its GameData rows,
     its map scripts, and DownloadableContent.IsActive = 0 (the game rebuilds without it).
  4. Write a plan and run `civ5headless.exe builddb`, which copies the snapshot and applies every
     OnModActivated UpdateDatabase file in modinfo order (XML through Firaxis's XMLSerializer,
     SQL through Connection::ExecuteMultiple), with a schema-only text database attached so
     Language_* statements resolve the way they do in the game; then registers the mods'
     MapScript entry points (GetMapScriptInfo) and runs the DLL's PerformDatabasePostProcessing.
  5. With --oracle, compares the result with dbdiff.py and prints the verdict.

Map script FileName values are absolute paths into the MODS folder, as the game records them.
--path-as gives the MODS folder to record instead of --mods-dir (default: the user's real
MODS folder, so a build from a pinned copy matches the game's database).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_GAME = Path(r"E:\SteamLibrary\steamapps\common\Sid Meier's Civilization V")
DOCS_MODS = Path.home() / "Documents/My Games/Sid Meier's Civilization 5/MODS"
# Local inputs live in the main checkout's work/headless/db (a worktree is at <main>/work/wt/<name>).
MAIN = ROOT.parents[2] if ROOT.parent.name == 'wt' else ROOT
DEFAULT_SNAPSHOT = MAIN / 'work/headless/db/dlc-snapshot-CBF411E4.db'

# Schema of the game's localization database (Localization-Merged.db): Language_en_US is a view
# over LocalizedText with INSTEAD OF triggers. The game resolves mods' Language_* statements
# against it; the builder attaches an empty copy so they behave the same and leave the game
# database alone. Text itself is not built (plan 4.5 step 5).
TEXT_SCHEMA = [
    'CREATE TABLE ScannedFiles("Path" TEXT NOT NULL PRIMARY KEY, "DateTime" INTEGER NOT NULL)',
    'CREATE TABLE Languages( "ID" INTEGER PRIMARY KEY AUTOINCREMENT, "Type" TEXT NOT NULL UNIQUE, "Name" TEXT NOT NULL, '
    '"TableName" TEXT NOT NULL, "TagColumnName" TEXT DEFAULT "Tag", "TextColumnName" TEXT DEFAULT "Text", '
    '"PluralityColumnName" TEXT DEFAULT "Plurality", "GenderColumnName" TEXT DEFAULT "Gender", "PluralRule" INTEGER DEFAULT 1, '
    '"UseExtendedFont" INTEGER DEFAULT 0, "FontName" TEXT DEFAULT "MS PGothic", "FontWidthScale" FLOAT DEFAULT 0.4, '
    '"FontHeightScale" FLOAT DEFAULT 0.8)',
    'CREATE TABLE LocalizedText("Language" TEXT, "Tag" TEXT, "Text" TEXT, "Gender" TEXT, "Plurality" TEXT, PRIMARY KEY(Language, Tag))',
    'CREATE TABLE LanguagePriorities("LanguageSet" TEXT, "Language" TEXT, "Priority" INT, PRIMARY KEY(LanguageSet, Language))',
    'CREATE TABLE SpokenLanguages( "ID" INTEGER PRIMARY KEY AUTOINCREMENT, "Type" TEXT NOT NULL UNIQUE, "DisplayName" TEXT NOT NULL, "Path" TEXT NOT NULL)',
] + [f'CREATE TABLE Language_{lang}("ID" INTEGER PRIMARY KEY AUTOINCREMENT, "Tag" TEXT UNIQUE NOT NULL, "Text" TEXT NOT NULL, '
     '"Gender" TEXT, "Plurality" TEXT)' for lang in ('DE_DE', 'ES_ES', 'FR_FR', 'IT_IT', 'JA_JP', 'RU_RU', 'PL_PL', 'KO_KR', 'ZH_HANT_HK')] + [
    'CREATE INDEX "LocalizedText_ByTag" ON "LocalizedText" ("Tag" ASC)',
    'CREATE INDEX "LanguagePriorities_ByLanguageSet" ON "LanguagePriorities" ("LanguageSet" ASC)',
    "CREATE VIEW Language_en_US AS SELECT Tag, Text, Gender, Plurality from LocalizedText where Language = 'en_US'",
    "CREATE TRIGGER Language_en_US_insert INSTEAD OF INSERT ON Language_en_US BEGIN insert into LocalizedText(Language, Tag, Text, "
    "Gender, Plurality) VALUES('en_US', NEW.Tag, NEW.Text, NEW.Gender, NEW.Plurality); END",
    "CREATE TRIGGER Language_en_US_update INSTEAD OF UPDATE ON Language_en_US BEGIN UPDATE LocalizedText SET Text = NEW.Text , "
    "Gender = NEW.Gender, Plurality = NEW.Plurality WHERE Language = 'en_US' and Tag = NEW.Tag; END",
    "CREATE TRIGGER Language_en_US_delete INSTEAD OF DELETE ON Language_en_US BEGIN DELETE from LocalizedText where "
    "Language = 'en_US' and Tag = OLD.Tag; END",
]


def norm_id(s):
    return (s or '').strip().strip('{}').lower()


def text_of(el, tag):
    child = el.find(tag)
    return (child.text or '').strip() if child is not None and child.text else ''


class ModInfo:
    def __init__(self, path: Path):
        self.path = path
        self.folder = path.parent
        root = ET.fromstring(path.read_bytes())
        self.id = norm_id(root.get('id'))
        self.version = int(root.get('version') or 0)
        props = root.find('Properties')
        self.name = text_of(props, 'Name') if props is not None else path.stem
        self.dependencies = [(norm_id(m.get('id')), int(m.get('minversion') or 0), int(m.get('maxversion') or 999))
                             for m in root.findall('Dependencies/Mod')]
        self.references = [(norm_id(m.get('id')), int(m.get('minversion') or 0), int(m.get('maxversion') or 999))
                           for m in root.findall('References/Mod')]
        self.blocked_dlc = [norm_id(d.get('id')) for d in root.findall('Blocks/Dlc')]
        self.update_db = [(e.text or '').strip() for e in root.findall('Actions/OnModActivated/UpdateDatabase')]
        self.map_scripts = [e.get('file') for e in root.findall('EntryPoints/EntryPoint') if e.get('type') == 'MapScript']
        self.imports = [(f.text or '').strip() for f in root.findall('Files/File') if f.get('import') == '1']

    def key(self):
        return (self.id, self.version)


def scan_mods(mods_dir: Path):
    mods = {}
    for p in sorted(mods_dir.glob('*/*.modinfo')):
        m = ModInfo(p)
        if m.key() in mods:
            print(f'warning: {p} duplicates mod {m.id} v{m.version} ({mods[m.key()].path})', file=sys.stderr)
            continue
        mods[m.key()] = m
    return mods


def activated_from_registry(mods_db: Path):
    con = sqlite3.connect(mods_db.resolve().as_uri() + '?mode=ro', uri=True)
    rows = con.execute('SELECT ModID, Version FROM Mods WHERE Activated = 1 ORDER BY RowID').fetchall()
    con.close()
    return [(norm_id(r[0]), int(r[1])) for r in rows]


def check_registry(mods_db: Path, ordered):
    """Warn when the registry's UpdateDatabase list differs from the modinfo files."""
    con = sqlite3.connect(mods_db.resolve().as_uri() + '?mode=ro', uri=True)
    notes = []
    for m in ordered:
        reg = [r[0] for r in con.execute(
            "SELECT Param1 FROM ModActions WHERE lower(ModID) = ? AND Version = ? AND Location = 'OnModActivated' "
            "AND Action = 'UpdateDatabase' ORDER BY rowid", (m.id, m.version))]
        if reg != m.update_db:
            notes.append(f'{m.name}: registry UpdateDatabase list ({len(reg)}) differs from {m.path.name} ({len(m.update_db)})')
    con.close()
    return notes


def order_mods(mods, wanted):
    """Stable topological order: dependencies and references among active mods first."""
    active = []
    for mid, ver in wanted:
        cand = [m for (i, v), m in mods.items() if i == mid and (ver is None or v == ver)]
        if not cand:
            raise SystemExit(f'mod {mid} v{ver} not found below the MODS folder')
        active.append(max(cand, key=lambda m: m.version))
    by_id = {m.id: m for m in active}
    for m in active:
        for dep, lo, hi in m.dependencies:
            if dep not in by_id:
                print(f'warning: {m.name} depends on {dep}, which is not active', file=sys.stderr)
    done, out = set(), []

    def visit(m, stack):
        if m.id in done:
            return
        if m.id in stack:
            raise SystemExit('mod dependency cycle: ' + ' -> '.join(stack + [m.id]))
        for dep, lo, hi in m.dependencies + m.references:
            if dep in by_id:
                visit(by_id[dep], stack + [m.id])
        done.add(m.id)
        out.append(m)

    for m in active:
        visit(m, [])
    return out


def find_dlc_packages(game: Path):
    pkgs = {}
    for pkg in (game / 'Assets/DLC').glob('*/*.Civ5Pkg'):
        root = ET.fromstring(pkg.read_bytes())
        guid = norm_id(text_of(root, 'GUID'))
        pkgs[guid] = (pkg, root)
    return pkgs


def sql_literal(v):
    return "'" + v.replace("'", "''") + "'"


def dlc_removal_sql(game: Path, snapshot: Path, blocked):
    """SQL that takes a blocked DLC package out of the snapshot."""
    pkgs = find_dlc_packages(game)
    con = sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)
    lines, notes = [], []
    for guid in blocked:
        package_id = guid.replace('-', '').upper()
        row = con.execute('SELECT IsActive FROM DownloadableContent WHERE PackageID = ?', (package_id,)).fetchone()
        if not row:
            notes.append(f'blocked DLC {guid} is not in the snapshot')
            continue
        if not row[0]:
            continue
        if guid not in pkgs:
            raise SystemExit(f'blocked DLC {guid} is active in the snapshot but not installed below {game}')
        pkg, root = pkgs[guid]
        folder = pkg.parent
        lines.append(f'-- {folder.name} ({guid})')
        lines.append(f"UPDATE DownloadableContent SET IsActive = 0 WHERE PackageID = {sql_literal(package_id)};")
        for gd in root.findall('GameData'):
            path = folder / (gd.text or '').strip()
            data = ET.fromstring(path.read_bytes())
            for table in data:
                for row_el in table:
                    if row_el.tag != 'Row':
                        raise SystemExit(f'{path}: <{table.tag}><{row_el.tag}> cannot be undone; rebuild the DLC snapshot instead')
                    cond = ' AND '.join(f'"{c.tag}" = {sql_literal((c.text or "").strip())}' for c in row_el)
                    lines.append(f'DELETE FROM "{table.tag}" WHERE {cond};')
        for md in root.findall('Gameplay/MapDirectory'):
            prefix = 'Assets\\DLC\\' + folder.name + '\\' + (md.text or '').strip().replace('/', '\\') + '\\'
            like = sql_literal(prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
            for t in ('MapScriptOptionPossibleValues', 'MapScriptOptions', 'MapScripts'):
                lines.append(f"DELETE FROM {t} WHERE FileName LIKE {like} ESCAPE '\\';")
        notes.append(f'blocked DLC {folder.name} ({guid}) taken out of the snapshot')
    con.close()
    return lines, notes


def build_vfs(game: Path, ordered, blocked_folders):
    """include() index for map scripts: game Lua files, then active DLC, then mods' imports."""
    vfs = {}
    assets = game / 'Assets'
    def add_tree(base):
        for p in sorted(base.rglob('*.lua')):
            vfs[p.name.lower()] = p
    for p in sorted(assets.rglob('*.lua')):
        if 'DLC' not in p.relative_to(assets).parts[:1]:
            vfs[p.name.lower()] = p
    dlc = assets / 'DLC'
    order = ['Expansion', 'Expansion2']
    others = sorted(d.name for d in dlc.iterdir() if d.is_dir() and d.name not in order)
    for name in others + order:
        if name not in blocked_folders and (dlc / name).is_dir():
            add_tree(dlc / name)
    for m in ordered:
        for rel in m.imports:
            if rel.lower().endswith('.lua'):
                p = m.folder / rel.replace('/', os.sep)
                if p.is_file():
                    vfs[p.name.lower()] = p
    return vfs


def latest_exe():
    marker = ROOT / 'work/latest-headless-build-path.txt'
    if marker.is_file():
        exe = Path(marker.read_text(encoding='utf-8').strip()) / 'civ5headless.exe'
        if exe.is_file():
            return exe
    raise SystemExit('no civ5headless.exe: build it with python work/build-headless.py, or pass --exe')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest().upper()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mods-dir', type=Path, required=True, help='MODS folder (or a pinned copy) holding the .modinfo files')
    ap.add_argument('--mods-db', type=Path, help='Civ5ModsDatabase.db: activated mods (Activated = 1) and a cross-check')
    ap.add_argument('--mod', action='append', default=[], help='activated mod GUID[:version] (repeatable; overrides --mods-db)')
    ap.add_argument('--out', type=Path, required=True, help='database to write')
    ap.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT, help='DLC snapshot (Civ5DebugDatabase.db, no mods)')
    ap.add_argument('--path-as', type=Path, help='MODS folder recorded in MapScripts.FileName (default: the real MODS folder)')
    ap.add_argument('--game-dir', type=Path, default=DEFAULT_GAME)
    ap.add_argument('--dll', type=Path, help='game DLL for post-processing (default: the CP mod folder\'s CvGameCore_Expansion2.dll)')
    ap.add_argument('--exe', type=Path, help='civ5headless.exe (default: the latest work/build-headless.py output)')
    ap.add_argument('--no-postprocess', action='store_true', help='skip PerformDatabasePostProcessing')
    ap.add_argument('--oracle', type=Path, help='reference database to compare with (dbdiff.py)')
    ap.add_argument('--keep-run', action='store_true', help='keep the run folder (logs, plan, report) next to --out')
    a = ap.parse_args(argv)
    t0 = time.monotonic()

    mods_dir = a.mods_dir.resolve()
    out = a.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    run = out.with_name(out.name + '.build')
    run.mkdir(exist_ok=True)
    mods = scan_mods(mods_dir)
    if a.mod:
        wanted = []
        for s in a.mod:
            mid, _, ver = s.partition(':')
            wanted.append((norm_id(mid), int(ver) if ver else None))
    elif a.mods_db:
        wanted = activated_from_registry(a.mods_db)
    else:
        raise SystemExit('give --mod or --mods-db')
    ordered = order_mods(mods, wanted)
    notes = check_registry(a.mods_db, ordered) if a.mods_db else []
    path_as = (a.path_as or DOCS_MODS)
    path_as = str(path_as).rstrip('\\/')

    blocked = []
    for m in ordered:
        blocked += [g for g in m.blocked_dlc if g not in blocked]
    dlc_lines, dlc_notes = dlc_removal_sql(a.game_dir, a.snapshot, blocked)
    notes += dlc_notes
    pkgs = find_dlc_packages(a.game_dir)
    blocked_folders = {pkgs[g][0].parent.name for g in blocked if g in pkgs}

    text_db = run / 'text-schema.db'
    if text_db.exists():
        text_db.unlink()
    con = sqlite3.connect(text_db)
    for stmt in TEXT_SCHEMA:
        con.execute(stmt)
    con.commit()
    con.close()

    dll = a.dll
    if dll is None and not a.no_postprocess:
        cp = next((m for m in ordered if m.id == 'd1b6328c-ff44-4b0d-aad7-c657f83610cd'), None)
        cand = cp.folder / 'CvGameCore_Expansion2.dll' if cp else None
        if cand is None or not cand.is_file():
            raise SystemExit('no game DLL for post-processing: pass --dll (or --no-postprocess)')
        dll = cand

    plan = [f'snapshot\t{a.snapshot.resolve()}', 'phase\tdlc']
    if dlc_lines:
        dlc_sql = run / 'dlc-removal.sql'
        dlc_sql.write_text('\n'.join(dlc_lines) + '\n', encoding='utf-8')
        plan.append(f'sql\t{dlc_sql}')
    plan.append(f'attach\t{text_db}\tLocalization')
    files = []
    for m in ordered:
        plan.append(f'mod\t{m.id}\t{m.version}\t{m.name}')
        for rel in m.update_db:
            p = m.folder / rel.replace('/', os.sep).replace('\\', os.sep)
            kind = 'missing' if not p.is_file() else ('sql' if p.suffix.lower() == '.sql' else 'xml')
            plan.append(f'{kind}\t{p}')
            files.append(p)
    plan += ['phase\tmapscripts']
    for m in ordered:
        for rel in m.map_scripts:
            p = m.folder / rel.replace('/', os.sep)
            recorded = path_as + '\\' + m.folder.name + '\\' + rel
            plan.append(f'mapscript\t{p}\t{recorded}')
    # Map scripts look up the mods' text (Continental Drift's Name), so the text database stays
    # attached until they are registered.
    plan.append('detach\tLocalization')
    if not a.no_postprocess:
        plan += ['phase\tpostprocess', 'postprocess']
    vfs = build_vfs(a.game_dir, ordered, blocked_folders)
    plan += [f'vfs\t{k}\t{v}' for k, v in sorted(vfs.items())]
    plan_path = run / 'plan.txt'
    plan_path.write_text('\n'.join(plan) + '\n', encoding='utf-8')

    exe = (a.exe or latest_exe()).resolve()
    cmd = [str(exe), 'builddb', '--game-dir', str(a.game_dir), '--plan', str(plan_path), '--out', str(out), '--run', str(run)]
    if dll and not a.no_postprocess:
        cmd += ['--dll', str(Path(dll).resolve())]
    t1 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    host_seconds = time.monotonic() - t1
    report_path = run / 'builddb-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    if proc.returncode != 0:
        print(proc.stdout[-4000:])
        print(proc.stderr[-4000:], file=sys.stderr)
    failed = [s for s in report.get('steps', []) if not s.get('ok')]
    summary = {
        'out': str(out), 'status': report.get('status', 'failed'), 'host_exit': proc.returncode,
        'mods': [f'{m.name} (v{m.version})' for m in ordered], 'update_files': len(files),
        'steps_with_errors': [{k: s.get(k) for k in ('kind', 'mod', 'path', 'note', 'errors') if s.get(k)} for s in failed],
        'notes': notes, 'host_seconds': round(host_seconds, 2), 'run': str(run),
        'exe': str(exe), 'dll': str(dll) if dll else None, 'snapshot': str(a.snapshot.resolve()),
    }
    if a.oracle:
        sys.path.insert(0, str(HERE))
        import dbdiff
        diff = dbdiff.diff(a.oracle, out)
        (run / 'dbdiff.json').write_text(json.dumps(diff, indent=1, default=str) + '\n', encoding='utf-8')
        summary['oracle'] = str(a.oracle)
        summary['identical'] = diff['identical']
        summary['tables_differ'] = [t['table'] for t in diff['tables_differ']]
    summary['seconds'] = round(time.monotonic() - t0, 2)
    (run / 'build-summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f"{summary['status']}: {out} ({len(ordered)} mods, {len(files)} update files, host {host_seconds:.1f} s)")
    for m in summary['mods']:
        print('  mod', m)
    for n in notes:
        print('  note:', n)
    for s in summary['steps_with_errors']:
        print(f"  error in {s.get('kind')} {s.get('path')}: {s.get('note', '')} {(s.get('errors') or [''])[0]}")
    if a.oracle:
        print('oracle:', 'identical' if summary['identical'] else 'DIFFERENT (' + ', '.join(summary['tables_differ'][:12]) + ')')
        print(f'  details: python work/headless/dbdiff.py "{a.oracle}" "{out}"')
    ok = summary['status'] == 'built' and (not a.oracle or summary['identical'])
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
