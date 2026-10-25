"""Game database cache for headless runs: one build per (mods input, game DLL, snapshot, builder exe).

  python work/headless/dbcache.py --mods-dir MODS --mods-db Civ5ModsDatabase.db --dll DLL [--exe EXE]

prints the path of the cached database, building it with build_db.py on a miss (about 3 s).

The key hashes the contents of every .modinfo/.xml/.sql/.lua file below the MODS folder (the only files the
builder reads), the mods database, the DLL (its post-processing runs on the database), the DLC snapshot and
the builder exe. Entries live in <cache>/<key>/built.db with build_db.py's report next to it
(built.db.build/) and an inputs.json; a finished entry has built.db.ok.
"""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys, time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_db  # noqa: E402  (DEFAULT_SNAPSHOT, find_exe)

DEFAULT_CACHE = ROOT / 'work/headless/cache/db'
SOURCE_EXT = {'.modinfo', '.xml', '.sql', '.lua'}
_sha_memo = {}


def sha256_file(path):
    path = Path(path).resolve()
    st = path.stat()
    memo = (str(path), st.st_size, st.st_mtime_ns)
    if memo in _sha_memo:
        return _sha_memo[memo]
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    _sha_memo[memo] = h.hexdigest().upper()
    return _sha_memo[memo]


def mods_hash(mods_dir):
    h = hashlib.sha256()
    root = Path(mods_dir)
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in SOURCE_EXT)
    for p in files:
        h.update(str(p.relative_to(root)).replace('\\', '/').lower().encode('utf-8') + b'\0')
        h.update(bytes.fromhex(sha256_file(p)))
    return h.hexdigest().upper(), len(files)


def find_exe(exe=None):
    if exe:
        return Path(exe).resolve()
    marker = ROOT / 'work/latest-headless-build-path.txt'
    if marker.is_file():
        p = Path(marker.read_text(encoding='utf-8').strip())
        p = p / 'civ5headless.exe' if p.is_dir() else p
        if p.is_file():
            return p
    builds = sorted((ROOT / 'work/headless-output/Release').glob('*/civ5headless.exe'))
    if builds:
        return builds[-1]
    raise SystemExit('no civ5headless.exe: build it with python work/build-headless.py, or pass --exe')


def get_db(mods_dir, mods_db, dll, exe=None, snapshot=None, cache=None, log=print):
    """Path of the built database for these inputs; builds it on a miss."""
    exe = find_exe(exe)
    snapshot = Path(snapshot or build_db.DEFAULT_SNAPSHOT)
    mhash, nfiles = mods_hash(mods_dir)
    inputs = dict(modsDir=str(Path(mods_dir).resolve()), modsFiles=nfiles, modsSHA256=mhash,
                  modsDb=str(Path(mods_db).resolve()), modsDbSHA256=sha256_file(mods_db),
                  dll=str(Path(dll).resolve()), dllSHA256=sha256_file(dll),
                  snapshot=str(snapshot.resolve()), snapshotSHA256=sha256_file(snapshot),
                  exe=str(exe), exeSHA256=sha256_file(exe))
    key = hashlib.sha256('|'.join(inputs[k] for k in ('modsSHA256', 'modsDbSHA256', 'dllSHA256', 'snapshotSHA256', 'exeSHA256'))
                         .encode()).hexdigest()[:16].upper()
    entry = Path(cache or DEFAULT_CACHE) / key
    db = entry / 'built.db'
    if (entry / 'built.db.ok').is_file() and db.is_file():
        return db, inputs, key
    entry.mkdir(parents=True, exist_ok=True)
    (entry / 'inputs.json').write_text(json.dumps(inputs, indent=1) + '\n', encoding='utf-8')
    t = time.monotonic()
    cmd = [sys.executable, '-B', str(HERE / 'build_db.py'), '--mods-dir', str(mods_dir), '--mods-db', str(mods_db),
           '--dll', str(dll), '--exe', str(exe), '--snapshot', str(snapshot), '--out', str(db)]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    (entry / 'build_db.out.txt').write_text(r.stdout + r.stderr, encoding='utf-8')
    if r.returncode or not db.is_file():
        raise RuntimeError(f'database build failed (exit {r.returncode}); see {entry / "build_db.out.txt"}')
    (entry / 'built.db.ok').write_text(f'{time.monotonic() - t:.1f}\n', encoding='ascii')
    log(f'database built in {time.monotonic() - t:.1f} s: {db}')
    return db, inputs, key


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--mods-dir', required=True)
    a.add_argument('--mods-db', required=True)
    a.add_argument('--dll', required=True)
    a.add_argument('--exe')
    a.add_argument('--snapshot')
    a.add_argument('--cache', default=str(DEFAULT_CACHE))
    args = a.parse_args()
    db, inputs, key = get_db(args.mods_dir, args.mods_db, args.dll, args.exe, args.snapshot, args.cache, log=lambda m: print(m, file=sys.stderr))
    print(db)


if __name__ == '__main__':
    main()
