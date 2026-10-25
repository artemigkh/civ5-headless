# Resume: platform workstream (c5h-platform)

Removed when the branch is merged.

## Work order (summary)

Platform workstream of civ5-headless (plan section 9, phase B and real-game automation). Worktree
`civ5-headless-wt/platform`, branch `c5h-platform`. Owns `python/civ5headless/` (except `fingerprint.py`,
`hazards.py`, `data/`, `verify/`), `tools/get_toolchain.py`, `examples/`, `pyproject.toml`, `docs/user-guide.md`,
`README.md` and their tests under `tests/`.

Milestone 1 (stop and report after it): pyproject and `c5h`; modules moved into the plan 9.1 layout with `git mv`;
`config.py` with discovery; no machine paths; `cli.py`; tests; equivalence of a Tiny 30-turn game through the old
hhbench.py and the new path.

Milestone 2 (only after "continue"): `realgame/` per plan 9.4 (tuner, launch, mods, seeds, session; then probe,
record, dbcapture on top; psapi process stats), full `c5h doctor`, `tools/get_toolchain.py` (tested with `--iso`
against the ISO already on disk, extracted into a temporary folder, then a host build with it), user guide
rewritten around `c5h`. Real-game code tested against a fake tuner server only.

Rules: never launch the real game or connect FireTuner to it; never write into the game folder or the My Games
folder; at most 6 host processes; the source repository is read-only; commit locally, never push; no mention of
AI assistance in commits.

## State (2026-10-25, about 35 minutes used)

Milestone 1 done; waiting for "continue". Nothing uncommitted.

Commits on `c5h-platform`:
- `9c830b1` moves only (history follows: `git log --follow`);
- `b255595` the package: config, CLI, doctor, package-relative imports, machine paths removed;
- `7f880b3` tests, example queues, tools, README and a command table at the top of the user guide;
- this RESUME.md.

Verified:
- `python -m unittest discover -s tests`: 50 tests pass, 2 skipped (integration). With `C5H_INTEGRATION=1` and a
  config naming a snapshot, DLL and database, all 50 pass (map script registration identical on the 35 base/DLC
  scripts; a Tiny 3-turn game twice through `run.play`, digests identical).
- Equivalence: host built in the worktree (`out/Release/20261025-190731`, exe SHA-256 6F0C2044...); Tiny Continents
  30 turns (`examples/specs/continents-tiny.json`, seeds 30017/40017), field-map DLL CB6B0BED, mods-reference
  database, game-cache mods.db and Localization-Merged.db. Old `hhbench.py` (from `git archive main`) and
  `c5h run`: the 30 HHDIGEST lines (and the HHDIGESTSIZE lines) identical, the whole HeadlessDigest.log differs only
  in the HHENV thread ids, 32 checkpoints and replay data identical, final dumps identical (33 sections). The two
  host command lines differ only in order and an explicit `--mods-dir` (the host's own default, same folder).
- `c5h dbcache` from the pinned mods-reference input builds a database identical to the game's (dbdiff);
  `tools/dbbuild_test_edits.py` passes its four checks; a 2-game `c5h queue` run and `queue compare` work.

## Next steps (milestone 2, after "continue")

1. `realgame/tuner.py` from the source repository's `tools/civ5_tuner.py` (+ its test), a fake tuner server for
   tests; `launch.py` (tools/civ5_control.py, launch-civ5.ps1, vpbench-launch.ps1, optional CPU guard), `mods.py`
   (ensure-benchmark-mods.py), `seeds.py` (config.ini MapRandSeed/SyncRandSeed with backup and restore),
   `session.py` (RealGameSession, plan 9.4), process stats through psapi.
2. Rebuild `realgame/probe.py`, `record.py`, `dbcapture.py` on the session (they stop with a message now).
3. `c5h doctor`: config.ini EnableTuner/LoggingEnabled (read only), toolchain, mods.
4. `tools/get_toolchain.py --iso` against the ISO on disk, into a temporary folder; build the host with it.
5. `docs/user-guide.md` rewritten around `c5h`.

Local, not committed: `civ5headless.toml` is not used; the equivalence and integration runs used a config file in
the session's scratch folder (C5H_CONFIG) and run folders under `runs/` (ignored).
