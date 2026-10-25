# Ledger: standalone repository, any DLL or mod, verification suite

Resume point for the work in [plan.md](plan.md). Newest state first in "Resume here"; the log below is append-only.
The host's own history (milestones M0–M6, parity work against the real game) is in [history/](history).

## Resume here

- Phase A done (2026-10-25): history split, SDK vendored, own build, replay check passed.
- Phases B, C, D: running as three workstreams (plan section 9), each in a worktree `../civ5-headless-wt/<name>`
  next to this checkout, on branch `c5h-<name>`. Each writes `RESUME.md` in its worktree at every milestone and on a
  pause; merges into main leave `RESUME.md` out.
  - platform: milestones 1 (package, configuration, `c5h`) and 2 (real-game session, DLC snapshot from the game's
    files, doctor, get_toolchain, user guide) merged; milestone 3 (integrating anydll's pieces: `--profiles`,
    `--fingerprint`, `c5h fingerprint`/`hazards`, mods registry generator `c5h modsdb`) under way.
  - anydll: phase C items 1–5 and 7 merged (973c324). C.6's real-game comparisons wait for phase E.
  - verify: under way (started from main after platform milestone 1).
- Open for phase E or later: UI popups reach add-in listeners only through profiles (generic routing not evaluated);
  the order of `<LuaContext>` children before the parent's script is assumed (engine-contract open question 11); the
  real-game session has run only against a fake game.
- The real game is not used until calibration (phase E) and the coverage comparisons (phase C.6); workstreams run
  host-only games only.

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
