"""civ5headless.exe self-checks that need no game state: a one-turn Tiny game whose boot self-test includes the
--skip-addin name matching (file name with or without .lua/.xml), and the run report's city-state section.

Integration test: runs only with C5H_INTEGRATION=1 and a configuration that can play games (c5h doctor). One host
process of a few seconds; the run folder goes to a temporary folder.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from civ5headless import config, run

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('C5H_INTEGRATION') == '1', 'integration test: set C5H_INTEGRATION=1')
class HostChecksTest(unittest.TestCase):
    def test_self_checks(self):
        cfg = config.load()
        if not (cfg.game_dir and cfg.dll and cfg.exe and (cfg.db or cfg.snapshot or cfg.cache_dir)):
            self.skipTest('needs game_dir, dll, exe and a game database (db, snapshot or the game cache)')
        with tempfile.TemporaryDirectory() as tmp:
            r = run.play(REPO / 'examples/specs/continents-tiny-fixed-seed.json', 1, run_dir=Path(tmp) / 'checks', cfg=cfg,
                         skip_addins=['NoSuchAddin.lua'])
            self.assertTrue(r.ok, r.status.get('error'))
            boot = json.loads((r.dir / 'newgame-report.json').read_text(encoding='utf-8'))
            checks = boot['self_test']['checks']
            self.assertIn('ok: --skip-addin matches a context by file name with or without extension', checks)
            report = r.report
            if 'minorCivs' in report:  # a host with the city-state section
                section = report['minorCivs']
                self.assertIn(section['chosenBy'], ('dll', 'host', ''))
                self.assertEqual(section['pinned'], 0)
                self.assertTrue(all(s['id'] >= 0 and s['type'] for s in section['slots']))


if __name__ == '__main__':
    unittest.main()
