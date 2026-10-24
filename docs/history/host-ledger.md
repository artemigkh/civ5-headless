# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M0 in progress; M1 done (fc197fd34); M2 started.
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
  Staging packs the mod files of the checkout it runs in, so restore from an `ai-improvements` checkout
  (a temporary worktree with the toolchain junction), not from this branch.
- **Done:** `tools/headless/gen_interfaces.py` (0c9645861): trace proxies, host stubs, method table,
  compile-tested with VC9. Baseline release build of this branch: `work/msvc-output/Release/20261024-233829`.
- **Agents in flight** (Opus, high effort; each in its own worktree and branch, all from 0c9645861; each
  writes `RESUME.md` in its worktree when paused):
  - recorder: D1 boundary recorder and `-Trace` build, worktree `work/wt/hh-recorder`, branch
    `hh-recorder`.
  - digest: D2–D5 (digest, seeds, runtime facts, hook probe), worktree `work/wt/hh-digest`, branch
    `hh-digest`.
  - host: M1 done and merged (fc197fd34; boot passes under `--strict` in 1.55 s, all 24 info counts
    match, no unimplemented engine call). Now on M2 (new-game generation) in the same worktree and
    branch `hh-host`.
  On resume after a pause: read each worktree's `RESUME.md` and relaunch each agent with its original
  work order (the briefs are summarised in plan section 4) plus the checkpoint.
- **M0 steps 5–6 done** (run `hh-dbcapture-20261025b`): the cached `Civ5DebugDatabase.db` equals the
  in-memory database table by table, both at the mod-free main menu (367 tables) and after mod
  activation (839 tables). DLC snapshot kept as `work/headless/db/dlc-snapshot-CBF411E4.db` (local; see
  the README there). The modded copy was taken with the AI program's mod package deployed, so
  recapture after deploying a headless-host package before using it as the builder oracle.
- **Runs in flight:** none.
- **Also done:**
  - `work/headless/gamespec.py` (a93d5faa8): spec → resolved spec (IDs, seeds) and front-end pregame
    Lua; examples in `work/headless/specs/`.
  - `vpbench newgame --spec` (7fbcbb988).
  - `work/headless/dbdiff.py` (87e91a8b3).
  - The game's `Civ5ModsDatabase.db` lists every mod's actions (`ModActions`), files and VFS imports
    (`ModFiles.Import`) and entry points; useful for M4 and the VFS.
- **Next steps:**
  1. When the digest agent reports: add seed pinning, digest logging and the pregame snapshot to
     `vpbench newgame --spec`.
  2. Merge agent branches into `headless-host` as they finish (only `VoxPopuli.vcxproj` is expected to
     conflict).
  3. Deploy the merged trace build, record S1, S3 and S4, then restore the AI build and mods.
  4. After the host skeleton merges: start M4 (database builder) as a host subcommand.
- **Uncommitted files:** none besides this ledger and `work/headless/db_capture.py`.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | todo | | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | done | fc197fd34 | go: boot passes; small-block allocator disabled (all DLL memory from the MSVCR90 heap) |
| M2 | New-game generation | in progress | | T000 digest parity, incl. Communitu and Continental Drift |
| M3 | Turn loop and autoplay | todo | | per-turn digest parity |
| M4 | Database builder | todo | | can run alongside M3; `dbdiff.py` oracle |
| M5 | Breadth parity | todo | | matrix in plan section 6 |
| M6 | Tooling and throughput | todo | | vpbench backend, parallel runner |
| M7 | Saves | not planned | | optional follow-up |

## Log

- 2026-10-24: branch and worktree created; plan written; the user's answers recorded as decisions.
  Database builder added (M4), saves made optional (M7), VP map scripts added to the matrix.
