# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M0–M6 done; **M5 closed 2026-10-25** by the final Standard game (plan section 9.6). M7 (saves) optional.
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
  Staging packs the mod files of the checkout it runs in, so restore from an `ai-improvements` checkout
  (a temporary worktree with the toolchain junction), not from this branch.
- **Batch-1 references** were recorded with the pre-fix field-map DLL `work/msvc-output/Release-fieldmap/20261025-015157`
  (`39F621D3…`, headless-host 98d7661bf; dumps also write `<section>.fields.txt`).
- **Agents in flight** (Opus, high effort; own worktree and branch; `RESUME.md` in the worktree on pause):
  - host: M5, worktree `work/wt/hh-host`, branch `hh-host`. Work order: Continental Drift (first divergent map
    RNG call 189922 from `work/test-runs/hh-m3-cdrift-randlog/RandCalls.csv`: the real game makes one more
    `Random float` draw; suspected iteration order in the script); address-perturbation self-test; find why the
    game's logging profile changes AI results and make it result-neutral; matrix comparisons against the
    `hh-m5-*` references (`work/headless/parity_run.py`).
  On resume after a pause: read each worktree's `RESUME.md` and relaunch the agent with its work order (above)
  plus the checkpoint.
- **Merged into headless-host:**
  - D1 recorder (021ba53f4), D2–D5 digest (92caccb78), M4 database builder (0c240f6bb).
  - M2 first part (hh-host 67b9a9887, merge 7f4e2a49c): `civ5headless.exe newgame --spec`,
    pregame from a resolved spec, VFS and include, map-script Lua, start sequence. All test maps generate
    under `--strict`; the Earth T000 map section is byte-identical to the real game's; HHSEEDS and the
    whole HHPREGAME snapshot match S1 and S3 line for line.
  - Engine contract (`docs/headless-engine-contract.md`, merge "Merge hh-contract"): phases, threads and
    locks, net loopback, state-changing UI calls, gaps G1–G16, open questions.
  - M2 parity (b687e42bf): load-screen state byte-identical to the real game for continents, earth and communitu;
    host runs deterministic; digest normalisation of the uninitialised bytes the save writes;
    `tools/headless/parity_t000.py`, `tools/headless/fieldmap_transform.py`.
  - M3 (73d4f1932): `civ5headless.exe newgame --turns N` (autoplay in game_probe order, net loopback, UI frame emulation:
    EUI civ ribbon gold rate, VP observer notification aging, human-turn engine frame, WhosWinning popup RNG;
    autosaves shown not to matter). Independently reproduced end to end with a `build_db.py` database. The host
    copies the reference profile's DLL logging, because logging changes AI results (under investigation).
  - M6 (d0711220f): `work/headless/hhbench.py` (also `vpbench newgame --backend headless`), run folders read unchanged by
    compare.py, abcompare.py, samerun.py and summarize-ai-features.py; `work/headless/runner.py run|status|compare
    QUEUE.json` (workers pinned P-cores first, job-object limits, resumable, database cache `dbcache.py`); guide
    `docs/headless-host.md`. Host fix: each database connection owns its own logger (a shared static one was
    freed at close: shutdown crash or hang in some builds).
  - Measured (M6, with the real game recording in the background): 250 turns in 490 s against 1,600–1,900 s real
    (3.5x; 6.5x early, about 3x after T150); 100 turns of the reference game 82–87 s against 443 s; about 280–330 MB
    per game against 1.8 GB; 8 workers about 29,000 game turns per hour, 24 workers about 55,000 (steady queue).
    Headless A/A between two builds that differ only in digest code: identical final states on 4 seeds x 150
    turns. The ai-improvements DLL also runs headless (no digests: it lacks the additions).
- **Fixes on headless-host:**
  - 393b7ceb7: DLL crash at unload (static destruction order); trace end line from `DllMain`; host log
    paths.
  - 255e26ba2: the seeds file is applied at `setGameStarted(true)` too, so the random civs and city-states
    follow the spec seed (before, the engine's clock seed chose them: S1, S3 and the first AA100 pair
    are not reproducible for civs).
  - M5 part 1 (f551e3815), gameplay, AI logging no longer changes results: ff259285d (`GetBestSettlePlot` decided
    with fresh found values and changed the shared flavor multipliers when AI logging was on; now always the
    cached values) and eecc6ddc7 (`PlotPillageMoves` set the citadel/improved-resource threshold only inside the
    logging block; now always, as its comment intends). Logging on/off give identical 100-turn digests on two
    maps. The address-perturbation self-test (`--heap-perturb SEED`: random heap spacers, rebased DLL) passes:
    no pointer-ordered container affects results. References recorded before these fixes need the pre-fix DLL.
  - M5 matrix (bc8b57f5a): `work/headless/parity_run.py REF_RUN` (or `--matrix --workers N`) replays a reference
    and compares every digest point and both dumps. 49 of the matrix cases are identical (8 base scripts,
    all VP scripts but Continental Drift, premade maps, all sizes, quick and epic speeds, difficulties, player
    counts and teams); speed-marathon is identical with `--pregame-turn-timer 1` (the real exe kept the previous
    launch's timer; the spec will pin it); era starts differ only in one UI field (initial unit selection).
    Fixes: VFS-first map script paths, slot claims, closed slots of city-states dropped at map generation, and
    567a18084 `CvPlot::m_iFreeMoveAcross` initialised (upstream field left as heap garbage).
  - 3fbccb312 (gameplay, uninitialised reads): public opinion fields, pantheon holy-city coordinates and the
    trade difference tables are initialised. Gameplay could read heap garbage there; references recorded
    before it have different values in those fields.
- **M0 data** (`work/test-runs/`):
  - First recordings (trace DLL 660FFF0C, civs from the clock seed): S1 `hh-m0-s1-continents`, S3
    `hh-m0-s3s4-earth`, S4 `hh-m0-s4-hooks`, `hh-m0-aa100-{a,b,c}` (invalid as A/A: different civs).
  - Facts: x87 0x027F, MXCSR 0x1F80, `timeBeginPeriod(1)` = 0; autosave = OUT `AutoSave` then synchronous IN
    `Write` calls on turn 0 and every 10th turn, no `WriteReplay`; `Game`, `Map`, `Players` nil in the front
    end; GameEvents: every listener runs in order, a raising listener is skipped (no vote), `CallHook`'s value
    is forced false; one `Update` per alive player per turn.
  - Database: `work/headless/db/` (README there): DLC snapshot; oracle pairs for the AI package
    (`mods-reference-08D19878`) and this branch's package (`mods-headless-host-0ed40de35`).
- **Re-recorded references** (trace DLL 008A4227, early pin; every run logs `HHSEEDS point=gameStarted`):
  `hh-m0-s1b-continents` (vpbench order, to T5), `hh-m0-s3b-earth`, `hh-m0-communitu`, `hh-m0-cdrift`
  (game_probe order: load-screen `dump-t000` and a dump after 2–3 turns); `hh-m0-s1c-continents` (trace DLL
  2CF44F11, game_probe order, 5 turns, dumps at T0 and T5, phase-reset trace: the best M3 reference).
- **Real-game A/A** (`hh-m0-aa100b-a`, `-b` with digest, `-c` without; Continents spec, 100 turns): same civs;
  pregame, map and support digests identical every turn; every T100 dump section has the same size in all
  three runs, and the differences are short byte runs (2 bytes at a 507-byte stride in `game` from T14, 3
  bytes per player, padding-like runs in teams). Conclusion: the real game is deterministic, digest on or
  off; the digest still hashes uninitialised bytes, which the host agent is mapping to fields for
  normalisation.
- **M4 accepted** (`hh-m4-testedits`): the four test edits in a real launch gave the builder's values, the
  engine also stops an SQL file at its first error, and the built database equals the game's (dbdiff).
- **M2 references** (field-map DLL 39F621D3): `hh-m2-cdrift`, `hh-m2-continents`, `hh-m2-earth`,
  `hh-m2-communitu` (load-screen dump and one after 2–5 turns, Lua.log kept), `hh-m2-aa100-a`, `-b` (100 turns).
- **Real-game A/A is exact:** `hh-m2-aa100-a` vs `-b`: per-turn digests identical at all 100 points
  (`hhdigest.py compare`), and all 57 sections of the T100 dumps byte-identical (`parity_t000.py`). With the
  digest normalisation and the three fixes, the real game is a reproducible oracle for M3.
- **Matrix batch 1 recorded:** all 58 cases done (`work/test-runs/hh-m5-matrix.json`).
- **Continental Drift probe** (`work/test-runs/hh-m5-cdrift-probe`, probe script swapped into MODS for one launch and
  restored byte-identical; source and `.orig` in `hh-m5-cdrift-probe-src`): the first differing value is the
  very first height-map sample, tile (0,0), height(2.2,0) real -0.2492 vs host 0.0656, with identical RNG draws.
- **Continental Drift cause found** (probe 2, `work/test-runs/hh-m5-cdrift-probe2`; ipairs probes
  `hh-m5-ipairs-probe`, `-probe2`): the engine's `ipairs(t)` starts at index 0 when `t[0] ~= nil` (initial
  control -1, else 0; stock iterator). The map script keeps its height grids from `maps[0]`, so the real game adds
  grid 0 and the stock-Lua host did not. `debug` is nil in the real front end and unusable in the map-script
  thread. The host agent is matching both.
- **M5 matrix batch 1 complete (1d70b7db0): all 58 cases identical** (pre-fix DLL as recorded; vp-west-vs-east needs
  the `m_iFreeMoveAcross` init, speed-marathon `--pregame-turn-timer 1` as an old reference). Last fixes: engine
  `ipairs` and per-thread `debug` (Continental Drift), era-start unit selection, CP city-event popup notification,
  great-person reward popup, closed slots of dead city-states, turn-timer pin in gamespec and host.
- **Deployed now:** field-map DLL `work/msvc-output/Release-fieldmap/20261025-155805` (`CB6B0BED…DAC424C836`, DLL
  source = headless-host c08b24207: artifact pick, trade stats and unit maintenance fixes, UI-only digest
  normalisation). Earlier references (`hh-m5`, `hh-m5f`, `hh-m5g`: 89F146A7; `hh-m5b-mapopt-*`: 6C73DC9A) compare
  against their own DLLs.
- **Final game, first attempt** (`hh-m5z-continents-s1`, DLL CB6B0BED, host-first): identical to the host T0–T140
  (past the old T125 divergence: the three DLL fixes hold). From T141 only `pregame` differs (game, map, players
  identical through T143); the real game stopped at T144 with dumps T137–143. Cause: one slot's status (two arrays,
  pregame offsets 718 and 11271): real SS_COMPUTER, host SS_CLOSED: the host's "dead city-state slots closed" emulation
  closes a slot the real engine kept open. Cause (hh-host 2cc045925, merged 42871835a): city-state 36 died at T125
  (both closed its slot) and was liberated at T140; the real engine reopened the slot (SS_COMPUTER), the host only
  ever closed dead city-states. The DLL tells the engine itself (`CvPlayer::setAlive` -> `closeSlot`/`openSlot`); the
  host now implements those calls (any player, closed on death, reopened when alive again) instead of polling. Verified:
  attempt 1 identical T0–T143 with the new host, host A/A, and the batch-1/smoke cases that close slots. Attempt 1's
  runs kept as `*-attempt1`. Attempt 2 running (same DLL CB6B0BED, host exe
  `work/wt/hh-host/work/headless-output/Release/20261025-164925`).
- **Final game, attempt 2: pass (M5 closed).** `hh-m5z-continents-s1` (Standard Emperor 1001/2002, DLL CB6B0BED, host
  exe 20261025-164925): same result (game over T302, team 1, victory type 3, state 2); 300 of 302 per-turn digests
  identical; two one-turn transients (T276 p00; T284 p00–p04), both only `tacticalAI.m_tacticalMap` (an AI scratch
  cache rebuilt each turn; its build stamp differs by one), identical again the next turn and to the end. The final dump
  differs (p01) because the real game keeps processing in GAMESTATE_EXTENDED for the seconds before its end probe while
  the host stops at once; the T301 digests match. Timing: real autoplay 2,358 s (5.1 / 7.9 / 10.3 s per turn for
  T1–100 / 100–200 / 200–300), host 692 s (0.72 / 2.11 / 3.95): 3.4x overall (7.0x early, 2.6x late). Memory: real peak
  working set 2,025 MB, peak private 2,423 MB, about 2.7 cores; host 424 MB / 480 MB, one core (681 s CPU).
  Optional follow-up: normalise the tactical map's build stamp in the digest if it never affects decisions.
- **Seeding with a stock DLL works (2026-10-25):** `config.ini` `MapRandSeed`/`SyncRandSeed` (Firaxis
  `CvPreGame::loadFromIni`) pin a menu-started game's seeds before the random civs are drawn. Two real Tiny launches
  without our seeds file (`game_probe --engine-seeds`, runs `hh-seedtest-a/-b`) were identical (civs, all 33 turn-0
  sections, digests T0–T2); clock-seeded controls (`hh-seedtest-clock-a/-b`) differed everywhere; the host with the
  same seeds matched the real game. The future test suite's exact checks therefore work with any SDK-derived DLL.
- **Archaeology was nondeterministic in the real game too:** `CultureHelpers::GetArtifact` chose the dug-up great
  work with SQLite `order by Random()`, which SQLite seeds from the OS, so no run (real or host) reproduced past the
  first dig. Fixed in 6d42ad0c5 (candidates by ID, picked with `urandLimitExclusive` and a plot/class/era seed; a
  candidate for upstream VP).
- **Smoke with the fixed DLL** (`hh-m5f`, 11 cases, references recorded with 89F146A7): all 11 identical in the host,
  victory.json included (host 3–91 s against 67–524 s real).
- **First full game diverges:** `hh-m5g-continents-s1` (Standard, Emperor, 1001/2002) ended at T277 in the real game
  (team 1, victory type 3; 2,228 s) and at T285 in the host (653 s). Digests match to T124; p01 differs T125–127,
  p03 at T131, then the game diverges. continents-s2 was stopped at T163 (partial digests kept in its run folder,
  status "failed"); s3 and Pangaea Small dropped.
- **Real-game time rules (user, 2026-10-25):** keep real-game runs short. Hunt divergences on Tiny maps (default 4
  majors, 8 city-states); one larger-map game only once Tiny is clean (the Standard reference `hh-m5g-continents-s1`
  serves while the DLL stays 89F146A7). Run the host first and let the real game stop just after the first
  difference:
  - `work/headless/host_first.py MATRIX --dll ... --mods-db ... --loc-db ... --exe ...` plays each case in the host
    into `work/headless-runs/first-<prefix>-<name>` (databases: `work/headless/db/game-cache-20261025/`);
  - `record_matrix.py MATRIX --require-host --host-digest "work/headless-runs/first-{run}/Logs/HeadlessDigest.log"
    --rolling-dumps 5`: game_probe compares the live digest log, writes `divergence.json`/`live-compare.json`, quits 2
    turns after the first difference and keeps the per-turn DLL dumps from 5 turns before it (`<run>/HeadlessDumps`);
  - short re-records: game_probe `--stop-turn S` (same `--turns` arm count) and `--dump-from/--dump-to`.
- **Frame-count dependence (T125 cause, 326c159b6, merged 23bb05ebf):** `CvPlayerTrade::UpdateTradeStats` cached the
  per-city trade route counts for one turn slice (one `CvGame::update`, one engine frame); a route cleared in the same
  slice left `UpdateReligion` reading the old count (+production per active trade route: real game 600, host 400 for
  one turn). The real game's value was the stale one; results depended on how many Updates each engine runs. Fixed
  with a trade connections version. Host `--frame-skew K` (8c4406842) adds an Update before every K-th one: a
  host-only detector of frame-dependent caches. Rule: no more real-game recording until skew vs no-skew is identical
  across the Tiny long games, the 100-turn Tiny cases and continents-s1/-s2 Standard (K=2 and K=7).
- **Second frame-count dependence (3241633ea, in hh-host):** `CvTreasury::GetExpensePerTurnUnitMaintenance` returned the
  value the last `CalculateTotalCosts` stored, which the UI's gold refresh also calls; AI unit production, vassal costs,
  CvEconomicAI and replay data read it (host skew 7 on s1: T85 p06, 17 vs 18). Now computed on each call. AI logging
  on/off is identical over a 295-turn game since 6d42ad0c5 (the T264 difference was the artifact Random()).
  The agent's `work/headless/skew_sweep.py` runs each case at K=0, 2, 7.
- **Map options identical** (`hh-m5b-mapopt-*`, DLL 6C73DC9A, Tiny): Continents, Communitu_79a and Continental_Drift
  with every option at min, max and random: 9/9 identical (digests T0–T2 and both dumps; `parity_run.py --matrix
  work/test-runs/hh-m5b-matrix.json --tag b`). About 75 s of real time per case.
- **Frame-skew sweep complete (host only, K=2 and K=7, 18 cases: 7 Tiny 100-turn, 9 Tiny games to victory, Standard
  continents-s1/-s2): no persistent frame-count dependence.** Three one-turn transients (observer notification
  `m_bDismissed`, UI timing), gone after the UI-only normalisation (hh-host 75397ee04, merged c08b24207: observer
  notifications' dismissed flag, `CvUnit::m_iEverSelectedCount`, tutorial/right-click/advisor flags; documented in
  `docs/headless-dll-additions.md`; host A/A and end dumps confirm unchanged results). References recorded with older
  DLLs differ from it in those fields: new references need the new DLL.
- **Closing M5 (user, 2026-10-25; plan section 9.6):** after the frame-skew sweep (K=7) and the UI-only
  normalisation (hh-host 75397ee04, being verified) are done: merge hh-host, build the field-map DLL from the merge
  (`tools/headless/fieldmap_transform.py apply`, `work/build-vp-msvc.py --no-ltcg --pch-memory 400`,
  `git checkout -- CvGameCoreDLL_Expansion2`), deploy (`work/stage_vp.py --dll/--pdb`, `--verify`, `work/deploy-vp.ps1`),
  then one Standard game to victory, host-first:
  `python work/headless/host_first.py work/headless/matrix/m5-final.json --dll <field-map DLL> --mods-db
  work/headless/db/game-cache-20261025/mods.db --loc-db work/headless/db/game-cache-20261025/Localization-Merged.db
  --exe <host exe>`, then `python work/headless/record_matrix.py work/headless/matrix/m5-final.json --require-host
  --host-digest "work/headless-runs/first-{run}/Logs/HeadlessDigest.log" --rolling-dumps 5`, then
  `parity_run.py hh-m5z-continents-s1 --turns 400`. Identical means M5 is done. The 16 Tiny cases are not re-recorded.
- **Not scheduled:** moving the host to its own repository, for sharing with other mod developers: notes in
  [headless-repo-migration.md](headless-repo-migration.md). The user will decide later; not a plan step.
- **Later, once the host is finished (user request 2026-10-25): benchmark Vox Deorum's no-render approach against
  ours.** Vox Deorum (John Chen, github.com/vox-deorum, github.com/civitas-john) runs the real
  `CivilizationV_DX11.exe` with a proxy `d3d9.dll` from `civitas-john/d3d9-blank-proxy`. The proxy hooks D3D11
  `Present` (kiero + MinHook), skips drawing and sleeps 33 ms per frame; a watchdog exits after 300 s without a frame.
  They also ship a rebuilt `lua51_Win32.dll` with a global lock (`vox-deorum/vox-deorum-lua51`), needed only for
  their IPC thread. Download and build the proxy (VS project, x86), drop it next to the DX11 exe with our DLL and
  mods, and run the same specs/seeds three ways: the plain real game, the real game with the proxy, and
  `civ5headless.exe`. Compare time per turn, memory, how many run side by side, and that the digests still match
  (the proxy should not change results). Not a plan step until the host work is done.
- **User rule (2026-10-25): UI-only state is not a difference.** Anything that cannot affect the game (notification
  `m_bDismissed`, the era-start initial unit selection, and any other purely UI field) is normalised out of the digest
  (`HH_DIGEST_NORM`, digest-only, result-neutral). On resume, before the next DLL build: the host agent audits the
  serialised state for UI-only fields (selection, camera, popup queues, notification display state), normalises those
  with no gameplay reader (keep anything gameplay reads, e.g. end-turn blocking notifications), and lists them in
  `docs/headless-dll-additions.md`. The real game and the host use the same DLL, so new references and the host agree;
  references recorded with older DLLs keep comparing against their own DLL.
- **Host agent** (`a4cb41447b56da966`, `work/wt/hh-host`, branch `hh-host`, all merged through 2cc045925): idle.
- **Next steps (none scheduled):**
  1. Restore the AI program's DLL and mods before handing the real game back (see "AI program" above).
  2. Optional: re-measure parallel scaling on an idle machine (`work/headless/m6/queues/scale-w<W>.json`).
  3. Optional: normalise the tactical map build stamp in the digest; M7 saves.
  4. Later, user's call: the test suite design (config.ini seeding works with stock DLLs), the repository migration
     ([headless-repo-migration.md](headless-repo-migration.md)), upstream VP PRs for the determinism fixes.
- **Uncommitted files:** none besides this ledger.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | done | f96b1be30 | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | done | fc197fd34 | go: boot passes; small-block allocator disabled (all DLL memory from the MSVCR90 heap) |
| M2 | New-game generation | done | 1d70b7db0 | T000 digest parity, incl. Communitu and Continental Drift (engine ipairs) |
| M3 | Turn loop and autoplay | done | 73d4f1932 | per-turn digest parity, 100 turns |
| M4 | Database builder | done | 0c240f6bb | can run alongside M3; `dbdiff.py` oracle |
| M5 | Breadth parity | done (2026-10-25) | 42871835a | batch 1 (58), smoke (11), map options (9), frame-skew sweep (18, host), final Standard game to victory (plan 9.6) |
| M6 | Tooling and throughput | done | d0711220f | vpbench backend, parallel runner |
| M7 | Saves | not planned | | optional follow-up |

## Log

- 2026-10-24: branch and worktree created; plan written; the user's answers recorded as decisions.
  Database builder added (M4), saves made optional (M7), VP map scripts added to the matrix.
- 2026-10-25: M1 done (fc197fd34). Real-game include() probe (run hh-probe-include-20261025a): one file
  per name, later-activated mod wins (VP's AssignStartingPlots over CP's), mods over DLC and base; the
  return value is a table of included paths; a missing name returns an empty table; no `debug` library.
- 2026-10-25: D1 recorder and D2–D5 digest merged. Fixed the unload crash in static destruction. vpbench
  pins spec seeds. M4 agent started. Trace build deployed for the M0 recordings.
- 2026-10-25: M4 merged (0c240f6bb): builder output identical to both game oracles; mod order, error semantics and
  engine-only steps (DLC blocking, map script defaults, DLL post-processing) in `docs/headless-dbbuild.md`.
- 2026-10-25: M2 first part and the engine contract merged. Found that the clock seed chose the random civs;
  fixed with the early seed pin (255e26ba2), redeployed the trace build and started re-recording the
  references and the A/A pair.
- 2026-10-25: references re-recorded with the early pin; real-game A/A over 100 turns shows identical games
  (digest differences are uninitialised bytes only); M4 test edits checked against a game launch: identical.
- 2026-10-25: trace cap periods restart at game init and the first update; x87 at game init is 0x027F on the
  UI thread too; S1c recorded. Contract open questions 1–4 resolved.
- 2026-10-25: M2 parity merged (b687e42bf); three uninitialised reads fixed (3fbccb312); field-map DLL deployed and the
  M2 references re-recorded; host agent moves on to M3.
- 2026-10-25: paused for an app restart (host agent at WIP 6e587ab57, chain stopped after hh-m2-aa100-a);
  resumed: hh-m2-aa100-b started, host agent continues M3 from its RESUME.md.
- 2026-10-25: real-game A/A with the normalisation and fixes is byte-exact over 100 turns (hh-m2-aa100-a/-b).
- 2026-10-25: M3 done and merged (73d4f1932); M5 (host agent) and M6 (tooling agent) started; matrix batch 1 recording.
- 2026-10-25 ~02:40: both agents stopped on the session usage limit (work saved: hh-host with an uncommitted
  experiment in HHScriptSystem.cpp, hh-tooling at b6769a7d2 plus RESUME.md); resumed with SendMessage after the
  reset at 03:30.
- 2026-10-25: M6 merged (d0711220f): headless A/B batches run end to end with the existing comparison tools.
- 2026-10-25: M5 part 1 merged (f551e3815): two logging-dependent AI decisions fixed; heap perturbation changes nothing.
- 2026-10-25: M5 matrix comparisons merged (bc8b57f5a): 49 cases identical; Continental Drift, era selection and
  the options cases open.
- 2026-10-25: M5 matrix batch 1 fully identical (1d70b7db0); fixed DLL deployed; smoke re-record started.
