#!/usr/bin/env python3
"""Build the headless autoplay host civ5headless.exe with the VC9 toolchain.

  python tools/build_host.py [--config release|debug] [--jobs N] [--toolchain DIR] [--check]

Uses the game DLL's compiler, CRT (/MD: MSVCR90/MSVCP90) and STL settings, because std::string, std::vector, CvString
and FireWorks objects cross the engine interfaces (tools/toolchain.py says how the toolchain is found). Sources are
every .cpp and .asm below host/; headers and import libraries come from sdk/; the 22 FireWorks exports come from
host/civ5headless.def.

Output: out/<Config>/<timestamp>/ with civ5headless.exe, .pdb, logs/ and build-result.json (status, toolchain, inputs
with hashes, outputs with hashes); out/latest.txt names the newest successful build. Intermediates go to
build/<Config>/<timestamp>/.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'host'
SDK = ROOT / 'sdk'
DEF_FILE = HOST / 'civ5headless.def'
SDK_INCLUDES = [SDK / 'CvGameCoreDLLUtil/include', SDK / 'CvLocalization/include', SDK / 'CvGameDatabase/include',
                SDK / 'FirePlace/include', SDK / 'FirePlace/include/FireWorks', SDK / 'ThirdPartyLibs/Lua51/include']
SDK_LIBS = [SDK / 'CvLocalization/lib/CvLocalizationWin32.lib', SDK / 'CvGameDatabase/lib/CvGameDatabaseWin32.lib',
            SDK / 'ThirdPartyLibs/Lua51/lib/lua51_Win32.lib']


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest().upper()


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_response(path, args):
    path.write_text('\n'.join(subprocess.list2cmdline([str(a)]) for a in args) + '\n', encoding='mbcs')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', choices=['release', 'debug'], default='release')
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--toolchain', help='VC9 toolchain folder (see tools/toolchain.py)')
    parser.add_argument('--check', action='store_true', help='Print the resolved build plan; compile nothing')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    config = args.config.title()
    tools, env, tc_info = toolchain.find(args.toolchain)

    sources = sorted(HOST.rglob('*.cpp'))
    asm_sources = sorted(HOST.rglob('*.asm'))
    headers = sorted(p for p in HOST.rglob('*') if p.suffix.lower() in {'.h', '.inl'})
    if not sources:
        raise RuntimeError('No sources below ' + str(HOST))
    if len({p.stem.lower() for p in sources + asm_sources}) != len(sources) + len(asm_sources):
        raise RuntimeError('Duplicate source basenames')
    for p in [DEF_FILE] + SDK_LIBS:
        if not p.is_file():
            raise FileNotFoundError(p)

    includes = [HOST] + SDK_INCLUDES
    defines = ['WIN32', '_WINDOWS', '_CONSOLE', 'FINAL_RELEASE', '_CRT_SECURE_NO_WARNINGS',
               # The DLL's PCH sets these before any STL header; container layouts must match.
               '_SECURE_SCL=0', '_HAS_ITERATOR_DEBUGGING=0']
    # Both configurations use the release CRT (/MD), as the DLL does; debug only drops optimisation.
    defines.append('NDEBUG')
    if config == 'Debug':
        defines.append('HH_DEBUG_BUILD')
    flags = ['/nologo', '/c', '/MD', '/W3', '/Zi', '/Gm-', '/GS', '/EHsc', '/Gd', '/fp:precise',
             '/Zc:wchar_t', '/Zc:forScope', '/wd4996', '/wd4251']
    flags.append('/O2' if config == 'Release' else '/Od')
    flags += ['/D' + d for d in defines]
    flags += ['/I' + str(p) for p in includes]

    system_libs = ['kernel32.lib', 'user32.lib', 'advapi32.lib', 'shell32.lib', 'winmm.lib', 'psapi.lib', 'delayimp.lib']
    # The Firaxis DLLs live in the game folder, which the host only learns from its command
    # line: delay-load them, so the driver can load them from there before first use.
    delay_loaded = ['CvGameDatabaseWin32Final Release.dll', 'CvLocalizationWin32Final Release.dll', 'lua51_Win32.dll']
    # /PDBALTPATH: the exe names its .pdb without the build folder, so released binaries carry no local paths.
    link_flags = ['/NOLOGO', '/MACHINE:X86', '/DEBUG', '/PDBALTPATH:%_PDB%', '/SUBSYSTEM:CONSOLE', '/LARGEADDRESSAWARE',
                  '/DYNAMICBASE', '/NXCOMPAT', '/MANIFEST', '/INCREMENTAL:NO', '/OPT:REF', '/OPT:ICF',
                  '/DEF:' + str(DEF_FILE)] + ['/DELAYLOAD:' + name for name in delay_loaded]

    plan = {'config': config, 'toolchain': tc_info, 'sources': [str(p) for p in sources + asm_sources],
            'compile_flags': flags, 'link_flags': link_flags,
            'libraries': [str(p) for p in SDK_LIBS] + system_libs, 'jobs': args.jobs}
    if args.check:
        print(json.dumps(plan, indent=2))
        return 0

    run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    build = ROOT / 'build' / config / run_id
    output = ROOT / 'out' / config / run_id
    for p in (build, output):
        if p.exists():
            raise RuntimeError('Output run directory already exists: ' + str(p))
        p.mkdir(parents=True)
    logs = output / 'logs'
    logs.mkdir()
    objects = build / 'obj'
    objects.mkdir()

    inputs = set(sources + asm_sources + headers + [DEF_FILE, Path(__file__).resolve(), Path(toolchain.__file__).resolve()]
                 + SDK_LIBS)
    for directory in SDK_INCLUDES:
        inputs.update(p for p in directory.rglob('*') if p.is_file() and p.suffix.lower() in {'.h', '.hpp', '.inl', '.inc'})
    input_hashes = {str(p.resolve().relative_to(ROOT)): sha256(p) for p in sorted(inputs, key=str)}
    (output / 'source-inputs.json').write_text(json.dumps(input_hashes, indent=2), encoding='utf-8')
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain', '--', 'host', 'sdk', 'tools/build_host.py', 'tools/toolchain.py'],
                           cwd=ROOT, capture_output=True, text=True)

    commands = []
    started = time.monotonic()

    def run(label, command):
        log = logs / (label + '.log')
        event = {'label': label, 'command': [str(a) for a in command], 'started_utc': timestamp(), 'log': str(log)}
        commands.append(event)
        print(f'{label}: {log}', flush=True)
        with log.open('wb') as stream:
            proc = subprocess.run([str(a) for a in command], cwd=HOST, env=env, stdout=stream, stderr=subprocess.STDOUT)
        event['returncode'] = proc.returncode
        event['finished_utc'] = timestamp()
        (output / 'commands.json').write_text(json.dumps(commands, indent=2), encoding='utf-8')
        if proc.returncode:
            print(log.read_text(encoding='mbcs', errors='replace')[-12000:])
            raise RuntimeError(f'{label} failed with {proc.returncode}; see {log}')

    exe = output / 'civ5headless.exe'
    pdb = output / 'civ5headless.pdb'
    metadata = {'status': 'building', 'started_utc': timestamp(), 'plan': plan,
                'git_head': git.stdout.strip(), 'git_dirty_paths': dirty.stdout.splitlines(),
                'wrapper_sha256': sha256(Path(__file__)), 'output': str(output),
                'source_inputs_manifest': str(output / 'source-inputs.json')}
    (output / 'build-result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    try:
        compile_rsp = build / 'compile.rsp'
        write_response(compile_rsp, flags + ['/Fd' + str(build / 'vc90.pdb'), f'/MP{args.jobs}',
                                             '/Fo' + str(objects) + '\\'] + [str(p) for p in sources])
        run('01-compile', [tools['cl'], '@' + str(compile_rsp)])
        for n, source in enumerate(asm_sources):
            run(f'01-assemble-{n}', [tools['ml'], '/nologo', '/c', '/coff', '/Zi', '/Fo' + str(objects / (source.stem + '.obj')), source])
        object_files = [objects / (p.stem + '.obj') for p in sources + asm_sources]
        for path in object_files:
            if not path.is_file():
                raise FileNotFoundError(path)
        manifest = build / 'civ5headless.exe.intermediate.manifest'
        link_rsp = build / 'link.rsp'
        link_args = link_flags + ['/OUT:' + str(exe), '/PDB:' + str(pdb), '/IMPLIB:' + str(build / 'civ5headless.lib'),
                                  '/MANIFESTFILE:' + str(manifest)]
        write_response(link_rsp, link_args + [str(p) for p in object_files + SDK_LIBS] + system_libs)
        run('02-link', [tools['link'], '@' + str(link_rsp)])
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        run('03-embed-manifest', [tools['mt'], '/nologo', '/manifest', manifest, '/outputresource:' + str(exe) + ';1'])
        changed = [name for name, digest in input_hashes.items() if not (ROOT / name).is_file() or sha256(ROOT / name) != digest]
        if changed:
            metadata['changed_inputs'] = changed
            raise RuntimeError('Build inputs changed during compilation: ' + ', '.join(changed[:8]))
        metadata.update({'status': 'success', 'finished_utc': timestamp(), 'elapsed_seconds': time.monotonic() - started,
                         'exe': {'path': str(exe), 'sha256': sha256(exe), 'bytes': exe.stat().st_size},
                         'pdb': {'path': str(pdb), 'sha256': sha256(pdb), 'bytes': pdb.stat().st_size}})
        (ROOT / 'out' / 'latest.txt').write_text(str(output), encoding='utf-8')
        print(json.dumps({k: metadata[k] for k in ('status', 'exe', 'elapsed_seconds')}, indent=2))
        return 0
    except Exception as exc:
        metadata.update({'status': 'failed', 'finished_utc': timestamp(), 'elapsed_seconds': time.monotonic() - started,
                         'error': str(exc)})
        raise
    finally:
        (output / 'build-result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
