"""tools/get_toolchain.py: its guards, and with C5H_SDK_ISO naming GRMSDK_EN_DVD.iso, the UDF reader against the disc
(the three packages' .msi files must have the hashes Microsoft's packages have; 7-Zip, when installed, must agree).
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('get_toolchain', REPO / 'tools/get_toolchain.py')
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

MSI_SHA256 = {'vc_stdx86.msi': '0A524433918357E8476FBF0191AD3A7FB45FAD11EC929F5BD69B0D2713306ADE',
              'WinSDKBuild_x86.msi': 'F1268291829854745ED2AB80E854C8A8514E876E71E3F810FDC06F40CA97EDC3',
              'WinSDKWin32Tools_x86.msi': 'BA17C91C2FBDC09CF23AD126A489B6CD7B38AE2FF7098CC748348BF4BBE895F7'}


class GuardTest(unittest.TestCase):
    def test_out_too_long_or_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(gt.ToolchainError, 'too long'):
                gt.build(Path(tmp) / ('x' * 80))
            (Path(tmp) / 'file').write_text('x')
            with self.assertRaisesRegex(gt.ToolchainError, 'not empty'):
                gt.build(tmp)

    def test_wrong_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            iso = Path(tmp) / 'x.iso'
            iso.write_bytes(b'not an iso')
            with self.assertRaisesRegex(gt.ToolchainError, 'bytes'):
                gt.check_iso(iso)
            with self.assertRaisesRegex(gt.ToolchainError, 'UDF'):
                gt.UdfImage(iso)


@unittest.skipUnless(os.environ.get('C5H_SDK_ISO'), 'set C5H_SDK_ISO to GRMSDK_EN_DVD.iso')
class IsoTest(unittest.TestCase):
    def test_packages(self):
        iso = os.environ['C5H_SDK_ISO']
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gt.extract_packages(iso, Path(tmp) / 'udf', use_7zip=False), 'built-in UDF reader')
            for folder, msi, _ in gt.PACKAGES:
                self.assertEqual(gt.sha256(Path(tmp) / 'udf' / folder / msi), MSI_SHA256[msi])
            if gt.seven_zip():
                gt.extract_packages(iso, Path(tmp) / '7z', use_7zip=True)
                files = sorted(p.relative_to(Path(tmp) / 'udf') for p in (Path(tmp) / 'udf').rglob('*') if p.is_file())
                self.assertEqual(files, sorted(p.relative_to(Path(tmp) / '7z') for p in (Path(tmp) / '7z').rglob('*') if p.is_file()))
                for rel in files:
                    self.assertEqual(gt.sha256(Path(tmp) / 'udf' / rel), gt.sha256(Path(tmp) / '7z' / rel), rel)


if __name__ == '__main__':
    unittest.main()
