# Resume: verify workstream (phase D, c5h verify)

Work order (summary): build `c5h verify` (plan section 5) in `python/civ5headless/verify/`, `docs/verification.md`
and `tests/verify_tests/`, on branch `c5h-verify` in this worktree. Checks 5.1-5.4, modes quick/full/host-only with
a time budget, HTML + JSON report, exit codes. Real-game paths only against a fake session; host-only mode end to
end with real host runs (field-map DLL, local gitignored civ5headless.toml); statistics self-tests. Never launch the
real game, never write into the game or My Games folders, never modify the source repository, no pushes, no machine
paths in committed files, at most 8 host processes.

## State (2026-10-25)

Done and committed:
- package: settings, capabilities, stats (envelope + bias with leave-one-out calibration), series, exact (digest,
  fingerprint, checkpoint comparisons; pregame; Lua errors; same_game), hostside (phases, cost model, budget),
  realside (RealGameSession driver), checks, perf (thirds, load timeline, throughput, history), report (HTML),
  selftest, suite (plan/execute/analyse), CLI in `__init__.py`;
- ensemble seed choice: a short sync-seed probe; Vox Populi ignores the sync seed, so the ensemble varies the map;
- tests: `python -m unittest discover -s tests` (96 tests, about 40 s): fakes in tests/verify_tests.

In progress / next:
1. Host-only mode at full size with real host runs; measure the wall time against 5 minutes:
   `PYTHONPATH=python python -m civ5headless verify --host-only` (config: civ5headless.toml in this worktree).
2. Statistics self-test on a real ensemble: `c5h verify --analyse <run> --self-test --foreign <other-map run>`.
3. docs/verification.md; final report.

Uncommitted: civ5headless.toml (gitignored, local paths), runs/ (gitignored).
