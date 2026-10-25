# Platform workstream: resume notes (milestone 2)

Branch `c5h-platform` in this worktree. Milestone 1 is merged into main (653ae69); main's d2be5e3 merged in here.
This file stays on the branch (left out of main).

## Work order (milestone 2)

1. `realgame/` per plan 9.4 (FireTuner client, launcher with CPU guard, mod activation, config.ini seeds,
   RealGameSession, process stats), probe/record/dbcapture on top; tested against a fake tuner only.
2. Full `c5h doctor`.
3. `tools/get_toolchain.py` from the Windows SDK 7.0 ISO; tested with `--iso` into a temp folder, host built with it.
4. `docs/user-guide.md` around `c5h`; `docs/database-builder.md` on the new commands.
5. `c5h.cmd` launcher (pip install -e needs setuptools from the network).
Coordinator: DLC snapshot from the game's files as the default when possible (done: it is possible).

## Done (all committed)

- 29cdbe1 DLC snapshot from the game's files (`snapshot.py`, `c5h snapshot`), default for dbcache/dbbuild.
- e38d1dc realgame/: tuner, launch (+ CPU guard), mods, seeds, session, probe/record/dbcapture; fake-tuner tests.
- 8195820 doctor: host games / real game / building the host.
- 72930e6 tools/get_toolchain.py (7-Zip or built-in UDF reader, msiexec /a).
- 232bc19 c5h.cmd, user guide, database builder doc, example toml.
- (this commit) session: relaunch stats not nested; fake game resets its turn at a new game.

Verified: 96 tests (with C5H_INTEGRATION=1, C5H_SNAPSHOT_ORACLE, C5H_LUPA_PATH, C5H_SDK_ISO) plus the map script
test with a captured snapshot configured; the verify workstream's realside.py ran against RealGameSession and the
fake game (3 games, logs, stats); the toolchain made from the ISO is file-identical to the old one and built a host
that played the integration game.

## Next

- Milestone 2 complete; waiting for the coordinator. Nothing runs, nothing uncommitted.

## Commands

- Tests: `python -B -m unittest discover -s tests`
- Integration: `C5H_INTEGRATION=1 C5H_SNAPSHOT_ORACLE=<captured snapshot> C5H_LUPA_PATH=<folder with lupa>
  C5H_SDK_ISO=<GRMSDK_EN_DVD.iso> python -B -m unittest discover -s tests`
- Host build: `python tools/build_host.py --toolchain <toolchain>`
