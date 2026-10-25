# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M0 nearly done (A/A and VP-map references being re-recorded); M1 done; M2 in progress (agent,
  load-screen T000 parity); M4 done (game check of test edits open).
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
  Staging packs the mod files of the checkout it runs in, so restore from an `ai-improvements` checkout
  (a temporary worktree with the toolchain junction), not from this branch.
- **Deployed now:** headless-host trace build `work/msvc-output/Release-trace/20261025-005905` (DLL
  `008A4227…17F91B5D`: digest additions plus the early seed pin), with this branch's mod package. Matching
  normal build: `work/msvc-output/Release/20261025-005758`.
- **Agents in flight** (Opus, high effort; own worktree and branch; `RESUME.md` in the worktree on pause):
  - host: M2, worktree `work/wt/hh-host`, branch `hh-host`. Work order: merge headless-host; T000
    load-screen state byte-identical to the real game's `dump-t000` for continents (s1b), earth (s3b),
    communitu and cdrift; normalise or report the uninitialised bytes the DLL serialises (digest not even
    host-A/A stable today); the unidentified -1 field in major players; contract gaps that affect T000;
    `work/headless/parity_t000.py`.
  On resume after a pause: read the worktree's `RESUME.md` and relaunch the agent with its work order (above)
  plus the checkpoint.
- **Merged into headless-host:**
  - D1 recorder (021ba53f4), D2–D5 digest (92caccb78), M4 database builder (0c240f6bb).
  - M2 first part (hh-host 67b9a9887, merge 7f4e2a49c): `civ5headless.exe newgame --spec`,
    pregame from a resolved spec, VFS and include, map-script Lua, start sequence. All test maps generate
    under `--strict`; the Earth T000 map section is byte-identical to the real game's; HHSEEDS and the
    whole HHPREGAME snapshot match S1 and S3 line for line.
  - Engine contract (`docs/headless-engine-contract.md`, merge "Merge hh-contract"): phases, threads and
    locks, net loopback, state-changing UI calls, gaps G1–G16, open questions.
- **Fixes on headless-host:**
  - 393b7ceb7: DLL crash at unload (static destruction order); trace end line from `DllMain`; host log
    paths.
  - 255e26ba2: the seeds file is applied at `setGameStarted(true)` too, so the random civs and city-states
    follow the spec seed (before, the engine's clock seed chose them: S1, S3 and the first AA100 pair
    are not reproducible for civs).
- **M0 data** (`work/test-runs/`):
  - First recordings (trace DLL 660FFF0C, civs from the clock seed): S1 `hh-m0-s1-continents`, S3
    `hh-m0-s3s4-earth`, S4 `hh-m0-s4-hooks`, `hh-m0-aa100-{a,b,c}` (invalid as A/A: different civs).
  - Facts: x87 0x027F, MXCSR 0x1F80, `timeBeginPeriod(1)` = 0; autosave = OUT `AutoSave` then synchronous IN
    `Write` calls on turn 0 and every 10th turn, no `WriteReplay`; `Game`, `Map`, `Players` nil in the front
    end; GameEvents: every listener runs in order, a raising listener is skipped (no vote), `CallHook`'s value
    is forced false; one `Update` per alive player per turn.
  - Database: `work/headless/db/` (README there): DLC snapshot; oracle pairs for the AI package
    (`mods-reference-08D19878`) and this branch's package (`mods-headless-host-0ed40de35`).
- **Runs in flight:** chain with trace DLL 008A4227 (script in the session scratchpad, `m0-chain2.sh`):
  `hh-m0-s1b-continents` (vpbench order, to T5), `hh-m0-s3b-earth`, `hh-m0-communitu`, `hh-m0-cdrift`
  (load-screen dump and after 2–3 turns), `hh-m0-aa100b-{a,b,c}` (100-turn A/A, c without digest). Each
  `<run>.out` ends with a `quit` line when complete.
- **Next steps:**
  1. When the chain ends: `python tools/headless/hhdigest.py compare` on the aa100b-a/b
     `HeadlessDigest.log`; compare the aa100b-c T100 dump with a and b (digest on vs off); check the
     `HHPREGAME slot` lines match across runs (early pin).
  2. Check the four M4 test edits against game launches (`work/headless/dbbuild_test_edits.py`, steps in
     `docs/headless-dbbuild.md`).
  3. Review and merge the host agent's M2 parity work; then M3 (turn loop: threads, locks, net loopback,
     autoplay order per the contract).
  4. Restore the AI build and mods before handing back.
- **Uncommitted files:** none besides this ledger.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | nearly done | f96b1be30 | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | done | fc197fd34 | go: boot passes; small-block allocator disabled (all DLL memory from the MSVCR90 heap) |
| M2 | New-game generation | in progress | | T000 digest parity, incl. Communitu and Continental Drift |
| M3 | Turn loop and autoplay | todo | | per-turn digest parity |
| M4 | Database builder | done (game check of test edits open) | 0c240f6bb | can run alongside M3; `dbdiff.py` oracle |
| M5 | Breadth parity | todo | | matrix in plan section 6 |
| M6 | Tooling and throughput | todo | | vpbench backend, parallel runner |
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
