"""A synthetic Civ V game for the verification suite's tests: the same seeds give the same per-turn digests, replay
data, checkpoints and probe lines, whether the fake host (fake_host.py) or the fake real-game session
(fake_session.py) plays it.

By default the game depends on the map seed only (as Vox Populi's games do); sync_matters makes the sync seed count
too. diverge_at makes every player section differ from that turn on (a lasting difference), transient_at for one
turn only. Each game's metric level is drawn from its seeds, so an ensemble has spread; scale multiplies every
metric (a biased game).

City-states (slots 22 to 24): chooser 'dll' (the DLL chooses, from the map seed, as Vox Populi does), 'exe' (the real
game's exe chooses: a draw the host cannot make) or 'host' (the host chooses: the spec's minorCivs pins, else its own
draw). They are a state section, so games with other city-states differ from turn 0.
"""
import hashlib
import json
import random

PLAYERS = 4
DATASETS = ('REPLAYDATASET_SCORE', 'REPLAYDATASET_CITYCOUNT', 'REPLAYDATASET_TOTALGOLD', 'REPLAYDATASET_TECHSKNOWN',
            'REPLAYDATASET_POPULATION', 'REPLAYDATASET_MILITARYMIGHT')
METRICS = ('cities', 'population', 'techs', 'units')
MAX_MAJORS = 22
MINORS = 3
MINOR_POOL = ('MINOR_CIV_GENEVA', 'MINOR_CIV_BUDAPEST', 'MINOR_CIV_SYDNEY', 'MINOR_CIV_SINGAPORE', 'MINOR_CIV_MONACO',
              'MINOR_CIV_HANOI', 'MINOR_CIV_LHASA', 'MINOR_CIV_ALMATY')


def h(*parts):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:16]


class Game:
    def __init__(self, spec, sync_matters=False, diverge_at=None, transient_at=None, tag='', scale=1.0, victory_turn=None,
                 chooser='dll'):
        seeds = spec.get('seeds') or {}
        self.map, self.sync = int(seeds.get('map', 1)), int(seeds.get('sync', 2))
        self.key = (self.map, self.sync) if sync_matters else (self.map,)
        self.diverge_at, self.transient_at, self.tag, self.scale = diverge_at, transient_at, tag, scale
        self.victory_turn = victory_turn
        self.script = (spec.get('map') or {}).get('file') or (spec.get('map') or {}).get('script') or 'Continents.lua'
        self.world = (spec.get('worldSize') or {}).get('id', 1)
        self.chooser = chooser
        pins = [m['type'] if isinstance(m, dict) else m for m in spec.get('minorCivs') or []]
        self.pinned = pins if chooser == 'host' else []
        self.minors = self.pinned[:MINORS] or self.draw(chooser)
        self.pins = pins

    def draw(self, who):
        pool = sorted(MINOR_POOL, key=lambda t: h(who, self.map, t))
        return pool[:MINORS]

    def changed(self, t):
        return (self.diverge_at is not None and t >= self.diverge_at) or (self.transient_at is not None and t == self.transient_at)

    def end_turn(self, turns):
        return min(turns, self.victory_turn) if self.victory_turn else turns

    def sections(self, t):
        out = {'pregame': h('pregame', self.map, self.sync), 'game': h('game', self.map, self.sync, t),
               'minors': h('minors', *self.minors)}
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

    def meta_lines(self):
        """What the fingerprint probe prints when it is injected (turn 0): the meta line and one per player."""
        out = ['C5HFP|v=1|meta|turn=0|plots=1056|width=44|height=24|maxMajors=%d|maxCivs=63|every=1' % MAX_MAJORS]
        for p in range(PLAYERS):
            out.append('C5HFP|v=1|player|turn=0|player=%d|team=%d|civ=CIVILIZATION_%d|leader=LEADER_%d' % (p, p, p, p))
        for i, m in enumerate(self.minors):
            out.append('C5HFP|v=1|player|turn=0|player=%d|team=%d|civ=CIVILIZATION_MINOR|minor=%s'
                       % (MAX_MAJORS + i, MAX_MAJORS + i, m))
        return out

    def minor_report(self):
        """host-report.json's minorCivs section for this game in the host."""
        slots = []
        for i, m in enumerate(self.minors):
            x = dict(slot=MAX_MAJORS + i, id=MINOR_POOL.index(m), type=m)
            pinned = self.pins[i] if i < len(self.pins) else None
            match = pinned == m if pinned else None
            x['chosenBy'] = 'dll' if self.chooser == 'dll' else 'spec' if match else 'host'
            if pinned:
                x.update(pinnedId=MINOR_POOL.index(pinned) if pinned in MINOR_POOL else -1, pinnedType=pinned, match=match)
            slots.append(x)
        n = sum(1 for x in slots if 'pinnedType' in x)
        k = sum(1 for x in slots if x.get('match'))
        return dict(chosenBy='host' if self.chooser == 'host' else 'dll', pinned=n, matching=k,
                    allMatch=(n == k) if n else None, slots=slots)

    def fingerprint_lines(self, t):
        """A turn's lines in probes/fingerprint.lua's format (version 1), read by civ5headless.fingerprint."""
        s = {k: v for k, v in self.sections(t).items() if k not in ('pregame', 'savedb')}
        s['game'] = h('game', self.map, t)  # the probe's game section holds no seed
        total = h(*[s[k] for k in sorted(s)])
        out = []
        out.append('C5HFP|v=1|turn=%d|point=PlayerDoTurn|part=1/1|total=%s|' % (t, total)
                   + '|'.join('%s=%s' % (k, v) for k, v in s.items()))
        for p in range(PLAYERS):
            out.append('C5HM|v=1|turn=%d|player=%d|alive=1|' % (t, p) + '|'.join('%s=%s' % (m, self.value(m, p, t)) for m in METRICS))
        return out


def read_spec(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)
