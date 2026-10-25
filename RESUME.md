# Resume: verify workstream (phase D, c5h verify)

Work order (summary): build `c5h verify` (plan section 5) in `python/civ5headless/verify/`, `docs/verification.md`
and `tests/verify_tests/`, on branch `c5h-verify` in this worktree. Checks 5.1-5.4, modes quick/full/host-only with
a time budget, HTML + JSON report, exit codes. Real-game paths only against a fake session; host-only mode end to
end with real host runs (field-map DLL, local gitignored civ5headless.toml); statistics self-tests. Never launch the
real game, never write into the game or My Games folders, never modify the source repository, no pushes, no machine
paths in committed files, at most 8 host processes.

Follow-up round (2026-10-25, after platform milestone 3 and anydll milestone 2): use the new interfaces
(run.play fingerprint/mods/no_mods, start_game fingerprint, replay_data, hazards reach and scan_report,
civ5headless.probes); city-state pins from the real game's turn-0 fingerprint for the compared host games, with the
civ-choice check on them; host-only reruns on Vox Populi and on the stock DLL with no mods; docs.

## State (2026-10-25): follow-up round complete

Done and committed (latest: e4a4206):
- main merged (fast-forward to 6121025), host rebuilt in out/Release (tools/build_host.py);
- fingerprint probe through run.play(fingerprint=...) and start_game(fingerprint=...); own lookup dropped;
  replay data through replay_data() only; INPUT_TRIGGERS/hazard_reach dropped (hazards' own reach);
  --mod/--no-mods and mods/no_mods settings for host, database and real game;
- pins.py: real side publishes each game's city-states right after its start (collect_logs, fingerprint player
  lines); compared host jobs (setups, trajectory family, standard) wait and play a pinned spec (<spec>-cs<hash>.json);
  real mode phase order probe, ensemble, setups, single, references, long; host-only specs name city-states from
  minor_civs; setup.civ-choice judges compared games (allMatch, host draws);
- DLLs without digests: probe-off reference with sparse fingerprints (sparse_every 25); matched counts capped at the
  horizon (fingerprint has the state after the last turn);
- tests: `python -m unittest discover -s tests` (188 tests, 8 skipped, about 85 s);
- runs: runs/host-only-3 (VP) 4.0 min, pass; runs/host-only-stock-2 (stock DLL, --no-mods, config
  runs/stock/civ5headless.toml via C5H_CONFIG) 0.8 min, warn (37 game-reachable UI hazards, 25 unknown EUI files).

Next: the final report to the orchestrator (only).

Uncommitted: civ5headless.toml and runs/ (gitignored: local paths, run folders, runs/stock/civ5headless.toml).
