"""Saved games: the .Civ5Save header reader, c5h save, and c5h run --load and the save options against a fake host."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
import uuid
from unittest import mock

from civ5headless import cli, config, modsdb, queue, run, savegame

from .test_modsdb import ADDON_ID, BASE_ID, make_mods
from .test_spec import make_db

HERE = Path(__file__).resolve().parent
DLL_GUID = '{bf9bf7f0-e078-4d4e-8a3e-84712f85aa2b}'


def text(s):
    b = s.encode('utf-8')
    return struct.pack('<I', len(b)) + b


def guid(s):
    return uuid.UUID(s.strip('{}')).bytes_le


def make_save(path, turn=5, mods=(), version=8, game_type=0, tail=savegame.TAIL_GUID):
    """A .Civ5Save header as the game writes it (mods: (id, version, name)), then a few bytes standing for the rest."""
    b = b'CIV5' + struct.pack('<I', version) + text('1.0.3.279 (403694)') + text('403694') + struct.pack('<IB', turn, game_type)
    for s in ('CIVILIZATION_GREECE', 'HANDICAP_PRINCE', 'ERA_ANCIENT', 'ERA_CLASSICAL', 'GAMESPEED_QUICK', 'WORLDSIZE_TINY',
              'Assets\\Maps\\Continents.lua'):
        b += text(s)
    dlc = [('{293ac8ee-5a17-4d2f-90bf-b2e7a6b1bd6a}', 'Mongolia'), ('{0e3751a1-f840-4e1b-9706-519bf484e59d}', 'Expansion - Gods and Kings')]
    b += struct.pack('<I', len(dlc)) + b''.join(guid(g) + struct.pack('<I', 1) + text(n) for g, n in dlc)
    b += struct.pack('<I', len(mods)) + b''.join(text(i) + struct.pack('<I', v) + text(n) for i, v, n in mods)
    b += text('') + text('') + text('PLAYERCOLOR_GREECE') + guid(DLL_GUID) + text('1.0.0') + guid(tail) + struct.pack('<I', 0)
    b += struct.pack('<I', 3) + b'pregame and body'
    Path(path).write_bytes(b)
    return path


class HeaderTest(unittest.TestCase):
    def test_read_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = make_save(Path(tmp) / 'AutoSave_0012 BC-3520.Civ5Save', turn=12,
                          mods=[(BASE_ID, 3, 'Base Mod'), (ADDON_ID, 1, 'Addon')])
            h = savegame.read_header(p)
            self.assertEqual((h.turn, h.gameType, h.civilization, h.handicap, h.startEra, h.currentEra, h.speed, h.worldSize),
                             (12, 0, 'CIVILIZATION_GREECE', 'HANDICAP_PRINCE', 'ERA_ANCIENT', 'ERA_CLASSICAL',
                              'GAMESPEED_QUICK', 'WORLDSIZE_TINY'))
            self.assertEqual(h.mapScript, 'Assets\\Maps\\Continents.lua')
            self.assertEqual([d['name'] for d in h.dlc], ['Mongolia', 'Expansion - Gods and Kings'])
            self.assertEqual(h.dlc[0]['id'], '{293ac8ee-5a17-4d2f-90bf-b2e7a6b1bd6a}')
            self.assertEqual(h.mod_set, [f'{BASE_ID}:3', f'{ADDON_ID}:1'])
            self.assertEqual((h.playerColor, h.dllGuid, h.dllVersion), ('PLAYERCOLOR_GREECE', DLL_GUID, '1.0.0'))
            self.assertEqual(h.fileBytes, p.stat().st_size)
            self.assertEqual(p.read_bytes()[h.headerBytes:h.headerBytes + 4], struct.pack('<I', 3))  # the pregame's version
            self.assertIn('turn 12, single player', savegame.describe(h))
            self.assertEqual(json.loads(json.dumps(h.as_dict()))['mods'][1]['name'], 'Addon')

    def test_not_a_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'x.Civ5Save').write_bytes(b'PK\x03\x04')
            cut = make_save(tmp / 'cut.Civ5Save')
            cut.write_bytes(cut.read_bytes()[:60])
            for path, message in ((tmp / 'x.Civ5Save', 'no CIV5'), (make_save(tmp / 'v7.Civ5Save', version=7), 'save version 7'),
                                  (cut, 'cut short'), (make_save(tmp / 't.Civ5Save', tail=str(uuid.uuid4())), 'does not end')):
                with self.subTest(path=path.name), self.assertRaises(savegame.SaveError) as ctx:
                    savegame.read_header(path)
                self.assertIn(message, str(ctx.exception))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = make_save(Path(tmp) / 'a.Civ5Save', turn=3)
            (Path(tmp) / 'empty.toml').write_text('', encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(['--config', str(Path(tmp) / 'empty.toml'), 'save', str(p), '--json'])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(json.loads(out.getvalue())['turn'], 3)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(savegame.main([str(p), str(Path(tmp) / 'missing.Civ5Save')]), 1)
            self.assertIn('missing.Civ5Save', err.getvalue())


class OptionTest(unittest.TestCase):
    def test_autosave_modes(self):
        self.assertEqual([run.autosave_mode(v) for v in (None, 'none', 'GAME', '5', 7)], ['none', 'none', 'game', '5', '7'])
        for bad in ('0', '-2', 'often'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                run.autosave_mode(bad)

    def test_save_host_args(self):
        a = mock.Mock(autosave='game', save_at=[10, 20], save_final=True, load=None)
        with mock.patch.object(run, 'host_supports', return_value=True):
            self.assertEqual(run.save_host_args(a, 'host.exe'), ['--autosave', 'game', '--save-at', '10', '--save-at', '20'])
            # by default only the host's own final save; --no-save-final turns it off
            self.assertEqual(run.save_host_args(mock.Mock(autosave=None, save_at=None, save_final=True, load=None), 'host.exe'), [])
            self.assertEqual(run.save_host_args(mock.Mock(autosave=None, save_at=None, save_final=False, load=None), 'host.exe'),
                             ['--no-save-final'])
        with mock.patch.object(run, 'host_supports', return_value=False):  # a host from before saves saves nothing
            self.assertEqual(run.save_host_args(mock.Mock(autosave='none', save_at=[], save_final=False, load=None), 'old.exe'), [])
            with self.assertRaises(ValueError):
                run.save_host_args(mock.Mock(autosave='none', save_at=[], save_final=True, load='a.Civ5Save'), 'old.exe')

    def test_load_mod_set(self):
        """--load keeps the configured registry when its mods that affect saved games are the save's (UI mods may be
        active beside them, as a save lists only the others), else the save's mods."""
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / 'mods.db'
            con = sqlite3.connect(registry)
            con.execute('CREATE TABLE Mods(ModID TEXT, Version TEXT, Activated BOOL)')
            con.execute('CREATE TABLE ModProperties(ModID TEXT, Version TEXT, Name TEXT, Value TEXT)')
            con.executemany('INSERT INTO Mods VALUES(?,?,?)', [(BASE_ID, '3', 1), (ADDON_ID, '1', 1), ('07e00000-1111-4222-8333-944444444444', '5', 0)])
            con.executemany('INSERT INTO ModProperties VALUES(?,?,?,?)', [(ADDON_ID, '1', 'AffectsSavedGames', '0'),
                                                                           (BASE_ID, '3', 'AffectsSavedGames', '1')])
            con.commit()
            con.close()
            self.assertEqual(len(modsdb.activated(registry)), 2)
            self.assertEqual(modsdb.activated(registry, saved_games_only=True), [(BASE_ID, 3)])
            cfg = config.Config(mods_db=registry)
            fits = savegame.read_header(make_save(Path(tmp) / 'a.Civ5Save', mods=[(BASE_ID, 3, 'Base Mod')]))
            self.assertIsNone(run.load_mod_set(cfg, fits))
            other = savegame.read_header(make_save(Path(tmp) / 'b.Civ5Save', mods=[(BASE_ID, 2, 'Base Mod')]))
            self.assertEqual(run.load_mod_set(cfg, other), [f'{BASE_ID}:2'])
            self.assertEqual(run.load_mod_set(None, fits), [f'{BASE_ID}:3'])

    def test_queue_jobs_from_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_save(tmp / 'a.Civ5Save', mods=[(BASE_ID, 3, 'Base Mod')])
            make_save(tmp / 'bare', turn=2)  # a save without the extension: its first bytes say what it is
            jobs = {j['name']: j for j in queue.expand({'jobs': [
                {'name': 'spec-save', 'spec': 'a.Civ5Save', 'turns': 9},
                {'name': 'bare', 'spec': 'bare', 'turns': 9, 'saveFinal': False, 'autosave': 'GAME'}]}, tmp / 'q.json')}
            self.assertEqual((jobs['spec-save']['load'], jobs['spec-save']['spec']), (str((tmp / 'a.Civ5Save').resolve()), None))
            self.assertEqual(jobs['spec-save']['mods'], [f'{BASE_ID}:3'])  # no configuration given: the save's mods
            self.assertEqual((jobs['bare']['load'], jobs['bare'].get('noMods'), jobs['bare']['autosave']),
                             (str((tmp / 'bare').resolve()), True, 'game'))
            ns = queue.job_args(jobs['bare'], tmp / 'out', dict(db='x.db', modsDir=None, modsDb=None), None)
            self.assertEqual((ns.spec, ns.load, ns.save_final, ns.autosave), (None, str((tmp / 'bare').resolve()), False, 'game'))
            self.assertTrue(queue.job_args(jobs['spec-save'], tmp / 'out', dict(db='x.db', modsDir=None, modsDb=None), None).save_final)

    def test_run_option_checks(self):
        for argv, message in ((['--turns', '3'], 'one of them'),
                              (['spec.json', '--load', 'a.Civ5Save', '--turns', '3'], 'one of them'),
                              (['--load', 'a.Civ5Save', '--turns', '3', '--seeds', '1', '2'], 'does not apply'),
                              (['a.Civ5Save', '--turns', '3', '--seeds', '1', '2'], 'does not apply'),
                              (['a.Civ5Save', '--load', 'b.Civ5Save', '--turns', '3'], 'not both'),
                              (['spec.json', '--turns', '3', '--autosave', 'often'], 'autosave is none, game'),
                              (['spec.json', '--turns', '3', '--save-at', '0'], 'turn numbers > 0')):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as ctx:
                    run.main(argv, config.Config())
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(message, err.getvalue())


@unittest.skipUnless(os.name == 'nt', 'Windows only (job objects)')
class LoadTest(unittest.TestCase):
    """c5h run --load end to end with fake_host.cmd standing in for civ5headless.exe."""

    def test_load_takes_the_saves_mods_and_turn(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'C5H_TEST_PYTHON': sys.executable}), \
                mock.patch.object(run, 'host_supports', return_value=True):
            tmp = Path(tmp)
            db = tmp / 'game.db'
            make_db(db)
            own = tmp / 'Assets/DLC/Expansion2/CvGameCore_Expansion2.dll'
            own.parent.mkdir(parents=True)
            own.write_bytes(b'x')
            mods_dir = make_mods(tmp / 'MODS')
            cfg = config.Config(game_dir=tmp, mods_dir=mods_dir, mods_db=tmp / 'game-registry.db', exe=HERE / 'fake_host.cmd',
                                db=db, runs=tmp / 'runs', db_cache=tmp / 'cache')
            save = make_save(tmp / 'Turn_0005 BC-3800.Civ5Save', turn=5, mods=[(BASE_ID, 3, 'Base Mod'), (ADDON_ID, 1, 'Addon')])
            r = run.play(save, 9, cfg=cfg, autosave=3, save_at=[7], no_profiles=True)  # a save as the spec: a load
            self.assertTrue(r.ok, r.status.get('error'))
            self.assertEqual(r.dir.name[:len('Turn_0005-BC-3800-')], 'Turn_0005-BC-3800-')
            argv = json.loads((r.dir / 'argv.json').read_text(encoding='utf-8'))[1:]

            def value(opt):
                return [argv[i + 1] for i, a in enumerate(argv) if a == opt]

            self.assertEqual(argv[:3], ['loadgame', '--load', str(save.resolve())])
            self.assertEqual(value('--turns'), ['4'])  # turns 6 to 9
            self.assertNotIn('--spec', argv)
            self.assertEqual((value('--autosave'), value('--save-at'), '--no-save-final' in argv), (['3'], ['7'], False))
            # the save's mod set: a generated registry with both mods, activated
            con = sqlite3.connect(value('--mods-db')[0])
            self.assertEqual([tuple(x) for x in con.execute('SELECT ModID, Version FROM Mods WHERE Activated = 1 ORDER BY RowID')],
                             [(BASE_ID, '3'), (ADDON_ID, '1')])
            con.close()
            st = r.status
            self.assertEqual((st['startTurn'], st['endTurn'], st['turns'], st['wallSeconds'], st['secondsPerTurn']),
                             (5, 9, 4, 1.0, 0.25))
            self.assertEqual((st['loadedFrom'], st['spec']), (str(save.resolve()), None))
            self.assertTrue(st['save'].startswith('loaded-Turn_0005-BC-3800-t5-'))
            self.assertEqual(st['finalSave'], str(r.dir / 'saves/Final_0009.Civ5Save'))
            self.assertEqual([(x['kind'], x['turn']) for x in st['saves']], [('final', 9)])
            self.assertEqual(json.loads((r.dir / 'save-header.json').read_text(encoding='utf-8'))['turn'], 5)
            self.assertFalse((r.dir / 'spec-resolved.json').exists())
            self.assertEqual(json.loads((r.dir / 'turn-seen.json').read_text(encoding='utf-8'))['5'], 0.0)
            self.assertIn('Loaded from', (r.dir / 'report.html').read_text(encoding='utf-8'))
            # the configured registry when it activates just the save's mods
            registry = Path(value('--mods-db')[0])
            cfg.mods_db = tmp / 'game-registry.db'
            cfg.mods_db.write_bytes(registry.read_bytes())
            cfg.dll = own  # as for a new game, the configured registry plays the configured DLL
            r = run.play(None, 6, load=save, cfg=cfg, run='configured', report=False)
            self.assertTrue(r.ok, r.status.get('error'))
            argv = json.loads((r.dir / 'argv.json').read_text(encoding='utf-8'))[1:]
            self.assertEqual(value('--mods-db'), [str(cfg.mods_db.resolve())])
            # an unmodded save plays without mods; a target at or before the save's turn fails
            bare = make_save(tmp / 'bare.Civ5Save', turn=2)
            r = run.play(None, 3, load=bare, cfg=cfg, run='bare1', report=False, save_final=False)
            self.assertTrue(r.ok, r.status.get('error'))
            argv = json.loads((r.dir / 'argv.json').read_text(encoding='utf-8'))[1:]
            self.assertIn('--no-mods', argv)
            self.assertFalse((r.dir / 'saves').exists())  # --no-save-final: no saves
            self.assertIn('--no-save-final', json.loads((r.dir / 'argv.json').read_text(encoding='utf-8')))
            r = run.play(None, 2, load=bare, cfg=cfg, run='bare2', report=False)
            self.assertFalse(r.ok)
            self.assertIn('must be after it', r.status['error'])
            with self.assertRaises(ValueError):
                run.play(None, 3, cfg=cfg)


if __name__ == '__main__':
    unittest.main()
