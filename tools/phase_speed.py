"""Seconds per turn by game phase for vpbench run folders (real or headless) and boundary traces.

  python work/headless/phase_speed.py RUN_OR_TRACE [...] [--bucket 25] [--label NAME=PATH ...] [--json OUT]

- A run folder is read through turn-seen.json (vpbench: 5-second polls; headless: exact turn changes).
- A HeadlessTrace-*.log (trace DLL, real game) is read through its PublishNewGameTurn rows (exact).
Prints one column per input: mean seconds per turn in each bucket of turns, and the total.
"""
from pathlib import Path
import argparse, json


def from_run(path):
    seen = json.loads((Path(path) / 'turn-seen.json').read_text(encoding='utf-8'))
    return {int(k): float(v) for k, v in seen.items()}


def from_trace(path):
    out = {}
    with open(path, 'rb') as f:
        for line in f:
            if b'|OUT|ICvEngineUtility1::PublishNewGameTurn|' not in line:
                continue
            parts = line.decode('ascii', 'replace').split('|')
            out[int(parts[6])] = int(parts[1]) / 1e6
    return out


def load(path):
    p = Path(path)
    return from_run(p) if p.is_dir() else from_trace(p)


def buckets(seen, size):
    turns = sorted(seen)
    rows = {}
    lo = (turns[0] // size) * size
    while lo < turns[-1]:
        hi = lo + size
        a = max([t for t in turns if t <= lo] or [turns[0]])
        b = max([t for t in turns if t <= hi])
        if b > a:
            rows[f'T{lo}-{hi}'] = round((seen[b] - seen[a]) / (b - a), 3)
        lo = hi
    rows['total'] = round((seen[turns[-1]] - seen[turns[0]]) / (turns[-1] - turns[0]), 3)
    rows['turns'] = f'{turns[0]}-{turns[-1]}'
    return rows


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('inputs', nargs='*')
    a.add_argument('--label', action='append', default=[], help='NAME=PATH (a named input)')
    a.add_argument('--bucket', type=int, default=25)
    a.add_argument('--json')
    args = a.parse_args()
    named = [(Path(p).name if Path(p).is_dir() else Path(p).parent.name, p) for p in args.inputs]
    named += [tuple(x.split('=', 1)) for x in args.label]
    cols = {name: buckets(load(path), args.bucket) for name, path in named}
    keys = []
    for c in cols.values():
        keys += [k for k in c if k not in keys]
    keys.sort(key=lambda k: (k in ('total', 'turns'), int(k[1:].split('-')[0]) if k.startswith('T') else 0))
    print('s/turn | ' + ' | '.join(cols))
    for k in keys:
        print(k + ' | ' + ' | '.join(str(c.get(k, '')) for c in cols.values()))
    if args.json:
        Path(args.json).write_text(json.dumps(cols, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
