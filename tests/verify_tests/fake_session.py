"""A fake realgame.session.RealGameSession (plan 9.4) for the verification suite's tests: plays fakegame.Game, so the
real side of c5h verify runs without the game.

Like the real session, its Lua.log and HeadlessDigest.log grow over the whole session (every game appends), and
collect_logs copies them as they are. Class attributes configure a test: sync_matters, diverge_at (the "real" game
differs from that turn on), scale (a biased real game), fail_in (a method that raises), and the extras
(replay_data, game_database) can be switched off.
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
    instances = []

    def __init__(self, config, run_dir):
        self.config, self.dir = config, Path(run_dir)
        self.lua, self.digest, self.calls = [], [], []
        self.game, self.turns = None, 0
        FakeRealGameSession.instances.append(self)
        if not self.with_extras:
            self.replay_data = None
            self.game_database = None

    def _call(self, name):
        self.calls.append(name)
        if self.fail_in == name:
            raise RuntimeError(f'fake failure in {name}')

    def launch(self):
        self._call('launch')
        return dict(mainMenuSeconds=1.5)

    def set_mods(self, mod_ids):
        self._call('set_mods')
        self.mods = list(mod_ids)

    def start_game(self, spec, map_seed, sync_seed, lua_probes=()):
        self._call('start_game')
        spec = dict(spec, seeds=dict(map=map_seed, sync=sync_seed))
        self.game = fakegame.Game(spec, sync_matters=self.sync_matters, diverge_at=self.diverge_at,
                                  transient_at=self.transient_at, tag='real', scale=self.scale)
        self.probes = [Path(p).read_text(encoding='utf-8') for p in lua_probes]
        if any('C5HPG' in p for p in self.probes):
            self.lua += self.game.pregame_lines()
        return dict(seconds=2.0)

    def autoplay(self, turns, max_seconds=None):
        self._call('autoplay')
        self.turns = turns
        for t in range(turns):
            self.digest.append(self.game.digest_line(t))
            if any('C5HFP' in p for p in self.probes):
                self.lua += self.game.fingerprint_lines(t)
        return dict(turnSeconds={t: 4 * self.game.turn_seconds(t) for t in range(1, turns + 1)}, endTurn=turns,
                    endReason='target')

    def to_main_menu(self):
        self._call('to_main_menu')
        self.game = None

    def collect_logs(self, dest):
        self._call('collect_logs')
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'Lua.log').write_text(''.join(line + '\n' for line in self.lua), encoding='utf-8')
        (dest / 'HeadlessDigest.log').write_text(''.join(line + '\n' for line in self.digest), encoding='utf-8')
        return [dest / 'Lua.log', dest / 'HeadlessDigest.log']

    def process_stats(self):
        self._call('process_stats')
        return dict(PeakWorkingSet=2000 * 2 ** 20, PeakPrivateBytes=2400 * 2 ** 20, CPUSeconds=321.0)

    def replay_data(self):
        return self.game.replay_data(self.turns) if self.game else None

    def game_database(self, dest):
        shutil.copyfile(self.config.db, dest)
        return dest

    def quit(self):
        self._call('quit')
