# Headless host: user guide

> This guide predates the standalone repository and is being rewritten around `c5h`. Until then, read its commands
> through this table; inputs that were machine paths (game folder, MODS, databases, host build) now come from
> `civ5headless.toml` or discovery (`c5h doctor`), and run folders go to `runs/`.
>
> | In this guide | Now |
> |---|---|
> | `work/headless/hhbench.py newgame --run N --spec S --target-turn T ...` | `c5h run S --turns T --run N ...` |
> | `work/headless/runner.py run\|status\|compare Q` | `c5h queue run\|status\|compare Q` (relative paths in Q are relative to Q) |
> | `work/headless/gamespec.py resolve\|lua S` | `c5h spec resolve\|lua S` |
> | `work/headless/build_db.py`, `dbcache.py`, `dbdiff.py` | `c5h dbbuild`, `c5h dbcache`, `c5h dbdiff` |
> | `tools/headless/hhdigest.py compare A B` | `c5h compare A B` (run folders or logs) |
> | `tools/headless/hhdigest.py verify\|hash` | `c5h digest verify\|hash` |
> | `tools/headless/parity_t000.py` | `c5h dumps` |
> | `work/headless/parity_run.py`, `host_first.py`, `skew_sweep.py` | `c5h parity`, `c5h host-first`, `c5h skew` |
> | `work/headless/phase_speed.py` | `python tools/phase_speed.py` |
> | `work/build-headless.py` | `python tools/build_host.py` |
> | `work/vpbench/vpbench.py`, `game_probe.py`, `record_matrix.py` (real game) | not yet: `realgame/` (milestone 2) |

`civ5headless.exe` plays Vox Populi AI autoplay games with the unchanged game DLL and without Civilization V. A
game from a spec is the same game the real game plays from that spec: per-turn state digests are identical
(100-turn Continents reference, `hh-m2-aa100-a`). It is several times faster than the real game, needs about
300 MB instead of 1.9 GB, and many games run side by side.

Design and status: [plan](headless-host-plan.md), [ledger](headless-host-ledger.md), [engine
contract](headless-engine-contract.md), [database builder](headless-dbbuild.md), [DLL
additions](headless-dll-additions.md).

## 1. Build

```
python work/build-headless.py --config release      # -> work/headless-output/Release/<ts>/civ5headless.exe
python work/build-vp-msvc.py ...                     # the game DLL as usual (work/msvc-output/Release/<ts>/)
```

The host uses the VC9 toolchain in `work/toolchain`, like the DLL. The tools below pick the latest host build
(`work/latest-headless-build-path.txt`) unless `--exe` is given. The host loads the Firaxis DLLs (database,
localization, Lua) and the ICU data from the game folder (`--game-dir`, default the Steam install); nothing of the
game is copied or committed.

## 2. Game database

The host needs the modded game database. `build_db.py` builds it from the mod files in about 3 s
([details](headless-dbbuild.md)):

```
python work/headless/build_db.py --mods-dir <MODS> --mods-db <Civ5ModsDatabase.db> --dll <DLL> --out <built.db>
```

You rarely call it yourself: `hhbench.py` and the runner use `work/headless/dbcache.py`, which builds once per
(mods input, DLL, DLC snapshot, host exe) and reuses the result (`work/headless/cache/db/<key>/built.db`). The
key hashes the contents of the `.modinfo/.xml/.sql/.lua` files, so a mod edit gives a new database automatically.

Mods input: a MODS folder and its `Civ5ModsDatabase.db` (the activated mods). Use a pinned copy, for example
`work/headless/db/mods-headless-host-0ed40de35-input/` (in the main checkout), or the live
`Documents\My Games\Sid Meier's Civilization 5\MODS` with a copy of `cache\Civ5ModsDatabase.db` (the live one
has no activated mods while the game sits in the mod browser). Both are only read.

## 3. Game specs

A spec is JSON mirroring the single-player setup screens; omitted fields behave like an untouched screen
(`work/headless/gamespec.py` docstring, plan section 4.4). Examples are in `work/headless/specs/`:

```json
{"map": {"script": "Assets/Maps/Continents.lua", "size": "WORLDSIZE_STANDARD"},
 "speed": "GAMESPEED_STANDARD", "era": "ERA_ANCIENT", "difficulty": "HANDICAP_EMPEROR",
 "seeds": {"map": 1001, "sync": 2002}}
```

- Other fields: `map.options`, `map.civ5map` (premade maps), `majors`, `cityStates`, `slots` (civ, team per
  slot), `gameOptions`, `victories`, `maxTurns`.
- The two seeds fix the whole game (map, civs, city-states, every AI decision). Same spec + same DLL + same
  database = the same game, on every run and in the real game.
- `python work/headless/gamespec.py resolve SPEC.json --db <built.db> --out RESOLVED.json` validates names and
  writes the explicit form the host reads. hhbench resolves for you; it also accepts a resolved spec, and the
  runner substitutes seeds per job.

## 4. One game

```
python work/headless/hhbench.py newgame --run NAME --spec work/headless/specs/continents-standard.json \
       --target-turn 250 --dll <DLL> --mods-dir <MODS> --mods-db <Civ5ModsDatabase.db> [--diagnostics 1]
# the same through vpbench:
python work/vpbench/vpbench.py newgame --backend headless --run NAME --spec ... --target-turn 250 --dll ... \
       --mods-dir ... --mods-db ...
```

The run folder is `work/test-runs/NAME` (or `--run-dir DIR`). Useful options:

| Option | Meaning |
|---|---|
| `--db DB` | use this database instead of the cached build |
| `--diagnostics N` | `Game.SetStackingDiagnosticsLevel(N)` before autoplay (behaviour runs) |
| `--improved-mask N` | `Game.SetStackingAIImprovedMask(N)` (DLLs with the A/B switch, ai-improvements) |
| `--ab-role baseline\|test` | A/B of two DLL builds: records `improvedMask` 0 / -1 in `setup.json` for abcompare |
| `--checkpoint-every N` | checkpoint every N turns (default 1) |
| `--maximum-seconds S`, `--stall-seconds S` | kill the game after S seconds, or after S seconds without a new turn |
| `--max-memory-mb MB` | commit limit of the host process (job object; default 3500) |
| `--affinity MASK`, `--low-priority` | CPU pinning, below-normal priority |
| `--prune` | afterwards delete the database copy (60 MB), state dumps (35 MB) and the DLL's AI logs (60 MB at T100) |
| `--host-arg=ARG` | pass an option to `civ5headless.exe` (run it without arguments for the list); write it with `=` when ARG starts with `--` |

The host itself can also be run directly (`civ5headless.exe newgame --spec RESOLVED --out DIR --dll ... --db ...
--turns N`); hhbench adds the vpbench files, limits and the database cache.

### Run folders

hhbench writes the files vpbench writes, so `compare.py`, `abcompare.py`, `samerun.py` and
`summarize-ai-features.py` read headless runs unchanged:

| File | Headless content |
|---|---|
| `events.jsonl` | launched, diagnostics_enabled, improved_mask, checkpoint (every 10 turns), victory / target_reached, completed or failed |
| `setup.json` | vpbench's setup query (before arming), plus `improvedMask`, `backend`, `abRole`, `diagnosticsLevel`, `dllSHA256`, `specKey` |
| `spec-resolved.json` | the resolved spec |
| `checkpoints/turn-NNNN.json` | vpbench's CHECKPOINT query (the ai-improvements version with the abcompare strength metrics) at every turn change, `turn-NNNN-final.json` after autoplay; `turn-0000.json` is the host's own T000 checkpoint |
| `turn-times.jsonl`, `turn-seen.json` | exact seconds since autoplay started, per turn |
| `replay-messages.json`, `replay-data.json` | as vpbench: replay messages without type 2, and every major's replay series |
| `status.json` | `state`, `startTurn`/`endTurn`/`turns`, `wallSeconds` (autoplay), `secondsPerTurn`, `process` (host CPU seconds, peak working set, peak private bytes, peak virtual), `endReason` (target_turn, victory, killed), `winner`/`victory`, `save` (seed key), `background` |
| host outputs | `newgame-report.json`, `Logs/` (HeadlessDigest.log with the per-turn digests, Headless.log, Lua.log, the DLL's logs, `Stacking-*.log` with diagnostics), `t000-map.json`, `t000-digest.json`, `dump-t000/`, `dump-tN/` |

Fields that differ from a real run, by design:

- **Checkpoints** are exact: taken at the end of the update in which the game turn advanced, not by a 30-second
  poll in the middle of a turn. They do not change the game (digests over 100 turns are the same with and
  without per-turn checkpoints, and equal the real game's).
- **Times**: `wallSeconds` counts from arming autoplay to the target turn, as vpbench does; `hostSeconds` adds
  start-up (database copy, map generation, about 3 s) and shutdown. `pollSeconds` is 0.
- **process**: from the host process; `StartTicks` is the creation FILETIME. `PeakCommit` is the job object's
  peak.
- **save**: no save is written. `save` holds a seed key `headless-<spec>-m<map>-s<sync>-<hash>`; abcompare groups
  runs of the same game by it. `finalSave` is absent.
- **background**: system busy cores, the real game's CPU (`gameBusyCores`) and everything but the host
  (`otherBusyCores`) during the run, so timings can be judged.
- **Return player**: vpbench replaces autoplay's return player when player 0 dies (a real-game workaround for the
  defeat screen); the host does not need to. The game up to the target turn is the same.
- **Victory**: a victory ends autoplay; `endReason` is `victory` with `winner`/`victory`.

### Diagnostics (behaviour runs)

`--diagnostics 1` sets the stacking diagnostics level before autoplay, as vpbench does. The DLL writes
`Stacking-<session>-NN.log` into the run's `Logs` folder, and `status.diagnosticsLogPrefix` names the session:

```
python work/summarize-ai-features.py <diagnosticsLogPrefix> --logs <run>/Logs
```

## 5. A batch

`work/headless/runner.py` runs a queue with N parallel games:

```
python work/headless/runner.py run QUEUE.json [--workers N] [--affinity p-first|none] [--retry-failed]
python work/headless/runner.py status QUEUE.json
python work/headless/runner.py compare QUEUE.json
```

```json
{"out": "work/test-runs/ab-stack-v2", "workers": 8,
 "defaults": {"spec": "work/headless/specs/continents-standard.json", "turns": 250,
              "modsDir": "<MODS>", "modsDb": "<Civ5ModsDatabase.db>", "maxSeconds": 7200},
 "variants": {"A": {"dll": "<baseline DLL>", "abRole": "baseline"},
              "B": {"dll": "<test DLL>", "abRole": "test"}},
 "seeds": [[1001, 2002], [1003, 2004], [1005, 2006]]}
```

- Jobs are seeds × variants (named `<variant>-m<map>-s<sync>`) plus any explicit `jobs`; every job key
  (`spec`, `turns`, `dll`, `db`, `modsDir`, `modsDb`, `diagnostics`, `improvedMask`, `abRole`, `checkpointEvery`,
  `maxSeconds`, `stallSeconds`, `maxMemoryMB`, `prune` (default on), `hostArgs`, `lowPriority` (default on)) can be
  set in `defaults`, a variant or a job.
- Databases are built once per (mods input, DLL) before the workers start.
- Worker k is pinned to the k-th physical core: the 8 P-cores (both hyperthreads) first, then the E-cores.
- State is in `QUEUE.state.json`. Restarting skips completed runs, re-queues interrupted ones (the partial folder
  is kept as `<name>-rN`) and leaves failed ones failed unless `--retry-failed`. A killed runner takes its games
  with it (job objects), so nothing is left running. `QUEUE.stop` pauses: no new games start, running ones finish.
- `status` prints the job table and totals (game turns per hour, background load) and writes
  `QUEUE.summary.json`. `compare` runs `samerun.py` for every seed's variant pair and `abcompare.py` over the
  batch (`QUEUE.abcompare.json`), then `compare.py` for the first runs.

## 6. Comparing runs

The real-run tools read headless runs unchanged:

- `python work/vpbench/compare.py RUN...`: side-by-side summary (timing by phase, wars, captures, cities).
- `python work/vpbench/samerun.py RUN_A RUN_B`: did two runs play the same game (final checkpoint)?
  For an A/A pair or a decision-neutral change this must say "identical".
- `python work/vpbench/abcompare.py RUN... [--turns 100,150,200,250]`: per-player deltas of test runs against the
  baselines of the same seed (`save` key). With `--ab-role`, B runs count as "every player improved" (mask -1)
  against the A runs. With a mask-switch DLL use `--improved-mask` and the mirrored-mask design instead.
- `python work/headless/phase_speed.py RUN_OR_TRACE...`: seconds per turn by game phase.

Headless games are deterministic: the A/A noise floor that real runs need two baselines for is zero (a repeated
run is identical), so one run per (seed, variant) is enough and more seeds buy more signal.

## 7. Speed, scaling and memory

Measured 2026-10-25 on the i9-13900K (8 P-cores with hyperthreading, 16 E-cores, 64 GB), host build of
`hh-tooling`, DLL `20261025-015922`, database from `mods-headless-host-0ed40de35-input`, Continents Standard
Emperor, 8 majors, 16 city-states, the reference profile's DLL logging on. The machine was shared: the real game
was recording the M5 parity matrix the whole time, and another agent built DLLs part of the time. Each table gives
that background load (`otherBusyCores`: busy cores other than the hosts, from `status.background` and the batch
summary). Raw data: `work/headless/m6/` in the `hh-tooling` worktree (ignored).

### Single game against the real game

Host: one game pinned to one P-core (spec seeds 1001/2002, the `hh-m2-aa100-a` game), background 2.7 to 4.7 busy
cores. Real game: the vpbench runs `abq1-{A,B,C}-m0` (same settings, other seeds, the ai-improvements DLL with mask
0: the same AI for every player) and the trace-DLL runs `hh-m0-aa100b-a/-b` (this spec, exact per-turn times from
the trace). `python work/headless/phase_speed.py` gives the tables.

| s/turn | host (1001/2002) | real abq1-A | real abq1-B | real abq1-C | real trace aa100b-a | speed-up |
|---|---:|---:|---:|---:|---:|---:|
| T0-25 | 0.59 | 3.87 | 3.88 | 3.86 | 3.76 | 6.5x |
| T25-50 | 0.67 | 3.87 | 3.86 | 3.88 | 4.04 | 5.9x |
| T50-75 | 0.86 | 4.27 | 5.30 | 4.47 | 4.48 | 5.3x |
| T75-100 | 1.17 | 5.32 | 5.92 | 5.31 | 5.55 | 4.7x |
| T100-125 | 1.46 | 5.91 | 6.95 | 6.12 | | 4.3x |
| T125-150 | 1.66 | 6.34 | 7.15 | 6.33 | | 4.0x |
| T150-175 | 2.56 | 7.55 | 8.17 | 6.95 | | 2.9x |
| T175-200 | 3.35 | 8.16 | 11.44 | 8.57 | | 2.8x |
| T200-225 | 3.20 | 9.39 | 11.84 | 10.81 | | 3.3x |
| T225-250 | 4.08 | 10.22 | 11.64 | 10.02 | | 2.6x |
| **T0-250** | **1.96** | 6.49 | 7.62 | 6.63 | | **3.5x** |

(speed-up: the mean of the real columns over the host; after T100 the real games are other games, so the late
phases compare like with like only on average.)

- **Whole games:** 250 turns in 490 s of autoplay (493 s with start-up and shutdown) against 1,597 to 1,904 s in
  the real game. 100 turns of the reference game: 81.5 to 87 s against 443 s for the same game in the real game
  (`hh-m2-aa100-a`, about 9 minutes with launch and load), 5.2 to 5.4x.
- **Where the gain comes from:** early turns are bound by the real game's frame pacing (one player per `Update`,
  about 105 ms apart, so about 3.8 s per turn whatever the AI does); the host runs `Update` back to back. Late turns
  are AI work in both, and the host still saves the engine's rendering, UI and waiting.
- **CPU:** 451 CPU-s for 250 turns against 3,985 to 4,900 CPU-s for the real game (it keeps about 2.5 cores busy);
  9x less CPU per game.
- **DLL logging:** `--host-arg=--no-game-logging` takes 100 turns from 81.5 s to 55.6 s (-32%), but the logging
  changes AI results (the game differs from turn 53), so it is not comparable with logged runs or the real game.

### Memory

| | peak working set | peak private bytes |
|---|---:|---:|
| host, T100 | 270 to 283 MB | about 280 MB |
| host, T150 | 293 to 299 MB | |
| host, T250 | 327 MB | 326 MB (peak virtual 506 MB) |
| real game, T250 (abq m0 runs) | 1,763 to 1,825 MB | 2,046 to 2,080 MB (peak virtual 2.9 GB) |

So memory never limits parallelism: 24 games need under 8 GB. The runner's default commit limit of 3,500 MB per
game only catches runaway runs.

### Parallel scaling

W identical 100-turn games (spec seeds 1001/2002) on W workers, pinned P-cores first (`scale-w<W>` queues).
"Batch" is W x 100 turns over the batch time (the slowest game); "steady" is W x 100 turns over the mean game time,
the rate of a long queue that keeps every worker busy.

| workers | batch s | turns/h (batch) | turns/h (steady) | game s on P-cores | game s on E-cores | otherBusyCores |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 90 | 3,980 | 4,000 | 87.0 | | 4.7 |
| 2 | 97 | 7,430 | 7,730 | 89.8 | | 5.2 |
| 4 | 97 | 14,830 | 15,710 | 88.3 | | 5.4 |
| 8 | 109 | 26,450 | 29,070 | 95.7 | | 6.3 |
| 12 | 147 | 29,450 | 36,890 | 101.6 | 135.1 | 6.2 |
| 16 | 163 | 35,360 | 45,190 | 105.3 | 140.2 | 7.3 |
| 24 | 267 | 32,360 | 55,010 | 113.0 | 170.3 | 9.9 |

- Up to 8 workers (one P-core each) scaling is almost linear: 8 games take 10% longer than one.
- An E-core game takes about 1.35x a P-core game. 16 workers give the best batch rate here; 24 give the best
  steady rate but stretch every game (the slowest took 254 s) and compete with the real game and builds.
- Recommendation: 8 workers (the default) while the machine is shared with the real game or builds; 16 to 24 for a
  long queue on an otherwise idle machine. Measured with background load; an idle machine will do somewhat better
  at 12 to 24 workers.
- In real-game terms: a 250-turn game takes the real game about 27 minutes and one host worker about 8; with 8
  workers each game slows by about 10%, so the machine plays roughly 25 times as many games per hour as the real
  game (which runs one game at a time).

### A/B batches (acceptance)

- **Two builds:** `ab-builds` queue: DLL `20261025-015922` (A, baseline) against `20261025-015258` (B, test; the two
  differ only in the digest code) on 4 seeds, 150 turns, 8 workers: 8 games in 244 s with heavy background load.
  `runner.py compare`: samerun says "identical final state" for all 4 pairs, abcompare shows zero change on every
  metric at turns 50, 100 and 150, as it must for a gameplay-neutral change.
- **Mask A/B on the AI program's DLL:** `ab-mask` queue: the ai-improvements DLL (`20261024-085658`) with its
  package (`mods-reference-08D19878-input`), masks 0, 85 and 170 on 4 seeds, 100 turns, 12 workers. The host runs
  this DLL unchanged (it has no digest additions, so no per-turn digests), `--improved-mask` sets the mask before
  arming, and abcompare prints the baseline comparison and the mirrored-pair table, as for real runs; samerun
  finds the masked runs diverging from the baseline in turns 1 to 10.
- Both queues are in `work/headless/queues/` (`example-ab.json`, `example-mask.json`).

## 8. Reference and parity workflow

Parity means the host plays exactly the real game's game. Check it after host changes, VP merges and DLL changes
that touch the engine boundary.

1. Record a reference in the real game: `vpbench newgame --spec SPEC --target-turn N` (game backend) pins the
   spec's seeds and turns on the per-turn digest (`HeadlessDigest.log`); `work/headless/game_probe.py --spec` with
   the probe `work/headless/probes/dump-state.lua` also dumps the state (`dump-t000`, `dump-tN`). The references of M0–M3 are in `work/test-runs/hh-m*`.
2. Play the same spec headless with the same DLL and database (the database built from the same mods input).
3. Compare:
   - `python tools/headless/hhdigest.py compare <ref>/HeadlessDigest.log <run>/Logs/HeadlessDigest.log`: first turn
     and section that differ. `savedb` (the save-only UI tables, see Limits) always differs at turn 0; a
     difference only there is a match.
   - `python tools/headless/parity_t000.py <ref>/dump-tN <run>/dump-tN [--fields DIR]`: byte-level section
     comparison of two state dumps, with field names from a field-map DLL (`tools/headless/fieldmap_transform.py`).
   - `python tools/headless/hhdigest.py verify DUMP`: recompute a dump's hashes.
4. A difference names a turn and section; the dump of that turn (`--host-arg=--dump-turns --host-arg=a:b` and a field-map
   DLL) names the fields. Fix the host when it answers differently from the engine; make the DLL result-neutral
   when it depends on something the host cannot reproduce (plan M5).

## 9. Limits

- **savedb:** the `savedb` digest section (the embedded `Civ5SavedGameDatabase.db` the real game's UI writes into
  saves) is not reproduced. It holds UI state, not game state; it is excluded from comparisons.
- **UI-driven state:** the host emulates the UI Lua that changes game state in the reference profile (EUI civ
  ribbon gold rate, VP observer notification aging, the WhosWinning popup's RNG rolls, the human turn after
  autoplay; `HHNewGame.cpp`). Another UI mod with stateful Lua would need the same.
- **Gameplay add-ins:** only `GlobalCityBombardRange.lua` and `CBP_IncaFunctions.lua` are loaded; other
  `InGameUIAddin` scripts are taken as UI-only (plan appendix C).
- **DLL logging changes AI results:** the host turns on the reference profile's logging like the real game's
  config. `--host-arg=--no-game-logging` is faster but plays a different game; never mix the two in a comparison.
- **No saves:** the host neither writes nor loads `.Civ5Save` files (plan M7), so headless runs start from a spec,
  not from a save.
- **Breadth:** exact parity is established for the Continents reference over 100 turns; the parity matrix (plan
  section 6, M5) extends it to other maps, sizes and options.
- **Text:** the localization database is the game's `Localization-Merged.db`; mod text edits need a game launch to
  appear in city names and replay messages (rules are unaffected).
- **32-bit:** the host is a large-address-aware 32-bit process (4 GB address space), far above its needs.
