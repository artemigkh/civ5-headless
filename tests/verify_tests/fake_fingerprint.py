"""A stand-in for civ5headless.fingerprint (plan 9.3) with the documented read() shape: .sections (turn -> section ->
hash), .metrics (turn -> player -> metric -> value), .meta. It reads fakegame's C5HFP/C5HM lines."""
from pathlib import Path
from types import SimpleNamespace

PROBE = Path(__file__).resolve().parent / 'fake_fingerprint.lua'


def _fields(text):
    out = {}
    for part in text.split('|'):
        if '=' in part:
            k, v = part.split('=', 1)
            out[k] = v
    return out


def read(path):
    sections, metrics = {}, {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        i = line.find('C5HFP|')
        if i >= 0:
            f = _fields(line[i + 6:])
            t = int(f.pop('turn'))
            sections[t] = f
            continue
        i = line.find('C5HM|')
        if i >= 0:
            f = _fields(line[i + 5:])
            t, p = int(f.pop('turn')), int(f.pop('player'))
            metrics.setdefault(t, {})[p] = {k: float(v) for k, v in f.items()}
    return SimpleNamespace(sections=sections, metrics=metrics, meta={})
