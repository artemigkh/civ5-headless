# Resume: platform workstream (c5h-platform)

Removed when the branch is merged.

## Work order (summary)

Platform workstream of civ5-headless (plan section 9, phase B and real-game automation). Worktree
`civ5-headless-wt/platform`, branch `c5h-platform`. Owns `python/civ5headless/` (except `fingerprint.py`,
`hazards.py`, `data/`, `verify/`), `tools/get_toolchain.py`, `examples/`, `pyproject.toml`, `docs/user-guide.md`,
`README.md` and their tests under `tests/`.

Milestone 1 (stop and report after it):
1. `pyproject.toml`: package dir `python/`, console script `c5h`, `python -m civ5headless`, Python 3.11+, stdlib only.
2. Modules moved into the plan 9.1 layout with `git mv`; package-relative imports; vpbench-dependent modules marked.
3. `config.py`: `civ5headless.toml` plus discovery (Steam registry and libraryfolders.vdf, Documents known folder,
   MODS, cache, mods database and active mods, host exe, runs folder); `config.load(path=None) -> Config` with the
   source of each value. `civ5headless.example.toml`.
4. No machine-specific paths in the package, docs, examples or tests.
5. `cli.py`: run, queue, compare, dbbuild, doctor, verify hook.
6. Tests: `python -m unittest discover -s tests` (config discovery, spec resolution, digest comparison).
7. Equivalence: a Tiny 30-turn game through the old hhbench.py and through `c5h run`; HHDIGEST lines identical.
8. RESUME.md and report.

Milestone 2 (only after "continue"): `realgame/` (tuner, launch, mods, seeds, session, probe, record, dbcapture),
full `c5h doctor`, `tools/get_toolchain.py` (tested with `--iso` against the ISO on disk), user guide around `c5h`.

Rules: never launch the real game or connect FireTuner to it; never write into the game folder or the My Games
folder; at most 6 host processes; the source repository is read-only; commit locally, never push; no mention of
AI assistance in commits.

## State

- Step 2 started: the modules are moved (renames only, committed first so history follows).
