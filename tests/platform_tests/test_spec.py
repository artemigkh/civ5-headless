"""Game spec resolution (spec.py) against a small synthetic game database, and run.py's spec handling."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from civ5headless import run, spec

REPO = Path(__file__).resolve().parents[2]

SCHEMA = [
    'CREATE TABLE Worlds(ID INTEGER, Type TEXT, DefaultPlayers INTEGER, DefaultMinorCivs INTEGER)',
    'CREATE TABLE MapScripts(FileName TEXT, SupportsSinglePlayer INTEGER, Hidden INTEGER)',
    'CREATE TABLE MapScriptOptions(FileName TEXT, OptionID TEXT, Name TEXT)',
    'CREATE TABLE MapScriptOptionPossibleValues(FileName TEXT, OptionID TEXT, Value INTEGER, Name TEXT)',
    'CREATE TABLE Map_Sizes(FileName TEXT, MapType TEXT, WorldSizeType TEXT)',
    'CREATE TABLE GameSpeeds(ID INTEGER, Type TEXT)',
    'CREATE TABLE Eras(ID INTEGER, Type TEXT)',
    'CREATE TABLE HandicapInfos(ID INTEGER, Type TEXT)',
    'CREATE TABLE Victories(ID INTEGER, Type TEXT)',
    'CREATE TABLE GameOptions(ID INTEGER, Type TEXT, SupportsSinglePlayer INTEGER)',
    'CREATE TABLE Civilizations(ID INTEGER, Type TEXT, Playable INTEGER)',
]
ROWS = {
    'Worlds': [(0, 'WORLDSIZE_DUEL', 2, 4), (1, 'WORLDSIZE_TINY', 4, 8), (3, 'WORLDSIZE_STANDARD', 8, 16)],
    'MapScripts': [('Assets\\Maps\\Continents.lua', 1, 0), ('Assets\\Maps\\Pangaea.lua', 1, 0),
                   ('Assets\\DLC\\Expansion2\\Maps\\Hidden.lua', 1, 1),
                   ('<MODS>\\(2) Vox Populi\\Mapscripts/Communitu_79a.lua', 1, 0)],
    'MapScriptOptions': [('Assets\\Maps\\Continents.lua', '1', 'TXT_KEY_MAP_OPTION_SEA_LEVEL'),
                         ('Assets\\Maps\\Continents.lua', '2', 'TXT_KEY_MAP_OPTION_RAINFALL'),
                         ('Assets\\Maps\\Continents.lua', '3', 'TXT_KEY_MAP_OPTION_TOGGLE')],
    'MapScriptOptionPossibleValues': [('Assets\\Maps\\Continents.lua', '1', v, f'SEA_{v}') for v in (1, 2, 3, 4)]
    + [('Assets\\Maps\\Continents.lua', '2', 1, 'Arid'), ('Assets\\Maps\\Continents.lua', '2', 2, 'Normal'),
       ('Assets\\Maps\\Continents.lua', '2', 3, 'Wet')],
    'Map_Sizes': [('Assets\\Maps\\Earth_Small.Civ5Map', 'MAP_EARTH', 'WORLDSIZE_TINY'),
                  ('Assets\\Maps\\Earth_Standard.Civ5Map', 'MAP_EARTH', 'WORLDSIZE_STANDARD')],
    'GameSpeeds': [(0, 'GAMESPEED_MARATHON'), (2, 'GAMESPEED_STANDARD'), (3, 'GAMESPEED_QUICK')],
    'Eras': [(0, 'ERA_ANCIENT'), (1, 'ERA_CLASSICAL')],
    'HandicapInfos': [(3, 'HANDICAP_PRINCE'), (5, 'HANDICAP_EMPEROR')],
    'Victories': [(0, 'VICTORY_TIME'), (1, 'VICTORY_SPACE_RACE'), (2, 'VICTORY_DOMINATION')],
    'GameOptions': [(0, 'GAMEOPTION_RAGING_BARBARIANS', 1), (1, 'GAMEOPTION_PITBOSS', 0)],
    'Civilizations': [(0, 'CIVILIZATION_AMERICA', 1), (1, 'CIVILIZATION_GREECE', 1), (2, 'CIVILIZATION_MINOR', 0)],
}


def make_db(path):
    con = sqlite3.connect(path)
    for stmt in SCHEMA:
        con.execute(stmt)
    for table, rows in ROWS.items():
        con.executemany(f'INSERT INTO {table} VALUES({",".join("?" * len(rows[0]))})', rows)
    con.commit()
    con.close()


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'game.db'
        make_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self, s):
        return spec.resolve(s, self.db)

    def test_script_map(self):
        r = self.resolve({'map': {'script': 'Assets/Maps/Continents.lua', 'size': 'WORLDSIZE_TINY',
                                  'options': {'TXT_KEY_MAP_OPTION_SEA_LEVEL': 3, '2': 'Wet', 'TXT_KEY_MAP_OPTION_TOGGLE': True}},
                          'majors': 3, 'slots': [{'slot': 1, 'civ': 'CIVILIZATION_GREECE', 'team': 0}],
                          'gameOptions': {'GAMEOPTION_RAGING_BARBARIANS': True}, 'victories': ['VICTORY_DOMINATION'],
                          'maxTurns': 200, 'seeds': {'map': 7, 'sync': 8}})
        self.assertEqual(r['specVersion'], 1)
        self.assertEqual(r['seeds'], {'map': 7, 'sync': 8})
        self.assertEqual(r['map'], {'kind': 'script', 'file': 'Assets\\Maps\\Continents.lua',
                                    'options': {1: {'name': 'TXT_KEY_MAP_OPTION_SEA_LEVEL', 'value': 3},
                                                2: {'name': 'TXT_KEY_MAP_OPTION_RAINFALL', 'value': 3},
                                                3: {'name': 'TXT_KEY_MAP_OPTION_TOGGLE', 'value': 1}}})
        self.assertEqual(r['worldSize'], {'type': 'WORLDSIZE_TINY', 'id': 1})
        self.assertEqual(r['speed'], {'type': 'GAMESPEED_STANDARD', 'id': 2})
        self.assertEqual(r['era'], {'type': 'ERA_ANCIENT', 'id': 0})
        self.assertEqual(r['difficulty'], {'type': 'HANDICAP_EMPEROR', 'id': 5})
        self.assertEqual((r['majors'], r['cityStates'], r['maxTurns']), (3, 8, 200))
        self.assertEqual({k: v['enabled'] for k, v in r['victories'].items()},
                         {'VICTORY_TIME': False, 'VICTORY_SPACE_RACE': False, 'VICTORY_DOMINATION': True})
        self.assertEqual(r['gameOptions'], {'GAMEOPTION_RAGING_BARBARIANS': {'id': 0, 'value': 1}})
        self.assertEqual(len(r['slots']), spec.MAX_MAJOR_CIVS)
        self.assertEqual([s['status'] for s in r['slots'][:4]], ['taken', 'computer', 'computer', 'closed'])
        self.assertEqual(r['slots'][1], {'slot': 1, 'status': 'computer', 'civ': 'CIVILIZATION_GREECE', 'civId': 1, 'team': 0})
        self.assertEqual(r['slots'][2], {'slot': 2, 'status': 'computer', 'civ': 'random', 'civId': -1, 'team': 2})

    def test_defaults_follow_world_size(self):
        r = self.resolve({'seeds': {'map': 1, 'sync': 2}})
        self.assertEqual(r['map']['file'], 'Assets\\Maps\\Continents.lua')
        self.assertEqual(r['worldSize']['type'], 'WORLDSIZE_STANDARD')
        self.assertEqual((r['majors'], r['cityStates']), (8, 16))
        self.assertTrue(all(v['enabled'] for v in r['victories'].values()))
        self.assertEqual(r['map']['options'], {})

    def test_file_suffix_match(self):
        self.assertEqual(self.resolve({'map': {'script': 'Pangaea.lua'}})['map']['file'], 'Assets\\Maps\\Pangaea.lua')
        r = self.resolve({'map': {'script': '(2) Vox Populi/Mapscripts/Communitu_79a.lua'}})
        self.assertEqual(r['map']['file'], '<MODS>\\(2) Vox Populi\\Mapscripts/Communitu_79a.lua')

    def test_premade_maps(self):
        r = self.resolve({'map': {'civ5map': 'Assets/Maps/Earth_Small.Civ5Map'}})
        self.assertEqual(r['map'], {'kind': 'civ5map', 'file': 'Assets\\Maps\\Earth_Small.Civ5Map', 'mapType': 'MAP_EARTH', 'options': {}})
        self.assertEqual(r['worldSize']['type'], 'WORLDSIZE_TINY')
        r = self.resolve({'map': {'type': 'MAP_EARTH', 'size': 'WORLDSIZE_STANDARD'}})
        self.assertEqual(r['map']['file'], 'Assets\\Maps\\Earth_Standard.Civ5Map')

    def test_random_choices_follow_the_seeds(self):
        s = {'map': {'script': 'random', 'size': 'random'}, 'seeds': {'map': 11, 'sync': 12}}
        a, b = self.resolve(s), self.resolve(s)
        self.assertEqual(a, b)
        self.assertNotIn('Hidden.lua', a['map']['file'])
        self.assertIn(a['worldSize']['type'], [w[1] for w in ROWS['Worlds']])

    def test_seeds_drawn_when_absent(self):
        r = self.resolve({'seeds': {'map': 5}})
        self.assertEqual(r['seeds']['map'], 5)
        self.assertTrue(1 <= r['seeds']['sync'] < 2 ** 31)

    def test_errors(self):
        bad = [
            {'map': {'size': 'WORLDSIZE_HUGE'}},
            {'map': {'script': 'Nowhere.lua'}},
            {'map': {'script': 'Continents.lua', 'options': {'TXT_KEY_MAP_OPTION_NONE': 1}}},
            {'map': {'script': 'Continents.lua', 'options': {'TXT_KEY_MAP_OPTION_SEA_LEVEL': 9}}},
            {'majors': 0}, {'majors': spec.MAX_MAJOR_CIVS},
            {'majors': 2, 'slots': [{'slot': 3, 'civ': 'CIVILIZATION_GREECE'}]},
            {'slots': [{'slot': 1, 'civ': 'CIVILIZATION_MINOR'}]},
            {'gameOptions': {'GAMEOPTION_PITBOSS': True}},
            {'victories': ['VICTORY_CULTURE']},
            {'speed': 'GAMESPEED_LIGHTNING'},
        ]
        for s in bad:
            with self.subTest(spec=s), self.assertRaises(spec.SpecError):
                self.resolve(dict(s, seeds={'map': 1, 'sync': 1}))

    def test_ambiguous_suffix(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO MapScripts VALUES('Assets\\DLC\\Maps\\Pangaea.lua', 1, 0)")
        con.commit()
        con.close()
        with self.assertRaises(spec.SpecError) as error:
            self.resolve({'map': {'script': 'Pangaea.lua'}})
        self.assertIn('matches 2', str(error.exception))

    def test_pregame_lua(self):
        r = self.resolve({'map': {'script': 'Continents.lua', 'size': 'WORLDSIZE_TINY', 'options': {'TXT_KEY_MAP_OPTION_SEA_LEVEL': 2}},
                          'speed': 'GAMESPEED_QUICK', 'slots': [{'slot': 1, 'civ': 'CIVILIZATION_GREECE', 'team': 0}],
                          'seeds': {'map': 1, 'sync': 2}})
        lua = spec.pregame_lua(r)
        self.assertIn('PreGame.SetMapScript("Assets\\\\Maps\\\\Continents.lua")', lua)
        self.assertIn('PreGame.SetWorldSize(1);PreGame.SetNumMinorCivs(8)', lua)
        # standard speed first (turn timer), then the spec's
        self.assertLess(lua.index('GAMESPEED_STANDARD.ID'), lua.index('PreGame.SetGameSpeed(3)'))
        self.assertIn('PreGame.SetMapOption(1,2)', lua)
        self.assertIn('PreGame.SetSlotStatus(3,SlotStatus.SS_COMPUTER)', lua)
        self.assertIn('PreGame.SetSlotStatus(4,SlotStatus.SS_CLOSED)', lua)
        self.assertIn('PreGame.SetCivilization(1,1)', lua)
        self.assertIn('PreGame.SetTeam(1,0)', lua)
        self.assertTrue(lua.rstrip().endswith('return out'))


class RunSpecTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.db = self.folder / 'game.db'
        make_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_spec_and_seeds(self):
        raw = self.folder / 'tiny.json'
        raw.write_text(json.dumps({'map': {'script': 'Continents.lua', 'size': 'WORLDSIZE_TINY'}, 'seeds': {'map': 1, 'sync': 2}}),
                       encoding='utf-8')
        resolved = run.resolve_spec(raw, self.db)
        self.assertEqual(resolved['seeds'], {'map': 1, 'sync': 2})
        reseeded = run.resolve_spec(raw, self.db, {'map': 3, 'sync': 4})
        self.assertEqual(reseeded['seeds'], {'map': 3, 'sync': 4})
        self.assertEqual(dict(reseeded, seeds=None), dict(resolved, seeds=None))
        # an already resolved spec is used as is, with new seeds when given
        done = self.folder / 'tiny-resolved.json'
        done.write_text(json.dumps(resolved), encoding='utf-8')
        self.assertEqual(run.resolve_spec(done, self.folder / 'no-database-needed.db'), resolved)
        self.assertEqual(run.resolve_spec(done, None, {'sync': 9})['seeds'], {'map': 1, 'sync': 9})
        key = run.spec_key(resolved, done)
        self.assertRegex(key, r'^headless-tiny-m1-s2-[0-9a-f]{8}$')
        self.assertEqual(key, run.spec_key(json.loads(json.dumps(resolved)), raw))


class ExampleSpecsTest(unittest.TestCase):
    def test_examples_are_specs(self):
        files = sorted((REPO / 'examples/specs').glob('*.json'))
        self.assertTrue(files)
        for p in files:
            with self.subTest(spec=p.name):
                s = json.loads(p.read_text(encoding='utf-8'))
                self.assertIn('map', s)
                self.assertEqual(set(s['seeds']), {'map', 'sync'})
                self.assertFalse(set(s) - {'map', 'speed', 'era', 'difficulty', 'majors', 'cityStates', 'slots', 'gameOptions',
                                           'victories', 'maxTurns', 'seeds'})


if __name__ == '__main__':
    unittest.main()
