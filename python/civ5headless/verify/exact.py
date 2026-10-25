"""Exact comparisons of two games, turn by turn, and the other per-game facts the exact checks read.

Methods, best first:
- digest: the DLL's HHDIGEST lines (HeadlessDigest.log; DLLs with the optional additions), through
  compare.digest.compare;
- fingerprint: the C5HFP section hashes the fingerprint probe writes to Lua.log (any SDK-derived DLL), read with
  civ5headless.fingerprint.read and compared here section by section;
- checkpoint: the host's per-turn checkpoints (checkpoints/turn-NNNN.json): cities, players, wars and a few totals.
  Coarse, and host only: it serves the host references (A/A, frame skew, heap perturbation, probe on/off) when the
  DLL has no digests and the host cannot run the fingerprint probe.

Every comparison gives one dict shape (compare_sections): the turns compared, the turns matched before the first
lasting difference (matchedTurns), the transients (differences that heal within heal_turns turns) and the
differences only in sections known to be UI-only or scratch state, which are listed apart and never count.
"""
from __future__ import annotations
import collections
import json
import re
from pathlib import Path

from ..compare import digest as hhdigest

PREGAME_PREFIX = 'C5HPG|'
VOLATILE_CHECKPOINT_KEYS = ('autoplay',)  # remaining autoplay count: differs with --turns, not with the game


# ---- sources ----

def digest_log(folder):
    """The HeadlessDigest.log of a run or real-game folder when it has HHDIGEST lines, else None."""
    p = Path(folder)
    for c in ((p,) if p.is_file() else (p / 'Logs/HeadlessDigest.log', p / 'HeadlessDigest.log')):
        if c.is_file():
            with open(c, encoding='utf-8', errors='replace') as f:
                if any(line.startswith('HHDIGEST|') for line in f):
                    return c
    return None


def lua_log(folder):
    p = Path(folder)
    for c in ((p,) if p.is_file() else (p / 'Lua.segment.log', p / 'Logs/Lua.log', p / 'Lua.log')):
        if c.is_file():
            return c
    return None


def fingerprint_sections(folder, fingerprint):
    """{turn: {section: hash}} from the fingerprint lines in Lua.log, or None (no module, no log, no lines)."""
    if fingerprint is None:
        return None
    log = lua_log(folder)
    if log is None:
        return None
    try:
        fp = fingerprint.read(log)
    except Exception:  # noqa: BLE001 (a format problem is reported as "no fingerprint")
        return None
    sections = getattr(fp, 'sections', None) or {}
    return {int(t): dict(s) for t, s in sections.items()} or None


def checkpoint_states(folder):
    """{turn: canonical JSON of the checkpoint data} from checkpoints/turn-NNNN.json, or None."""
    d = Path(folder) / 'checkpoints'
    out = {}
    for p in sorted(d.glob('turn-[0-9][0-9][0-9][0-9].json')) if d.is_dir() else []:
        try:
            data = json.loads(p.read_text(encoding='utf-8')).get('data') or {}
        except (OSError, ValueError):
            continue
        for k in VOLATILE_CHECKPOINT_KEYS:
            data.pop(k, None)
        out[int(p.stem.split('-')[1])] = {'state': json.dumps(data, sort_keys=True)}
    return out or None


def available(a, b, fingerprint=None, host_only=False):
    """The best method both folders support: digest, fingerprint, checkpoint (host_only) or None."""
    if digest_log(a) and digest_log(b):
        return 'digest'
    if fingerprint_sections(a, fingerprint) and fingerprint_sections(b, fingerprint):
        return 'fingerprint'
    if host_only and checkpoint_states(a) and checkpoint_states(b):
        return 'checkpoint'
    return None


# ---- comparison ----

def compare_sections(a, b, heal_turns=2, ui_sections=()):
    """Compare {turn: {section: hash}} maps; same result shape as normalise()."""
    turns = sorted(set(a) & set(b))
    runs, open_run, ui_only = [], None, []
    for t in turns:
        sa, sb = a[t], b[t]
        diff = [s for s in list(sa) + [s for s in sb if s not in sa] if sa.get(s) != sb.get(s)]
        ui = [s for s in diff if s in ui_sections]
        diff = [s for s in diff if s not in ui_sections]
        if ui:
            ui_only.append(dict(turn=t, sections=ui))
        if diff:
            if open_run is None:
                open_run = dict(turn=t, until=None, sections=[])
            open_run['sections'] += [s for s in diff if s not in open_run['sections']]
        elif open_run is not None:
            open_run['until'] = t
            runs.append(open_run)
            open_run = None
    if open_run is not None:
        runs.append(open_run)
    return _result(turns, runs, ui_only, heal_turns, max(a, default=None), max(b, default=None))


def _result(turns, runs, ui_only, heal_turns, last_a, last_b, method=None):
    transients = [r for r in runs if r['until'] is not None and r['until'] - r['turn'] <= heal_turns]
    divergence = next((r for r in runs if r not in transients), None)
    matched = sum(1 for t in turns if divergence is None or t < divergence['turn'])
    return dict(method=method, identical=not runs, compared=len(turns), firstTurn=turns[0] if turns else None,
                lastCommonTurn=turns[-1] if turns else None, lastTurnA=last_a, lastTurnB=last_b,
                matchedTurns=matched, divergence=divergence, transients=transients, uiOnly=ui_only,
                firstDifference=runs[0] if runs else None, healTurns=heal_turns)


def compare_digest(a_log, b_log, heal_turns=2):
    """compare.digest.compare in this module's shape; savedb (outside the digest total) is the UI-only section."""
    da, db = hhdigest.digest_lines(a_log), hhdigest.digest_lines(b_log)
    r = hhdigest.compare(da, db, heal_turns)
    turns = sorted({k[1] for k in set(da) & set(db)})
    runs = [dict(turn=x['turn'], until=x['until'], sections=list(x['sections'])) for x in r['runs']]
    ui = [dict(turn=r['savedbFirstTurn'], sections=['savedb'])] if r.get('savedbFirstTurn') is not None else []
    return _result(turns, runs, ui, heal_turns, r['lastTurnA'], r['lastTurnB'])


def compare(a, b, method, heal_turns=2, fingerprint=None, ui_sections=('savedb',)):
    """Compare two game folders with a method from available(); None when either side lacks it."""
    if method == 'digest':
        la, lb = digest_log(a), digest_log(b)
        if not (la and lb):
            return None
        out = compare_digest(la, lb, heal_turns)
    elif method == 'fingerprint':
        sa, sb = fingerprint_sections(a, fingerprint), fingerprint_sections(b, fingerprint)
        if not (sa and sb):
            return None
        out = compare_sections(sa, sb, heal_turns, ui_sections)
    elif method == 'checkpoint':
        sa, sb = checkpoint_states(a), checkpoint_states(b)
        if not (sa and sb):
            return None
        out = compare_sections(sa, sb, heal_turns)
    else:
        return None
    out['method'] = method
    return out


def summary(r, what='the games'):
    """One line for a comparison."""
    if r is None:
        return 'not compared'
    n = r['matchedTurns']
    text = f"{what} match for {n} of {r['compared']} compared turns"
    if r['divergence']:
        d = r['divergence']
        text += f"; lasting difference from turn {d['turn']} ({', '.join(d['sections'][:6])}{', ...' if len(d['sections']) > 6 else ''})"
    if r['transients']:
        text += f"; {len(r['transients'])} transient(s) healed within {r['healTurns']} turns"
    if r['uiOnly']:
        text += f"; UI-only differences from turn {r['uiOnly'][0]['turn']}"
    return text + f" [{r['method']}]"


SEED_SECTIONS = {'game', 'pregame', 'savedb', 'turn', 'point', 'total'}  # the seeds, RNG state and digest metadata


def same_game(a, b):
    """Did two games started with different seeds play the same game? (True/False/None, how it was decided).

    With digests: every section but the ones that hold the seeds and RNG state (game, pregame) at every common point.
    Otherwise: replay data and checkpoints."""
    la, lb = digest_log(a), digest_log(b)
    if la and lb:
        da, db = hhdigest.digest_lines(la), hhdigest.digest_lines(lb)
        keys = set(da) & set(db)
        if keys:
            for k in keys:
                fa, fb = da[k][0], db[k][0]
                if any(fa.get(s) != fb.get(s) for s in set(fa) | set(fb) if s not in SEED_SECTIONS):
                    return False, 'digest'
            return True, 'digest'
    ra, rb = _read(Path(a) / 'replay-data.json'), _read(Path(b) / 'replay-data.json')
    ca, cb = checkpoint_states(a), checkpoint_states(b)
    if ra is not None and rb is not None and (ra or ca):
        return ra == rb and ca == cb, 'replay data and checkpoints'
    return None, None


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


# ---- pregame and Lua errors ----

def pregame_values(folder):
    """{key: value} from the C5HPG lines of the pregame probe in Lua.log, or None."""
    log = lua_log(folder)
    if log is None:
        return None
    out = {}
    with open(log, encoding='utf-8', errors='replace') as f:
        for line in f:
            i = line.find(PREGAME_PREFIX)
            if i < 0:
                continue
            parts = line[i + len(PREGAME_PREFIX):].rstrip('\r\n').split('|', 1)
            if len(parts) == 2:
                out[parts[0]] = parts[1]
    return out or None


def compare_values(a, b, ignore=()):
    """Key-by-key comparison of two {key: value} dicts: (differing [(key, a, b)], only in a, only in b)."""
    skip = lambda k: any(k == i or k.startswith(i + '.') for i in ignore)
    differing = [(k, a[k], b[k]) for k in sorted(set(a) & set(b)) if a[k] != b[k] and not skip(k)]
    return differing, sorted(k for k in set(a) - set(b) if not skip(k)), sorted(k for k in set(b) - set(a) if not skip(k))


_ERROR = re.compile(r'(Runtime Error|Syntax Error|stack traceback|attempt to (call|index|compare|perform|concatenate))', re.I)
_STAMP = re.compile(r'^\[\s*[\d.]+\]\s*')
_PATH = re.compile(r'(?:[A-Za-z]:)?[^\s:]*[\\/]([^\\/\s:]+\.lua)')


def lua_errors(folder):
    """Counter of normalised Lua error lines in a Lua.log (timestamps dropped, paths reduced to file names)."""
    log = lua_log(folder)
    out = collections.Counter()
    if log is None:
        return out
    with open(log, encoding='utf-8', errors='replace') as f:
        for line in f:
            if _ERROR.search(line) and 'stack traceback' not in line.lower():
                text = _PATH.sub(lambda m: m.group(1), _STAMP.sub('', line.strip()))
                out[text[:300]] += 1
    return out
