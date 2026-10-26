# Ledger: standalone repository, any DLL or mod, verification suite

Resume point for the work in [plan.md](plan.md). Newest state first in "Resume here"; the log below is append-only.
The host's own history (milestones M0–M6, parity work against the real game) is in [history/](history).

## Resume here

- **Paused (2026-10-26, user: "pause when possible"):** the run-outputs work on `c5h-platform`
  (`../civ5-headless-wt/platform`, not yet merged into main). Its work order:
  1. DLL choice for `--no-mods` and `--mod` (the game's own DLL, or the first mod in the set that ships one).
  2. `--detail summary|standard|full`.
  3. A `report.html` per run, `c5h report RUN...` and a queue summary page, built on shared HTML/SVG helpers.
  4. A final ownership map.
  5. User-guide updates.

  Its checkpoint is `RESUME.md` in that worktree. To resume:
  1. Relaunch an agent with the work order and the checkpoint.
  2. Merge main into the branch first, because main has the bundled-Python kit and `docs/running.md`.
  3. When it is done, review and merge it.
  4. Update section 6 of `docs/running.md` ("What a run leaves behind") with the detail levels and the report.
  5. Remake the kit (`python tools/make_kit.py --smoke`) and try a run plus its report from the unpacked kit.
- **State (2026-10-25):** phases A–D done as far as they go without the real game, all merged into main (188
  tests). The three workstream branches (`c5h-platform`, `c5h-anydll`, `c5h-verify`, worktrees in
  `../civ5-headless-wt/`) are fully merged and idle; their `runs/` folders hold the host-only evidence.
- **Stopped here: everything next needs the real game** (the user's rule: do all that needs no game, stop before
  it). Phase E, calibration, about 2 hours of real game, in this order:
  1. Preconditions: the real game free (no other autoplay or A/B queue), `c5h doctor` clean on the real-game group
     (`EnableTuner = 1`, `LoggingEnabled = 1` in config.ini), the DLL under test deployed with its mods.
  2. Live smoke of `RealGameSession`, never run live so far: launch, set_mods, start_game (Tiny, fingerprint), 5 turns
     of autoplay, collect_logs, replay_data, quit; config.ini restored. About 5 minutes. Fix what breaks first.
  3. `c5h verify --quick` with this fork's digest DLL and mods (exact match expected for the whole horizon).
  4. `c5h verify --quick` with plain VP (upstream build plus its mod files deployed; back up and restore MODS) and with
     the stock DLL and no mods (city-states learned from the real game's turn 0).
  5. `c5h verify --full` once, then set the thresholds, ensemble sizes, budgets and the planner's real/host ratio
     (docs/verification.md, "Calibration"); C.6's database and turn-0 coverage comes from the same runs.
  6. Afterwards restore the real game to what it had before (the source repository's AI program DLL and mods).
- **Waiting on the user, not on the game:** creating the GitHub repository `ruskyandrei/civ5-headless` (private) and
  pushing; phase F (README quickstart, release with binaries); opening the upstream VP pull requests (branches
  `vp-det-*` in the source repository, texts in its `docs/headless-upstream-prs.md`).
- **Open, known limits:** UI popups reach add-in listeners only through profiles (generic routing not evaluated); the
  order of `<LuaContext>` children before the parent's script is assumed (engine-contract open question 11);
  `CalculateGoldRate` counts as fixed only for DLLs with the digest additions; Squads reads options from user mod data
  (empty in the host); the hazard scan does not follow `include()`; statistical power is about a 25% shift when the
  DLL ignores the sync seed (VP), so the ensemble varies the map; installed-package data for `probes/`.

## Log

### 2026-10-25: phase A

- History: the 139 commits of the source repository's `headless-host` branch that touch the host paths, exported with
  `git fast-export` (path-limited) and renamed with `git filter-repo` (`Civ5Headless/` to `host/`, `work/headless/`
  and the generic `tools/headless/` scripts to `python/civ5headless/`, `docs/headless-*.md` to `docs/`). Every file at
  the tip is byte-identical to the source branch at `df9d682d4`. (A direct `git filter-repo` of a clone failed on
  objects reachable only from old VP release tags; the path-limited export avoids them.)
- `sdk/`: 49 headers (exactly what `/showIncludes` reports for the host sources) and 3 import libraries, copied
  unchanged; provenance and licence in `sdk/README.md`. The licence is GPL v3 (`License.rtf` of the source repository
  is the Community Patch Project's GPL v3), so `LICENSE` is the GPL v3 text.
- Build: `tools/build_host.py` no longer borrows the DLL build; `tools/toolchain.py` finds VC9 through `--toolchain`,
  `C5H_TOOLCHAIN`, `toolchain/` or an installed Visual Studio 2008 (registry). `tools/gen_interfaces.py` reads
  `sdk/` and writes `host/gen/`; regenerating changes only the banner line.
- Replay check: the new exe replays the M5 final game (Standard Continents, seeds 1001/2002, field-map DLL CB6B0BED)
  for 120 turns with digests identical to the reference host run in every section except `game`, which holds the
  remaining-autoplay count (the reference ran 302 turns). The previous exe, built from the same host source, run for
  the same 120 turns gives identical digest lines; the logs differ only in the OS thread id of the `HHENV` lines.
- Known: `host/setup/HHNewGame.cpp(823)` warning C4129 (an escape in embedded Lua; harmless, predates the split).

### 2026-10-25: platform milestone 1 merged

- Python modules moved with `git mv` into the plan's layout (`spec`, `dbbuild`, `run`, `queue`, `compare/`,
  `realgame/`), package-relative imports, `config.py` (civ5headless.toml plus discovery of Steam library, My Games,
  mods, cache, active mods, host exe), `c5h` (`python -m civ5headless`) with doctor, run, queue, compare and the
  former scripts as subcommands. 50 unit tests (2 integration tests need `C5H_INTEGRATION=1`).
- Equivalence: a Tiny 30-turn game through `c5h run` and through the old `hhbench.py` gives identical digests,
  checkpoints, replay data and final dumps.
- Behaviour changes: queue paths resolve against the queue file; a difference only in `savedb` no longer counts in
  `compare` and `skew` (as in `parity`). Test packages must not use standard-library names (`tests/platform_tests`).

### 2026-10-25: platform milestone 2 and anydll merged

- Platform milestone 2 (fcda9f6): `realgame/` (FireTuner client and service, launcher with optional CPU guard, mod
  activation, config.ini seeds with restore, `RealGameSession`, probe/record/dbcapture on it), tested against a fake
  game only; `c5h snapshot` builds the DLC snapshot from the game's files (modded databases built from it equal those
  from a captured snapshot); full `doctor`; `tools/get_toolchain.py` (from the SDK 7.0 ISO, `--iso`: identical files,
  host builds and plays); `c5h.cmd`; user guide and database-builder docs on `c5h`.
- Anydll (973c324): every InGameUIAddin runs in a stub UI context (no allowlist); the five UI emulations are profiles
  (`profiles/`, docs/profiles.md); `host-report.json`; `probes/fingerprint.lua` with `--lua-probe` and
  `fingerprint.py`; UI hazard scan `hazards.py`; MAX_MAJOR_CIVS from the game; game folder from the Steam registry;
  crash logging; stock BNW DLL support (the host picks random civilizations, which cannot match the real game: specs
  for real-game comparisons must name them).
- Checks: this fork's results unchanged after every host step (anydll: 8 cases, 7 Tiny x 100 turns and Standard x 120;
  independently, the 120-turn M5 replay with anydll's exe has identical digests). Probe on/off identical with the
  digest DLL; dense against sparse fingerprints identical on the stock DLL (3 x 150 turns) and on plain VP (upstream
  master + determinism fixes, 3 x 100 turns). On main: 104 tests pass; `c5h snapshot --dll <stock DLL>` runs the
  post-processing and equals the captured snapshot.

### 2026-10-25: verify merged

- `c5h verify` (22d209f): modes quick, full and host-only; checks setup (database, pregame, turn 0, civ choice,
  health: Lua errors, stubs, UI hazards), trajectory (real against host, A/A, frame skew, heap perturbation, probe
  neutrality), statistics (ensemble envelope and bias sign test over replay datasets and fingerprint metrics, with
  mean, max and sum aggregates), performance (per-turn time, memory, CPU, throughput at 1/4/8 workers, history
  file); HTML and JSON report; exit codes 0 pass, 1 fail, 2 usage, 3 incomplete. docs/verification.md.
- Host-only on the field-map DLL and this fork's mods (the agent's run): 3.5 min; A/A, skew 7 and heap-perturb all
  150/150 turns; probes neutral; 4/4 setups reproduce; the one warning is UI hazards (58 game-reachable state-changing
  calls without a profile). Throughput 56 / 231 / 394 games per hour at 1 / 4 / 8 workers.
- Statistics self-test (32-game ensemble): 12 held-out host games pass the envelope (mean coverage 93.1%), bias quiet
  in 11/12; a 5% shift of one metric is not detectable (about 25% is); foreign setups are caught once world sums are
  aggregated. VP ignores the sync seed for these games, so ensembles vary the map seed.
- Runs only against fakes: the whole real side. Calibration (phase E) must set the envelope and bias thresholds,
  ensemble sizes and budgets per mode, the real/host time ratio of the planner, `heal_turns`, the default setups and
  civilization list, and pregame/UI ignore lists from real dumps.

### 2026-10-25: platform milestone 3 merged

- 26e4a4e: `c5h modsdb` builds the mods registry from `.modinfo` files (game schema; activation order respects
  dependencies). For this fork's 5 mods it equals the game's live registry in every row; the database built from it
  and two Tiny 30-turn games (digests, fingerprints, host report) are identical to those from the game's registry.
  `c5h run --mod/--no-mods`, `dbcache`, queue keys use it. Profiles and fingerprint wired into `run`, `queue` and
  `RealGameSession.start_game` (same files, same injection point as the host); `c5h fingerprint`, `c5h hazards`;
  config keys `profiles`, `probes`; spec `minorCivs`; `RealGameSession.replay_data()` (one player per tuner call:
  the tuner caps a result at 10,000 items and 256 KiB). 174 tests.
- Host-only `c5h verify` on main (before this merge): 3.6 min, verdict warn (UI hazards only), as in the agent's run.

### 2026-10-25: anydll milestone 2 merged

- 9671c70: the host honours spec `minorCivs` when it chooses civs itself (stock-like DLLs; VP chooses in the DLL and
  is left alone, with a match report), `host-report.json` `minorCivs` section, random city-states only from IDs the
  database has; `--skip-addin` accepts names with an extension; `hazards.scan_report` and a per-hit `reach`
  (load/game/input) with better call resolution, curated reviews and host/DLL rules: on the M5 reference run 0
  uncovered game-reachable UI hazards (was 60), plain VP 5, stock DLL 37 (base-game UI); `fingerprint.probe_path()`.
  Invariant (8 cases) identical. 181 tests.
- Open: `CalculateGoldRate` counts as fixed only for DLLs with the digest additions (no better marker yet); Squads
  reads its options from user mod data, which the host keeps empty; the hazard scan does not follow `include()`;
  installed-package data for `probes/` (only `data/*.json` ships).
- Independent check after the merge: the 120-turn M5 replay with main's exe (out 20261025-211224) has digests identical
  to the phase A run.

### 2026-10-25: verify follow-up merged; stop before the real game

- b19eb10: verify uses the merged interfaces (fingerprint through `run.play`/`start_game`, `replay_data()`,
  `hazards.scan_report` reach, `--mod`/`--no-mods`); compared host games get the real game's city-states (read from
  its turn-0 fingerprint) when the DLL leaves the choice to the exe; DLLs without digests get a sparse-fingerprint
  probe-off reference; turn counts capped at the horizon. 188 tests.
- Host-only runs (agent): this fork's DLL and mods pass in 4.0 min (0 uncovered game-reachable UI hazards; A/A, skew
  and perturbation 150/150; 0.43 s/turn, 450 MB; 53 / 201 / 328 games/h at 1 / 4 / 8 workers). Stock DLL with no
  mods: warn in 0.8 min, only the expected 37 UI hazards of the base-game and EUI UI; fingerprint A/A, skew and
  perturbation 150/150; the stock DLL draws on the sync seed, so its ensemble keeps the map (0.08 s/turn, 121 MB).

### 2026-10-26: release kit

- Running needs no VC9: `civ5headless.exe` imports only Windows DLLs, MSVCR90/MSVCP90 (the Visual C++ 2008 runtime,
  which Civ V ships in `VCRedist\vcredist_x86.exe` and installs; the game's own DLLs import it too) and the Firaxis
  DLLs it loads from the game folder. VC9 is only for building.
- Decision (user, 2026-10-26: "whatever makes most sense"): binaries ship as a kit attached to GitHub releases, not in
  the repository. `tools/make_kit.py` makes `dist/civ5-headless-<version>-<commit>.zip` (about 1.5 MB) from `git
  archive HEAD` plus a host built at that commit: `bin\` (exe, pdb, build-info.json), the `c5h` package, profiles,
  probes, examples, user docs, LICENSE, SOURCE.txt (GPL source pointer), the SDK notice. `kit.json` makes config treat
  the folder as a kit (workspace, exe, profiles, probes); `c5h.cmd` uses a bundled `runtime\python.exe`
  (`--python-embed`), else `C5H_PYTHON`, Python on PATH or the py launcher. The host links with `/PDBALTPATH`, so
  the exe carries no build-folder path.
- Checked: `--smoke` (doctor from an unpacked kit finds the kit's exe, profiles, probes); from an unpacked kit outside
  the repository, a 20-turn Tiny game with the active mods (snapshot and database built from the game's files in
  under 4 s, six profiles from the kit, fingerprint on) and a 30-turn stock-DLL game with no mods, both fine.
- Open: bundle the embeddable Python in release kits or not; a GitHub Actions release workflow once the repository
  is on GitHub.

### 2026-10-26: bundled Python, running guide

- Decision (user, 2026-10-26): kits bundle Python. `make_kit.py` adds python.org's embeddable Python 3.12.10
  (amd64), which is pinned by SHA-256 and has its Authenticode signers checked (PSF and Microsoft), in `runtime\`.
  `python312._pth` is patched to add `..\python`, because the embeddable Python ignores PYTHONPATH. The kit is about
  12.6 MB.
- Checked: the smoke test confirms that the bundled Python ran. With no system Python on PATH, from an unpacked kit
  outside the repository:
  - run, fingerprint compare, hazards and modsdb all work;
  - `c5h verify --host-only` passes in 3.5 min (150/150 turns for A/A, frame skew and heap perturbation).
- An exe built at an earlier commit is accepted when the host sources have not changed since that commit.
- `docs/running.md`: how to run, with every option and examples. It is in the kit and linked from the README and the
  kit's QUICKSTART. Its section 6 waits on the run-outputs work.
- Found while writing it: `--no-mods` and `--mod` still played the active mods' DLL. The fix is part of the
  run-outputs work on `c5h-platform`, paused (see "Resume here").
