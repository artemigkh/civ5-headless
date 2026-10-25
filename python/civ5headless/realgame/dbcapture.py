"""Capture the game's databases for the headless host, and check them against the live game.

  python work/headless/db_capture.py --run NAME [--dll-sha SHA]

Launches the game (vpbench launcher: tuner service and CPU guard), then:
  1. Main menu, no mods active: copies cache/Civ5DebugDatabase.db (the expansion/DLC snapshot the
     database builder starts from) and exports the database the game holds in memory.
  2. Activates the benchmark mods (as vpbench does), then copies the modded Civ5DebugDatabase.db and
     exports the in-memory database again.
  3. Quits normally and compares each copy with its in-memory export, table by table.

The in-memory export runs in-game: ATTACH a new file and CREATE TABLE ... AS SELECT for every table.
Results go to work/test-runs/NAME (dlc-debug.db, dlc-ingame.db, mods-debug.db, mods-ingame.db,
db-capture.json).
"""
from pathlib import Path
import argparse, hashlib, json, shutil, sqlite3, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/vpbench'))
import vpbench
from vpbench import tuner, write, utc

CACHE = Path.home() / "Documents/My Games/Sid Meier's Civilization 5/cache"
INSTALLED_DLL = Path.home() / "Documents/My Games/Sid Meier's Civilization 5/MODS/(1) Community Patch/CvGameCore_Expansion2.dll"

EXPORT = r'''
local path=%s
local ok,err=pcall(function() for _ in DB.Query("ATTACH DATABASE '"..path.."' AS hhx") do end end)
if not ok then return {error='attach: '..tostring(err)} end
local names,failed={},{}
for row in DB.Query("SELECT name FROM main.sqlite_master WHERE type='table'") do
 if string.sub(row.name,1,7)~='sqlite_' then names[#names+1]=row.name end
end
for _,t in ipairs(names) do
 local ok2,e2=pcall(function() for _ in DB.Query('CREATE TABLE hhx."'..t..'" AS SELECT * FROM main."'..t..'"') do end end)
 if not ok2 then failed[#failed+1]=t..': '..tostring(e2) end
end
for _ in DB.Query("DETACH DATABASE hhx") do end
local mods={};local okm,act=pcall(Modding.GetActivatedMods);if okm and act then for _,m in ipairs(act) do mods[#mods+1]=m.ID end end
return {tables=#names,failed=failed,activated=mods}
'''


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''): h.update(part)
    return h.hexdigest().upper()


def wait_db_written(after, label, b, timeout=300):
    """Wait until Civ5DebugDatabase.db is newer than `after` and unchanged for 5 s; return its mtime."""
    db = CACHE / 'Civ5DebugDatabase.db'
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        st = db.stat()
        sig = (st.st_mtime, st.st_size)
        if st.st_mtime > after and sig == last:
            b.log('debug_db_ready', phase=label, mtime=st.st_mtime, size=st.st_size)
            return st.st_mtime
        last = sig
        time.sleep(5)
    raise TimeoutError(f'{label}: Civ5DebugDatabase.db was not rewritten')


def table_rows(conn, table):
    cols = [r[1] for r in conn.execute(f'pragma table_info("{table}")')]
    rows = conn.execute(f'select * from "{table}"').fetchall()
    return cols, sorted(rows, key=lambda r: tuple((v is None, type(v).__name__, str(v)) for v in r))


def compare(cached, ingame):
    a, b = sqlite3.connect(cached), sqlite3.connect(ingame)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--dll-sha')
    args = ap.parse_args()
    dll_sha = args.dll_sha or sha256(INSTALLED_DLL)
    b = vpbench.Bench(args.run)
    started = time.time()
    log = b.run.parent / (args.run + '-launch.log')
    with log.open('wb') as stream:
        code = subprocess.run([vpbench.PWSH, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'work/vpbench/vpbench-launch.ps1'),
                               '-RunName', args.run, '-ExpectedDLLSHA', dll_sha, '-MaximumSeconds', '1800'],
                              stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT).returncode
    if code: raise RuntimeError(f'Launch failed; see {log}')
    (b.run / 'calls').mkdir(exist_ok=True)
    b.guards = json.loads((b.run / 'watcher-manifest.json').read_text(encoding='utf-8-sig'))
    b.log('launched', game=b.guards['Game'], dllSha=dll_sha)
    result = {'utc': utc(), 'dllSha': dll_sha}
    try:
        deadline = time.monotonic() + 240
        while not ({'MainMenu', 'LegalScreen', 'ModsBrowser'} & b.states()):
            if time.monotonic() >= deadline: raise TimeoutError('Main menu did not appear')
            time.sleep(2)
        wait_db_written(started, 'dlc', b)
        shutil.copy2(CACHE / 'Civ5DebugDatabase.db', b.run / 'dlc-debug.db')
        out = str((b.run / 'dlc-ingame.db').resolve()).replace('\\', '/')
        result['dlcExport'] = b.call('MainMenu', EXPORT % tuner.lua_string(out), 'export-dlc', timeout=120)
        if not (b.run / 'ensure-mods-result.json').exists():
            code = subprocess.run([vpbench.PY, '-B', '-u', str(ROOT / 'work/ensure-benchmark-mods.py'), '--run-dir', str(b.run),
                                   '--expected-mods-json', str(vpbench.MODS)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
            if code.returncode: raise RuntimeError('Benchmark mods could not be verified: ' + code.stdout[-400:])
            b.call('LegalScreen', 'UIManager:DequeuePopup(ContextPtr)', 'dismiss-legal')
        before_mods = (CACHE / 'Civ5DebugDatabase.db').stat().st_mtime
        b.call('ModsBrowser', "assert(#Modding.GetEnabledModsByActivationOrder()>0,'No mods enabled');OnNextButtonClicked();return 'activated'", 'activate-mods')
        deadline = time.monotonic() + 240
        while 'ModsSinglePlayer' not in b.states():
            if time.monotonic() >= deadline: raise TimeoutError('Mod activation did not complete')
            time.sleep(1)
        wait_db_written(before_mods, 'mods', b)
        shutil.copy2(CACHE / 'Civ5DebugDatabase.db', b.run / 'mods-debug.db')
        out = str((b.run / 'mods-ingame.db').resolve()).replace('\\', '/')
        result['modsExport'] = b.call('ModsSinglePlayer', EXPORT % tuner.lua_string(out), 'export-mods', timeout=120)
    finally:
        b.quit()
    for phase in ('dlc', 'mods'):
        cached, ingame = b.run / f'{phase}-debug.db', b.run / f'{phase}-ingame.db'
        if cached.exists() and ingame.exists():
            result[phase + 'Compare'] = compare(cached, ingame)
            result[phase + 'DebugSha'] = sha256(cached)
    write(b.run / 'db-capture.json', result)
    print(json.dumps({k: (v if not isinstance(v, dict) or 'differing' not in v else {'differing': len(v['differing']), 'only_cached': len(v['only_cached']), 'only_ingame': len(v['only_ingame'])}) for k, v in result.items()}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
