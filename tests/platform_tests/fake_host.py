"""A stand-in for civ5headless.exe newgame and loadgame (run through fake_host.cmd): records its arguments in argv.json
and writes the outputs run.py reads, for --turns turns (after the --load save's turn): turn-times.jsonl,
newgame-report.json, host-report.json, lua-before-arm.json, lua-before-dump.json, checkpoints/turn-NNNN-final.json and
Logs/HeadlessDigest.log; unless --no-save-final a Final save (a copy of the loaded one, or a few bytes) and its
record."""
import json
from pathlib import Path
import shutil
import struct
import sys


def save_turn(path):
    """The turn in a .Civ5Save's header: after CIV5, the save version and two strings."""
    data, pos = Path(path).read_bytes(), 8
    for _ in range(2):
        pos += 4 + struct.unpack_from('<I', data, pos)[0]
    return struct.unpack_from('<I', data, pos)[0]


def main(argv):
    opts, i = {}, 1
    while i < len(argv):
        if argv[i].startswith('--') and i + 1 < len(argv) and not argv[i + 1].startswith('--'):
            opts.setdefault(argv[i], []).append(argv[i + 1])
            i += 2
        else:
            i += 1
    out = Path(opts['--out'][0])
    start = save_turn(opts['--load'][0]) if '--load' in opts else 0
    turns = start + int(opts['--turns'][0])  # the last turn
    (out / 'argv.json').write_text(json.dumps(argv), encoding='utf-8')
    with open(out / 'turn-times.jsonl', 'w', encoding='utf-8') as f:
        for t in range(start + 1, turns + 1):
            f.write(json.dumps(dict(turn=t, seconds=(t - start) * 0.25)) + '\n')
    saves = []
    if '--no-save-final' not in argv:
        folder = out / 'saves'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'Final_{turns:04d}.Civ5Save'
        shutil.copyfile(opts['--load'][0], path) if '--load' in opts else path.write_bytes(b'CIV5')
        saves.append(dict(kind='final', turn=turns, path=str(path), bytes=path.stat().st_size, error=''))
    (out / 'Logs').mkdir(exist_ok=True)
    (out / 'Logs/HeadlessDigest.log').write_text(
        ''.join(f'HHDIGEST|turn={t}|point=doTurnBegin|total={t:016x}|game={t:016x}\n' for t in range(turns)), encoding='utf-8')
    (out / 'checkpoints').mkdir(exist_ok=True)
    (out / f'checkpoints/turn-{turns:04d}-final.json').write_text(json.dumps(dict(data=dict(turn=turns))), encoding='utf-8')
    (out / 'lua-before-arm.json').write_text(json.dumps(dict(setup=dict(turn=0), improvedMask=-2, diagnosticsLevel=-1)), encoding='utf-8')
    (out / 'lua-before-dump.json').write_text(json.dumps(dict(victory=dict(winner=-1), messages=[], replayData={})), encoding='utf-8')
    load = dict(path=opts['--load'][0], turn=start, warnings=[]) if '--load' in opts else None
    (out / 'newgame-report.json').write_text(json.dumps(dict(status='passed', newgame=dict(autoplay=dict(updates=turns), load=load,
                                                                                         saves=saves))), encoding='utf-8')
    (out / 'host-report.json').write_text(json.dumps({'format': 'civ5headless-host-report/1', 'status': 'passed',
                                                     'command': argv}), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
