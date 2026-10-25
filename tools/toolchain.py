"""Locate the MSVC 2008 SP1 (VC9) x86 toolchain the host must be built with.

The host shares C++ objects (std::string, std::vector, CvString, FireWorks types) with the game DLL across the
engine interfaces, so it has to use the DLL's compiler and CRT: cl 15.00.30729 and MSVCR90/MSVCP90 (/MD).

Search order, first match wins:
  1. --toolchain DIR on the command line;
  2. the C5H_TOOLCHAIN environment variable;
  3. a portable toolchain in <repo>/toolchain (tools/get_toolchain.py extracts one from Microsoft's Windows SDK 7.0
     ISO, the same source Vox Populi's CI uses);
  4. an installed Visual Studio 2008 plus a Windows SDK (v7.0, v6.0A), found through the registry.

A toolchain folder may use either layout:
  - portable: admin/vc9/Program Files/Microsoft Visual Studio 9.0/{Vc7/bin,Common7/IDE},
    admin/win32tools/Program Files/Microsoft SDKs/Windows/v7.0/Bin, vc9/{include,lib}, windows/{Include,Lib};
  - installed: a Visual Studio 9.0 folder with VC/bin, VC/include, VC/lib and Common7/IDE (the Windows SDK is then
    looked up in the registry).
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = '15.00.30729'
SDK_VERSIONS = ('v7.0', 'v7.0A', 'v6.0A', 'v6.1')


def _first(candidates, filename):
    for directory in candidates:
        if directory and (Path(directory) / filename).is_file():
            return Path(directory)
    return None


def _registry_value(key_path, name):
    try:
        import winreg
    except ImportError:
        return None
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ | view) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            continue
    return None


def _windows_sdk_dirs():
    for version in SDK_VERSIONS:
        folder = _registry_value('SOFTWARE\\Microsoft\\Microsoft SDKs\\Windows\\' + version, 'InstallationFolder')
        if folder:
            yield Path(folder)


def _layout(root):
    """The seven toolchain folders under ROOT, or None for any that is missing."""
    root = Path(root)
    vs = root / 'admin/vc9/Program Files/Microsoft Visual Studio 9.0'
    sdks = list(_windows_sdk_dirs())
    dirs = {
        'cl': _first([vs / 'Vc7/bin', vs / 'VC/bin', root / 'VC/bin', root / 'Vc7/bin', root / 'bin'], 'cl.exe'),
        'ide': _first([vs / 'Common7/IDE', root / 'Common7/IDE', root / 'VC/bin', root / 'bin'], 'mspdb80.dll'),
        'sdk_bin': _first([root / 'admin/win32tools/Program Files/Microsoft SDKs/Windows/v7.0/Bin', root / 'sdk/Bin']
                          + [s / 'Bin' for s in sdks], 'mt.exe'),
        'vc_include': _first([root / 'vc9/include', root / 'VC/include', root / 'include'], 'stdio.h'),
        'vc_lib': _first([root / 'vc9/lib', root / 'VC/lib', root / 'lib'], 'msvcrt.lib'),
        'sdk_include': _first([root / 'windows/Include', root / 'sdk/Include'] + [s / 'Include' for s in sdks], 'windows.h'),
        'sdk_lib': _first([root / 'windows/Lib', root / 'sdk/Lib'] + [s / 'Lib' for s in sdks], 'kernel32.lib'),
    }
    return dirs


def candidates(explicit=None):
    """(label, folder) pairs in search order."""
    out = []
    if explicit:
        out.append(('--toolchain', Path(explicit)))
    if os.environ.get('C5H_TOOLCHAIN'):
        out.append(('C5H_TOOLCHAIN', Path(os.environ['C5H_TOOLCHAIN'])))
    out.append(('repository toolchain/', ROOT / 'toolchain'))
    vc = _registry_value(r'SOFTWARE\Microsoft\VisualStudio\9.0\Setup\VC', 'ProductDir')
    if vc:
        out.append(('Visual Studio 2008 (registry)', Path(vc).parent))
    return out


def find(explicit=None):
    """Return (tools, env, info) for the first complete toolchain; raise with what was tried."""
    tried = []
    for label, root in candidates(explicit):
        if not root.is_dir():
            tried.append(f'{label}: {root} (not a folder)')
            continue
        dirs = _layout(root)
        missing = [k for k, v in dirs.items() if v is None]
        if missing:
            tried.append(f'{label}: {root} (missing {", ".join(missing)})')
            if label in ('--toolchain', 'C5H_TOOLCHAIN'):
                break  # an explicit choice that is incomplete is an error, not a reason to look elsewhere
            continue
        tools = {'cl': dirs['cl'] / 'cl.exe', 'link': dirs['cl'] / 'link.exe', 'ml': dirs['cl'] / 'ml.exe',
                 'mt': dirs['sdk_bin'] / 'mt.exe'}
        env = os.environ.copy()
        env['PATH'] = ';'.join([str(dirs['cl']), str(dirs['ide']), str(dirs['sdk_bin']), env.get('PATH', '')])
        env['INCLUDE'] = ';'.join([str(dirs['vc_include']), str(dirs['sdk_include'])])
        env['LIB'] = ';'.join([str(dirs['vc_lib']), str(dirs['sdk_lib'])])
        # Inherited global compiler flags could change the target or the runtime.
        for name in ('CL', '_CL_', 'LINK', '_LINK_'):
            env.pop(name, None)
        banner = subprocess.run([str(tools['cl'])], env=env, capture_output=True, text=True, errors='replace')
        compiler = (banner.stdout + banner.stderr).strip()
        if EXPECTED_VERSION not in compiler:
            tried.append(f'{label}: {root} (cl is not MSVC 2008 SP1 {EXPECTED_VERSION}: {compiler.splitlines()[:2]})')
            continue
        info = {'source': label, 'root': str(root), 'dirs': {k: str(v) for k, v in dirs.items()},
                'compiler': compiler}
        return tools, env, info
    raise RuntimeError('No MSVC 2008 SP1 x86 toolchain found. Tried:\n  ' + '\n  '.join(tried)
                       + '\nRun python tools/get_toolchain.py, or pass --toolchain / set C5H_TOOLCHAIN.')


if __name__ == '__main__':
    import json
    import sys
    _, _, found = find(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(found, indent=2))
