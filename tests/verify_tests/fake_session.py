"""A fake realgame.session.RealGameSession (plan 9.4) for the verification suite's tests: plays fakegame.Game, so the
real side of c5h verify runs without the game.

Like the real session: launch(map_seed, sync_seed) pins seeds; a start_game with other seeds relaunches (a new
process: new logs) and says so; Lua.log and HeadlessDigest.log grow over a process's life (every game appends) and
collect_logs copies them as they are; autoplay returns turnSeconds (cumulative), endTurn and endReason 'turns';
process_stats uses the session's key names; replay_data() as the session returns it; game_database exports.
start_game(fingerprint=...) prints the fingerprint probe's lines (meta and players at the start, then every turn).
Class attributes configure a test: sync_matters, diverge_at (the "real" game differs from that turn on),
transient_at, scale (a biased real game), fail_in (a method that raises), with_extras (game_database), exe_chooses
(the DLL leaves city-states to the exe: the real game's are a draw the host cannot make).
"""
from pathlib import Path
import shutil

import fakegame


class FakeRealGameSession:
    sync_matters = False
    diverge_at = None
    transient_at = None
    scale = 1.0
    fail_in = None
    with_extras = True
    exe_chooses = False
    instances = []

    def __init__(self, cfg, run_dir):
        self.config, self.dir = cfg, Path(run_dir)
        self.lua, self.digest, self.calls = [], [], []
        self.game, self.turns = None, 0
        self.launch_seeds, self.launches = None, 0
        FakeRealGameSession.instances.append(self)
        if not self.with_extras:
            self.game_database = None

    def _call(self, name):
        self.calls.append(name)
        if self.fail_in == name:
            raise RuntimeError(f'fake failure in {name}')

    def launch(self, map_seed=None, sync_seed=None):
        self._call('launch')
        self.launch_seeds, self.launches = (map_seed, sync_seed), self.launches + 1
        return dict(seconds=1.5, seeds=dict(map=map_seed, sync=sync_seed), launches=self.launches)

    def set_mods(self, mod_ids):
        self._call('set_mods')
        self.mods = list(mod_ids)
        return dict(mods=[dict(id=i) for i in mod_ids])

    def start_game(self, spec, map_seed=None, sync_seed=None, lua_probes=(), fingerprint=None):
        self._call('start_game')
        relaunched = (map_seed, sync_seed) != self.launch_seeds
        if relaunched:  # a new process: new logs
            self.launch_seeds, self.launches = (map_seed, sync_seed), self.launches + 1
            self.lua, self.digest = [], []
        spec = dict(spec, seeds=dict(map=map_seed, sync=sync_seed))
        self.game = fakegame.Game(spec, sync_matters=self.sync_matters, diverge_at=self.diverge_at,
                                  transient_at=self.transient_at, tag='real', scale=self.scale,
                                  chooser='exe' if self.exe_chooses else 'dll')
        self.probes = [Path(p).read_text(encoding='utf-8') for p in lua_probes]
        self.fingerprint = bool(fingerprint)
        self.lua.append(f'[1.0] Game started: {map_seed}/{sync_seed}')
        if self.fingerprint:  # the fingerprint probe runs first, then lua_probes
            self.lua += self.game.meta_lines()
        if any('C5HPG' in p for p in self.probes):
            self.lua += self.game.pregame_lines()
        return dict(seeds=dict(map=map_seed, sync=sync_seed), relaunched=relaunched, probes=len(self.probes))

    def autoplay(self, turns, max_seconds=None):
        self._call('autoplay')
        self.turns = turns
        for t in range(turns):
            self.digest.append(self.game.digest_line(t))
        for t in range(turns + 1):  # the probe also prints the state after the last turn
            if self.fingerprint:
                self.lua += self.game.fingerprint_lines(t)
        return dict(startTurn=0, endTurn=turns, turns=turns, endReason='turns', victory=None,
                    turnSeconds={t: 4 * self.game.turn_seconds(t) for t in range(1, turns + 1)},
                    wallSeconds=4 * self.game.turn_seconds(turns))

    def replay_data(self):
        self._call('replay_data')
        return self.game.replay_data(self.turns)

    def to_main_menu(self):
        self._call('to_main_menu')
        self.game = None
        return {}

    def collect_logs(self, dest):
        self._call('collect_logs')
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'Lua.log').write_text(''.join(line + '\n' for line in self.lua), encoding='utf-8')
        (dest / 'HeadlessDigest.log').write_text(''.join(line + '\n' for line in self.digest), encoding='utf-8')
        return ['Lua.log', 'HeadlessDigest.log']

    def process_stats(self):
        self._call('process_stats')
        return dict(peakWorkingSet=2000 * 2 ** 20, peakPrivateBytes=2400 * 2 ** 20, cpuSeconds=321.0,
                    launches=self.launches, alive=True)

    def game_database(self, dest):
        shutil.copyfile(self.config.db, dest)
        return Path(dest)

    def quit(self):
        self._call('quit')
        return {}
