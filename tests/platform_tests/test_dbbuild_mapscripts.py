"""The database builder's map script registration against the game's own rows for base and DLC scripts.

Integration test: runs only with C5H_INTEGRATION=1 and a configured game folder, DLC snapshot and host exe
(c5h doctor). It empties MapScripts, MapScriptOptions and MapScriptOptionPossibleValues in a copy of the DLC
snapshot, re-registers every map script the snapshot lists (base game and DLC, game Lua only) with
`civ5headless.exe builddb`, and compares the three tables with the snapshot: the builder's GetMapScriptInfo rules
(defaults, value tables, Folder) must match the engine's on the base and DLC scripts, independent of the mods'
scripts that a whole-database comparison covers.
"""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from civ5headless import config, dbbuild, dbdiff


@unittest.skipUnless(os.environ.get('C5H_INTEGRATION') == '1', 'integration test: set C5H_INTEGRATION=1')
class MapScriptRegistrationTest(unittest.TestCase):
    def test_base_and_dlc_scripts(self):
        cfg = config.load()
        game, snapshot, exe = cfg.game_dir, cfg.snapshot, cfg.exe
        if not (game and snapshot and exe):
            self.skipTest('needs game_dir, snapshot and exe in the configuration')
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            con = sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)
            names = [r[0] for r in con.execute('SELECT FileName FROM MapScripts ORDER BY rowid')]
            con.close()
            clear = run / 'clear.sql'
            clear.write_text('DELETE FROM MapScriptOptionPossibleValues;\nDELETE FROM MapScriptOptions;\nDELETE FROM MapScripts;\n',
                             encoding='utf-8')
            plan = [f'snapshot\t{snapshot.resolve()}', f'sql\t{clear}']
            plan += [f'mapscript\t{game / n}\t{n}' for n in names]
            plan += [f'vfs\t{k}\t{v}' for k, v in sorted(dbbuild.build_vfs(game, [], set()).items())]
            (run / 'plan.txt').write_text('\n'.join(plan) + '\n', encoding='utf-8')
            out = run / 'out.db'
            proc = subprocess.run([str(exe), 'builddb', '--game-dir', str(game), '--plan', str(run / 'plan.txt'),
                                   '--out', str(out), '--run', str(run / 'build')], capture_output=True, text=True, errors='replace')
            self.assertEqual(proc.returncode, 0, [l for l in proc.stdout.splitlines() if 'FAILED' in l])
            d = dbdiff.diff(snapshot, out, show=3)
            self.assertTrue(d['identical'], f"{len(names)} map scripts differ: {[t['table'] for t in d['tables_differ']]}")


if __name__ == '__main__':
    unittest.main()
