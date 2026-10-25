"""run.play with the real civ5headless.exe: a short Tiny game, played twice (the host reproduces itself).

Integration test: runs only with C5H_INTEGRATION=1 and a configuration that can play games (c5h doctor: game_dir,
dll, exe, and db or a snapshot). Two host processes, a few seconds each. Run folders go to a temporary folder.
"""
import os
from pathlib import Path
import tempfile
import unittest

from civ5headless import config, run
from civ5headless.compare import digest

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('C5H_INTEGRATION') == '1', 'integration test: set C5H_INTEGRATION=1')
class HostGameTest(unittest.TestCase):
    def test_tiny_game_twice(self):
        cfg = config.load()
        if not (cfg.game_dir and cfg.dll and cfg.exe and (cfg.db or cfg.snapshot)):
            self.skipTest('needs game_dir, dll, exe and db or snapshot in the configuration')
        with tempfile.TemporaryDirectory() as tmp:
            results = [run.play(REPO / 'examples/specs/continents-tiny.json', 3, run_dir=Path(tmp) / f'aa-{k}', cfg=cfg)
                       for k in (1, 2)]
            for r in results:
                self.assertTrue(r.ok, r.status.get('error'))
                self.assertEqual(r.status['endTurn'], 3)
                self.assertEqual(r.report.get('status'), 'passed')
            a, b = (r.digest_log for r in results)
            if a.is_file() and b.is_file():  # a DLL with the digest additions
                c = digest.compare(a, b)
                self.assertTrue(c['identical'], digest.summary(c))
                self.assertGreaterEqual(c['common'], 3)


if __name__ == '__main__':
    unittest.main()
