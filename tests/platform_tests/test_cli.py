"""The c5h command line, module imports, run.play against a fake host, queue expansion, and the no-machine-paths rule."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from civ5headless import cli, config, queue, run

from .test_spec import make_db

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class ImportTest(unittest.TestCase):
    def test_every_module_imports(self):
        for path in sorted((REPO / 'python/civ5headless').rglob('*.py')):
            if path.name == '__main__.py':
                continue
            parts = path.relative_to(REPO / 'python').with_suffix('').parts
            name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_cli_commands_exist(self):
        for name, module, function, _ in cli.COMMANDS:
            if module == 'civ5headless.verify':
                continue  # the verification workstream's package
            with self.subTest(command=name):
                self.assertTrue(callable(getattr(importlib.import_module(module), function)))

    def test_pyproject(self):
        import tomllib
        project = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))
        module, function = project['project']['scripts']['c5h'].split(':')
        self.assertIs(getattr(importlib.import_module(module), function), cli.main)
        self.assertEqual(project['project']['requires-python'], '>=3.11')
        self.assertEqual(project['project']['dependencies'], [])
        self.assertEqual(project['tool']['setuptools']['package-dir'], {'': 'python'})

    def test_realgame_tools_stop_clearly(self):
        from civ5headless.realgame import dbcapture, probe, record
        cfg = config.Config()
        with mock.patch.dict(sys.modules, {'vpbench': None}):
            for mod, argv in ((probe, ['--run', 'x']), (record, ['matrix.json']), (dbcapture, ['--run', 'x'])):
                with self.subTest(module=mod.__name__), self.assertRaises(SystemExit) as stop:
                    mod.main(argv, cfg)
                self.assertIn('not functional yet', str(stop.exception))


class CliTest(unittest.TestCase):
    def test_help_and_errors(self):
        code, out, _ = call(['--help'])
        self.assertEqual(code, 0)
        for name, _, _, _ in cli.COMMANDS:
            self.assertIn(name, out)
        self.assertEqual(call([])[0], 2)
        code, _, err = call(['nosuchcommand'])
        self.assertEqual(code, 2)
        self.assertIn('unknown command', err)
        code, _, err = call(['--config', str(REPO / 'missing.toml'), 'compare', 'a', 'b'])
        self.assertEqual(code, 2)
        self.assertIn('configuration error', err)

    def test_verify_hook(self):
        try:
            importlib.import_module('civ5headless.verify')
        except ModuleNotFoundError:
            code, _, err = call(['verify'])
            self.assertEqual(code, 2)
            self.assertIn('civ5headless.verify', err)
        else:
            self.skipTest('civ5headless.verify is present')

    def test_compare_through_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('a', 'b'):
                p = Path(tmp) / name / 'Logs/HeadlessDigest.log'
                p.parent.mkdir(parents=True)
                p.write_text('HHDIGEST|turn=0|point=doTurnBegin|total=0000000000000001|game=0000000000000001\n', encoding='utf-8')
            code, out, _ = call(['compare', str(Path(tmp) / 'a'), str(Path(tmp) / 'b')])
            self.assertEqual(code, 0)
            self.assertIn('identical on 1', out)

    def test_doctor_runs(self):
        code, out, _ = call(['doctor'])
        self.assertIn(code, (0, 1))
        self.assertIn('checks:', out)
        code, out, _ = call(['doctor', '--json'])
        self.assertEqual(set(json.loads(out)['values']), set(config.KEYS))


@unittest.skipUnless(os.name == 'nt', 'Windows only (job objects)')
class PlayTest(unittest.TestCase):
    """run.play end to end with fake_host.cmd standing in for civ5headless.exe."""

    def test_play_builds_the_host_command(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'C5H_TEST_PYTHON': sys.executable}):
            tmp = Path(tmp)
            db = tmp / 'game.db'
            make_db(db)
            game = tmp / 'game folder'
            game.mkdir()
            probe = tmp / 'probe.lua'
            probe.write_text('print(1)', encoding='utf-8')
            for name in ('mods.db', 'loc.db', 'game.dll'):
                (tmp / name).write_bytes(b'x')
            cfg = config.Config(game_dir=game, mods_dir=tmp / 'MODS', mods_db=tmp / 'mods.db', loc_db=tmp / 'loc.db',
                                dll=tmp / 'game.dll', exe=HERE / 'fake_host.cmd', db=db, runs=tmp / 'runs')
            spec = {'map': {'script': 'Continents.lua', 'size': 'WORLDSIZE_TINY'}, 'seeds': {'map': 1, 'sync': 2}}
            r = run.play(spec, 4, run='p1', cfg=cfg, lua_probes=[probe], heap_perturb=5, host_args=['--no-ui-frame'],
                         seeds={'sync': 3})
            self.assertTrue(r.ok, r.status.get('error'))
            self.assertEqual(r.dir, (tmp / 'runs/p1').resolve())
            self.assertEqual((r.status['endTurn'], r.status['endReason'], r.status['wallSeconds']), (4, 'target_turn', 1.0))
            self.assertEqual(r.report['status'], 'passed')
            argv = json.loads((r.dir / 'argv.json').read_text(encoding='utf-8'))[1:]
            self.assertEqual(argv[0], 'newgame')

            def value(opt):
                return [argv[i + 1] for i, a in enumerate(argv) if a == opt]

            self.assertEqual(value('--turns'), ['4'])
            self.assertEqual(value('--db'), [str(db.resolve())])
            self.assertEqual(value('--dll'), [str((tmp / 'game.dll').resolve())])
            self.assertEqual(value('--game-dir'), [str(game)])
            self.assertEqual(value('--mods-db'), [str((tmp / 'mods.db').resolve())])
            self.assertEqual(value('--loc-db'), [str((tmp / 'loc.db').resolve())])
            self.assertEqual(value('--lua-probe'), [str(probe.resolve())])
            self.assertEqual(value('--heap-perturb'), ['5'])
            self.assertIn('--no-ui-frame', argv)
            resolved = json.loads((r.dir / 'spec-resolved.json').read_text(encoding='utf-8'))
            self.assertEqual(resolved['seeds'], {'map': 1, 'sync': 3})
            self.assertEqual(json.loads((r.dir / 'spec.json').read_text(encoding='utf-8')), spec)
            # a second game into the same folder is refused
            with self.assertRaises(FileExistsError):
                run.play(r.dir / 'spec.json', 4, run_dir=r.dir, cfg=cfg)


class QueueTest(unittest.TestCase):
    def test_example_queues_expand(self):
        for p in sorted((REPO / 'examples/queues').glob('*.json')):
            with self.subTest(queue=p.name):
                q = json.loads(p.read_text(encoding='utf-8'))
                jobs = queue.expand(q, p)
                self.assertEqual(len(jobs), len(q['seeds']) * len(q['variants']))
                for job in jobs:
                    self.assertTrue(Path(job['spec']).is_file(), job['spec'])
                    self.assertRegex(job['name'], r'^\w+-m\d+-s\d+$')

    def test_paths_relative_to_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            qpath = Path(tmp) / 'q' / 'queue.json'
            qpath.parent.mkdir()
            q = {'defaults': {'spec': 'spec.json', 'turns': 5, 'luaProbes': ['p.lua']},
                 'variants': {'A': {'dll': 'a/x.dll'}}, 'seeds': [[1, 2], {'map': 3, 'sync': 4}],
                 'jobs': [{'name': 'extra', 'turns': 9, 'db': 'built.db'}]}
            jobs = {j['name']: j for j in queue.expand(q, qpath)}
            self.assertEqual(set(jobs), {'A-m1-s2', 'A-m3-s4', 'extra'})
            self.assertEqual(Path(jobs['A-m1-s2']['dll']), (qpath.parent / 'a/x.dll').resolve())
            self.assertEqual(Path(jobs['A-m1-s2']['spec']), (qpath.parent / 'spec.json').resolve())
            self.assertEqual(jobs['A-m3-s4']['seeds'], {'map': 3, 'sync': 4})
            self.assertEqual(Path(jobs['extra']['db']), (qpath.parent / 'built.db').resolve())
            self.assertEqual([Path(p) for p in jobs['extra']['luaProbes']], [(qpath.parent / 'p.lua').resolve()])
            self.assertEqual(jobs['extra']['turns'], 9)
            qpath.write_text(json.dumps(q), encoding='utf-8')
            cfg = config.Config(runs=Path(tmp) / 'runs')
            self.assertEqual(queue.Queue(qpath, cfg).out, Path(tmp) / 'runs/queue')
            with self.assertRaises(SystemExit):
                queue.expand({'jobs': [{'name': 'x'}, {'name': 'x', 'spec': 's'}]}, qpath)


class NoMachinePathsTest(unittest.TestCase):
    """Committed code, docs, examples and tests of this workstream name no drive paths, user folders or user name."""
    FILES = ['README.md', 'docs/user-guide.md', 'pyproject.toml', 'civ5headless.example.toml', 'tools/phase_speed.py',
             'tools/dbbuild_test_edits.py', 'tools/get_toolchain.py']
    TREES = ['python/civ5headless', 'examples', 'tests/platform_tests']

    def files(self):
        out = [REPO / f for f in self.FILES if (REPO / f).is_file()]
        for tree in self.TREES:
            out += [p for p in (REPO / tree).rglob('*') if p.is_file() and p.suffix in ('.py', '.json', '.md', '.toml', '.cmd', '.lua')]
        return out

    def test_no_machine_paths(self):
        drive = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]')
        users = re.compile(r'[\\/]Users[\\/]', re.I)
        names = {n for n in (os.environ.get('USERNAME'), os.environ.get('USER')) if n and len(n) >= 4}
        found = []
        for p in self.files():
            text = p.read_text(encoding='utf-8', errors='replace')
            for n, line in enumerate(text.splitlines(), 1):
                if drive.search(line) or users.search(line) or any(name.lower() in line.lower() for name in names):
                    found.append(f'{p.relative_to(REPO)}:{n}: {line.strip()[:100]}')
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
