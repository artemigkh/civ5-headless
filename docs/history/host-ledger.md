# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), checked out in the main checkout
  `E:\Projects\Civ5StackMod` since 2026-10-24 (the user allowed switching it; `ai-improvements` is
  committed and on hold).
- **Phase:** M0 and M1 in progress.
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. Before handing back, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods.
- **Done:** `tools/headless/gen_interfaces.py` (0c9645861): trace proxies, host stubs, method table,
  compile-tested with VC9. Baseline release build of this branch: `work/msvc-output/Release/20261024-233829`.
- **Agents in flight** (Opus, high effort; each in its own worktree and branch, all from 0c9645861; each
  writes `RESUME.md` in its worktree when paused):
  - recorder: D1 boundary recorder and `-Trace` build, worktree `work/wt/hh-recorder`, branch
    `hh-recorder`.
  - digest: D2–D5 (digest, seeds, runtime facts, hook probe), worktree `work/wt/hh-digest`, branch
    `hh-digest`.
  - host: M1 host skeleton, worktree `work/wt/hh-host`, branch `hh-host`.
  On resume after a pause: read each worktree's `RESUME.md` and relaunch each agent with its original
  work order (the briefs are summarised in plan section 4) plus the checkpoint.
- **Runs in flight:** `work/headless/db_capture.py --run hh-dbcapture-20261025a` (DLC snapshot and
  in-memory database check; installed DLL unchanged).
- **Next steps:**
  1. Review the capture; keep `dlc-debug.db` as the DLC snapshot.
  2. Merge agent branches into `headless-host` as they finish (only `VoxPopuli.vcxproj` is expected to
     conflict).
  3. Deploy the merged trace build, record S1, S3 and S4, then restore the AI build and mods.
- **Uncommitted files:** none besides this ledger and `work/headless/db_capture.py`.

## Milestones

| ID | Milestone | Status | Commit | Notes |
|---|---|---|---|---|
| M0 | Record the engine contract | todo | | trace recordings, reference A/A, DB check, DLC snapshot |
| M1 | Host boots the DLL | todo | | go/no-go after this |
| M2 | New-game generation | todo | | T000 digest parity, incl. Communitu and Continental Drift |
| M3 | Turn loop and autoplay | todo | | per-turn digest parity |
| M4 | Database builder | todo | | can run alongside M3; `dbdiff.py` oracle |
| M5 | Breadth parity | todo | | matrix in plan section 6 |
| M6 | Tooling and throughput | todo | | vpbench backend, parallel runner |
| M7 | Saves | not planned | | optional follow-up |

## Log

- 2026-10-24: branch and worktree created; plan written; the user's answers recorded as decisions.
  Database builder added (M4), saves made optional (M7), VP map scripts added to the matrix.
