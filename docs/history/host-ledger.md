# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M3 done; M6 done (d0711220f); M5 (breadth parity) in progress. M0, M1, M4 done; M2 done except
  Continental Drift (an M5 item).
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
  Staging packs the mod files of the checkout it runs in, so restore from an `ai-improvements` checkout
  (a temporary worktree with the toolchain junction), not from this branch.
- **Deployed now:** the field-map DLL `work/msvc-output/Release-fieldmap/20261025-015157` (`39F621D3…111F192D`,
  headless-host 98d7661bf with `tools/headless/fieldmap_transform.py` applied: dumps also write
  `<section>.fields.txt`; otherwise identical to the normal build `work/msvc-output/Release/20261025-015258`).
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
- **Runs in flight:** `work/headless/record_matrix.py work/headless/matrix/m5-batch1.json --retry-failed`
  (58 cases; 30 done in the first pass; status `work/test-runs/hh-m5-matrix.json`, log
  `work/test-runs/hh-m5-matrix.log`). First pass: case names with underscores were rejected by the launcher
  (renamed with hyphens), and the Huge game ignored `UI.ExitGame`, blocking every later case (vpbench now ends
  such a game after 120 s; the Huge data was complete). Stop it cleanly
  between cases by creating `work/test-runs/hh-m5-matrix.stop`; rerunning the same command resumes.
  The real-game config.ini is unchanged (`RandLog` was 5 for the cdrift run only; backup in
  `work/test-runs/hh-m3-cdrift-randlog-config/`).
- **Next steps:**
  1. Review and merge the host agent's work (cdrift, then M3 milestones).
  2. Re-measure parallel scaling on an idle machine (`work/headless/m6/queues/scale-w<W>.json`, see
     `docs/headless-host.md`).
  3. Restore the AI build and mods before handing back.
- **Uncommitted files:** none besides this ledger.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | done | f96b1be30 | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | done | fc197fd34 | go: boot passes; small-block allocator disabled (all DLL memory from the MSVCR90 heap) |
| M2 | New-game generation | nearly done (cdrift open) | | T000 digest parity, incl. Communitu and Continental Drift |
| M3 | Turn loop and autoplay | done | 73d4f1932 | per-turn digest parity, 100 turns |
| M4 | Database builder | done | 0c240f6bb | can run alongside M3; `dbdiff.py` oracle |
| M5 | Breadth parity | in progress | | matrix in plan section 6 |
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
