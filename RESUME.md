# Resume notes: anydll workstream, round 2 milestone 2

Work order (coordinator, round 2 milestone 2): city-state pins in the host (spec `minorCivs`), `--skip-addin` with
or without extension, `hazards.scan_report` with a per-hit `reach`, lower hazard noise where evidence supports it,
`fingerprint.probe_path()`. Same rules and invariant as before (HHDIGEST identical to runs/baseline).

Done (committed on c5h-anydll):
- hazards: reach (load/game/input), trigger resolution (table entries and keys, field functions, nested calls,
  callback registrations through local helpers, LuaEvents fire sites across files, pcall), curated `reviews`,
  `writesWithArgs`, `notWithDll`, host-run add-ins; `scan_report()`; tests.
- verify's `_hazard_scan` uses `scan_report` and the per-hit reach (two small edits in verify/checks.py).
- `fingerprint.probe_path()` and its test.
- host: `--skip-addin` matches with or without .lua/.xml (boot self-test check); spec `minorCivs` pins applied when
  the host chooses city-states; `host-report.json` `minorCivs` section; random city-state pool limited to IDs in
  the database (the DLC snapshot has no ID 0).
- docs: engine-contract (run report, section 15, add-ins), profiles.md (reach, coverage, curated data).

Verification: unit tests (`python -m unittest discover -s tests` with `python` on PYTHONPATH); invariant 8/8 with
the new exe; stock DLL pins (full and partial) and fingerprint player lines; skip-addin both forms on the reference
mod set; integration test `tests/anydll_tests/test_host_checks.py` (C5H_INTEGRATION=1).

Next if resumed: check `git status`, rerun the tests, then the final report to the coordinator.
