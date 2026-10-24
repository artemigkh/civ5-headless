# Headless autoplay host: implementation plan

Branch `headless-host` (from master `363d26698`), worktree `work/wt/headless`. Progress and the resume point
are in [the ledger](headless-host-ledger.md).

## 1. Goal

A command-line program, `civ5headless.exe`, that plays a complete AI autoplay game of Vox Populi without
launching Civilization V:

- **Any map:** every Lua map script the game offers (54 in the current setup), including VP's own 24 such as
  Continental Drift and Communitu, and premade `.Civ5Map` maps without fixed players (Earth, the DLC map
  pack).
- **Any setup option** from the single-player setup screens: map size, map script options, game speed,
  starting era, difficulty, number of major civs, city-states, civ/leader/team per slot, game options,
  victory types, max turns, seeds. Appendix B lists the full inventory.
- **From start to finish:** a new game is generated from the settings, played under AI autoplay until
  victory, max turns or a requested turn, and written out as checkpoints, replay data and logs.
- **Same result as the real game:** given the same DLL, mods, settings and seeds, the host produces exactly
  the game the real game produces (section 3 defines and tests this).

- **No game launch after mod edits:** the tool builds the game database from the mod files itself (M4).
  The game's own cache stays as a fallback and as the check that the build is right.

Non-goals: rendering, sound, UI, multiplayer and multiplayer-only options, hotseat or human play, Steam
features, scenario maps with fixed players. Saves are an optional follow-up (M7). The host never changes
game rules; the game DLL is loaded unchanged.

## 2. Why this is feasible

Findings from the exploration on 2026-10-24 (details in the appendices):

- **The DLL is the game.** Rules, AI, combat, pathfinding, RNG, the turn loop, new-game setup
  (`CvGame::init2`: players, random civs, city-states), map generation (`CvGame::InitMap` →
  `CvMapGenerator`, which runs the map script's `GetMapInitData`/`GenerateMap` through the engine's Lua
  system), start positions (`AssignStartingPlots.lua`, via the map script), starting units
  (`setInitialItems`) and premade-map loading (`CvWorldBuilderMapLoader`) all live in the DLL or in Lua
  scripts it runs.
- **The DLL imports nothing from the exe.** Its import table lists only Firaxis's
  `CvGameDatabaseWin32Final Release.dll`, `CvLocalizationWin32Final Release.dll`, `lua51_Win32.dll`, the VC9
  runtime and Windows DLLs. Everything else goes through interface pointers the exe hands over at runtime
  (`ICvEngineUtility4`, the UI interface, the Lua script system, the database connection).
- **One binary-level contract:** the FireWorks code linked into the DLL resolves 22 functions exported by
  the host exe (allocator, temp heap, empty-string data, log and file managers, job system) with
  `GetProcAddress`. The dedicated server exe in the SDK exports the same 22, so this is a stable,
  host-independent contract.
- **Most engine calls are visual.** Of about 160 distinct `gDLL->` methods the DLL uses, most are
  animations, achievements, Steam stats and notifications. About 80 UI methods are used, mostly
  `setDirty`, popups and messages.
- **The real game is deterministic.** Same save + same DLL gives the same game (A/A runs in the AI
  program), which makes exact parity testable.
- **Expected gain:** in the 2026-10-11 diagnostics run only 51% of wall time was inside the DLL's AI
  phases (T0–50: 0.9 of 3.9 s/turn; T250–300: 12.8 of 19.4 s/turn). The rest is mostly engine waiting.
  The real game also burns about 2.5 cores (4,044 CPU-s over 1,618 s wall). Expect roughly 1.5–2× per
  game and, more importantly, about 8 games in parallel on the 13900K.

## 3. What "the same result" means

**Reference run:** the real game, driven by `vpbench` (new game from the spec, quick combat and movement,
`Game.SetAIAutoPlay(turns, 0)`), with both random seeds pinned to the spec's values and digest logging on.

**Host run:** the same spec, DLL build, mod set and database.

**Equality:**

1. **Per-turn state digest:** at a fixed point in every turn, the DLL serializes the complete game state
   (the same `Write` calls a save uses) into memory and logs one hash per section (game, map, each player,
   each team) plus a total. Host and reference must match on every turn. A mismatch names the first turn
   and section that differ.
2. **End result:** winner, victory type, final turn and final checkpoint are identical.
3. **Boundary trace** (diagnosis only): the sequence of engine↔DLL calls in the host matches the recorded
   reference, apart from visual-only calls.

The real game must itself pass (1) as an A/A test (two reference runs, same seeds, identical digests every
turn). M0 establishes this and finds any serialized fields that legitimately vary (timers, wall-clock
fields), which are excluded from the digest and documented.

**Random choices made outside the DLL** (for example "random map script" or "random map size" in the setup
screen) are resolved by the tool from the spec seed and written into the resolved spec, which the
reference run then uses verbatim.

## 4. Architecture

```
civ5headless.exe (32-bit, VC9 /MD, LARGEADDRESSAWARE, exports the 22 FireWorks functions)
 ├─ loads from the game folder: CvGameDatabase…dll, CvLocalization…dll, lua51_Win32.dll
 ├─ loads the game DLL under test: CvGameCore_Expansion2.dll → DllGetGameContext()
 ├─ engine services (host-side implementations of the DLL's interfaces)
 │    EngineUtility · UserInterface · ScriptSystem/GameEvents · NetLoopback · Paths/Logs
 ├─ setup: game spec → pregame setters, seeds, map options, mods/VFS, gameplay Lua add-ins
 └─ driver: start sequence → autoplay arming → update loop → digests/checkpoints/outputs
```

### 4.1 Host components

| # | Component | Responsibility |
|---|---|---|
| H1 | Exe exports | `FSBA*`, `GetSmallObjectAllocator*`, `GetTempHeap`, `FStringA/W_GetStringInitData`, `GetLogFileMgr`/`PeekLogFileMgr`, `GetFileSystemMgr`, `GetMemTrackerForDLL`, `FJobSet*`, `_Init_locks` operator. Start as logging stubs; implement what the DLL calls (layouts from `FirePlace/include/FireWorks`). Log files go to the run's `Logs` folder. |
| H2 | Interface stubs | Full vtables for `ICvEngineUtility1–4` (258 methods), `ICvUserInterface1–2` (150), script system and args, generated from the headers by `tools/headless/gen_interfaces.py`. Every unimplemented method logs its first call and returns the value the reference recorded. |
| H3 | EngineUtility | The behaviourally relevant methods: turn gates (`CanAdvanceTurn`, `allAICivsProcessedThisTurn`, `HasReceived…`), `IsHost`, `GetAutorun`, `IsModActivated`, `IsDLCValid`, `getPlayerOption`, `GetCacheFolderPath`, `GetEvaluatedMapScriptPath`, `EnumerateFiles`, `AutoSave`/`SaveGame` (no-op, or M7), locks (single thread: never held, so the tactical search skips its UI yields), `Gameplay*` visuals (no-op, optional counters). |
| H4 | UserInterface | Answers the recorded way: no diplomacy screen, no popups queued, no selection, `isDiploActive` false. `GetScratchDeal`/deal-screen methods return what the reference returned. |
| H5 | NetLoopback | `send…` calls are queued and delivered to the DLL's `ICvNetMessageHandler` `Response…` methods at the point in the frame where the exe delivers them (from the M0 trace). |
| H6 | ScriptSystem | Lua 5.1 via `lua51_Win32.dll`. `CreateLuaThread`, `LoadFile` (through the VFS), args objects, `CallFunction`/`CallCFunction`. `GameEvents` registry with `Add`/`Remove`, and `CallHook`/`CallTestAll`/`CallTestAny`/`CallAccumulator` with the engine's exact semantics (M0 probe). |
| H7 | Lua environment | DLL libraries (`RegisterScriptLibraries`), `GameInfo`/`DB` (`Database::Scripting::Lua::PushDatabase`), `GameDefines`, `include` with engine VFS precedence, `print` to `Lua.log`, `Locale`, the `Modding` subset map scripts use (`GetActivatedMods`, `GetActivatedModEntryPoints`), `MapModData`, and an `Events` table whose members accept any call and do nothing (Communitu's debug code calls `Events.SerialEventHexHighlight`). Standard `os`/`io` libraries as the engine provides them. |
| H8 | Database | Phase A (M1): a per-run copy of the game-built `cache\Civ5DebugDatabase.db`, then the DLL's `PerformDatabasePostProcessing`. Phase B (M4): the database builder in section 4.5. Phase A stays available as a fallback (`--db cache`). |
| H9 | Localization | `Localization::Initialize(Locale\icudt44l.dat, Localization-Merged.db, …, "en_US")`, so city names and other stored strings are identical. |
| H10 | Mods and VFS | Activated mod list and order, VFS file index (base `Assets`, active DLC, mods' `import="1"` files, later wins as in the engine), gameplay `InGameUIAddin` scripts. |
| H11 | Setup | Game spec → pregame setters, map-option defaults from `MapScriptOptions`, premade maps through `ICvWorldBuilderMapLoader` (`Preload`, `SetupPlayers`, `SetupGameOptions`, `SetInitialItems`), seed pinning, spec validation. |
| H12 | Driver and outputs | Start sequence, autoplay arming as `vpbench` does it, update loop, end conditions, per-turn digest and `CHECKPOINT` (same Lua as `vpbench`, run at the end of each turn), replay data, timings, run folder in `vpbench` layout. |
| H13 | Runtime environment | x87 control word and MXCSR set to the game-core thread's values; `timeBeginPeriod(1)` as the DLL expects; per-run cache, logs and user folders so parallel runs never share files (`Civ5SavedGameDatabase.db` lives in the cache folder). |

### 4.2 DLL-side additions

All are result-neutral and off by default; normal builds behave exactly as today.

| # | Addition | Purpose |
|---|---|---|
| D1 | Boundary recorder (trace builds only) | Inbound: an entry hook in every `CvDll*` wrapper method (about 1,300), inserted by the build script into a transformed source copy for `-Trace` builds, so tracked sources stay untouched. Outbound: generated forwarding proxies for `ICvEngineUtility4`, the UI interface and the script system, installed in `SetDLLIFace`. Records sequence, thread, turn, method, simple arguments and return values. High-frequency rendering getters are capped per turn. |
| D2 | State digest | `Game.GetStateDigest()` for Lua and an automatic per-turn log line (`HeadlessDigest` define or environment switch) at a fixed point in `CvGame::doTurn`. Per-section hashes of the serialized state. Optional full dump of one turn's sections for diffing, and the existing `CvSyncArchive` variable names to point at the field that differs. |
| D3 | Seed pinning and logging | Log map and sync seeds at `InitMap`. Accept pinned seeds from the spec for reference runs (config `MapRandSeed`/`SyncRandSeed` if the engine honours them for menu-started games, otherwise a small pregame hook). |
| D4 | Runtime facts | Log the x87 control word, MXCSR and thread id at the first `CvGame::update`. |
| D5 | Hook probe mod (test only) | A tiny mod registering listeners with known return patterns, to pin down the engine's `GameEvents` semantics. |

### 4.3 Tooling (Python, `work/headless/` and `vpbench`)

- `gen_interfaces.py`: stubs and proxies from the interface headers (H2, D1).
- `trace_diff.py`: aligns two boundary traces, ignoring visual-only calls; reports the first mismatch.
- `parity.py SPEC`: runs the reference (real game) and the host, compares per-turn digests, then traces.
- `dbdiff.py`: compares two game databases (schema, indexes, triggers, rows); the M4 oracle.
- `vpbench` extensions: `newgame --spec FILE` sets every option from the spec and pins the seeds; a
  `--backend headless` path writes the same run folder (`setup.json`, `checkpoints/`, `turn-times.jsonl`,
  `status.json`, `replay-data.json`, `events.jsonl`).
- Parallel runner: an `abqueue`-compatible queue with N workers, CPU affinity, per-run folders, crash and
  minidump capture. (`abqueue.py`, `abcompare.py` and `samerun.py` are on `ai-improvements`; they come over
  when that branch merges, or are cherry-picked.)

### 4.4 Game spec

One JSON format drives both the host and the reference run:

```json
{
  "map": {"script": "Assets\\Maps\\Continents.lua", "size": "WORLDSIZE_STANDARD",
          "options": {"TXT_KEY_MAP_OPTION_SEA_LEVEL": 2}},
  "speed": "GAMESPEED_STANDARD", "era": "ERA_ANCIENT", "difficulty": "HANDICAP_EMPEROR",
  "majors": 8,
  "slots": [{"slot": 0, "civ": "random", "team": 0}],
  "cityStates": 16,
  "gameOptions": {"GAMEOPTION_RAGING_BARBARIANS": true},
  "victories": ["VICTORY_DOMINATION", "VICTORY_SPACE_RACE", "VICTORY_CULTURAL", "VICTORY_DIPLOMATIC", "VICTORY_TIME"],
  "maxTurns": 0,
  "seeds": {"map": 123456, "sync": 654321},
  "autoplay": {"untilTurn": null, "stopAtVictory": true},
  "outputs": {"checkpointEvery": 1, "digest": true, "logs": "default"}
}
```

- A premade map uses `"map": {"civ5map": "Assets\\Maps\\Earth_Standard.Civ5Map"}`.
- Omitted fields behave like a setup screen the player didn't touch. The screen only calls
  `PreGame.SetMapOption`/`SetGameOption` when a value changes, so an untouched option stays unset (-1 or
  nil), and the map script, not the database `DefaultValue`, decides what unset means. The tool leaves
  them unset too. The DLL's pregame snapshot at game start (D3) checks that both sides agree.
- `"random"` is allowed wherever the setup screen allows it. `--resolve` writes the resolved spec.
- Validation follows the DLL's rules. Autoplay needs a free major slot for the observer
  (`CvGame::setAIAutoPlay`), and the human slot's handicap is the game difficulty. Slot 0's civ plays as
  an AI during autoplay, so `majors` counts it.

### 4.5 Database builder

The game builds its database in three layers. The tool rebuilds only the layer that changes during
development, the mods, and reuses the game's own loader code for it.

| Layer | Contents | Source in the tool |
|---|---|---|
| Base game | vanilla tables (`Civ5CoreDatabase.db`: 365 tables, 20 civilizations) | Not used directly. |
| Expansions and DLC | G&K, BNW, DLC civs and map packs, EUI (`Assets\DLC\*`) | **DLC snapshot:** `Civ5DebugDatabase.db` saved once from a game launch with no mods enabled. This changes only after a game patch, a DLC change or a VP installer update. The tool hashes the DLC folders and warns when the snapshot is stale. |
| Mods | 423 update files today: CP 100 SQL + 75 XML, VP 174 SQL + 69 XML, EUI compatibility 3 XML, Squads 1 + 1 | **Built by the tool** from the staged package (`work/staging/...`) or the MODS folder. |

Build steps:

1. Copy the DLC snapshot.
2. Determine the active mods and their order: dependencies first (VP depends on CP), then the engine's
   tie-break, confirmed against the oracle below.
3. Apply each mod's `OnModActivated` `UpdateDatabase` files in their listed order:
   - XML through `Database::XMLSerializer::Load`, the loader the game itself uses, exported by
     `CvGameDatabaseWin32Final Release.dll` (it handles `<Table>`, `<Row>`, `<Update>`, `<Delete>`,
     `<Replace>`).
   - SQL through `Connection::ExecuteMultiple`.
   - Transaction use and error handling match the engine: errors are logged and loading continues. The
     game's own `Database.log` shows errors it tolerates today.
4. Register map scripts: evaluate `GetMapScriptInfo` of every base, DLC and mod map script into
   `MapScripts`, `MapScriptOptions` and `MapScriptOptionPossibleValues`. The spec's map-option defaults
   need this anyway.
5. Text: keep using the game's `Localization-Merged.db`. Mod text affects only display strings such as
   city names, never rules. After a text-only edit, a parity run needs one game launch to refresh it.
   Routing `Language_*` rows into a copy is a possible later addition.
6. Run the DLL's `PerformDatabasePostProcessing` as in phase A.

**Oracle:** `work/headless/dbdiff.py` compares a tool-built database with the game's `Civ5DebugDatabase.db`
for the same mods: schema, indexes, triggers and every row. It runs in M4's acceptance, and again any time
the game has been launched, so a silent builder error can't last.

**Estimate:** 3–5 days. The risk is low because the XML dialect and SQL engine are Firaxis's own code. The
unknowns are the mod order tie-break, the transaction and error semantics, and any engine-only step; the
oracle exposes all three. Rebuilding the expansion and DLC layer too was considered and rejected: about one
more week, more unknowns (package descriptors, directory-wide load order), and that layer doesn't change
during development.

**Status (2026-10-25):** built. `work/headless/build_db.py` with `civ5headless.exe builddb` gives databases identical
to both game oracles in about 3 s. Usage, the mod-order rule, the error semantics and the engine-only steps are in
`docs/headless-dbbuild.md`. The engine-only steps are DLC blocking (VP blocks DLC_SP_Maps), the map script defaults
and the DLL post-processing. Still open is the check of the test edits against game launches, run by
`work/headless/dbbuild_test_edits.py`.

## 5. Milestones

Each milestone ends with a ledger update and a commit. Estimates assume roughly daily sessions and are
rough. M0 and M1 are the de-risking stage (about two weeks); go or no-go after M1. M0–M6 total roughly
7–10 weeks; M4 can run alongside M3 because it needs only M1.

### M0: Record the engine contract (about 1 week, a few short real-game sessions)

1. Build D1–D4 and the `-Trace` build variant in `work/build-vp-msvc.py`.
2. Record in the real game, with a trace build deployed during an agreed window (never while an A/B
   queue runs):
   - S1: `vpbench newgame` (Continents, Standard) + arm autoplay + 5 turns.
   - S2 (optional, only useful for M7): save, quit to menu, load, 3 turns.
   - S3: new game on `Earth_Standard.Civ5Map` + 2 turns.
   - S4: the hook probe mod (D5) + 2 turns.
3. Write `docs/headless-engine-contract.md` from the traces:
   - **Bootstrap:** database load, context `Init`, `CacheGameDatabaseData`.
   - **New-game start:** pregame finalisation, `Init`, `Init2`, `InitTacticalAnalysisMap`,
     `DoGameStarted`, `SetFinalInitialized`, …
   - **Per-frame order:** `Update`, `UpdateTestEndTurn`, net delivery.
   - **Constant answers:** every outbound query answered the same way throughout, for H2–H4.
   - **State-dependent answers:** which ones change, and on what.
   - **Event semantics:** `GameEvents` behaviour (no listeners, several listeners, `nil`/`false`/`true`
     returns, errors).
   - **Runtime facts:** threads used, x87/MXCSR values, the `include` precedence observed.
4. Run reference A/A: two runs from the same pinned seeds for 100 turns, with digests identical on every
   turn. Document the excluded fields.
5. Database: dump a table-by-table hash of the in-game database via Lua and compare with
   `Civ5DebugDatabase.db` after post-processing.
6. DLC snapshot for M4: launch once with no mods enabled. Confirm the game writes `Civ5DebugDatabase.db` in
   that state, keep the copy, then restore the benchmark mods (`ensure-benchmark-mods.py`).

Done when: the traces are committed (compressed), the contract document is written, the reference A/A
passes and the database comparison passes or its differences are explained.

### M1: Host boots the DLL (about 1 week)

1. Project `Civ5Headless/` and `work/build-headless.ps1`, using the same VC9 toolchain and flags as the DLL
   (`/MD /fp:precise /EHsc`, x86), plus `/LARGEADDRESSAWARE` and a `.def` file with the 22 exports.
2. H1 as logging stubs, then real implementations for what the DLL touches during boot.
3. H2 generated. Unexpected calls abort with the method name in debug runs.
4. H8 phase 1, H9, H13, and a minimal H6/H7: one Lua state, DLL libraries, `GameInfo`.
5. Boot sequence from the contract: `DllGetGameContext` → `SetDLLIFace` → `SetGameDatabase` → `Init` →
   `CacheGameDatabaseData` → `PerformDatabasePostProcessing`.

Done when: data caching succeeds with no asserts, the info counts (units, buildings, techs, policies, …)
match the real game, and `GameInfo` and `DB.Query` work from host Lua.

**Go/no-go:** stop or rescope if the contract shows gameplay computation inside the exe that the host
cannot reproduce. Nothing seen so far suggests this.

### M2: New-game generation (1.5–2 weeks)

1. H10: mod list and order, VFS index, `include` precedence. CP and VP both ship
   `AssignStartingPlots.lua`; the host must pick the same file the engine picks.
2. H7 complete: `Modding`, `MapModData`, `Locale`, `GameDefines`, `print` → `Lua.log`.
3. H11: spec → pregame setters, mirroring what the setup screen leaves in pregame (from the trace).
   Map-option defaults, seeds, spec validation.
4. Lua map scripts through the DLL's `CvMapGenerator`. Premade maps through the loader interface,
   including the loader's Lua post-processing (`AddRandomItems`, mod data, post-process script).
5. Start sequence from the contract. Write the T000 digest and checkpoint.

Done when: host T000 digests equal the reference T000 digests for about 20 seeds covering at least 8 map
scripts (base, BNW, VP, including `Communitu_79a` and `Continental_Drift`), all 6 sizes, 2 premade maps, random map options, and
both the default and maximum city-state counts.

### M3: Turn loop and autoplay (1.5–2 weeks)

1. Update loop in the recorded per-frame order. H5 net loopback. H3 turn gates.
2. Gameplay Lua add-ins: load every active `InGameUIAddin` that registers `GameEvents` listeners and has
   no UI dependence, in engine order. Today that is `GlobalCityBombardRange.lua` (bombard range,
   `TeamTechResearched`) and `CBP_IncaFunctions.lua` (`PlayerCityFounded`). UI-only add-ins are skipped,
   with the rule documented and a checker that flags new gameplay listeners in mod updates.
3. Autoplay arming at the same point as `vpbench`: quick combat and quick movement on,
   `SetAIAutoPlay(turns, 0)` while the T0 human turn is active.
4. End conditions: victory (game state over), max turns, target turn, a stall watchdog (no progress for N
   seconds), DLL assert or crash (minidump).
5. Per-turn digest, `CHECKPOINT` at the end of each turn (exact, unlike the mid-turn polling in the real
   game), replay data and turn timings.

Done when: per-turn digests equal the reference for the M0 spec over 10, 50, 100 and 250 turns, and one
full game to victory matches on every turn.

### M4: Database builder (3–5 days)

1. DLC snapshot handling: load, hash check, stale warning.
2. Mod discovery from the staged package or the MODS folder, and ordering.
3. XML and SQL application with engine-equivalent transactions and errors (section 4.5).
4. Map script registry via `GetMapScriptInfo`.
5. `dbdiff.py` oracle.

Done when: the tool-built database is identical to the game's `Civ5DebugDatabase.db` for the current mod set
and after three test edits made in a scratch copy of the mods (a changed XML row, an SQL update, a new
table), each checked against a game launch. M3's reference spec, rerun on the built database, still
matches the reference digests.

### M5: Breadth parity (1–2 weeks, mostly debugging)

1. Run the parity matrix (section 6) on the tool-built database. Fix each divergence at its source:
   - A host or contract mistake is fixed in the host.
   - A DLL dependence on something the host can't reproduce is made result-neutral in the DLL, which
     helps the real game too. Examples: address-ordered iteration, side effects in getters the UI calls.
2. Address-perturbation self-test: two host runs with different allocator padding must give identical
   digests. This proves results don't depend on heap addresses. Audit the 45 containers ordered by object
   pointer; `CvPlot*` keys are safe because plots are one array.
3. Full games to victory for at least 3 seeds and 2 map types, identical end to end.

Done when: the whole matrix is digest-identical over its compared ranges.

### M6: Tooling and throughput (about 1 week)

1. `vpbench --backend headless`, compatible run folders, and `abcompare`/`samerun` working unchanged on
   headless runs.
2. Parallel runner: N workers (default 8, P-cores first), per-run folders, memory and time limits,
   resumable queue state.
3. Measure single-game speed against the real game across the game phases, and parallel scaling, then
   record both.
4. User guide: `docs/headless-host.md`.

Done when: an A/B batch runs headless end to end and the measurements are documented.

### M7: Saves (optional follow-up, 1–2 weeks)

Not part of the goal. Do it only if viewing headless games in the real game, or resuming A/B runs from
existing saves, becomes worth the time.

1. Reverse the `.Civ5Save` container from S2 (trace offsets of every `Read`/`Write` call against the
   file; zlib sections; the embedded `Civ5SavedGameDatabase.db`).
2. Host writes saves the real game opens, so any headless game can be inspected visually.
3. Host loads real saves, so A/B can resume from existing saves such as the T260 replay.

Done when: a host-written save loads in the real game, and continuing it in both gives identical digests.

## 6. Parity matrix

Each row is a reference-vs-host comparison. "Turns" is the compared range (full = to victory).

| Area | Cases | Turns |
|---|---|---|
| Base and BNW map scripts | Continents, Pangaea, Archipelago, Fractal, Terra, Small Continents, Tilted Axis, Inland Sea | 0–50 |
| VP map scripts | all 24 VP entries at T000; Communitu_79a and Continental_Drift with default and random options | 0, and 0–100 for those two |
| VP map scripts, full game | Communitu_79a Standard, Continental_Drift Standard | full |
| Premade maps | Earth Standard, one DLC map | 0–50 |
| Map sizes | Duel … Huge (Huge also tests memory) | 0–100 |
| Map options | every option of 3 scripts at min/max/random | 0 |
| Speeds | Quick, Standard, Epic, Marathon | 0–100 |
| Eras | Ancient, Medieval, Industrial, Future | 0–50 |
| Difficulty | Settler, Prince, Emperor, Deity | 0–100 |
| Players | 2, 8, 12 majors; 0, default and max city-states; teams of 2 | 0–100 |
| Game options | each visible SP option on at least once (31; Appendix B), grouped 4–6 per run | 0–100 |
| Victories | each victory type disabled once; max turns 150 (time victory) | full |
| Full games | 3 seeds Continents Standard Emperor, 1 seed Pangaea Small | full |

Re-run a small smoke subset (Continents, 50 turns, 2 seeds) after every VP merge or engine-relevant DLL
change.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hidden engine behaviour (call order, answers, timing of net delivery) | D1 recorder and `trace_diff.py` make the exe's behaviour observable; host answers come from recordings. |
| `GameEvents` semantics differ (no listeners, mixed returns, errors) | D5 probe mod in M0; the host is tested against the same probe. |
| UI scripts call DLL getters that have side effects | Shows up as a digest divergence; the outbound trace shows which UI-context calls happen; fix the getter in the DLL. |
| x87 precision differs (DLL uses x87 with `/fp:precise`) | D4 records the game-core thread's control word; H13 sets it. |
| Results depend on heap addresses | M5 perturbation test plus the container audit. |
| CRT/STL ABI mismatch across the interface (`std::string`, `std::vector` cross it) | Host built with the same VC9 toolchain and `/MD`. |
| FireWorks export semantics (allocator, temp heap, string data) | Log first, implement from the FireWorks headers; the dedicated server exports the same set. |
| The cached debug database differs from the in-memory one | M0 database comparison. |
| The database builder diverges from the game's build (order, transactions, an engine-only step) | `dbdiff.py` against the game's own database in M4, and again after any game launch; `--db cache` fallback. |
| The DLC snapshot goes stale after a patch or VP installer update | Hash check on the DLC folders; refresh by one mod-free launch. |
| Mod or VFS precedence wrong | Trace of `LoadFile`/`include`; T000 parity across many scripts. |
| Reference runs can't pin seeds | D3 fallback hook in the DLL. |
| 32-bit memory on Huge maps | `/LARGEADDRESSAWARE`; host overhead is far below the real game's 1.9 GB peak. |
| VP merges change the interface | The interfaces are Firaxis-frozen. Re-run the smoke parity after merges. |

## 8. Working rules

- Develop in `work/wt/headless` on `headless-host`. The main checkout stays on `ai-improvements`, which
  is paused while this work runs.
- The real game is free for recordings and reference runs. Deploying replaces the DLL and mods the game
  loads, so every deployment for this work is followed, before the work is reported done, by restoring the
  AI program's deployed build (DLL SHA in the AI ledger) and its benchmark mods. Record both in the ledger.
- Builds use `work/toolchain` (VC9), and not during timing runs.
- The host loads Firaxis DLLs from the local install only; nothing from the game is redistributed or
  committed.
- Commit at every milestone and keep the ledger's "Resume here" current. Subagent briefs carry the pause
  protocol from the global instructions.

## 9. Decisions (2026-10-24)

1. **Saves:** not needed; optional follow-up only (M7).
2. **Database:** the tool builds the mod layer itself (M4, about 3–5 days, low risk). The game's cache
   stays as fallback and oracle.
3. **Real-game time:** the AI program is paused during this work, so recordings and reference runs can
   use the game whenever needed (restoring its build afterwards, section 8).
4. **Maps:** no scenario maps with fixed players. VP's map scripts, Continental Drift and Communitu among
   them, are in scope and in the parity matrix. Premade maps without fixed players stay in scope.
5. **Multiplayer-only options** (simultaneous turns, turn timer, pitboss) are out of scope.

## Appendix A: engine contract inventory (2026-10-24)

- Interfaces the host implements: `ICvEngineUtility1–4` 258 methods; `ICvUserInterface1–2` 150;
  `ICvEngineScriptSystem1` 13 plus its args object 12.
- DLL usage: about 160 distinct `gDLL->` methods and 83 distinct UI methods (`setDirty` 191 call sites,
  `AddPopup` 61, `AddMessage` 28, …).
- DLL entry points the engine can call: about 1,300 wrapper methods in `CvDll*.cpp` (pregame 216, context
  149, game 92, player 72, net messages 66, …).
- Exe exports used by FireWorks: `FJobSetAddJobImpl`, `FJobSetInitImpl`, `FJobSetUninitImpl`,
  `FJobSetWaitImpl`, `FSBAAllocate`, `FSBADeallocate`, `FSBADisable`, `FSBAGetMaxAllocatorSize`,
  `FSBAHasAllocatorForSize`, `FSBAIsDisabled`, `FSBAIsSmallBlock`, `FSBAPreventCreation`,
  `FStringA_GetStringInitData`, `FStringW_GetStringInitData`, `GetFileSystemMgr`, `GetLogFileMgr`,
  `GetMemTrackerForDLL`, `GetSmallObjectAllocator`, `GetSmallObjectAllocatorInitParams`, `GetTempHeap`,
  `PeekLogFileMgr`, `std::_Init_locks::operator=`.
- Firaxis DLLs loaded from the game folder: `CvGameDatabaseWin32Final Release.dll` (46 imports used),
  `CvLocalizationWin32Final Release.dll` (16), `lua51_Win32.dll` (45). ICU data: `Locale\icudt44l.dat`.
- Files the DLL touches outside logs: `<cache>\Civ5SavedGameDatabase.db` (mod save data, embedded in
  saves), the MODS folder (found through the registry "Personal" folder), `SqliteLogger` databases in the
  cache folder.

## Appendix B: setup option inventory (from `Civ5DebugDatabase.db`, 841 tables)

- **Map sizes:** Duel, Tiny, Small, Standard, Large, Huge.
- **Speeds:** Quick, Standard, Epic, Marathon.
- **Eras:** Ancient through Future (8).
- **Difficulties:** Settler through Deity (8; `HANDICAP_AI_DEFAULT` is the AI's own).
- **Victories:** Domination, Science, Cultural, Diplomatic, Time.
- **Civilizations:** 43 playable. City-state types: 120.
- **Map scripts:** 54, with 233 map options and 1,019 option values (`MapScripts`, `MapScriptOptions`,
  `MapScriptOptionPossibleValues`).
- **Premade maps:** 6 map types with per-size files (`Maps`, `Map_Sizes`), plus user `.Civ5Map` files.
- **Visible single-player game options (31):** `NO_CITY_RAZING`, `NO_BARBARIANS`, `RAGING_BARBARIANS`,
  `ONE_CITY_CHALLENGE`, `COMPLETE_KILLS`, `NO_GOODY_HUTS`, `RANDOM_PERSONALITIES`, `POLICY_SAVING`,
  `PROMOTION_SAVING`, `QUICK_COMBAT`, `DISABLE_START_BIAS`, `QUICK_MOVEMENT`, `NO_ESPIONAGE`,
  `BARB_GG_GA_POINTS`, `CHILL_BARBARIANS`, `DISABLE_AI_VICTORY_COMPETITION`,
  `DISABLE_AI_ENDGAME_AGGRESSION`, `RANDOMIZED_VICTORIES`, `TRANSPARENT_DIPLOMACY`,
  `RANDOMIZE_CITY_NAMES`, `DISABLE_RESEARCH_AGREEMENTS`, `ENABLE_TECH_TRADING`, `NO_TECH_BROKERING`,
  `BAD_EVENTS`, `CIV_SPECIFIC_EVENTS`, `GOOD_EVENTS`, `NEUTRAL_EVENTS`, `TRADE_EVENTS`, `ENABLE_VASSALAGE`,
  `NO_VOLUNTARY_VASSALAGE`, `PASSIVE_ESPIONAGE`.
- **Hidden options** (accepted in the spec, not in the matrix): `ALWAYS_WAR`, `ALWAYS_PEACE`,
  `NO_CHANGING_WAR_PEACE`, `NO_SCIENCE`, `NO_POLICIES`, `NO_HAPPINESS`, `NO_RELIGION`, `NO_LEAGUES`, ….
  Multiplayer-only options are rejected.

## Appendix C: Lua that affects gameplay in the enabled mod set

| Script | Listener | Effect |
|---|---|---|
| CP `Core Files/New Lua/GlobalCityBombardRange.lua` | `GetBombardRange` (value), `TeamTechResearched` | City bombard range per team's techs |
| VP `Core Files/New Lua/CBP_IncaFunctions.lua` | `PlayerCityFounded` | Places an improvement for the Inca |
| Map generation chain | map script + `MapGenerator`, `AssignStartingPlots`, `FeatureGenerator`, `NaturalWondersCustomMethods`, `MapmakerUtilities` (CP/VP overrides) | Map, start positions |

UI-only listeners (`DiploCorner`, `NotificationPanel`, `UnitFlagManager`, `TechTree`) are not loaded. The
`Stacking*Tests.lua` helpers are not add-ins.

**VP map scripts** (24 `MapScript` entry points in the VP modinfo, under `Mapscripts/` and `Mapscripts/EMP/`):

- **Randomness:** all of it comes from the DLL's map RNG, so a map is fully determined by the map seed.
  - Communitu draws through `PWRand()` → `Map.Rand`, and seeds Lua's `math.random` from two `Map.Rand`
    calls.
  - Continental Drift uses `Map.Rand`; its `math.random` calls are inside a commented-out block.
- **Extra includes:** `IslandMaker`, `FLuaVector`, `MultilayeredFractal` (base-game files found through
  the VFS).
- **Engine-only calls:**
  - Communitu calls `os.clock` only when its `debugTime` flag is set (off).
  - Communitu's `io.open` sits in a debug dump function.
  - Communitu calls `Events.SerialEventHexHighlight` in debug paths. The H7 `Events` stub absorbs it.

## Appendix D: planned file layout

```
Civ5Headless/                 host sources (C++), .def exports, project
  engine/                     H1–H5, H13
  lua/                        H6, H7
  setup/                      H8–H11
  driver/                     H12
tools/headless/               gen_interfaces.py, trace_diff.py, probe mod
work/headless/                parity.py, dbdiff.py, runner, specs/ (tracked examples),
                              local outputs and the DLC snapshot (ignored)
docs/headless-host-plan.md    this plan
docs/headless-host-ledger.md  status and resume point
docs/headless-engine-contract.md   written in M0
docs/headless-host.md         user guide (M6)
```
