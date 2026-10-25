# Resume: any-DLL workstream (c5h-anydll)

Work order (summary of the brief, 2026-10-25): phase C items 1-5 of docs/plan.md plus the 9.2/9.3 interfaces, in
the worktree `civ5-headless-wt/anydll`, branch `c5h-anydll`. Own: `host/`, `profiles/`, `probes/`,
`python/civ5headless/fingerprint.py`, `hazards.py`, `data/`, `docs/engine-contract.md`, `docs/profiles.md`,
`tests/anydll_tests/`. Never launch the real game, never write into the game folder, My Games or the Civ5StackMod
repository; commit locally, never push.

1. InGameUIAddins in stub UI contexts (no allowlist), errors reported, `--skip-addin`, `--no-addins`.
2. UI emulation profiles in `profiles/` with manifests, `--profiles`, `docs/profiles.md`.
3. `python/civ5headless/hazards.py`: static scan of the UI Lua for state-changing DLL methods.
4. `<run>/host-report.json` (plan 9.2): stubs with known-harmless flag, Lua errors, add-ins, profiles, UI files.
5. `probes/fingerprint.lua` + `--lua-probe` + `python/civ5headless/fingerprint.py` (plan 9.3); probe on/off identical.
6. Small fixes: MAX_MAJOR_CIVS from the database, game folder from the registry, no machine paths.
7. Stock BNW DLL coverage runs (host only); optional plain VP (vp-det build, see coordinator note).

Invariant for every step: HHDIGEST lines identical to `runs/baseline/` (main's exe) for the field-map DLL; checked
with `python tests/anydll_tests/invariant.py run --config runs/invariant.json --exe EXE --out runs/NAME --workers 5`
then `... compare runs/baseline runs/NAME` (config and baselines are under the ignored `runs/`).

## State

- Milestone 1 (committed): items 1, 2 (profiles moved), 4 (host-report.json), 6 (MAX_MAJOR_CIVS, game folder).
  Invariant: 8 of 8 identical (runs/step1).
- main merged (platform milestone 1 module moves).
- Milestone 2 (committed): item 5. probes/fingerprint.lua, python/civ5headless/fingerprint.py,
  tests/anydll_tests/test_fingerprint.py (unit), tests/anydll_tests/probe_check.py (dense / sparse / off runs).
  Probe on, all 8 cases: digests identical to the baseline (runs/probe-on). probe_check speed-quick and
  players-teams2 with --every 7: passed (runs/probe-check).
- Milestone 3 (committed): item 3. python/civ5headless/hazards.py (scan, methods), data/lua-state-methods.json
  (derived from the VP fork and stock sources), data/lua-hazards.json (curated), tests/anydll_tests/test_hazards.py.
  Reference set: `python -m civ5headless.hazards scan --report runs/step1/speed-quick/host-report.json`
  (112 files, 281 calls, 6 covered by profiles).
- Next: docs/profiles.md, engine-contract section on the run report, known-ui-files.json filled from the reference
  set, item 7 (stock DLL, mod-free database, probe_check with it).

## Build and run

- `set C5H_TOOLCHAIN=E:\Projects\Civ5StackMod\work\toolchain\sdk`, `python tools/build_host.py`.
- Baseline exe copy: `runs/baseline/exe/civ5headless.exe`.
