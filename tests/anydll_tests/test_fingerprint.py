"""civ5headless.fingerprint: reading the probe's lines from a Lua.log and comparing two runs (synthetic logs)."""
from pathlib import Path
import tempfile
import unittest

from civ5headless import fingerprint

REPO = Path(__file__).resolve().parents[2]


def turn_lines(turn, prefix='[1.0] Main: ', point='PlayerDoTurn', p01='00000002', score=6, total=None):
    head = f'C5HFP|v=1|turn={turn}|point={point}'
    total = total or ('%08x' % (1000 + turn))
    return [
        f'{prefix}{head}|part=1/2|total={total}|game={turn:08x}|map=0000000a|players=0000000b|p00=00000001',
        f'{prefix}{head}|part=2/2|p01={p01}|t00=00000003|d00=00000004',
        f'{prefix}C5HM|v=1|turn={turn}|player=0|alive=1|score={score}|gold={turn * 7}|cities=1',
    ]


def log(lines):
    meta = ['InGame: C5HFP|v=1|meta|turn=0|plots=2016|width=56|height=36|maxMajors=22|maxCivs=63|every=1',
            'InGame: C5HFP|v=1|player|turn=0|player=0|team=0|civ=CIVILIZATION_KOREA|leader=LEADER_SEJONG',
            'InGame: C5HFP|v=1|player|turn=0|player=22|team=22|civ=CIVILIZATION_MINOR|minor=MINOR_CIV_GENEVA']
    return '\n'.join(['Main: unrelated line'] + meta + lines) + '\n'


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding='utf-8')
        return p

    def test_read(self):
        lines = turn_lines(0, prefix='InGame: ', point='inject') + turn_lines(1) + turn_lines(2)
        fp = fingerprint.read(self.write('Lua.log', log(lines)))
        self.assertEqual(fp.turns(), [0, 1, 2])
        self.assertEqual(fp.sections[1]['p01'], '00000002')
        self.assertEqual(fp.sections[1]['total'], '%08x' % 1001)
        self.assertNotIn('part', fp.sections[1])
        self.assertEqual(fp.points[0], 'inject')
        self.assertEqual(fp.metrics[2][0]['gold'], 14.0)
        self.assertEqual(fp.meta['plots'], '2016')
        self.assertEqual(fp.players[0]['leader'], 'LEADER_SEJONG')
        self.assertEqual(fp.players[22]['minor'], 'MINOR_CIV_GENEVA')
        self.assertEqual(fp.metric('score', 0), {0: 6.0, 1: 6.0, 2: 6.0})
        self.assertEqual(fp.incomplete, [])
        self.assertEqual(fp.games, 1)

    def test_run_folder_and_incomplete(self):
        run = self.dir / 'run'
        (run / 'Logs').mkdir(parents=True)
        lines = turn_lines(1) + turn_lines(2)[:1]  # turn 2 lost its second part
        (run / 'Logs' / 'Lua.log').write_text(log(lines), encoding='utf-8')
        fp = fingerprint.read(run)
        self.assertEqual(fp.incomplete, [2])

    def test_last_game(self):
        text = log(turn_lines(1, score=1)) + log(turn_lines(1, score=2))
        path = self.write('Lua.log', text)
        self.assertEqual(fingerprint.read(path).metrics[1][0]['score'], 2.0)
        self.assertEqual(fingerprint.read(path, game=0).metrics[1][0]['score'], 1.0)
        self.assertEqual(fingerprint.read(path).games, 2)

    def test_identical_and_sparse(self):
        dense = self.write('a.log', log(sum((turn_lines(t) for t in range(0, 11)), [])))
        sparse = self.write('b.log', log(sum((turn_lines(t, prefix='[9.5] InGame: ') for t in range(0, 11, 5)), [])))
        r = fingerprint.compare(dense, sparse)
        self.assertTrue(r['identical'], fingerprint.summary(r))
        self.assertEqual((r['common'], r['onlyA'], r['onlyB']), (3, 8, 0))

    def test_transient_and_divergence(self):
        a, b = [], []
        for t in range(0, 12):
            a += turn_lines(t)
            bad = t in (3, 4) or t >= 8
            b += turn_lines(t, p01='00000009' if bad else '00000002', score=7 if bad else 6,
                            total='ffffffff' if bad else None)
        r = fingerprint.compare(self.write('a.log', log(a)), self.write('b.log', log(b)), heal_turns=2)
        self.assertFalse(r['identical'])
        self.assertEqual(r['first']['turn'], 3)
        self.assertEqual(r['first']['sections'], ['p01', 'total'])
        self.assertEqual(r['first']['metrics'], {0: {'score': [6.0, 7.0]}})
        self.assertEqual([(x['turn'], x['until']) for x in r['transients']], [(3, 5)])
        self.assertEqual(r['divergence']['turn'], 8)
        self.assertFalse(r['lastPointIdentical'])
        self.assertIn('diverges at turn 8', fingerprint.summary(r))

    def test_extra_player_section_differs(self):
        a = turn_lines(1)
        b = [a[0], a[1] + '|p30=00000005', a[2]]
        r = fingerprint.compare(self.write('a.log', log(a)), self.write('b.log', log(b)))
        self.assertEqual(r['first']['sections'], ['p30'])

    def test_probe_error_line(self):
        lines = turn_lines(1) + ['Main: C5HFP|v=1|turn=2|point=PlayerDoTurn|error=attempt to index a nil value']
        fp = fingerprint.read(self.write('Lua.log', log(lines)))
        self.assertEqual(fp.errors, {2: 'attempt to index a nil value'})
        self.assertEqual(fp.turns(), [1])

    def test_probe_format_matches_reader(self):
        # The probe's documented line heads are the ones the reader looks for.
        text = (REPO / 'probes' / 'fingerprint.lua').read_text(encoding='utf-8')
        for head in ("'C5HFP|v=%d|meta|turn=%d", "'C5HFP|v=%d|player|turn=%d|player=%d", "'C5HFP|v=%d|turn=%d|point=%s'",
                     "'C5HM|v=%d|turn=%d|player=%d'", '%s|part=%d/%d'):
            self.assertIn(head, text)
        self.assertIn('local VERSION = %d' % fingerprint.VERSION, text)


if __name__ == '__main__':
    unittest.main()
