#!/usr/bin/env python3
"""Build the headless autoplay host civ5headless.exe with the native VC9 toolchain.

  python work/build-headless.py [--config release|debug] [--jobs N] [--check]

Uses the same compiler, CRT (/MD: MSVCR90/MSVCP90), STL settings and include paths as the
game DLL build (work/build-vp-msvc.py), because std::string, std::vector, CvString and
FireWorks objects cross the engine interfaces. Sources are every .cpp below Civ5Headless/;
the 22 FireWorks exports come from Civ5Headless/civ5headless.def.

Output: work/headless-output/<Config>/<timestamp>/ with civ5headless.exe, .pdb, logs/ and
build-result.json (status, inputs with hashes, outputs with hashes). Intermediates go to
work/headless-build/<Config>/<timestamp>/. Nothing outside work/ is written.
"""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
HOST = ROOT / 'Civ5Headless'
DEF_FILE = HOST / 'civ5headless.def'


def load_dll_build():
    spec = importlib.util.spec_from_file_location('build_vp_msvc', WORK / 'build-vp-msvc.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', choices=['release', 'debug'], default='release')
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--check', action='store_true', help='Print the resolved build plan; compile nothing')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    bv = load_dll_build()
    config = args.config.title()
    dll_spec = bv.parse_project('Release')
    tools, env = bv.tools_and_environment()

    sources = sorted(p for p in HOST.rglob('*.cpp'))
    asm_sources = sorted(p for p in HOST.rglob('*.asm'))
    headers = sorted(p for p in HOST.rglob('*') if p.suffix.lower() in {'.h', '.inl'})
    if not sources:
        raise RuntimeError('No sources below ' + str(HOST))
    if len({p.stem.lower() for p in sources + asm_sources}) != len(sources) + len(asm_sources):
        raise RuntimeError('Duplicate source basenames')
    if not DEF_FILE.is_file():
        raise FileNotFoundError(DEF_FILE)

    # Same include set as the DLL, plus the host tree.
    includes = [HOST] + list(dll_spec['include_dirs'])
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

    wanted_libs = {'cvgamedatabasewin32.lib', 'cvlocalizationwin32.lib', 'lua51_win32.lib'}
    libraries = [p for p in dll_spec['libraries'] if p.name.lower() in wanted_libs]
    if len(libraries) != len(wanted_libs):
        raise RuntimeError('Missing Firaxis import libraries: ' + ', '.join(str(p) for p in libraries))
    system_libs = ['kernel32.lib', 'user32.lib', 'advapi32.lib', 'shell32.lib', 'winmm.lib', 'psapi.lib', 'delayimp.lib']
    # The Firaxis DLLs live in the game folder, which the host only learns from its command
    # line: delay-load them, so the driver can load them from there before first use.
    delay_loaded = ['CvGameDatabaseWin32Final Release.dll', 'CvLocalizationWin32Final Release.dll', 'lua51_Win32.dll']
    link_flags = ['/NOLOGO', '/MACHINE:X86', '/DEBUG', '/SUBSYSTEM:CONSOLE', '/LARGEADDRESSAWARE',
                  '/DYNAMICBASE', '/NXCOMPAT', '/MANIFEST', '/INCREMENTAL:NO', '/OPT:REF', '/OPT:ICF',
                  '/DEF:' + str(DEF_FILE)] + ['/DELAYLOAD:' + name for name in delay_loaded]

    banner = subprocess.run([str(tools['cl'])], env=env, capture_output=True, text=True, errors='replace')
    compiler_banner = (banner.stdout + banner.stderr).strip()
    if '15.00.30729' not in compiler_banner:
        raise RuntimeError('Compiler is not the expected MSVC 2008 SP1: ' + compiler_banner)
    plan = {'config': config, 'compiler': compiler_banner, 'sources': [str(p) for p in sources + asm_sources],
            'compile_flags': flags, 'link_flags': link_flags,
            'libraries': [str(p) for p in libraries] + system_libs, 'jobs': args.jobs}
    if args.check:
        print(json.dumps(plan, indent=2))
        return 0

    run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    build = WORK / 'headless-build' / config / run_id
    output = WORK / 'headless-output' / config / run_id
    for p in (build, output):
        if p.exists():
            raise RuntimeError('Output run directory already exists: ' + str(p))
        p.mkdir(parents=True)
    logs = output / 'logs'
    logs.mkdir()
    objects = build / 'obj'
    objects.mkdir()

    inputs = set(sources + asm_sources + headers + [DEF_FILE, Path(__file__).resolve(), WORK / 'build-vp-msvc.py'] + libraries)
    for directory in dll_spec['include_dirs']:
        inputs.update(p for p in directory.rglob('*') if p.is_file() and p.suffix.lower() in {'.h', '.hpp', '.inl', '.inc'})
    input_hashes = {str(p.resolve()): bv.sha256(p) for p in sorted(inputs, key=str)}
    (output / 'source-inputs.json').write_text(json.dumps(input_hashes, indent=2), encoding='utf-8')
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain', '--', 'Civ5Headless', 'work/build-headless.py'],
                           cwd=ROOT, capture_output=True, text=True)

    commands = []
    started = time.monotonic()

    def run(label, command):
        log = logs / (label + '.log')
        event = {'label': label, 'command': [str(a) for a in command], 'started_utc': bv.timestamp(), 'log': str(log)}
        commands.append(event)
        print(f'{label}: {log}', flush=True)
        with log.open('wb') as stream:
            proc = subprocess.run([str(a) for a in command], cwd=HOST, env=env, stdout=stream, stderr=subprocess.STDOUT)
        event['returncode'] = proc.returncode
        event['finished_utc'] = bv.timestamp()
        (output / 'commands.json').write_text(json.dumps(commands, indent=2), encoding='utf-8')
        if proc.returncode:
            print(log.read_text(encoding='mbcs', errors='replace')[-12000:])
            raise RuntimeError(f'{label} failed with {proc.returncode}; see {log}')

    exe = output / 'civ5headless.exe'
    pdb = output / 'civ5headless.pdb'
    metadata = {'status': 'building', 'started_utc': bv.timestamp(), 'plan': plan,
                'git_head': git.stdout.strip(), 'git_dirty_paths': dirty.stdout.splitlines(),
                'wrapper_sha256': bv.sha256(Path(__file__)), 'output': str(output),
                'source_inputs_manifest': str(output / 'source-inputs.json')}
    (output / 'build-result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    try:
        compile_rsp = build / 'compile.rsp'
        bv.write_response(compile_rsp, flags + ['/Fd' + str(build / 'vc90.pdb'), f'/MP{args.jobs}',
                                                '/Fo' + str(objects) + '\\'] + [str(p) for p in sources])
        run('01-compile', [tools['cl'], '@' + str(compile_rsp)])
        ml = Path(tools['cl']).with_name('ml.exe')
        for n, source in enumerate(asm_sources):
            run(f'01-assemble-{n}', [ml, '/nologo', '/c', '/coff', '/Zi', '/Fo' + str(objects / (source.stem + '.obj')), source])
        object_files = [objects / (p.stem + '.obj') for p in sources + asm_sources]
        for path in object_files:
            if not path.is_file():
                raise FileNotFoundError(path)
        manifest = build / 'civ5headless.exe.intermediate.manifest'
        link_rsp = build / 'link.rsp'
        link_args = link_flags + ['/OUT:' + str(exe), '/PDB:' + str(pdb), '/IMPLIB:' + str(build / 'civ5headless.lib'),
                                  '/MANIFESTFILE:' + str(manifest)]
        bv.write_response(link_rsp, link_args + [str(p) for p in object_files + libraries] + system_libs)
        run('02-link', [tools['link'], '@' + str(link_rsp)])
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        run('03-embed-manifest', [tools['mt'], '/nologo', '/manifest', manifest, '/outputresource:' + str(exe) + ';1'])
        changed = [name for name, digest in input_hashes.items() if not Path(name).is_file() or bv.sha256(Path(name)) != digest]
        if changed:
            metadata['changed_inputs'] = changed
            raise RuntimeError('Build inputs changed during compilation: ' + ', '.join(changed[:8]))
        metadata.update({'status': 'success', 'finished_utc': bv.timestamp(), 'elapsed_seconds': time.monotonic() - started,
                         'exe': {'path': str(exe), 'sha256': bv.sha256(exe), 'bytes': exe.stat().st_size},
                         'pdb': {'path': str(pdb), 'sha256': bv.sha256(pdb), 'bytes': pdb.stat().st_size}})
        (WORK / 'latest-headless-build-path.txt').write_text(str(output), encoding='utf-8')
        print(json.dumps({k: metadata[k] for k in ('status', 'exe', 'elapsed_seconds')}, indent=2))
        return 0
    except Exception as exc:
        metadata.update({'status': 'failed', 'finished_utc': bv.timestamp(), 'elapsed_seconds': time.monotonic() - started,
                         'error': str(exc)})
        raise
    finally:
        (output / 'build-result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
