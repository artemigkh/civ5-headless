"""A synthetic Civ V game for the verification suite's tests: the same seeds give the same per-turn digests, replay
data, checkpoints and probe lines, whether the fake host (fake_host.py) or the fake real-game session
(fake_session.py) plays it.

By default the game depends on the map seed only (as Vox Populi's games do); sync_matters makes the sync seed count
too. diverge_at makes every player section differ from that turn on (a lasting difference), transient_at for one
turn only. Each game's metric level is drawn from its seeds, so an ensemble has spread; scale multiplies every
metric (a biased game).
"""
import hashlib
import json
import random

PLAYERS = 4
DATASETS = ('REPLAYDATASET_SCORE', 'REPLAYDATASET_CITYCOUNT', 'REPLAYDATASET_TOTALGOLD', 'REPLAYDATASET_TECHSKNOWN',
            'REPLAYDATASET_POPULATION', 'REPLAYDATASET_MILITARYMIGHT')
METRICS = ('cities', 'population', 'techs', 'units')


def h(*parts):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:16]


class Game:
    def __init__(self, spec, sync_matters=False, diverge_at=None, transient_at=None, tag='', scale=1.0, victory_turn=None):
        seeds = spec.get('seeds') or {}
        self.map, self.sync = int(seeds.get('map', 1)), int(seeds.get('sync', 2))
        self.key = (self.map, self.sync) if sync_matters else (self.map,)
        self.diverge_at, self.transient_at, self.tag, self.scale = diverge_at, transient_at, tag, scale
        self.victory_turn = victory_turn
        self.script = (spec.get('map') or {}).get('file') or (spec.get('map') or {}).get('script') or 'Continents.lua'
        self.world = (spec.get('worldSize') or {}).get('id', 1)

    def changed(self, t):
        return (self.diverge_at is not None and t >= self.diverge_at) or (self.transient_at is not None and t == self.transient_at)

    def end_turn(self, turns):
        return min(turns, self.victory_turn) if self.victory_turn else turns

    def sections(self, t):
        out = {'pregame': h('pregame', self.map, self.sync), 'game': h('game', self.map, self.sync, t)}
        for p in range(PLAYERS):
            out['p%02d' % p] = h('p', self.key, p, t, self.tag if self.changed(t) else '')
        out['savedb'] = h('savedb', t)
        return out

    def digest_line(self, t):
        s = self.sections(t)
        total = h(*[s[k] for k in sorted(s) if k != 'savedb'])
        return 'HHDIGEST|turn=%d|point=doTurnBegin|total=%s|' % (t, total) + '|'.join('%s=%s' % (k, v) for k, v in s.items())

    def level(self, what, p):
        rnd = random.Random(h(self.key, what, p))
        return max(0.3, 1.0 + 0.15 * rnd.gauss(0, 1))

    def value(self, what, p, t):
        v = self.level(what, p) * (5 + 2.0 * t + 0.02 * t * t) * self.scale
        if self.changed(t):
            v *= 1.01
        return round(v, 2)

    def replay_data(self, turns):
        end = self.end_turn(turns)
        return {str(p): {ds: [[t, self.value(ds, p, t)] for t in range(0, end + 1)] for ds in DATASETS} for p in range(PLAYERS)}

    def checkpoint(self, t):
        return dict(turn=t, autoplay=0, players=[dict(owner=p, score=self.value('REPLAYDATASET_SCORE', p, t)) for p in range(PLAYERS)])

    def turn_seconds(self, t):
        return round(0.01 * t * (1 + t / 100), 3)

    def pregame_lines(self):
        out = ['C5HPG|GetMapScript|%s' % self.script, 'C5HPG|GetWorldSize|%s' % self.world, 'C5HPG|GetNickName|someone']
        for p in range(PLAYERS):
            out.append('C5HPG|GetCivilization.%d|%d' % (p, int(h('civ', self.map, p), 16) % 40))
        out.append('C5HPG|end|1')
        return out

    def fingerprint_lines(self, t):
        s = self.sections(t)
        out = ['C5HFP|turn=%d|' % t + '|'.join('%s=%s' % (k, v) for k, v in s.items() if k not in ('game', 'pregame', 'savedb'))]
        for p in range(PLAYERS):
            out.append('C5HM|turn=%d|player=%d|' % (t, p) + '|'.join('%s=%s' % (m, self.value(m, p, t)) for m in METRICS))
        return out


def read_spec(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)
