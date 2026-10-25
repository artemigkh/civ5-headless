"""A stand-in for civ5headless.exe newgame (run through fake_host.cmd): records its arguments in argv.json and writes
the outputs run.py reads, for --turns turns: turn-times.jsonl, newgame-report.json, lua-before-arm.json,
lua-before-dump.json, checkpoints/turn-NNNN-final.json and Logs/HeadlessDigest.log."""
import json
from pathlib import Path
import sys


def main(argv):
    opts, i = {}, 1
    while i < len(argv):
        if argv[i].startswith('--') and i + 1 < len(argv):
            opts.setdefault(argv[i], []).append(argv[i + 1])
            i += 2
        else:
            i += 1
    out = Path(opts['--out'][0])
    turns = int(opts['--turns'][0])
    (out / 'argv.json').write_text(json.dumps(argv), encoding='utf-8')
    with open(out / 'turn-times.jsonl', 'w', encoding='utf-8') as f:
        for t in range(1, turns + 1):
            f.write(json.dumps(dict(turn=t, seconds=t * 0.25)) + '\n')
    (out / 'Logs').mkdir(exist_ok=True)
    (out / 'Logs/HeadlessDigest.log').write_text(
        ''.join(f'HHDIGEST|turn={t}|point=doTurnBegin|total={t:016x}|game={t:016x}\n' for t in range(turns)), encoding='utf-8')
    (out / 'checkpoints').mkdir(exist_ok=True)
    (out / f'checkpoints/turn-{turns:04d}-final.json').write_text(json.dumps(dict(data=dict(turn=turns))), encoding='utf-8')
    (out / 'lua-before-arm.json').write_text(json.dumps(dict(setup=dict(turn=0), improvedMask=-2, diagnosticsLevel=-1)), encoding='utf-8')
    (out / 'lua-before-dump.json').write_text(json.dumps(dict(victory=dict(winner=-1), messages=[], replayData={})), encoding='utf-8')
    (out / 'newgame-report.json').write_text(json.dumps(dict(status='passed', newgame=dict(autoplay=dict(updates=turns)))), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
