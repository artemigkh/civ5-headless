#!/usr/bin/env python3
"""Helpers for the DLL's headless-host state digest (docs/headless-dll-additions.md).

  hhdigest.py verify DUMP_FOLDER        recompute section hashes of a Game.DumpHeadlessState folder
  hhdigest.py compare LOG_A LOG_B       first turn/section where two HeadlessDigest.log files differ
  hhdigest.py hash FILE...              xxHash64 (seed 0) of files

The hash is xxHash64 with seed 0; the total is xxHash64 over, for each section in the total,
its name, a NUL byte and its 8-byte little-endian hash.
"""
import struct
import sys
from pathlib import Path

P1 = 11400714785074694791
P2 = 14029467366897019727
P3 = 1609587929392839161
P4 = 9650029242287828579
P5 = 2870177450012600261
M = (1 << 64) - 1


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & M


def _round(acc, lane):
    acc = (acc + lane * P2) & M
    return (_rotl(acc, 31) * P1) & M


def _merge(acc, val):
    acc ^= _round(0, val)
    return (acc * P1 + P4) & M


def xxh64(data: bytes, seed: int = 0) -> int:
    n = len(data)
    p = 0
    if n >= 32:
        v1 = (seed + P1 + P2) & M
        v2 = (seed + P2) & M
        v3 = seed & M
        v4 = (seed - P1) & M
        while p + 32 <= n:
            a, b, c, d = struct.unpack_from('<4Q', data, p)
            v1, v2, v3, v4 = _round(v1, a), _round(v2, b), _round(v3, c), _round(v4, d)
            p += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & M
        for v in (v1, v2, v3, v4):
            h = _merge(h, v)
    else:
        h = (seed + P5) & M
    h = (h + n) & M
    while p + 8 <= n:
        h ^= _round(0, struct.unpack_from('<Q', data, p)[0])
        h = (_rotl(h, 27) * P1 + P4) & M
        p += 8
    if p + 4 <= n:
        h ^= (struct.unpack_from('<I', data, p)[0] * P1) & M
        h = (_rotl(h, 23) * P2 + P3) & M
        p += 4
    while p < n:
        h ^= (data[p] * P5) & M
        h = (_rotl(h, 11) * P1) & M
        p += 1
    h ^= h >> 33
    h = (h * P2) & M
    h ^= h >> 29
    h = (h * P3) & M
    h ^= h >> 32
    return h


def parse_line(line):
    parts = line.rstrip('\n').split('|')
    fields = {}
    order = []
    for part in parts[1:]:
        if '=' in part:
            k, v = part.split('=', 1)
            fields[k] = v
            order.append(k)
    return parts[0], fields, order


META = {'turn', 'point', 'total'}
EXCLUDED = {'savedb'}


def total_of(fields, order):
    buf = b''
    for name in order:
        if name in META or name in EXCLUDED:
            continue
        buf += name.encode() + b'\0' + struct.pack('<Q', int(fields[name], 16))
    return xxh64(buf)


def cmd_verify(folder):
    folder = Path(folder)
    kind, fields, order = parse_line((folder / 'digest.txt').read_text().splitlines()[0])
    bad = 0
    for name in order:
        if name in META:
            continue
        got = '%016x' % xxh64((folder / (name + '.bin')).read_bytes())
        if got != fields[name]:
            print(f'{name}: file {got} != logged {fields[name]}')
            bad += 1
    total = '%016x' % total_of(fields, order)
    if total != fields['total']:
        print(f'total: recomputed {total} != logged {fields["total"]}')
        bad += 1
    print('ok' if not bad else f'{bad} mismatches')
    return 1 if bad else 0


def digest_lines(path):
    out = {}
    for line in Path(path).read_text(errors='replace').splitlines():
        if line.startswith('HHDIGEST|'):
            _, fields, order = parse_line(line)
            out[(fields.get('point'), int(fields['turn']))] = (fields, order)
    return out


def cmd_compare(a, b):
    da, db = digest_lines(a), digest_lines(b)
    keys = sorted(set(da) & set(db), key=lambda k: (k[1], k[0] or ''))
    for key in keys:
        fa, oa = da[key]
        fb, ob = db[key]
        if fa['total'] != fb['total'] or any(fa.get(n) != fb.get(n) for n in set(oa) | set(ob) if n not in META):
            diff = [n for n in oa if n not in META and fa.get(n) != fb.get(n)]
            diff += [n for n in ob if n not in META and n not in fa]
            print(f'first difference: turn {key[1]} point {key[0]}: sections {", ".join(diff)}')
            return 1
    print(f'identical on {len(keys)} common digest points'
          f' (only in A: {len(set(da) - set(db))}, only in B: {len(set(db) - set(da))})')
    return 0


def main(argv):
    if len(argv) >= 2 and argv[0] == 'verify':
        return cmd_verify(argv[1])
    if len(argv) >= 3 and argv[0] == 'compare':
        return cmd_compare(argv[1], argv[2])
    if len(argv) >= 2 and argv[0] == 'hash':
        for name in argv[1:]:
            print('%016x  %s' % (xxh64(Path(name).read_bytes()), name))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
