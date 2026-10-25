"""Make the portable VC9 toolchain the host is built with, from Microsoft's Windows SDK 7.0 ISO.

  python tools/get_toolchain.py [--iso GRMSDK_EN_DVD.iso | --download-dir DIR] [--out DIR] [--7zip | --no-7zip]

The Windows SDK 7.0 (GRMSDK_EN_DVD.iso, 1.5 GB; the source Vox Populi's CI uses) carries the Visual C++ 2008 SP1
compilers (cl 15.00.30729) and the Windows headers and libraries. Steps, none of which installs anything or needs
administrator rights:
  1. the ISO: --iso, or downloaded from the web archive's copy of Microsoft's link into --download-dir; its size
     and SHA-256 must match;
  2. the three packages from its Setup folder (vc_stdx86, WinSDKBuild, WinSDKWin32Tools: .msi plus .cab files),
     taken out with 7-Zip when it is installed, else with the UDF reader below (the disc is UDF only);
  3. `msiexec /a` (an administrative image: the files are unpacked, nothing is installed or registered) of each
     package into <out>/admin/{vc9,windows,win32tools};
  4. the VC and Windows include folders and the x86 libraries copied to <out>/vc9 and <out>/windows, the layout
     tools/toolchain.py expects;
  5. tools/toolchain.py checks the result (cl must report 15.00.30729); provenance.json records the hashes.

The default --out is toolchain\\ in the repository, which tools/build_host.py and c5h find by themselves. The deepest
unpacked path is about 190 characters below --out, so --out must be short (Windows' 260-character limit).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ISO_URL = ('https://web.archive.org/web/20161230154527id_/http://download.microsoft.com/download/2/E/9/'
           '2E911956-F90F-4BFB-8231-E292A7B6F287/GRMSDK_EN_DVD.iso')
ORIGINAL_URL = 'http://download.microsoft.com/download/2/E/9/2E911956-F90F-4BFB-8231-E292A7B6F287/GRMSDK_EN_DVD.iso'
ISO_BYTES = 1552508928
ISO_SHA256 = '65739FB0874CC17EA6962D8CE7915364C7161FA106ED1BF1C917924C18AC63CA'
# (ISO folder, package, admin image folder)
PACKAGES = [('Setup/vc_stdx86', 'vc_stdx86.msi', 'vc9'),
            ('Setup/WinSDKBuild', 'WinSDKBuild_x86.msi', 'windows'),
            ('Setup/WinSDKWin32Tools', 'WinSDKWin32Tools_x86.msi', 'win32tools')]
VS = 'Program Files/Microsoft Visual Studio 9.0'
SDK = 'Program Files/Microsoft SDKs/Windows/v7.0'
DEEPEST = 190


class ToolchainError(RuntimeError):
    pass


def sha256(path, progress=None):
    h = hashlib.sha256()
    done = 0
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1 << 22), b''):
            h.update(part)
            done += len(part)
            if progress:
                progress(done)
    return h.hexdigest().upper()


def check_iso(iso):
    size = Path(iso).stat().st_size
    if size != ISO_BYTES:
        raise ToolchainError(f'{iso} has {size} bytes, not {ISO_BYTES}: not GRMSDK_EN_DVD.iso, or incomplete')
    digest = sha256(iso)
    if digest != ISO_SHA256:
        raise ToolchainError(f'{iso} has SHA-256 {digest}, not {ISO_SHA256}')
    return digest


def download(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    iso = folder / 'GRMSDK_EN_DVD.iso'
    if iso.is_file() and iso.stat().st_size == ISO_BYTES:
        return iso
    partial = iso.with_suffix('.iso.partial')
    print(f'downloading {ISO_URL}\n  to {iso} ({ISO_BYTES / 2**30:.2f} GiB)', flush=True)
    t, last = time.monotonic(), 0
    with urllib.request.urlopen(ISO_URL, timeout=60) as response, open(partial, 'wb') as out:
        done = 0
        for part in iter(lambda: response.read(1 << 20), b''):
            out.write(part)
            done += len(part)
            if time.monotonic() - last > 10:
                last = time.monotonic()
                print(f'  {done / 2**20:.0f} MiB ({done / max(last - t, 1e-3) / 2**20:.1f} MiB/s)', flush=True)
    partial.replace(iso)
    return iso


# ---- UDF (ECMA-167 / UDF 1.02) reading, enough for a DVD image ----

class UdfImage:
    """Read-only access to the files of a UDF disc image."""

    SECTOR = 2048

    def __init__(self, path):
        self.f = open(path, 'rb')
        try:
            self._volume(path)
        except Exception:
            self.f.close()
            raise

    def _volume(self, path):
        anchor = self.read(256)
        if self.tag(anchor) != 2:
            raise ToolchainError(f'{path}: no UDF anchor at sector 256')
        length, location = struct.unpack_from('<II', anchor, 16)
        self.partition_start = self.block_size = fsd = None
        for i in range(length // self.SECTOR):
            d = self.read(location + i)
            kind = self.tag(d)
            if kind == 5:   # partition descriptor
                self.partition_start = struct.unpack_from('<I', d, 188)[0]
            elif kind == 6:  # logical volume descriptor
                self.block_size = struct.unpack_from('<I', d, 212)[0]
                fsd = struct.unpack_from('<I', d, 252)[0]  # long_ad of the file set descriptor: its block
            elif kind == 8:  # terminating descriptor
                break
        if None in (self.partition_start, self.block_size, fsd) or self.block_size != self.SECTOR:
            raise ToolchainError(f'{path}: unsupported UDF volume')
        fsd_data = self.read(self.partition_start + fsd)
        if self.tag(fsd_data) != 256:
            raise ToolchainError(f'{path}: no UDF file set descriptor')
        self.root = struct.unpack_from('<I', fsd_data, 404)[0]  # root directory ICB (long_ad block)

    def close(self):
        self.f.close()

    @staticmethod
    def tag(data):
        return struct.unpack_from('<H', data, 0)[0] if len(data) >= 16 else None

    def read(self, sector, count=1):
        self.f.seek(sector * self.SECTOR)
        return self.f.read(count * self.SECTOR)

    def entry(self, block):
        """(is_dir, size, extents [(sector, length)]) of the file entry at a partition block."""
        d = self.read(self.partition_start + block)
        kind = self.tag(d)
        if kind == 261:    # file entry
            size, l_ea, l_ad, base = struct.unpack_from('<Q', d, 56)[0], *struct.unpack_from('<II', d, 168), 176
        elif kind == 266:  # extended file entry
            size, l_ea, l_ad, base = struct.unpack_from('<Q', d, 56)[0], *struct.unpack_from('<II', d, 208), 216
        else:
            raise ToolchainError(f'unexpected UDF descriptor {kind} at block {block}')
        file_type, flags = d[27], struct.unpack_from('<H', d, 34)[0]
        ads = d[base + l_ea:base + l_ea + l_ad]
        kind_ad = flags & 7
        extents = []
        if kind_ad == 3:   # data embedded in the entry
            return file_type == 4, size, [('embedded', ads[:size])]
        step = 8 if kind_ad == 0 else 16
        if kind_ad not in (0, 1):
            raise ToolchainError(f'unsupported UDF allocation descriptors ({kind_ad})')
        for off in range(0, len(ads) - step + 1, step):
            length, position = struct.unpack_from('<II', ads, off)
            if length >> 30 == 3:
                raise ToolchainError('UDF allocation descriptor continuation is not supported')
            if length & 0x3FFFFFFF:
                extents.append((self.partition_start + position, length & 0x3FFFFFFF))
        return file_type == 4, size, extents

    def data(self, extents, size):
        out = bytearray()
        for sector, length in extents:
            if sector == 'embedded':
                out += length
                continue
            self.f.seek(sector * self.SECTOR)
            out += self.f.read(length)
        return bytes(out[:size])

    def listdir(self, block):
        """{name: block} of a directory's entries (no parent, no deleted)."""
        is_dir, size, extents = self.entry(block)
        if not is_dir:
            raise ToolchainError('not a directory')
        data = self.data(extents, size)
        out, i = {}, 0
        while i + 38 <= len(data):
            if self.tag(data[i:]) != 257:
                raise ToolchainError('bad UDF file identifier descriptor')
            chars, l_fi = data[i + 18], data[i + 19]
            icb = struct.unpack_from('<I', data, i + 24)[0]
            l_iu = struct.unpack_from('<H', data, i + 36)[0]
            raw = data[i + 38 + l_iu:i + 38 + l_iu + l_fi]
            if not chars & 0x0C and raw:  # not deleted, not the parent
                name = raw[1:].decode('utf-16-be') if raw[0] == 16 else raw[1:].decode('latin-1')
                out[name] = icb
            i += (38 + l_iu + l_fi + 3) & ~3
        return out

    def resolve(self, path):
        block = self.root
        for part in [p for p in path.replace('\\', '/').split('/') if p]:
            names = {k.lower(): v for k, v in self.listdir(block).items()}
            if part.lower() not in names:
                raise ToolchainError(f'{path} not found on the disc')
            block = names[part.lower()]
        return block

    def extract_dir(self, path, dest):
        """Copy the files of one disc folder (not recursive) into dest; returns their names."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for name, block in sorted(self.listdir(self.resolve(path)).items()):
            is_dir, size, extents = self.entry(block)
            if is_dir:
                continue
            with open(dest / name, 'wb') as f:
                left = size
                for sector, length in extents:
                    if sector == 'embedded':
                        f.write(length[:left])
                        left = 0
                        continue
                    self.f.seek(sector * self.SECTOR)
                    take = min(length, left)
                    while take > 0:
                        chunk = self.f.read(min(take, 1 << 22))
                        f.write(chunk)
                        take -= len(chunk)
                        left -= len(chunk)
            out.append(name)
        return out


def seven_zip():
    for candidate in [shutil.which('7z'), shutil.which('7za')] + [
            Path(os.environ[v]) / '7-Zip/7z.exe' for v in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)') if os.environ.get(v)]:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def extract_packages(iso, dest, use_7zip=None):
    """The Setup folders of PACKAGES from the ISO into dest; returns the method used."""
    exe = seven_zip() if use_7zip is not False else None
    if use_7zip and exe is None:
        raise ToolchainError('7-Zip is not installed')
    if exe:
        members = [f'{folder}/*' for folder, _, _ in PACKAGES]
        r = subprocess.run([str(exe), 'x', '-y', f'-o{dest}', str(iso)] + members, capture_output=True, text=True,
                           errors='replace')
        if r.returncode:
            raise ToolchainError(f'7-Zip failed ({r.returncode}): {r.stdout[-800:]} {r.stderr[-800:]}')
        return f'7-Zip ({exe})'
    image = UdfImage(iso)
    try:
        for folder, _, _ in PACKAGES:
            image.extract_dir(folder, Path(dest) / folder)
    finally:
        image.close()
    return 'built-in UDF reader'


def admin_extract(msi, target, log):
    """msiexec /a: unpack an .msi (and its cabinets) into target without installing it."""
    target.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(['msiexec', '/a', str(msi), '/qn', f'TARGETDIR={target}', '/L*v', str(log)],
                       capture_output=True, text=True, errors='replace')
    if r.returncode:
        raise ToolchainError(f'msiexec /a {msi.name} failed with {r.returncode}; see {log}')


def copy_tree(src, dest, files_only=False):
    """dest gets src's files (files_only: only those directly in src, e.g. the x86 libraries)."""
    dest.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file():
            shutil.copy2(p, dest / p.name)
        elif not files_only:
            shutil.copytree(p, dest / p.name, dirs_exist_ok=True)


def build(out, iso=None, download_dir=None, use_7zip=None, keep=False, log=print):
    out = Path(out).resolve()
    if len(str(out)) + DEEPEST > 259:
        raise ToolchainError(f'{out} is too long: the unpacked files go about {DEEPEST} characters deeper than the '
                             '260-character limit allows; use a shorter --out')
    if out.exists() and any(out.iterdir()):
        raise ToolchainError(f'{out} is not empty')
    t0 = time.monotonic()
    iso = Path(iso) if iso else download(download_dir or tempfile.gettempdir())
    log(f'checking {iso}')
    digest = check_iso(iso)
    out.mkdir(parents=True, exist_ok=True)
    work = out / 'packages'
    log('taking the packages out of the ISO')
    method = extract_packages(iso, work, use_7zip)
    log(f'  with {method}')
    packages = []
    for folder, msi, name in PACKAGES:
        path = work / folder / msi
        log(f'msiexec /a {msi}')
        admin_extract(path, out / 'admin' / name, out / 'admin' / f'{name}-extract.log')
        packages.append(dict(path=f'packages/{folder}/{msi}', sha256=sha256(path)))
    log('copying the include folders and x86 libraries')
    copy_tree(out / 'admin/vc9' / VS / 'Vc7/include', out / 'vc9/include')
    copy_tree(out / 'admin/vc9' / VS / 'Vc7/lib', out / 'vc9/lib', files_only=True)
    copy_tree(out / 'admin/windows' / SDK / 'Include', out / 'windows/Include')
    copy_tree(out / 'admin/windows' / SDK / 'Lib', out / 'windows/Lib', files_only=True)
    if not keep:
        shutil.rmtree(work)
    sys.path.insert(0, str(ROOT / 'tools'))
    import toolchain
    _, _, info = toolchain.find(out)
    provenance = dict(source='Windows SDK 7.0 (Microsoft; the ISO Vox Populi\'s CI uses)', download_url=ISO_URL,
                      original_url=ORIGINAL_URL, iso_bytes=ISO_BYTES, iso_sha256=digest, extraction=method + '; msiexec /a '
                      '/qn TARGETDIR (administrative image, nothing installed); include folders and root x86 libraries '
                      'copied to vc9/ and windows/', packages=packages, compiler=info['compiler'].splitlines(),
                      seconds=round(time.monotonic() - t0, 1))
    (out / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    log(f'toolchain ready in {out} ({provenance["seconds"]} s)')
    return out, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, help='GRMSDK_EN_DVD.iso already on disk (no download)')
    ap.add_argument('--download-dir', type=Path, help='where to download the ISO (default: the temp folder); kept')
    ap.add_argument('--out', type=Path, default=ROOT / 'toolchain', help='toolchain folder (default: toolchain\\ in the repository)')
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--7zip', dest='use_7zip', action='store_const', const=True, help='use 7-Zip (it must be installed)')
    group.add_argument('--no-7zip', dest='use_7zip', action='store_const', const=False, help='use the built-in UDF reader')
    ap.add_argument('--keep-packages', action='store_true', help='keep the .msi/.cab files in <out>/packages')
    a = ap.parse_args(argv)
    try:
        build(a.out, a.iso, a.download_dir, a.use_7zip, a.keep_packages)
    except (ToolchainError, RuntimeError, OSError) as error:
        print(f'get_toolchain: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
