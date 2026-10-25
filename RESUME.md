# Platform workstream: resume notes (milestone 2)

Branch `c5h-platform` in this worktree. Milestone 1 is merged into main (653ae69); main's d2be5e3 merged in here.
This file stays on the branch (left out of main).

## Work order (milestone 2)

1. `realgame/` per plan 9.4: FireTuner client and service (`tuner.py`, `tuner_result.lua`), launcher (`launch.py`,
   optional CPU-temperature guard), mod activation (`mods.py`), config.ini seed pinning with backup and restore
   (`seeds.py`), `RealGameSession` (`session.py`, interface exactly as plan 9.4: the verify workstream codes against
   it), process stats from psapi. Then probe/record/dbcapture on top. Tested against a fake tuner server only; never
   launch the real game.
2. Full `c5h doctor`: game and DLL, mods, Python, config.ini EnableTuner/LoggingEnabled (read only), host, toolchain,
   snapshot.
3. `tools/get_toolchain.py`: VC9 toolchain from the Windows SDK 7.0 ISO; test with `--iso` on the local ISO into a
   temporary folder, then build the host with it. No download.
4. `docs/user-guide.md` around `c5h`; `docs/database-builder.md` to the new commands.
5. `c5h.cmd` launcher at the repository root (pip install -e needs setuptools from the network).

## Done

- DLC snapshot from the game's files (`snapshot.py`, `c5h snapshot`), the default when `snapshot` is not set
  (dbcache, dbbuild). Verified: against the snapshot captured from the game only Defines and Resources differ
  (post-processing, not run by default); the mods database built from it is identical to the one built from the
  captured snapshot. Unit tests on a synthetic game folder; integration test with C5H_INTEGRATION=1
  (C5H_SNAPSHOT_ORACLE for the comparison).

- realgame/: tuner.py (+ tuner_result.lua as package data), launch.py (launcher, steam_appid.txt, CPU guard),
  mods.py, seeds.py (config.ini pin/restore with a marker in <workspace>/cache), session.py (RealGameSession),
  probe.py, record.py, dbcapture.py rebuilt on the session. Tests: tests/platform_tests/test_realgame.py with
  fake_tuner.py (a fake game behind a fake tuner); Lua tests with C5H_LUPA_PATH (lupa).
  Never run against the real game.

## In progress / next

- doctor, get_toolchain, c5h.cmd, docs.

## For the report

- Host builddb post-processing with the stock Firaxis CvGameCore_Expansion2.dll crashes (0xC0000005 after
  GetLogFileMgr) in both the platform and the anydll builds; the VP DLL works. Hence no post-processing by default.

## Commands

- Tests: `python -B -m unittest discover -s tests/platform_tests -t .`
- Integration: `C5H_INTEGRATION=1 C5H_SNAPSHOT_ORACLE=<captured snapshot> python -B -m unittest discover -s tests/platform_tests -t .`
- Host build: `C5H_TOOLCHAIN=<toolchain> python tools/build_host.py`
