"""The suite's parts: exact comparisons, series, settings, the real side's normalisation, performance, history, the
report, and the no-machine-paths rule for this workstream's files."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from civ5headless.verify import exact, hostside, perf, realside, report, series, settings as settings_mod

import fakegame

REPO = Path(__file__).resolve().parents[2]


def write_game(folder, spec, turns, **kw):
    """A run folder as the fake host writes it (digests, Lua.log lines, checkpoints, replay data)."""
    g = fakegame.Game(spec, **kw)
    folder = Path(folder)
    (folder / 'Logs').mkdir(parents=True)
    (folder / 'checkpoints').mkdir()
    (folder / 'Logs/HeadlessDigest.log').write_text(''.join(g.digest_line(t) + '\n' for t in range(turns)), encoding='utf-8')
    lines = g.pregame_lines() + [x for t in range(turns) for x in g.fingerprint_lines(t)]
    (folder / 'Logs/Lua.log').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for t in range(turns + 1):
        (folder / f'checkpoints/turn-{t:04d}.json').write_text(json.dumps(dict(data=g.checkpoint(t))), encoding='utf-8')
    (folder / 'replay-data.json').write_text(json.dumps(g.replay_data(turns)), encoding='utf-8')
    return folder


SPEC = {'seeds': {'map': 3, 'sync': 4}, 'map': {'file': 'Continents.lua'}}


class ExactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sections_divergence_transient_ui(self):
        a = {t: {'p00': 'a', 'p01': 'b', 'savedb': 'x'} for t in range(10)}
        b = {t: dict(v) for t, v in a.items()}
        b[2]['p00'] = 'changed'            # heals at turn 3: transient
        b[4]['savedb'] = 'ui'              # UI-only
        for t in range(6, 10):
            b[t]['p01'] = 'gone'           # lasting from turn 6
        r = exact.compare_sections(a, b, heal_turns=2, ui_sections=('savedb',))
        self.assertFalse(r['identical'])
        self.assertEqual(r['matchedTurns'], 6)
        self.assertEqual(r['divergence'], dict(turn=6, until=None, sections=['p01']))
        self.assertEqual(r['transients'], [dict(turn=2, until=3, sections=['p00'])])
        self.assertEqual(r['uiOnly'], [dict(turn=4, sections=['savedb'])])
        same = exact.compare_sections(a, a)
        self.assertTrue(same['identical'])
        self.assertEqual(same['matchedTurns'], 10)

    def test_slow_heal_is_a_divergence(self):
        a = {t: {'p': 'x'} for t in range(10)}
        b = {t: {'p': 'y' if 2 <= t < 6 else 'x'} for t in range(10)}
        r = exact.compare_sections(a, b, heal_turns=2)
        self.assertEqual(r['divergence']['turn'], 2)
        self.assertEqual(r['divergence']['until'], 6)
        self.assertEqual(r['matchedTurns'], 2)

    def test_methods_on_run_folders(self):
        from civ5headless import fingerprint
        a = write_game(self.root / 'a', SPEC, 8)
        b = write_game(self.root / 'b', SPEC, 8, diverge_at=5, tag='x')
        self.assertEqual(exact.available(a, b, fingerprint), 'digest')
        for method in ('digest', 'fingerprint', 'checkpoint'):
            r = exact.compare(a, b, method, 2, fingerprint)
            self.assertEqual(r['method'], method)
            self.assertEqual(r['divergence']['turn'], 5, method)
        (a / 'Logs/HeadlessDigest.log').unlink()
        self.assertEqual(exact.available(a, b, fingerprint), 'fingerprint')
        self.assertIsNone(exact.available(a, b, None))
        self.assertEqual(exact.available(a, b, None, host_only=True), 'checkpoint')
        self.assertIn('lasting difference from turn 5', exact.summary(exact.compare(a, b, 'checkpoint')))

    def test_same_game_ignores_the_seed_sections(self):
        a = write_game(self.root / 'a', SPEC, 6)
        b = write_game(self.root / 'b', dict(SPEC, seeds={'map': 3, 'sync': 99}), 6)
        c = write_game(self.root / 'c', dict(SPEC, seeds={'map': 3, 'sync': 99}), 6, sync_matters=True)
        self.assertEqual(exact.same_game(a, b), (True, 'digest'))
        self.assertEqual(exact.same_game(a, c), (False, 'digest'))
        for d in (a, c):
            (d / 'Logs/HeadlessDigest.log').unlink()
        self.assertEqual(exact.same_game(a, c), (False, 'replay data and checkpoints'))

    def test_pregame_and_lua_errors(self):
        a = write_game(self.root / 'a', SPEC, 2)
        v = exact.pregame_values(a)
        self.assertEqual(v['GetMapScript'], 'Continents.lua')
        diff, only_a, only_b = exact.compare_values(v, dict(v, GetWorldSize='9', GetNickName='other'), ignore=['GetNickName'])
        self.assertEqual(diff, [('GetWorldSize', v['GetWorldSize'], '9')])
        self.assertEqual((only_a, only_b), ([], []))
        log = self.root / 'Lua.log'
        log.write_text('[12.5] Runtime Error: MODS\\Mod\\UI\\Thing.lua:12: attempt to index a nil value\n'
                       '[12.6] stack traceback:\n[13.0] fine\n', encoding='utf-8')
        errors = exact.lua_errors(log)
        self.assertEqual(list(errors), ['Runtime Error: Thing.lua:12: attempt to index a nil value'])


class SeriesTest(unittest.TestCase):
    def test_replay_aggregates(self):
        data = {'0': {'REPLAYDATASET_SCORE': [[1, 10], [2, 20]]}, '1': {'REPLAYDATASET_SCORE': [[2, 40], [1, 30]]},
                '2': {'REPLAYDATASET_SCORE': [[1, 'bad']]}}
        s = series.from_replay(data)
        self.assertEqual(s['replay:SCORE:mean'], {1: 20.0, 2: 30.0})
        self.assertEqual(s['replay:SCORE:max'], {1: 30.0, 2: 40.0})
        self.assertEqual(series.label('replay:SCORE:mean'), 'Score (mean)')
        self.assertEqual(series.from_replay(data, exclude=('SCORE',)), {})

    def test_metric_aggregates(self):
        m = {0: {0: {'cities': 1, 'gold': 5}, 1: {'cities': 3}}}
        s = series.from_metrics(m, aggregates=('mean', 'max', 'min', 'sum'))
        self.assertEqual(s['lua:cities:mean'], {0: 2.0})
        self.assertEqual(s['lua:cities:sum'], {0: 4.0})
        self.assertEqual(s['lua:gold:min'], {0: 5.0})


class SettingsTest(unittest.TestCase):
    def test_precedence(self):
        table = {'turns': 100, 'workers': 6, 'host-only': {'ensemble': 5}, 'quick': {'workers': 7}}
        s = settings_mod.build('host-only', table, {'workers': 3, 'turns': None})
        self.assertEqual((s.turns, s.workers, s.ensemble, s.real, s.budget_minutes), (100, 3, 5, False, 5.0))
        q = settings_mod.build('quick', table)
        self.assertEqual((q.workers, q.ensemble, q.real, q.low_priority), (7, 32, True, True))
        f = settings_mod.build('full')
        self.assertEqual((f.real_aa, f.standard_turns, f.ensemble, f.victory_games), (True, 60, 64, 4))

    def test_errors(self):
        with self.assertRaises(settings_mod.SettingsError):
            settings_mod.build('quick', {'no_such_key': 1})
        with self.assertRaises(settings_mod.SettingsError):
            settings_mod.build('nightly')
        with self.assertRaises(settings_mod.SettingsError):
            settings_mod.build('quick', {'ensemble_vary': 'civs'})

    def test_spec_overrides_and_seeds(self):
        s = settings_mod.build('quick', overrides=dict(map='Assets/Maps/Pangaea.lua', size='WORLDSIZE_SMALL', players=5,
                                                        seeds=[7, 8], ensemble=3, ensemble_seed=8))
        spec = s.trajectory_spec()
        self.assertEqual(spec['map'], {'script': 'Assets/Maps/Pangaea.lua', 'size': 'WORLDSIZE_SMALL'})
        self.assertEqual((spec['majors'], spec['seeds']), (5, {'map': 7, 'sync': 8}))
        self.assertEqual(s.ensemble_seeds('sync'), [(7, 9), (7, 10), (7, 11)])   # 8 is the trajectory's sync seed
        self.assertEqual(s.ensemble_seeds('map'), [(8, 8), (9, 8), (10, 8)])     # 7 is its map seed
        self.assertEqual(settings_mod.DEFAULT_SPEC['seeds'], {'map': 30017, 'sync': 40017})  # untouched

    def test_spec_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 's.json'
            p.write_text(json.dumps({'map': {'script': 'X.lua'}}), encoding='utf-8')
            s = settings_mod.build('quick', {'spec': str(p), 'setups': [str(p), {'name': 'y'}]})
            self.assertEqual(s.spec, {'map': {'script': 'X.lua'}})
            self.assertEqual(s.setups, [{'map': {'script': 'X.lua'}}, {'name': 'y'}])


class RealSideTest(unittest.TestCase):
    def test_autoplay_shapes(self):
        a = realside._autoplay({'turnSeconds': {'1': 2.0, '2': 5.0}, 'endTurn': 2, 'endReason': 'target', 'x': 1}, 2)
        self.assertEqual(a['turnSeconds'], {'1': 2.0, '2': 5.0})
        self.assertEqual((a['endTurn'], a['endReason'], a['extra']), (2, 'target', {'x': 1}))
        b = realside._autoplay({'turn_durations': {'1': 2.0, '2': 3.0}}, 2)
        self.assertEqual(b['turnSeconds'], {'1': 2.0, '2': 5.0})
        self.assertEqual(b['endTurn'], 2)
        c = realside._autoplay([1.0, 2.5], 2)
        self.assertEqual(c['turnSeconds'], {'1': 1.0, '2': 2.5})
        d = realside._autoplay({'turn_times': [{'turn': 3, 'seconds': 4}]}, 3)
        self.assertEqual(d['turnSeconds'], {'3': 4.0})
        self.assertEqual(realside._autoplay(None, 5)['turnSeconds'], {})


class PerfTest(unittest.TestCase):
    def test_thirds(self):
        times = {t: t * 1.0 + (t > 60) * (t - 60) for t in range(1, 91)}
        p = perf.thirds(times, 90)
        self.assertEqual((p['early'], p['mid'], p['late']), (1.0, 1.0, 2.0))
        self.assertEqual(p['ranges'], [[1, 30], [31, 60], [61, 90]])
        self.assertEqual(p['all'], round(120 / 90, 3))
        self.assertEqual(perf.thirds({}), {})

    def test_history_and_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = perf.history_path(tmp, 'My PC/1')
            self.assertEqual(path.name, 'my_pc_1.jsonl')
            for k, spt in enumerate((1.0, 1.02, 0.98, 1.0)):
                perf.append_history(path, dict(setupKey='S', mode='quick', dllSHA256='A', host=dict(perTurn=dict(all=spt))))
            perf.append_history(path, dict(setupKey='T', mode='quick', host=dict(perTurn=dict(all=9.0))))
            hist = perf.load_history(path)
            self.assertEqual(len(hist), 5)
            slow = perf.regression(hist, dict(setupKey='S', mode='quick', dllSHA256='B', host=dict(perTurn=dict(all=1.3))))
            self.assertEqual(slow['status'], 'warn')
            self.assertEqual(slow['changed'], ['dllSHA256'])
            self.assertAlmostEqual(slow['change'], 0.3)
            ok = perf.regression(hist, dict(setupKey='S', mode='quick', dllSHA256='A', host=dict(perTurn=dict(all=1.05))))
            self.assertEqual(ok['status'], 'pass')
            self.assertIsNone(perf.regression(hist, dict(setupKey='S', mode='full', host=dict(perTurn=dict(all=1.0)))))

    def test_throughput_and_window(self):
        phases = [dict(name='single', workers=1, throughput=True, completed=1, seconds=100.0, turns=150, started=0, finished=100,
                       gamesPerHour=36.0, turnsPerHour=5400.0, meanGameSeconds=99.0),
                  dict(name='setups', workers=8, throughput=False, completed=8, seconds=10.0, turns=8, started=0, finished=10)]
        samples = [dict(t=50, busyCores=2.0, gameBusyCores=0.0, hosts=1), dict(t=200, busyCores=9.0, gameBusyCores=3.0, hosts=8)]
        rows = perf.throughput(phases, samples)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['workers'], rows[0]['gamesPerHour'], rows[0]['load']['busyCores']), (1, 36.0, 2.0))

    def test_cost_model(self):
        c = hostside.CostModel()
        prior = c.estimate('WORLDSIZE_TINY', 150)
        self.assertGreater(prior, 50)
        self.assertGreater(c.estimate('WORLDSIZE_STANDARD', 150), 3 * prior)
        c.observe('WORLDSIZE_TINY', [(t, 0.5 * t) for t in range(1, 101)], host_seconds=55.0, wall_seconds=50.0)
        self.assertAlmostEqual(c.estimate('WORLDSIZE_TINY', 50), 5.0 + 25.0)
        self.assertGreater(c.estimate('WORLDSIZE_TINY', 150), 5.0 + 75.0 - 1e-9)
        c.observe('WORLDSIZE_TINY', [(1, 0.1)], host_seconds=3.0, wall_seconds=0.1)  # too short to replace the curve
        self.assertAlmostEqual(c.estimate('WORLDSIZE_TINY', 50), 2.9 + 25.0)


class ReportTest(unittest.TestCase):
    def test_minimal_document(self):
        doc = dict(mode='host-only', verdict='warn', exitCode=0, headline='Host only: <x> & y', checks=[
            dict(id='trajectory.aa', section='trajectory', title='A/A', status='warn', summary='s', details=dict(k=[1]))],
            statistics=dict(charts=[dict(series='replay:SCORE:mean', label='Score (mean)', coverage=0.9, turns=[1, 2, 3],
                                         lo=[1, 2, 3], median=[2, 3, 4], hi=[3, 4, 5], reference=[2, 9, None], bias=None)],
                            envelope=dict(coverage=0.9, band=[0.025, 0.975]), bias=dict(flagged=[])),
            comparisons=dict(aa=dict(method='digest', matchedTurns=5, compared=10, firstTurn=0, healTurns=2,
                                     divergence=dict(turn=5, until=None, sections=['p01']), transients=[dict(turn=2, until=3)],
                                     uiOnly=[])))
        html = report.html(doc)
        self.assertIn('Host only: &lt;x&gt; &amp; y', html)
        self.assertIn('<svg', html)
        self.assertIn('turn 5: p01', html)
        self.assertNotIn('<script', html)


class NoMachinePathsTest(unittest.TestCase):
    """This workstream's code, docs and tests name no drive paths, user folders or user name."""

    def files(self):
        out = [REPO / 'docs/verification.md'] if (REPO / 'docs/verification.md').is_file() else []
        for tree in ('python/civ5headless/verify', 'tests/verify_tests'):
            out += [p for p in (REPO / tree).rglob('*') if p.is_file() and p.suffix in ('.py', '.json', '.md', '.toml', '.cmd', '.lua')]
        return out

    def test_no_machine_paths(self):
        drive = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]')
        users = re.compile(r'[\\/]Users[\\/]', re.I)
        names = {n for n in (os.environ.get('USERNAME'), os.environ.get('USER')) if n and len(n) >= 4}
        found = []
        for p in self.files():
            for n, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if drive.search(line) or users.search(line) or any(name.lower() in line.lower() for name in names):
                    found.append(f'{p.relative_to(REPO)}:{n}: {line.strip()[:100]}')
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
