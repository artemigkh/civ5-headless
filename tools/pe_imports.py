"""List the imports of a 32-bit PE file, or compare two.

  python tools/headless/pe_imports.py A.dll           # list
  python tools/headless/pe_imports.py BASE.dll NEW.dll  # what NEW adds or drops

Used to check that a trace build of the game DLL imports nothing unexpected.
"""
import struct
import sys
from pathlib import Path


def read_imports(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError(f'{path}: not a PE file')
    nsections = struct.unpack_from('<H', data, pe + 6)[0]
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from('<H', data, opt)[0] != 0x10B:
        raise ValueError(f'{path}: not PE32')
    import_rva = struct.unpack_from('<I', data, opt + 96 + 8)[0]
    sections = []
    for i in range(nsections):
        s = opt + opt_size + 40 * i
        vsize, va, rawsize, rawptr = struct.unpack_from('<IIII', data, s + 8)
        sections.append((va, max(vsize, rawsize), rawptr))

    def off(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError(f'rva {rva:#x} outside sections')

    def cstr(o):
        return data[o:data.index(b'\0', o)].decode('ascii', 'replace')

    result = {}
    d = off(import_rva)
    while True:
        ilt, _, _, name_rva, iat = struct.unpack_from('<IIIII', data, d)
        if name_rva == 0:
            break
        names = []
        t = off(ilt or iat)
        while True:
            entry = struct.unpack_from('<I', data, t)[0]
            if entry == 0:
                break
            names.append(f'#{entry & 0xFFFF}' if entry & 0x80000000 else cstr(off(entry) + 2))
            t += 4
        result[cstr(off(name_rva))] = names
        d += 20
    return result


def main(argv):
    if len(argv) == 2:
        for dll, names in read_imports(argv[1]).items():
            print(f'{dll} ({len(names)})')
            for n in names:
                print('   ', n)
        return 0
    if len(argv) != 3:
        print(__doc__)
        return 2
    base, new = read_imports(argv[1]), read_imports(argv[2])
    changed = False
    for dll in sorted(set(base) | set(new), key=str.lower):
        a, b = set(base.get(dll, [])), set(new.get(dll, []))
        if dll not in base:
            print(f'+ module {dll}')
        if dll not in new:
            print(f'- module {dll}')
        for n in sorted(b - a):
            print(f'+ {dll}!{n}')
        for n in sorted(a - b):
            print(f'- {dll}!{n}')
        changed |= a != b or (dll in base) != (dll in new)
    if not changed:
        print('imports identical')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
