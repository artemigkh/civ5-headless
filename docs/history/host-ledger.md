# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M0 in progress (real-game recordings); M1 done (fc197fd34); M2 in progress (agent); M4 in
  progress (agent).
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
  Staging packs the mod files of the checkout it runs in, so restore from an `ai-improvements` checkout
  (a temporary worktree with the toolchain junction), not from this branch.
- **Deployed now:** the headless-host trace build `work/msvc-output/Release-trace/20261025-002322`
  (DLL `660FFF0C…F10A7B3B`, includes the digest additions), with this branch's mod package.
- **Agents in flight** (Opus, high effort; each in its own worktree and branch; each writes `RESUME.md` in
  its worktree when paused):
  - host: M2 (new-game generation), worktree `work/wt/hh-host`, branch `hh-host` (at 92caccb78 when last
    checked; it has the merged recorder and digest work).
  - dbbuild: M4 (database builder as a host subcommand plus `work/headless/build_db.py`), worktree
    `work/wt/hh-dbbuild`, branch `hh-dbbuild` from 21856555b. Must not launch the game; it prepares three
    test edits for the main session to check against game launches.
  - contract: writes `docs/headless-engine-contract.md` from the M0 traces, worktree `work/wt/hh-contract`,
    branch `hh-contract` from 0ed40de35. Reads the run data in the main checkout; no game, no tuner.
  On resume after a pause: read each worktree's `RESUME.md` and relaunch each agent with its original
  work order (the briefs are summarised in plan section 4) plus the checkpoint.
- **Merged:** recorder (D1, 021ba53f4) and digest (D2–D5, 92caccb78); their worktrees are removed.
  Reference: `docs/headless-dll-additions.md`.
- **Fixed after the merges** (393b7ceb7): a crash at DLL unload (`~CvGlobals` reset the stacking rules
  cache after its static destruction), which also lost the trace tail; the trace now writes its end line
  from `DllMain`; the host's log files report full paths (the DLL finds the Logs folder through them).
  Host boot with the trace DLL: complete trace with end line, both with and without `FreeLibrary`.
- **M0 steps 5–6 done** (run `hh-dbcapture-20261025b`): the cached `Civ5DebugDatabase.db` equals the
  in-memory database table by table, both at the mod-free main menu (367 tables) and after mod
  activation (839 tables). Snapshots in `work/headless/db/` (local; see the README there):
  `dlc-snapshot-CBF411E4.db`, `mods-reference-08D19878.db` (AI program's package) and
  `mods-reference-08D19878-input/` (the mod files, `Civ5ModsDatabase.db` and database logs that produced
  it; the M4 oracle pair).
- **M0 recordings done** (trace build, runs in `work/test-runs/`):
  - S1 `hh-m0-s1-continents`: Continents spec, seeds 1001/2002 pinned from the file, autoplay to T5;
    complete trace (5.7 M boundary calls, 41 k lines kept), per-turn digests. The M2 T0 reference.
  - S3 `hh-m0-s3s4-earth`: `Earth_Small.Civ5Map`, 2 turns, state dumps at T0 and T2
    (`hhdigest.py verify` passes on both: the Python hash matches the DLL's).
  - S4 `hh-m0-s4-hooks`: GameEvents semantics. Every listener always runs (no short-circuit); nil counts as
    false; a raising listener counts as false or 0; `CallHook`'s value stays false; the accumulator sums
    numbers.
  - Facts: x87 control word 0x027F (53-bit, nearest), MXCSR 0x1F80, `timeBeginPeriod(1)` = 0. The engine's
    pregame seeds are map = sync = one clock value. Autosave = OUT `AutoSave(true,false)` followed by
    synchronous IN `Write` calls; no `WriteReplay`. `Game`, `Map`, `Players` are nil in the front end
    (`PreGame` exists), so the seeds file is the only pinning route.
- **Runs in flight:** 100-turn A/A on the Continents spec: `hh-m0-aa100-a` and `-b` (digest on), `-c`
  (digest off), each ending with a state dump (`game_probe.py --turns 100`).
- **Also done:**
  - `work/headless/gamespec.py` (a93d5faa8): spec → resolved spec (IDs, seeds) and front-end pregame
    Lua; examples in `work/headless/specs/`.
  - `vpbench newgame --spec` (7fbcbb988); seeds pinned through `<cache>\HeadlessSeeds.txt`, per-turn
    digest (`--no-digest` to disable), pregame snapshot, headless logs copied to the run, T0 save only with
    `--save-name`.
  - `work/headless/dbdiff.py` (87e91a8b3).
  - The game's `Civ5ModsDatabase.db` lists every mod's actions (`ModActions`), files and VFS imports
    (`ModFiles.Import`) and entry points; useful for M4 and the VFS.
- **Next steps:**
  1. Finish M0: compare the A/A pair (`python tools/headless/hhdigest.py compare A B` on their
     `HeadlessDigest.log`) and the digest-off run's T100 dump against them.
  2. Review `docs/headless-engine-contract.md` (agent) and merge.
  3. Review and merge `hh-host` (M2) and `hh-dbbuild` (M4) when they report; run the M4 test edits against
     game launches.
  4. Restore the AI build and mods before handing back.
- **Uncommitted files:** none besides this ledger.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | todo | | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | done | fc197fd34 | go: boot passes; small-block allocator disabled (all DLL memory from the MSVCR90 heap) |
| M2 | New-game generation | in progress | | T000 digest parity, incl. Communitu and Continental Drift |
| M3 | Turn loop and autoplay | todo | | per-turn digest parity |
| M4 | Database builder | in progress | | can run alongside M3; `dbdiff.py` oracle |
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
