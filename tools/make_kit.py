#!/usr/bin/env python3
"""Make the release kit: everything needed to run the host against a Civ V install, nothing needed to build it.

  python tools/make_kit.py [--exe BUILD] [--out dist] [--python-embed ZIP] [--worktree] [--smoke]

The kit is dist/civ5-headless-<version>-<commit>.zip with one top folder:

  bin/                    civ5headless.exe and its .pdb (from a tools/build_host.py build), build-info.json
  python/civ5headless/    the c5h package
  profiles/, probes/      the host's UI emulation profiles and Lua probes
  examples/               game specs and queues
  docs/                   the user guide, verification, profiles, engine contract, database builder, DLL additions
  runtime/                only with --python-embed: a private Python, so users need not install one
  c5h.cmd                 the command line (finds runtime\\python.exe, else Python on PATH or the py launcher)
  kit.json                version, commit, hashes; its presence makes config treat the folder as a kit (workspace,
                          bin\\civ5headless.exe, profiles\\, probes\\)
  README.md, QUICKSTART.txt, LICENSE, SOURCE.txt, licenses/SDK-NOTICE.md

Running needs no compiler: the exe uses the Visual C++ 2008 runtime that Civ V installs (its own DLLs need the same
runtime) and loads the Firaxis DLLs from the user's game folder. The c5h tools need Python 3.11 or newer, unless the
kit bundles one.

The files come from git (git archive HEAD), so the kit is exactly a commit plus an exe built from it: the build must be
successful, built at HEAD and from clean sources. --worktree takes the working tree instead and allows a dirty or older
build, for testing only (the kit is then marked dirty). --python-embed takes the Windows embeddable package from
python.org (python-3.1x.y-embed-amd64.zip); its ._pth file gets ..\\python added, since the embeddable Python ignores
PYTHONPATH. --smoke unpacks the zip into a temporary folder and runs c5h doctor there.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXE = 'civ5headless.exe'
# What the kit takes from the repository (files or folders).
KIT_PATHS = ['python/civ5headless', 'profiles', 'probes', 'examples', 'c5h.cmd', 'civ5headless.example.toml',
             'README.md', 'LICENSE', 'docs/user-guide.md', 'docs/verification.md', 'docs/profiles.md',
             'docs/engine-contract.md', 'docs/database-builder.md', 'docs/dll-additions.md']
RENAMED = {'sdk/README.md': 'licenses/SDK-NOTICE.md'}
REPOSITORY_URL = 'https://github.com/ruskyandrei/civ5-headless'

QUICKSTART = """civ5-headless {version}

Runs Civilization V (Brave New World) AI autoplay games without the game, with your DLL and mods.

Needs: Civilization V with Brave New World, started at least once (it writes its caches then); {python}.
Not needed: a compiler. civ5headless.exe uses the Visual C++ 2008 runtime that Civ V installs.

  c5h doctor                                    what was found (game, My Games, mods, DLL, host) and what is missing
  c5h run examples\\specs\\continents-tiny.json --turns 30
                                                one game with your active mods and DLL; the run goes to runs\\
  c5h verify --host-only                        the host-only part of the verification suite (about 5 minutes)
  c5h verify                                    host against the real game (needs the game and FireTuner on)

Run c5h.cmd from this folder (or put the folder on PATH). Settings go in civ5headless.toml next to it; see
civ5headless.example.toml. docs\\user-guide.md has the details, docs\\verification.md the verification suite.
"""

SOURCE = """civ5-headless is free software under the GNU General Public License v3 (LICENSE).

This kit was made from commit {commit} of the civ5-headless repository:
  {url}/tree/{commit}
The source code of civ5headless.exe is the host/ and sdk/ folders at that commit; tools/build_host.py builds it.
"""


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest().upper()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def find_build(arg):
    """The build folder (with civ5headless.exe and build-result.json) from --exe or out/latest.txt."""
    if arg:
        p = Path(arg).resolve()
        build = p.parent if p.is_file() else p
    else:
        marker = ROOT / 'out/latest.txt'
        if not marker.is_file():
            raise SystemExit('no out/latest.txt: build the host first (python tools/build_host.py) or pass --exe')
        build = Path(marker.read_text(encoding='utf-8').strip())
    if not (build / EXE).is_file():
        raise SystemExit(f'no {EXE} in {build}')
    result = build / 'build-result.json'
    info = json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {}
    if info.get('status') != 'success':
        raise SystemExit(f'{result}: not a successful tools/build_host.py build')
    return build, info


def stage_from_git(stage, commit):
    """Extract the kit's paths at COMMIT into stage (git archive applies .gitattributes line endings)."""
    sources = KIT_PATHS + list(RENAMED)
    data = subprocess.run(['git', 'archive', '--format=tar', commit, '--', *sources], cwd=ROOT,
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(stage, filter='data')
    for src, dst in RENAMED.items():
        (stage / dst).parent.mkdir(parents=True, exist_ok=True)
        (stage / src).replace(stage / dst)
    shutil.rmtree(stage / 'sdk', ignore_errors=True)


def stage_from_worktree(stage):
    for rel in KIT_PATHS:
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, stage / rel, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, stage / rel)
    for src, dst in RENAMED.items():
        (stage / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, stage / dst)


def add_runtime(stage, embed_zip):
    """Unpack the embeddable Python into runtime/ and let it find ..\\python. Returns its version string."""
    runtime = stage / 'runtime'
    with zipfile.ZipFile(embed_zip) as z:
        z.extractall(runtime)
    pth = sorted(runtime.glob('python3*._pth'))
    m = re.fullmatch(r'python3(\d+)\._pth', pth[0].name) if pth else None
    if not m or int(m.group(1)) < 11:
        raise SystemExit(f'{embed_zip}: not an embeddable Python 3.11 or newer (no python311._pth or later)')
    lines = pth[0].read_text(encoding='utf-8').splitlines()
    pth[0].write_text('\n'.join(lines + ['..\\python']) + '\n', encoding='utf-8')
    for name in ('_sqlite3.pyd', 'sqlite3.dll', 'python.exe'):
        if not (runtime / name).is_file():
            raise SystemExit(f'{embed_zip}: {name} is missing; c5h needs it')
    version = re.search(r'python-(\d+\.\d+\.\d+)', Path(embed_zip).name)
    return version.group(1) if version else f'3.{m.group(1)}'


def make_zip(stage, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():
                z.write(p, Path(stage.name) / p.relative_to(stage))


def smoke(zip_path):
    """Unpack into a temporary folder and run c5h doctor --json there; the kit's own files must be found."""
    with tempfile.TemporaryDirectory(prefix='c5h-kit-') as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        kit = next(Path(tmp).iterdir())
        env = {k: v for k, v in os.environ.items() if k not in ('C5H_CONFIG', 'PYTHONPATH')}
        proc = subprocess.run(['cmd', '/c', str(kit / 'c5h.cmd'), 'doctor', '--json'], cwd=kit, env=env,
                              capture_output=True, text=True, errors='replace')
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise SystemExit(f'smoke: c5h doctor did not print JSON (exit {proc.returncode}):\n{proc.stdout[-2000:]}\n'
                             f'{proc.stderr[-2000:]}')
        values = report.get('config', report).get('values', {})
        problems = []
        for key, want in (('workspace', kit), ('exe', kit / 'bin' / EXE), ('profiles', kit / 'profiles'),
                          ('probes', kit / 'probes')):
            got = (values.get(key) or {}).get('value')
            if not got or os.path.normcase(str(Path(got))) != os.path.normcase(str(want)):
                problems.append(f'{key}: {got} (expected {want})')
        print(f'smoke: c5h doctor exit {proc.returncode} in {kit.name}' + ('' if not problems else ': ' + '; '.join(problems)))
        return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', help='build folder or exe (default: out/latest.txt)')
    ap.add_argument('--out', default=str(ROOT / 'dist'), help='output folder (default: dist/)')
    ap.add_argument('--python-embed', metavar='ZIP', help="python.org's Windows embeddable package to bundle as runtime/")
    ap.add_argument('--worktree', action='store_true', help='take files from the working tree; allow a dirty or older build')
    ap.add_argument('--smoke', action='store_true', help='unpack the kit into a temporary folder and run c5h doctor there')
    args = ap.parse_args()

    build, info = find_build(args.exe)
    head = git('rev-parse', 'HEAD')
    dirty_paths = git('status', '--porcelain', '--', *KIT_PATHS, 'host', 'sdk', 'tools/build_host.py').splitlines()
    problems = []
    if info.get('git_head') != head:
        problems.append(f"the exe was built at {info.get('git_head', '?')[:10]}, HEAD is {head[:10]}")
    if info.get('git_dirty_paths'):
        problems.append('the exe was built from uncommitted host sources')
    if dirty_paths and args.worktree:
        problems.append('the working tree has uncommitted kit files')
    if problems and not args.worktree:
        raise SystemExit('not a clean kit: ' + '; '.join(problems) + ' (commit, rebuild, or --worktree for a test kit)')
    dirty = bool(problems)

    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    name = f'civ5-headless-{version}-{head[:9]}' + ('-dirty' if dirty else '')
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stage = out / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    if args.worktree:
        stage_from_worktree(stage)
    else:
        stage_from_git(stage, head)

    (stage / 'bin').mkdir()
    shutil.copy2(build / EXE, stage / 'bin' / EXE)
    pdb = build / 'civ5headless.pdb'
    if pdb.is_file():
        shutil.copy2(pdb, stage / 'bin' / pdb.name)
    plan = info.get('plan', {})
    compiler = (plan.get('toolchain') or {}).get('compiler') or plan.get('compiler', '')
    build_info = {'gitHead': info.get('git_head'), 'dirtySources': bool(info.get('git_dirty_paths')),
                  'config': plan.get('config'), 'built': info.get('finished_utc'),
                  'compiler': next((l for l in compiler.splitlines() if 'Version' in l), compiler.strip()),
                  'exeSha256': sha256(stage / 'bin' / EXE)}
    (stage / 'bin/build-info.json').write_text(json.dumps(build_info, indent=1) + '\n', encoding='utf-8')

    runtime = add_runtime(stage, args.python_embed) if args.python_embed else None
    python = f'nothing else: Python {runtime} is bundled in runtime\\' if runtime else \
        'Python 3.11 or newer (python.org; c5h.cmd finds python on PATH or the py launcher)'
    (stage / 'QUICKSTART.txt').write_text(QUICKSTART.format(version=f'{version} ({head[:9]})', python=python),
                                          encoding='utf-8')
    (stage / 'SOURCE.txt').write_text(SOURCE.format(commit=head, url=REPOSITORY_URL), encoding='utf-8')
    kit = {'name': name, 'version': version, 'commit': head, 'dirty': dirty, 'problems': problems,
           'made': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
           'exe': build_info, 'python': runtime or '>=3.11', 'pythonBundled': bool(runtime)}
    (stage / 'kit.json').write_text(json.dumps(kit, indent=1) + '\n', encoding='utf-8')

    zip_path = out / f'{name}.zip'
    make_zip(stage, zip_path)
    shutil.rmtree(stage)
    print(json.dumps({'zip': str(zip_path), 'bytes': zip_path.stat().st_size, 'sha256': sha256(zip_path),
                      'dirty': dirty, 'problems': problems, 'python': kit['python']}, indent=1))
    if args.smoke and not smoke(zip_path):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
