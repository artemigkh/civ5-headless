# Headless host ledger

State of the work described in [the plan](headless-host-plan.md). Update this file at every milestone and
commit it with the change it describes.

## Resume here

- **Branch:** `headless-host` (base: master `363d26698`), worktree `work/wt/headless`.
- **Phase:** planning done and decisions recorded (plan section 9); M0 not started.
- **AI program:** paused (`ai-improvements`, see `docs/ai-improvement-ledger.md` on that branch). The real
  game is free for this work. After any deployment here, restore the AI program's deployed DLL
  (`F7CB6626…3B111A24`, build `work/msvc-output/Release/20261024-085658`) and its benchmark mods before
  handing back.
- **Next steps:**
  1. D1–D4 in the DLL and the `-Trace` build variant.
  2. `tools/headless/gen_interfaces.py` (needed by D1 and H2).
  3. Deploy the trace build, record S1, S3 and S4 (S2 only if M7 is wanted), capture the DLC snapshot
     (mod-free launch), then restore the AI build and mods.
- **Uncommitted files:** this ledger and the plan, until the planning commit.
- **Runs in flight:** none.
- **Agents / sessions in flight:** none.

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
