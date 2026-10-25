"""c5h doctor's checks on a synthetic setup: the game database and DLC snapshot, config.ini (read only), mods."""
from pathlib import Path
import tempfile
import unittest

from civ5headless import config, doctor
from civ5headless.realgame import seeds

from .test_realgame import INI


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        user = root / 'user'
        (user / 'cache').mkdir(parents=True)
        (user / 'config.ini').write_bytes(INI.encode())
        self.cfg = config.Config(workspace=root / 'ws', game_dir=root / 'game', user_dir=user, cache_dir=user / 'cache',
                                 config_ini=user / 'config.ini', db_cache=root / 'ws/cache/db')
        for key in config.KEYS:
            self.cfg.sources.setdefault(key, config.Source('unset', 'test'))

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, what):
        found = [(s, d) for _, s, w, d in doctor.checks(self.cfg) if w == what]
        self.assertEqual(len(found), 1, what)
        return found[0]

    def test_snapshot(self):
        status, detail = self.check('DLC snapshot')
        self.assertEqual(status, 'FAIL')
        self.assertIn('start Civilization V once', detail)
        self.assertIn('dbcapture', detail)
        (self.cfg.cache_dir / 'Civ5CoreDatabase.db').write_bytes(b'')
        status, detail = self.check('DLC snapshot')
        self.assertEqual(status, 'ok')
        self.assertIn('built on first use', detail)
        self.cfg.snapshot = Path(self.tmp.name) / 'missing.db'
        self.assertEqual(self.check('DLC snapshot')[0], 'FAIL')
        self.cfg.db = Path(self.tmp.name) / 'game.db'
        self.cfg.db.write_bytes(b'')
        self.assertEqual(self.check('game database')[0], 'ok')

    def test_config_ini(self):
        self.assertEqual(self.check('EnableTuner')[0], 'ok')
        self.assertEqual(self.check('seeds')[0], 'ok')
        self.cfg.config_ini.write_bytes(INI.replace('EnableTuner = 1', 'EnableTuner = 0').replace('MapRandSeed = 0', 'MapRandSeed = 5').encode())
        status, detail = self.check('EnableTuner')
        self.assertEqual(status, 'warn')
        self.assertIn('[Debugging]', detail)
        self.assertIn('MapRandSeed = 5', self.check('seeds')[1])
        seeds.pin(self.cfg.config_ini, 1, 2, self.cfg.workspace / 'cache' / seeds.MARKER)
        self.assertIn('without restoring', self.check('seeds')[1])
        self.assertEqual(self.cfg.config_ini.read_bytes(), INI.replace('EnableTuner = 1', 'EnableTuner = 0').replace(
            'MapRandSeed = 0', 'MapRandSeed = 1').replace('SyncRandSeed = 0', 'SyncRandSeed = 2').encode())

    def test_active_mod_not_installed(self):
        mods_db = self.cfg.cache_dir / 'Civ5ModsDatabase.db'
        mods_db.write_bytes(b'')
        self.cfg.mods_db = mods_db
        self.cfg.mods_dir = Path(self.tmp.name) / 'MODS'
        self.cfg.mods_dir.mkdir()
        self.cfg.active_mods = [config.Mod('11111111-2222-3333-4444-555555555555', 3, 'Gone')]
        status, detail = self.check('active mods installed')
        self.assertEqual(status, 'FAIL')
        self.assertIn('Gone v3', detail)


if __name__ == '__main__':
    unittest.main()
