# Headless host: standalone repository, any DLL or mod, and a verification suite (plan, 2026-10-25)

This plan supersedes the notes in [headless-repo-migration.md](headless-repo-migration.md). It builds on the finished
host ([headless-host-plan.md](headless-host-plan.md), M0–M6 done) and the test suite design discussed on 2026-10-25.

## 1. Goal

A repository of its own, usable by anyone developing a Civ V DLL or mod (Vox Populi included), that:
- runs AI autoplay games headless with **any** SDK-derived game DLL and **any** mod set, on any machine with Civ V;
- tells its user how accurately a headless game represents a real Civ V autoplay game **for their DLL, mods and maps**,
  with a verification suite that runs in under 30 minutes (hard limit 1 hour);
- benchmarks speed and memory, headless against the real game, as part of the same run.

Exact equality with the real game is the strongest evidence when the DLL allows it, but it is not required: the goal
is an extremely accurate representation of a Civ V autoplay session.

## 2. Where things stand

| Area | Today | Coupling to remove |
|---|---|---|
| Host (`Civ5Headless/`, about 8,700 lines of C++) | Talks to the DLL only through the SDK interfaces; detects the optional DLL additions and runs without them (the ai-improvements DLL ran headless) | Build borrows this repo's DLL build: VC9 toolchain junction, include set, three SDK import libraries; default game folder is a path on this PC |
| Mod-specific behaviour, hardcoded in `HHNewGame.cpp` | Gameplay UI add-ins: an allowlist of two VP files. UI emulation as embedded Lua: EUI civ ribbon gold rate, this fork's observer notification aging, VP WhosWinning popup RNG, CP city-event popup, great-person popup | Needs automatic add-in handling and selectable emulation profiles |
| Database builder (`build_db.py` + host `builddb`) | Reproduces the game's database from MODS + Civ5ModsDatabase.db; verified for this mod set | Validate on other mod sets; default paths |
| Python tools (`work/headless`, `tools/headless`, about 25 scripts) | Generic: game specs, database cache, runner, hhbench, host_first, parity_run, digest compare, skew_sweep. Development-only: trace and field-map transforms, cdrift probe, contract tables, db capture | Package the generic ones, leave the rest here; machine paths in vpbench, build_db, hhbench, skew_sweep |
| Real-game control | vpbench + launcher + CPU-temperature guard + FireTuner service + mod activation; game_probe and record_matrix on top | Machine paths everywhere; the FireTuner protocol itself is generic |
| Comparison | Per-turn state digests and dumps from the DLL additions (xxHash per section, UI-only fields normalised) | DLLs without the additions need a Lua-side fingerprint |
| Seeding | Our seeds file (DLL addition) | Not needed: `config.ini` `MapRandSeed`/`SyncRandSeed` pin a menu-started game with the stock DLL code (verified 2026-10-25) |

## 3. Target repository

Suggested name `civ5-headless` (owner ruskyandrei), private until phase F.

```
civ5-headless/
  host/                 the C++ host (from Civ5Headless/), with its own build script
  sdk/                  only the SDK interface headers and import libraries the host compiles against (licence text kept)
  profiles/             UI emulation profiles: Lua plus a manifest saying which mods or files select them
  python/civ5headless/  one package and one CLI, c5h:
    spec, dbbuild, run, queue, compare     running games (from gamespec, build_db, hhbench, runner, parity tools)
    realgame/                              FireTuner client, launcher, mod activation, config.ini seeding
    verify/                                the verification suite (section 5)
  dll-additions/        optional patch for DLL sources: digests, state dumps, seeds file (as offered upstream)
  tests/                unit tests for the Python package and host self-tests
  docs/                 user guide, engine contract, database builder, verification method, project history
```

Commands:
- `c5h doctor`: checks the environment: game install, DLL, mods, Python, FireTuner enabled, host binary.
- `c5h run SPEC`: plays one game.
- `c5h queue FILE`: plays many games in parallel.
- `c5h compare A B`: compares two runs.
- `c5h verify [--quick|--full|--host-only]`: the verification suite.
- `c5h bench`: the performance part on its own.

What stays in this repository: the DLL additions and the determinism fixes (both also go upstream), the M0–M5 history
(ledger, matrices, references), and a pointer to the new repository. `Civ5Headless/` is removed here once the new
repository builds and passes its own suite.

## 4. Phases

### A. Split, keeping history (about half a day)
1. `git filter-repo` the host paths (Civ5Headless, the generic tools, headless docs) into the new repository.
2. Vendor the minimal SDK interface: `CvGameCoreDLLUtil/include`, the database, localization and Lua headers the host
   includes, and the three import libraries. This depends on decision 2.
3. Give the host its own build script: VC9 found through an environment variable or the registry, no junction.
4. Check: it builds, and the host replays one existing reference identically, with the DLL that reference used.

### B. Machine independence (1–2 days)
- One config file (`civ5headless.toml`) with auto-discovery for anything left out:
  - the Steam library through the registry and `libraryfolders.vdf`;
  - `Documents\My Games` through the known-folder API;
  - the MODS folder, the cache and the active mods from `Civ5ModsDatabase.db`.
- No hardcoded Python, PowerShell or project paths. The CPU-temperature guard becomes optional.
- Prebuilt `civ5headless.exe` in GitHub releases, so users don't need the VC9 toolchain.

### C. Any DLL, any mod set (3–5 days; the main engineering)
1. **Gameplay add-ins without an allowlist.** Run every `InGameUIAddin` in a stub UI context: no-op `Controls` and
   `ContextPtr`, and `Events` listeners recorded but only fired when the host emulates that event. Whatever registers
   `GameEvents` listeners then works as in the game. A script that fails in the stub is logged with its file name.
2. **UI emulation profiles.** Move the five embedded Lua emulations into `profiles/`. Each has a manifest naming the
   mod files that select it, matched by path and content hash. Profiles: base game, EUI, VP, CP, and this fork's
   observer aging. Unknown UI files are reported, not guessed.
3. **UI hazard scan.** Statically scan the active mods' UI Lua for calls into DLL methods that change state. The list
   of such methods comes from the DLL's Lua bindings when the source is available; otherwise a curated list. Note
   that `CalculateGoldRate` looks like a getter but writes state. Flagged calls without a profile become warnings in
   the verification report.
4. **Engine-call coverage.** Any engine method the host only stubs, called during a run, is listed in the run report.
   That is how a new DLL that needs new engine support shows up.
5. **Lua fingerprint for DLLs without the additions.**
   - A per-turn snapshot of game state through plain stored-value getters: per player, gold, cities, population,
     techs, policies, units and religion; per plot, owner, improvement, route and resource; plus the diplomacy matrix.
   - It is hashed per section and written to `Lua.log` from a `GameEvents.PlayerDoTurn` listener, identically in the
     game and the host.
   - A built-in check runs the host with and without the probe; the games must be identical, so the probe itself never
     changes a game.
6. **Coverage runs.** Each runs a few short games, and the database builder is compared with the game's own database:
   - the stock Firaxis BNW DLL with no mods;
   - Community Patch alone;
   - plain VP 5.4.8;
   - VP with EUI;
   - this fork.

### D. Verification suite: `c5h verify` (3–4 days, plus calibration)
Described in section 5.

### E. Calibration (about 2 hours of real-game time)
Run the suite on:
- this repository's deterministic DLL, where exact matching is expected for the whole horizon;
- plain VP 5.4.8, where only the statistical checks are expected to hold;
- the stock DLL with no mods.

These runs set the envelope thresholds, the ensemble size and the default map setups, and confirm the time budget.

### F. Documentation and release (1–2 days)
- A README with a quickstart, the user guide, the verification method and how to read its report.
- Contributing notes and versioning.
- A first public release with binaries. Announce to the VP developers once the upstream fixes (G) are offered.

### G. Upstream, in parallel and in this repository
Separate pull requests to Vox Populi:
- archaeology artifact pick;
- the frame-dependent trade-route counts and unit upkeep;
- the AI logging side effects;
- the uninitialised fields;
- optionally, the DLL additions, which are off by default and change no results.

## 5. Verification suite

The suite answers three questions for the user's DLL, mods and maps. It uses only the standard Lua API and
`config.ini` seeding. Where the DLL has the optional additions, it also uses their digests and dumps.

### 5.1 Exact setup checks (must pass; about 3 minutes of real game)
- **Database:** the host-built database against the game's cached database after the mods load, table by table.
- **Pregame:** every `PreGame` value after setup.
- **Turn-0 state:** the Lua fingerprint (or digest) for about 4 map setups, seeded through `config.ini`. They run in
  one game session, returning to the main menu between setups, so the launch cost is paid once.
- **Health:**
  - no Lua errors that only the host has;
  - no stubbed engine calls outside the known-harmless list;
  - the UI hazard scan clean, or every hazard covered by a profile.

### 5.2 Trajectory (about 7 minutes of real game)
- **One seeded Tiny game, 150 turns,** in both, fingerprinted every turn.
- **Host-only references** for the same game:
  - A/A: how long the DLL reproduces itself;
  - frame skew: whether it depends on the engine's frame count;
  - heap perturbation: whether it depends on memory addresses.
- **Verdict:** "the host matches the real game for N turns; the DLL itself is reproducible for M". It passes when N
  reaches M, or the whole horizon.
- **Transients:** differences that heal within two turns are reported, not failed. Differences in fields known to be
  UI-only or scratch caches are listed separately.

### 5.3 Statistical fidelity (in parallel with 5.1–5.2)
- **Host ensemble:** about 32 seeded Tiny games of 150 turns, with different sync seeds, about 3 minutes on 8 workers.
- **Envelope test:** where the real game's per-turn series sit inside the ensemble. The series are the replay datasets
  (score, economy, industry, agriculture and the rest) and Lua counts (cities, population, techs, policies, units,
  wars, captures, wonders, religions).
- **Pass rule:** about 95% of (metric, turn) points inside the 2.5–97.5% band.
- **Bias check:** a sign test flags a metric that sits on one side of the ensemble median for many turns. That catches
  a missing UI emulation even on DLLs that are not deterministic.

### 5.4 Performance (from the same runs)
- **Real game against host:**
  - wall time per turn, early, mid and late;
  - launch to first turn;
  - peak working set and private memory;
  - CPU time.
- **Host throughput:** the ensemble at 1, 4 and 8 workers or more, in games and turns per hour.
- **History:** a history file per machine, so regressions between DLL or mod versions show.

### 5.5 Modes and budget

| Mode | Real game | Host, in parallel | Total |
|---|---|---|---|
| Quick (default) | launch, 4 seeded setups at turn 0, a Tiny game of 150 turns: about 15–20 min | ensemble, A/A, skew, perturbation, throughput | about 20–25 min |
| Full | adds a Standard game of 60 turns (scale and memory) and a real A/A Tiny run | larger ensemble, Tiny games to victory | about 45–55 min |
| Host-only | none | A/A, skew, perturbation, throughput, ensemble sanity | about 5 min, suitable for CI |

### 5.6 Report
- One self-contained HTML page and a JSON file:
  - pass, warn or fail per check, and the "matches for N of M turns" line;
  - envelope charts per metric;
  - the performance table and the history trend.
- The exit code reflects the verdict, for scripts and CI.

## 6. Decisions (all approved as recommended, 2026-10-25)

1. **Repository:** `ruskyandrei/civ5-headless`, private until phase F. Local only for now; the GitHub repository is
   created when the user says so.
2. **SDK files:** vendor only the interface headers and import libraries the host needs, with the SDK licence text,
   as VP's repository does. `License.rtf` is the Community Patch Project's GPL v3 licence, so this repository is
   GPL v3 too ([LICENSE](../LICENSE), [sdk/README.md](../sdk/README.md)).
3. **Python:** one package, Python 3.11 or newer, standard library only. The report is a self-contained HTML page.
4. **Toolchain:** VC9 to build, because of the CRT ABI that crosses the DLL interfaces; users get prebuilt binaries.
5. **Supported DLLs:** any SDK-derived DLL for running games. Exact checks need `config.ini` seeding (stock code) and
   the Lua fingerprint; the digest additions stay optional.
6. **Real-game automation:** FireTuner (`EnableTuner = 1` in `config.ini`); the suite's `doctor` step checks it.
7. **This repository:** keeps the DLL additions, the fixes and the M0–M5 history; `Civ5Headless/` goes once the new
   repository passes its suite.

## 7. Estimate

About 2–3 weeks of agent work in total: A ½ day, B 1–2 days, C 3–5 days, D 3–4 days, E ½ day plus about 2 hours of
real game, F 1–2 days; G runs in parallel. Real-game time is needed only for C's coverage runs and E's calibration.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Mod UI scripts change game state in ways no profile covers | UI hazard scan plus the statistical bias check; profiles grow from what the report flags |
| A stub UI context breaks add-in scripts | Log per file; per-file opt-out in the config |
| Lua fingerprint getters with side effects | The probe on/off check runs on every verification |
| SDK header redistribution terms | Decision 2; fall back to pointing at an SDK or VP checkout |
| VC9 hard to obtain | Prebuilt binaries; document where VC9 comes from |
| Non-deterministic DLLs make exact checks meaningless | The verdict is relative to the DLL's own reproducibility (A/A), and the statistical tier stands on its own |

## 9. Work breakdown and shared interfaces (2026-10-25)

Phase A was done by hand (see [ledger.md](ledger.md)). Phases B, C and D then run as three workstreams on their own
branches, merged into `main` one at a time. Each owns its files; anything outside them is changed only by agreement
(through the ledger).

| Workstream | Branch | Owns |
|---|---|---|
| Platform (phase B, real-game automation) | `c5h-platform` | `python/civ5headless/` except the files below, `tools/get_toolchain.py`, `examples/`, `pyproject.toml`, `docs/user-guide.md`, `README.md` |
| Any DLL, any mod (phase C) | `c5h-anydll` | `host/`, `profiles/`, `probes/`, `python/civ5headless/fingerprint.py`, `python/civ5headless/hazards.py`, `python/civ5headless/data/`, `docs/engine-contract.md`, `docs/profiles.md` |
| Verification suite (phase D) | `c5h-verify` | `python/civ5headless/verify/`, `docs/verification.md` |

Tests live next to what they test, under `tests/<workstream area>/`.

### 9.1 Package layout (platform)

```
python/civ5headless/
  cli.py                c5h entry point; subcommands doctor, run, queue, compare, verify (from verify/), bench, dbbuild
  config.py             civ5headless.toml plus discovery (Steam library, My Games, MODS, cache, active mods, host exe)
  spec.py               game specs (was gamespec.py)
  dbbuild.py, dbcache.py, dbdiff.py
  run.py                one host game (was hhbench.py); queue.py (was runner.py); winproc.py
  compare/              digest.py (hhdigest), dumps.py (parity_t000), parity.py (parity_run, host_first), skew.py
  realgame/             tuner.py, launch.py, mods.py, seeds.py (config.ini), session.py, probe.py, record.py, dbcapture.py
  fingerprint.py        (any-DLL workstream)
  hazards.py            (any-DLL workstream)
  verify/               (verification workstream)
```

`config.load(path=None) -> Config` returns resolved, absolute paths with the source of each value (file, discovery or
default), so `c5h doctor` can print where everything came from.

### 9.2 Host options and run report (any-DLL)

- `--lua-probe FILE` (repeatable): runs FILE in the in-game Lua context once the game has started and before turn 0
  is processed, as the real-game session injects it through FireTuner.
- `--heap-perturb N`: shifts the host's heap layout (allocations of seeded random sizes before the DLL loads), for the
  verification suite's address-dependence check. N = 0 is off; the same N gives the same layout.
- `--profiles DIR`: the UI emulation profiles folder (default: `profiles/` next to the repository root or the exe).
- Every run writes `<run>/host-report.json`: host version, DLL path and hash, active mods, profiles selected (and why),
  UI add-ins run, failed or skipped, unknown UI files, stubbed engine calls with counts (and whether each is on the
  known-harmless list), Lua errors with file and line, turns played, wall time per turn, peak memory.

### 9.3 Lua fingerprint (any-DLL)

`probes/fingerprint.lua` runs identically in the real game (injected through FireTuner into the InGame context) and in
the host (`--lua-probe`). On the first `GameEvents.PlayerDoTurn` of each game turn it prints, through `print`, lines
that start with `C5HFP|` or `C5HM|`, which end up in `Lua.log` in both. The exact format is the any-DLL workstream's,
documented in `fingerprint.py`, which also parses it:

- `fingerprint.read(path) -> Fingerprint` with `.sections: dict[int, dict[str, str]]` (turn to section to hash),
  `.metrics: dict[int, dict[int, dict[str, float]]]` (turn to player to metric to value, major civs) and `.meta`;
- `fingerprint.compare(a, b, heal_turns=2) -> dict`: first differing turn, differing sections per turn, and transients
  (differences that heal within `heal_turns`), like the digest comparison.

It uses only plain stored-value getters that exist in the stock Firaxis Lua API, so it works with every SDK-derived
DLL. The metrics feed the statistical tier: at least score, gold, cities, population, techs, policies, units, culture,
faith, wonders, religions founded, wars and cities captured.

### 9.4 Real-game session (platform)

`realgame.session.RealGameSession` drives one Civ V process through FireTuner:

```
s = RealGameSession(config, run_dir)
s.launch()                                 # start Civ V with the tuner on; wait for the main menu; launch timings
s.set_mods(mod_ids)                        # activate exactly these mods (empty: none)
s.start_game(spec, map_seed, sync_seed, lua_probes=[...])   # config.ini seeding, setup, start, inject probes, continue
s.autoplay(turns, max_seconds=None)        # observer autoplay; per-turn wall times; stops at victory
s.to_main_menu()                           # for the next setup in the same session
s.collect_logs(dest)                       # Lua.log and, if present, the digest logs
s.process_stats()                          # peak working set, peak private bytes, CPU seconds
s.quit()
```

The verification suite codes against this interface; until it exists it uses a fake with the same methods. The host
side is `run.play(...)` (one game, returns the run folder and its report) and `queue` for many.
