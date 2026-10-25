"""The fingerprint probe files (probes.py): settings, the files a host run and a real-game session inject."""
from pathlib import Path
import tempfile
import unittest

from civ5headless import config, probes

REPO = Path(__file__).resolve().parents[2]


class FingerprintTest(unittest.TestCase):
    def test_options(self):
        self.assertIsNone(probes.fingerprint_options(None))
        self.assertIsNone(probes.fingerprint_options(False))
        self.assertEqual(probes.fingerprint_options(True), dict(every=None, turns=[], split=None))
        self.assertEqual(probes.fingerprint_options(None, every=4), dict(every=4, turns=[], split=None))
        self.assertEqual(probes.fingerprint_options(None, turns='1, 50,100'), dict(every=None, turns=[1, 50, 100], split=None))
        self.assertEqual(probes.fingerprint_options({'every': 2, 'split': 6}, turns=[7]), dict(every=2, turns=[7], split=6))
        with self.assertRaises(ValueError):
            probes.fingerprint_options({'evry': 2})
        with self.assertRaises(ValueError):
            probes.fingerprint_options(None, turns='1,x')

    def test_settings(self):
        self.assertEqual(probes.fingerprint_settings(), '')
        text = probes.fingerprint_settings(every=3, turns=[1, 2], split=8)
        self.assertEqual(text.splitlines()[1:], ['C5HFP_EVERY = 3', 'C5HFP_TURNS = {1, 2}', 'C5HFP_SPLIT = 8'])
        self.assertTrue(text.startswith('--'))
        for bad in (dict(every=0), dict(split=0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                probes.fingerprint_settings(**bad)

    def test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = config.Config(probes=tmp / 'probes')
            with self.assertRaises(config.ConfigError):
                probes.fingerprint_probes(cfg, tmp / 'run')
            with self.assertRaises(config.ConfigError):
                probes.fingerprint_probes(config.Config(), tmp / 'run')
            (tmp / 'probes').mkdir()
            (tmp / 'probes/fingerprint.lua').write_text('', encoding='utf-8')
            self.assertEqual(probes.fingerprint_probes(cfg, tmp / 'run'), [tmp / 'probes/fingerprint.lua'])
            files = probes.fingerprint_probes(cfg, tmp / 'run', every=5)
            self.assertEqual(files, [tmp / 'run/fingerprint-settings.lua', tmp / 'probes/fingerprint.lua'])
            self.assertIn('C5HFP_EVERY = 5', files[0].read_text(encoding='utf-8'))

    def test_the_probe_reads_these_globals(self):
        probe = REPO / 'probes/fingerprint.lua'
        if not probe.is_file():
            self.skipTest('no probes/fingerprint.lua')
        text = probe.read_text(encoding='utf-8')
        for name in ('C5HFP_EVERY', 'C5HFP_TURNS', 'C5HFP_SPLIT'):
            self.assertIn(name, text)


if __name__ == '__main__':
    unittest.main()
