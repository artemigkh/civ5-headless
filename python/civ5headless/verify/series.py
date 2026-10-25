"""Per-turn metric series of one game, for the statistical tier: {series name: {turn: value}}.

Sources:
- replay datasets: replay-data.json of a run folder ({player: {REPLAYDATASET_X: [[turn, value], ...]}}, every major
  civ), or the same structure from the real-game session;
- fingerprint metrics: the C5HM lines of Lua.log, read with civ5headless.fingerprint (turn -> player -> metric).

Players differ between games (random civs, eliminations), so each metric becomes world aggregates over the major
civs that have a value that turn: the mean and the maximum (the leader). Series names are "<source>:<METRIC>:<agg>",
for example "replay:SCORE:mean" or "lua:cities:max".
"""
from __future__ import annotations
import json
from pathlib import Path

AGGREGATES = ('mean', 'max')
PREFIX = 'REPLAYDATASET_'


def aggregate(per_turn, aggregates=AGGREGATES):
    """{turn: [values]} -> {agg: {turn: value}}."""
    out = {a: {} for a in aggregates}
    for t, values in per_turn.items():
        values = [v for v in values if v is not None]
        if not values:
            continue
        if 'mean' in out:
            out['mean'][t] = sum(values) / len(values)
        if 'max' in out:
            out['max'][t] = max(values)
        if 'min' in out:
            out['min'][t] = min(values)
        if 'sum' in out:
            out['sum'][t] = sum(values)
    return out


def from_replay(data, aggregates=AGGREGATES, datasets=None, exclude=()):
    """Series from replay data ({player: {dataset: [[turn, value], ...]}})."""
    per = {}
    for player, sets in (data or {}).items():
        for dataset, points in (sets or {}).items():
            name = dataset[len(PREFIX):] if dataset.startswith(PREFIX) else dataset
            if (datasets and name not in datasets) or name in exclude:
                continue
            cols = per.setdefault(name, {})
            for point in points or []:
                try:
                    t, v = int(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    continue
                cols.setdefault(t, []).append(v)
    out = {}
    for name, cols in per.items():
        for agg, s in aggregate(cols, aggregates).items():
            if s:
                out[f'replay:{name}:{agg}'] = s
    return out


def from_metrics(metrics, aggregates=AGGREGATES, exclude=()):
    """Series from fingerprint metrics ({turn: {player: {metric: value}}})."""
    per = {}
    for t, players in (metrics or {}).items():
        for player, values in (players or {}).items():
            for name, v in (values or {}).items():
                if name in exclude:
                    continue
                try:
                    per.setdefault(name, {}).setdefault(int(t), []).append(float(v))
                except (TypeError, ValueError):
                    continue
    out = {}
    for name, cols in per.items():
        for agg, s in aggregate(cols, aggregates).items():
            if s:
                out[f'lua:{name}:{agg}'] = s
    return out


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
        return default


def game_series(folder, fingerprint=None, aggregates=AGGREGATES, exclude=(), lua_log=None):
    """All series of one game folder: replay-data.json plus fingerprint metrics when the module and lines exist."""
    folder = Path(folder)
    out = from_replay(read_json(folder / 'replay-data.json', {}), aggregates, exclude=exclude)
    log = Path(lua_log) if lua_log else folder / 'Logs/Lua.log'
    if fingerprint is not None and log.is_file():
        try:
            fp = fingerprint.read(log)
            out.update(from_metrics(getattr(fp, 'metrics', None) or {}, aggregates, exclude=exclude))
        except Exception:  # noqa: BLE001 (a probe format problem must not stop the suite; the check says n/a)
            pass
    return out


def label(name):
    """'replay:SCORE:mean' -> 'Score (mean)'."""
    parts = name.split(':')
    if len(parts) != 3:
        return name
    source, metric, agg = parts
    text = metric.replace('_', ' ').lower().capitalize() if source == 'replay' else metric
    return f'{text} ({agg})' + ('' if source == 'replay' else ' [Lua]')


def truncate(series, to_turn):
    return {n: {t: v for t, v in s.items() if t <= to_turn} for n, s in series.items()}
