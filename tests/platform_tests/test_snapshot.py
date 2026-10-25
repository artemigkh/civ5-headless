"""snapshot: the DLC snapshot plan written from a synthetic game folder (no host), and with C5H_INTEGRATION=1 a real
build from the installed game.
"""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from civ5headless import config, dbdiff, snapshot

GUIDS = {'Expansion': '0E3751A1-F840-4E1B-9706-519BF484E59D', 'Expansion2': '6DA07636-4123-4018-B643-6575B4EC336B',
         'DLC_01': '293C1EE3-1176-44F6-AC1F-59663826DE74', 'DLC_02': 'B685D5DE-7CCA-4E75-8B2F-B9A04E9FCB80',
         'VPUI': '8D9A4F6B-0000-4000-8000-000000000001'}


def package(folder, priority=None, key=True, gamedata=(), gameplay=None, maps=None, upgrade=False, free=False):
    parts = [f'<GUID>{{{GUIDS[folder]}}}</GUID>', '<Version>2</Version>']
    if priority is not None:
        parts.append(f'<Priority>{priority}</Priority>')
    if key:
        parts.append('<Key>0123456789abcdef</Key>')
    if free:
        parts.append('<Ownership>FREE</Ownership>')
    if upgrade:
        parts.append('<Upgrade>1</Upgrade>')
    parts += [f'<GameData>{g}</GameData>' for g in gamedata]
    if gameplay is not None:
        core, files = gameplay
        parts.append('<Gameplay>' + (f'<GameCore>{core}</GameCore>' if core else '') +
                     ''.join(f'<GameData>{g}</GameData>' for g in files) +
                     (f'<MapDirectory>{maps}</MapDirectory>' if maps else '') + '</Gameplay>')
    return '<?xml version="1.0" encoding="utf-8"?>\n<Civ5Package>' + ''.join(parts) + '</Civ5Package>\n'


def make_game(root):
    game = Path(root) / 'game'
    dlc = game / 'Assets/DLC'
    files = {
        'Expansion/Expansion.Civ5Pkg': package('Expansion', 100, gameplay=('CvGameCore_Expansion1.dll', ['Gnk.xml'])),
        'Expansion/Gameplay/Gnk.xml': '<GameData/>',
        'Expansion2/Expansion2.Civ5Pkg': package('Expansion2', 200, gameplay=('CvGameCore_Expansion2.dll', ['Bnw.sql']),
                                                maps='Maps'),
        'Expansion2/Gameplay/Bnw.sql': '-- bnw',
        'Expansion2/Maps/Pangaea_XP2.lua': '-- map',
        'Expansion2/DLC/Expansion/Gnk.xml': '<GameData/>',
        'Expansion2/DLC/DLC_01/Mongol.xml': '<GameData/>',
        'DLC_01/DLC_01.Civ5Pkg': package('DLC_01', gamedata=['Mongol.xml', 'Units_Mongol.xml'], free=True),
        'DLC_01/Data/Mongol.xml': '<GameData/>',
        'DLC_01/Data/Units_Mongol.xml': '<GameData/>',
        'DLC_02/DLC_02.Civ5Pkg': package('DLC_02', gameplay=(None, ['Spain.xml']), maps='Maps', upgrade=True),
        'DLC_02/Spain.xml': '<GameData/>',
        'DLC_02/Maps/Spain.lua': '-- map',
        'VPUI/VPUI.Civ5Pkg': package('VPUI', 300, key=False),
    }
    for rel, text in files.items():
        (dlc / rel).parent.mkdir(parents=True, exist_ok=True)
        (dlc / rel).write_text(text, encoding='utf-8')
    (game / 'Assets/Maps').mkdir(parents=True)
    for name in ('Pangaea.lua', 'continents.lua'):
        (game / 'Assets/Maps' / name).write_text('-- map', encoding='utf-8')
    user = Path(root) / 'user'
    (user / 'Maps').mkdir(parents=True)
    (user / 'Maps/Random Luxuries.lua').write_text('-- map', encoding='utf-8')
    return game, user


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game, self.user = make_game(self.tmp.name)
        self.dlc = self.game / 'Assets/DLC'

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, postprocess=False):
        core = Path(self.tmp.name) / 'core.db'
        core.write_bytes(b'')
        path = snapshot.write_plan(self.game, self.user, core, Path(self.tmp.name) / 'work', postprocess)
        return [line.split('\t') for line in path.read_text(encoding='utf-8').splitlines()]

    def test_package_order(self):
        # no Priority counts as 0; equal priorities go by folder name
        self.assertEqual([p['folder'] for p in snapshot.packages(self.game)], ['DLC_01', 'DLC_02', 'Expansion', 'Expansion2', 'VPUI'])

    def test_gamedata_order_and_overrides(self):
        steps = [(s[0], Path(s[1])) for s in self.plan() if s[0] in ('xml', 'sql') and not Path(s[1]).parent.name == 'work']
        self.assertEqual([(k, p.relative_to(self.dlc).as_posix()) for k, p in steps], [
            ('xml', 'Expansion2/DLC/DLC_01/Mongol.xml'),   # the gameplay owner's copy wins
            ('xml', 'DLC_01/Data/Units_Mongol.xml'),
            ('xml', 'DLC_02/Spain.xml'),                   # a Gameplay section without GameCore
            ('xml', 'Expansion2/DLC/Expansion/Gnk.xml'),
            ('sql', 'Expansion2/Gameplay/Bnw.sql'),
        ])

    def test_package_ids_tagged(self):
        plan = self.plan()
        work = Path(self.tmp.name) / 'work'
        tags = [Path(s[1]).name for s in plan if s[0] == 'sql' and Path(s[1]).parent == work]
        self.assertEqual(tags[:3], ['mark.sql', 'package-DLC_01.sql', 'mark.sql'])
        text = (work / 'package-DLC_01.sql').read_text(encoding='utf-8')
        self.assertIn("UPDATE Civilizations SET PackageID = '293C1EE3117644F6AC1F59663826DE74'", text)
        self.assertIn('UPDATE Leaders', text)
        self.assertFalse((work / 'package-VPUI.sql').exists())  # no GameData, nothing to tag

    def test_downloadable_content(self):
        self.plan()
        lines = (Path(self.tmp.name) / 'work/downloadable-content.sql').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 4)  # VPUI has no Key
        self.assertTrue(lines[0].endswith("VALUES('293C1EE3117644F6AC1F59663826DE74', 'TXT_KEY_293C1EE3117644F6AC1F59663826DE74_NAME', "
                                          "'TXT_KEY_293C1EE3117644F6AC1F59663826DE74_DESCRIPTION', 2, 1, 1, 1);"))
        self.assertTrue(lines[1].endswith(', 2, 1, 0, 0);'))  # an Upgrade package is listed inactive

    def test_map_scripts(self):
        maps = [s[2] for s in self.plan() if s[0] == 'mapscript']
        self.assertEqual(maps, ['Assets\\Maps\\continents.lua', 'Assets\\Maps\\Pangaea.lua',
                                str(self.user / 'Maps') + '\\Random Luxuries.lua',
                                'Assets\\DLC\\DLC_02\\Maps\\Spain.lua', 'Assets\\DLC\\Expansion2\\Maps\\Pangaea_XP2.lua'])

    def test_structure(self):
        plan = self.plan()
        kinds = [s[0] for s in plan]
        self.assertEqual(plan[0][0], 'snapshot')
        self.assertEqual(plan[2][0], 'attach')
        self.assertLess(kinds.index('mapscript'), kinds.index('detach'))
        self.assertNotIn('postprocess', kinds)
        self.assertIn('postprocess', [s[0] for s in self.plan(postprocess=True)])

    def test_missing_gamedata(self):
        (self.dlc / 'DLC_01/Data/Units_Mongol.xml').unlink()
        with self.assertRaises(snapshot.SnapshotError):
            self.plan()

    def test_key_follows_inputs(self):
        core = Path(self.tmp.name) / 'core.db'
        core.write_bytes(b'core')
        exe = Path(self.tmp.name) / 'host.exe'
        exe.write_bytes(b'exe')
        _, a = snapshot.inputs(self.game, self.user, core, exe)
        self.assertEqual(snapshot.inputs(self.game, self.user, core, exe)[1], a)
        (self.dlc / 'DLC_02/Spain.xml').write_text('<GameData><Civilizations/></GameData>', encoding='utf-8')
        self.assertNotEqual(snapshot.inputs(self.game, self.user, core, exe)[1], a)

    def test_no_core_database(self):
        cfg = config.Config(cache_dir=Path(self.tmp.name) / 'cache')
        with self.assertRaisesRegex(config.ConfigError, 'start Civilization V once'):
            snapshot.core_db(cfg)


@unittest.skipUnless(os.environ.get('C5H_INTEGRATION') == '1', 'integration test: set C5H_INTEGRATION=1')
class BuildTest(unittest.TestCase):
    """Builds the snapshot from the installed game with the host. C5H_SNAPSHOT_ORACLE names a snapshot captured from
    the game (Civ5DebugDatabase.db at the main menu without mods) to compare with."""

    def test_build(self):
        cfg = config.load()
        if not (cfg.game_dir and cfg.exe and cfg.cache_dir and (cfg.cache_dir / snapshot.CORE_DB).is_file()):
            self.skipTest('needs game_dir, exe and the game cache')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'snapshot.db'
            summary = snapshot.build(cfg.game_dir, cfg.user_dir, snapshot.core_db(cfg), cfg.exe, out)
            self.assertEqual(summary['status'], 'built', summary)
            con = sqlite3.connect(out.as_uri() + '?mode=ro', uri=True)
            keyed = {p['id'] for p in snapshot.packages(cfg.game_dir) if p['root'].findtext('Key')}
            self.assertEqual({r[0] for r in con.execute('SELECT PackageID FROM DownloadableContent')}, keyed)
            con.close()
            oracle = os.environ.get('C5H_SNAPSHOT_ORACLE')
            if oracle:
                d = dbdiff.diff(oracle, out)
                # without post-processing only the tables PerformDatabasePostProcessing fills differ
                self.assertLessEqual({t['table'] for t in d['tables_differ']}, {'Defines', 'Resources'})
                self.assertFalse(d['schema_differs'] or d['tables_only_reference'] or d['tables_only_candidate'])


if __name__ == '__main__':
    unittest.main()
