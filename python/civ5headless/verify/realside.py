"""The real-game side of the suite, through realgame.session.RealGameSession (plan 9.4); tests use a fake.

One session:
1. launch with the first game's seeds pinned (the game reads them when it loads the DLL; the games are ordered so
   that each seed pair costs at most one relaunch), activate the configuration's mods;
2. the turn-0 setups: each started with the probes (the session leaves it paused at turn 0), one turn played (the
   fingerprint prints at turn 0), logs collected, back to the main menu; after the first game, the database the game
   holds in memory is exported for the database check;
3. the trajectory game: the Tiny game played to the horizon with the probes; per-turn wall times, replay data
   (session.call in InGame, as run.py's final query), process statistics right after its autoplay;
4. full mode: the same game again (real A/A) and a Standard game for scale and memory.

Each game's logs go to real/<game>/: collect_logs copies the session's logs, and Lua.segment.log (also Logs/Lua.log)
keeps only what that game appended; HeadlessDigest.log likewise. A relaunch starts new logs, which the segmenting
notices. Optional session methods (replay_data, call, game_database) are used when present.
"""
from __future__ import annotations
import inspect
import shutil
import time
import traceback
from pathlib import Path

from .. import run as host_run

SEGMENTED = ('Lua.log', 'HeadlessDigest.log')
HEAD = 256  # bytes of a log remembered to notice a new file (a relaunch) of the same name

# Every major's replay data, as run.FINAL collects it in the host.
REPLAY_LUA = r'''
local series={}
for owner=0,63 do local p=Players[owner]
 if p and p:IsEverAlive() and not p:IsBarbarian() and not p:IsMinorCiv() and not p:IsObserver() then
  local ok,d=pcall(function() return p:GetReplayData() end)
  if ok and d then local o={};for k,s in pairs(d) do local a={};for t,x in pairs(s) do a[#a+1]={t,x} end;o[k]=a end;series[tostring(owner)]=o end
 end
end
return series
'''
DONE = ('turns', 'victory', 'target', 'target_turn')   # autoplay endReason of a game played to its end


class RealSide:
    def __init__(self, cfg, settings, session_class, out_dir, games, probes, deadline, t0, log=print, state=None):
        """games: [{name, kind (setup, trajectory, aa, standard), spec (resolved dict), turns}]."""
        self.cfg, self.settings, self.session_class = cfg, settings, session_class
        self.dir = Path(out_dir) / 'real'
        self.games = games
        self.probes = [str(p) for p in probes]
        self.deadline, self.t0 = deadline, t0
        self.log = log
        self.state = state if state is not None else {}   # shared with the load timeline: {'phase': ...}
        self.offsets = {}
        self.result = dict(games=[], errors=[])

    def now(self):
        return time.monotonic() - self.t0

    def run(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        session = None
        try:
            self.state['phase'] = 'launch'
            session = self.session_class(self.cfg, self.dir)
            seeds = (self.games[0]['spec'].get('seeds') or {}) if self.games else {}
            t = time.monotonic()
            if 'map_seed' in inspect.signature(session.launch).parameters:
                info = session.launch(map_seed=seeds.get('map'), sync_seed=seeds.get('sync'))
            else:
                info = session.launch()
            self.result['launch'] = dict(_as_dict(info), seconds=round(time.monotonic() - t, 2), started=self.now())
            mods = [m.id for m in self.cfg.active_mods]
            t = time.monotonic()
            session.set_mods(mods)
            self.result['mods'] = dict(ids=mods, seconds=round(time.monotonic() - t, 2))
            database_done = False
            for game in self.games:
                if time.monotonic() > self.deadline - self.settings.reserve_seconds:
                    self.result['games'].append(dict(name=game['name'], kind=game['kind'], state='skipped', error='budget'))
                    continue
                g = self.play(session, game)
                self.result['games'].append(g)
                if not database_done and g.get('started'):
                    self.result['database'] = self.capture_database(session)
                    database_done = True
                if game is not self.games[-1]:
                    self.state['phase'] = 'menu'
                    session.to_main_menu()
            self.result['process'] = self.stats(session)
        except Exception as error:  # noqa: BLE001 (the real side reports, the suite goes on)
            self.result['errors'].append(f'{type(error).__name__}: {error}')
            (self.dir / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            self.log(f'real game: {type(error).__name__}: {error}')
        finally:
            self.state['phase'] = 'quit'
            if session is not None:
                try:
                    session.quit()
                except Exception as error:  # noqa: BLE001
                    self.result['errors'].append(f'quit: {type(error).__name__}: {error}')
            self.state['phase'] = None
            self.result['finished'] = self.now()
            host_run.write(self.dir / 'real.json', self.result)
        return self.result

    def stats(self, session):
        try:
            return _as_dict(session.process_stats())
        except Exception as error:  # noqa: BLE001
            self.result['errors'].append(f'process_stats: {type(error).__name__}: {error}')
            return {}

    def play(self, session, game):
        g = dict(name=game['name'], kind=game['kind'], turns=game['turns'], seeds=game['spec'].get('seeds'), state='failed')
        folder = self.dir / game['name']
        folder.mkdir(parents=True, exist_ok=True)
        seeds = game['spec'].get('seeds') or {}
        replay = None
        try:
            self.state['phase'] = f"start {game['name']}"
            t = time.monotonic()
            g['startedAt'] = self.now()
            info = _as_dict(session.start_game(game['spec'], seeds.get('map'), seeds.get('sync'), lua_probes=list(self.probes)))
            g['start'] = dict({k: v for k, v in info.items() if k in ('seeds', 'relaunched', 'seedsVerified', 'probes', 'seconds')},
                              seconds=round(time.monotonic() - t, 2))
            g['started'] = True
            if info.get('relaunched'):
                self.offsets = {}  # a new process writes new logs
            self.state['phase'] = f"autoplay {game['name']}"
            left = self.deadline - time.monotonic() - self.settings.reserve_seconds
            t = time.monotonic()
            g['autoplayStartedAt'] = self.now()
            info = session.autoplay(game['turns'], max_seconds=max(int(left), 10))
            g['autoplaySeconds'] = round(time.monotonic() - t, 2)
            g['autoplay'] = _autoplay(info, game['turns'])
            end, reason = g['autoplay'].get('endTurn'), g['autoplay'].get('endReason')
            g['state'] = 'completed' if reason in DONE or (reason is None and (end is None or end >= game['turns'])) else 'partial'
            g['process'] = self.stats(session)
            replay = self.replay(session, g)
        except Exception as error:  # noqa: BLE001
            g['error'] = f'{type(error).__name__}: {error}'
            self.log(f"real game {game['name']}: {g['error']}")
        finally:
            self.collect(session, folder, g)
        if replay is None and (folder / 'logs/replay-data.json').is_file():
            replay = host_run.read(folder / 'logs/replay-data.json')
        if replay is not None:
            host_run.write(folder / 'replay-data.json', replay)
        g['dir'] = str(folder)
        host_run.write(folder / 'game.json', g)
        return g

    def replay(self, session, g):
        """Every major's replay data: session.replay_data(), else the REPLAY_LUA query through session.call."""
        try:
            if callable(getattr(session, 'replay_data', None)):
                return session.replay_data()
            if callable(getattr(session, 'call', None)):
                return _replay_shape(session.call('InGame', REPLAY_LUA, 'replay-data'))
        except Exception as error:  # noqa: BLE001
            g['replayError'] = f'{type(error).__name__}: {error}'
        return None

    def collect(self, session, folder, g):
        """collect_logs into folder/logs, then the part of each session-wide log that this game added."""
        dest = folder / 'logs'
        dest.mkdir(parents=True, exist_ok=True)
        try:
            session.collect_logs(dest)
        except Exception as error:  # noqa: BLE001
            g['logsError'] = f'{type(error).__name__}: {error}'
            return
        for name in SEGMENTED:
            src = next(iter(sorted(dest.rglob(name))), None)
            if src is None:
                continue
            data = src.read_bytes()
            size, head = self.offsets.get(name, (0, b''))
            start = size if len(data) >= size and data[:len(head)] == head else 0  # else a new file
            segment = data[start:]
            self.offsets[name] = (len(data), data[:HEAD])
            (folder / name.replace('.log', '.segment.log')).write_bytes(segment)
            (folder / 'Logs').mkdir(exist_ok=True)
            (folder / 'Logs' / name).write_bytes(segment)

    def capture_database(self, session):
        """The game's database after the mods loaded: session.game_database(dest) (exported with CREATE TABLE AS:
        compared data only), else a copy of the cache's Civ5DebugDatabase.db (read only)."""
        dest = self.dir / 'game-database.db'
        try:
            if callable(getattr(session, 'game_database', None)):
                got = session.game_database(dest)
                dest, method = Path(got) if got else dest, 'export'
            elif self.cfg.cache_dir and (Path(self.cfg.cache_dir) / 'Civ5DebugDatabase.db').is_file():
                shutil.copyfile(Path(self.cfg.cache_dir) / 'Civ5DebugDatabase.db', dest)
                method = 'cache'
            else:
                return dict(error='no game database: the session has no game_database() and cache_dir has no Civ5DebugDatabase.db')
        except Exception as error:  # noqa: BLE001
            return dict(error=f'{type(error).__name__}: {error}')
        return dict(path=str(dest), method=method) if dest.is_file() else dict(error=f'{dest} was not written')


def _as_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, '__dict__'):
        return dict(vars(value))
    return dict(value=value)


def _replay_shape(data):
    """{player: {dataset: [[turn, value], ...]}} from what the tuner returns (lists or {index: item} tables)."""
    if not isinstance(data, dict):
        return None
    out = {}
    for player, sets in data.items():
        if not isinstance(sets, dict):
            continue
        o = {}
        for name, points in sets.items():
            items = points.values() if isinstance(points, dict) else points if isinstance(points, list) else []
            pairs = []
            for p in items:
                if isinstance(p, dict):
                    p = [p.get('1', p.get(1)), p.get('2', p.get(2))]
                if isinstance(p, (list, tuple)) and len(p) == 2 and p[0] is not None:
                    pairs.append([p[0], p[1]])
            o[name] = pairs
        out[str(player)] = o
    return out


def _autoplay(info, turns):
    """Normalise what autoplay() returns: {turnSeconds: {turn: seconds since autoplay started}, endTurn, endReason}.

    Accepted: a dict with turnSeconds / turn_seconds / turnTimes (cumulative seconds since autoplay started, as the
    host's turn-times.jsonl: dict turn -> seconds, or [[turn, seconds]], or [{turn, seconds}]) or turnDurations
    (dict turn -> seconds that turn took), endTurn / end_turn, endReason / end_reason; or a plain list of the
    cumulative times of turns 1, 2, ..."""
    d = _as_dict(info) if not isinstance(info, (list, tuple)) else dict(turnSeconds=list(info))
    raw = d.get('turnSeconds', d.get('turn_seconds', d.get('turnTimes', d.get('turn_times'))))
    times = {}
    if isinstance(raw, dict):
        times = {int(k): float(v) for k, v in raw.items()}
    elif isinstance(raw, (list, tuple)):
        for k, x in enumerate(raw):
            if isinstance(x, dict):
                times[int(x.get('turn', k + 1))] = float(x.get('seconds'))
            elif isinstance(x, (list, tuple)) and len(x) == 2:
                times[int(x[0])] = float(x[1])
            elif x is not None:
                times[k + 1] = float(x)
    durations = d.get('turnDurations', d.get('turn_durations'))
    if not times and isinstance(durations, dict) and durations:
        total = 0.0
        for k in sorted(durations, key=int):
            total += float(durations[k])
            times[int(k)] = total
    end = d.get('endTurn', d.get('end_turn'))
    if end is None and times:
        end = max(times)
    return dict(turnSeconds={str(k): times[k] for k in sorted(times)}, endTurn=end,
                endReason=d.get('endReason', d.get('end_reason')),
                extra={k: v for k, v in d.items() if k not in ('turnSeconds', 'turn_seconds', 'turnTimes', 'turn_times',
                                                                'turnDurations', 'turn_durations', 'endTurn', 'end_turn',
                                                                'endReason', 'end_reason')})


def load(out_dir):
    return host_run.read(Path(out_dir) / 'real/real.json')
