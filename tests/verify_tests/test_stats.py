"""The statistical tier on synthetic games: quantiles, the envelope test, the bias check, the self-test.

A synthetic game has 12 metrics over 120 turns: a growth curve times a per-game level (between-game spread) times a
slowly wandering factor (persistence within a game), which is what makes a plain sign test useless and the
leave-one-out calibration necessary.
"""
import random
import unittest

from civ5headless.verify import selftest, settings as settings_mod, stats


def game(rnd, metrics=12, turns=120, spread=0.08, shift=None, factor=1.0):
    out = {}
    for m in range(metrics):
        level = 1 + spread * rnd.gauss(0, 1)
        x, s = 0.0, {}
        for t in range(turns):
            x = 0.92 * x + rnd.gauss(0, 0.25)
            v = (20 + t * (1 + 0.1 * m)) * level * (1 + 0.02 * x)
            if shift is None or m in shift:
                v *= factor
            s[t] = v
        out[f'replay:M{m}:mean'] = s
    return out


class QuantileTest(unittest.TestCase):
    def test_type7(self):
        v = [1, 2, 3, 4]
        self.assertEqual(stats.quantile(v, 0), 1)
        self.assertEqual(stats.quantile(v, 1), 4)
        self.assertAlmostEqual(stats.quantile(v, 0.5), 2.5)
        self.assertAlmostEqual(stats.quantile(v, 0.25), 1.75)
        self.assertIsNone(stats.quantile([], 0.5))
        self.assertEqual(stats.quantile([7], 0.9), 7)

    def test_columns_need_members(self):
        ens = [{'a': {0: 1.0, 1: 2.0}}, {'a': {0: 3.0}}, {'a': {0: 2.0}}]
        cols = stats.columns(ens, min_members=3)
        self.assertEqual(cols, {'a': {0: [1.0, 2.0, 3.0]}})


class EnvelopeTest(unittest.TestCase):
    def setUp(self):
        self.rnd = random.Random(7)
        self.ens = [game(self.rnd) for _ in range(32)]
        self.em = stats.envelope_model(self.ens, min_members=8)

    def test_expected_coverage_is_measured(self):
        # 32 members, 2.5-97.5% band: a new game gets about 90%, not 95%
        e = stats.envelope_score(self.em, game(self.rnd))
        self.assertGreater(e['expected'], 0.8)
        self.assertLess(e['expected'], 0.95)
        self.assertLessEqual(e['threshold'], 0.95)
        self.assertEqual(len(e['looCoverages']), 32)

    def test_null_games_pass_mostly(self):
        results = [stats.envelope_score(self.em, game(self.rnd))['status'] for _ in range(30)]
        self.assertGreaterEqual(results.count('pass'), 25, results)

    def test_foreign_game_fails(self):
        # another setup: every metric 40% higher
        e = stats.envelope_score(self.em, game(self.rnd, factor=1.4))
        self.assertEqual(e['status'], 'fail')
        self.assertLess(e['coverage'], 0.3)

    def test_too_few_members(self):
        e = stats.envelope(game(self.rnd), self.ens[:3], min_members=8)
        self.assertEqual(e['status'], 'n/a')
        self.assertIn('needed', e['reason'])

    def test_series_detail(self):
        ref = game(self.rnd)
        e = stats.envelope_score(self.em, ref)
        s = e['series']['replay:M0:mean']
        self.assertEqual(s['points'], 120)
        lo, med, hi = s['bands'][60]
        self.assertLessEqual(lo, med)
        self.assertLessEqual(med, hi)
        self.assertEqual(s['inside'] + len(s['outsideTurns']), s['points'])


class BiasTest(unittest.TestCase):
    def setUp(self):
        self.rnd = random.Random(11)
        self.ens = [game(self.rnd) for _ in range(32)]
        self.bm = stats.bias_model(self.ens, min_members=8)

    def test_null_games_rarely_flagged(self):
        flagged = sum(stats.bias_score(self.bm, game(self.rnd))['status'] == 'warn' for _ in range(40))
        self.assertLessEqual(flagged, 6)  # max-T at alpha 0.05: a few false flags in 40 at most

    def test_shifted_metric_is_flagged(self):
        ref = game(self.rnd, shift={3}, factor=1.5)
        b = stats.bias_score(self.bm, ref)
        self.assertEqual(b['status'], 'warn')
        self.assertEqual(b['flagged'][0], 'replay:M3:mean')
        self.assertGreaterEqual(b['series']['replay:M3:mean']['signFraction'], 0.9)
        self.assertEqual(b['series']['replay:M3:mean']['side'], 'above')

    def test_detectable_shift_matches_the_spread(self):
        b = stats.bias_score(self.bm, game(self.rnd))
        shifts = [v['detectableShift'] for v in b['series'].values()]
        # an 8% between-game spread: shifts of a few tens of percent are needed for one game
        self.assertTrue(all(0.05 < s < 1.0 for s in shifts), shifts)
        twice = stats.bias_model([game(self.rnd, spread=0.02) for _ in range(32)], min_members=8)
        tight = stats.bias_score(twice, game(self.rnd, spread=0.02))
        self.assertLess(max(v['detectableShift'] for v in tight['series'].values()), min(shifts))

    def test_shifted_helper(self):
        g = {'a': {0: 1.0, 1: None}, 'b': {0: 2.0}}
        s = stats.shifted(g, 2.0, {'a'})
        self.assertEqual(s, {'a': {0: 2.0, 1: None}, 'b': {0: 2.0}})


class SelfTestTest(unittest.TestCase):
    def test_selftest_summary(self):
        rnd = random.Random(3)
        ens = [game(rnd, metrics=6, turns=60) for _ in range(16)]
        s = settings_mod.build('host-only', dict(min_members=8, stats_from_turn=0, turns=60))
        foreign = [('other-map', game(rnd, metrics=6, turns=60, factor=1.5))]
        r = selftest.run(ens, s, holdouts=6, shift_holdouts=2, shift=0.6, foreign=foreign, log=lambda m: None)
        sm = r['summary']
        self.assertEqual(sm['holdouts'], 6)
        self.assertGreaterEqual(sm['envelopePass'] + sm['envelopeWarn'], 5)
        self.assertEqual(sm['foreignCaught'], 1)
        self.assertEqual(sm['metrics'], 6)
        self.assertGreaterEqual(sm['shiftDetected'], 4)  # a 60% shift is far beyond an 8% spread
        too_few = selftest.run(ens[:5], s, log=lambda m: None)
        self.assertIn('error', too_few)


if __name__ == '__main__':
    unittest.main()
