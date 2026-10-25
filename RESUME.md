# Resume: verify workstream (phase D, c5h verify)

Work order (summary): build `c5h verify` (plan section 5) in `python/civ5headless/verify/`, `docs/verification.md`
and `tests/verify_tests/`, on branch `c5h-verify` in this worktree. Checks 5.1-5.4, modes quick/full/host-only with
a time budget, HTML + JSON report, exit codes. Real-game paths only against a fake session; host-only mode end to
end with real host runs (field-map DLL, local gitignored civ5headless.toml); statistics self-tests. Never launch the
real game, never write into the game or My Games folders, never modify the source repository, no pushes, no machine
paths in committed files, at most 8 host processes.

## State (2026-10-25): work order complete

Done and committed:
- package: settings, capabilities, stats (envelope + bias with leave-one-out calibration), series (mean, max, sum),
  exact, hostside (phases, cost model, budget), realside (RealGameSession driver: launch with seeds, games grouped
  by seed pair, log segments across relaunches, replay data through session.call, exported database), checks
  (incl. setup.civ-choice, host twin rule, UI hazards split into game-reachable and input-only), perf, report,
  selftest, suite, CLI in `__init__.py`;
- main merged (platform milestone 2, anydll): real fingerprint module, host-report.json, hazards, civ pinning;
- tests: `python -m unittest discover -s tests` (153 tests, about 55 s);
- host-only with the merged host: runs/host-only-2, 3.5 min, verdict warn (58 game-reachable UI hazards without a
  profile; 217 input-only), everything else pass/info;
- self-test (runs/host-only-e32 + runs/foreign): hold-outs 12/12 envelope pass, bias quiet 11/12; 5% shifts not
  detected; foreign Pangaea 2/3, Small 3/3 with sums;
- docs/verification.md up to date.

Next: the final report to the orchestrator (only). Phase E (real game) calibrates thresholds and budgets.

Uncommitted: civ5headless.toml (gitignored, local paths), runs/ (gitignored).
