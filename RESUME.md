# Platform workstream: resume point

Branch `c5h-platform` in this worktree. Main (973c324, anydll merged) is merged in. Never push.

## Work order: milestone 3 (integrate anydll's pieces), plus the coordinator's additions

1. pyproject package-data: `civ5headless = ["data/*.json"]` and the realgame Lua; profiles/ and probes/ resolve
   from the workspace (config keys `profiles`, `probes`). DONE
2. cli: `c5h fingerprint`, `c5h hazards` (main(argv), no cfg), `c5h modsdb`. DONE
3. run.py / queue.py: `--profiles` always passed; `--fingerprint` (+ every/turns/split through a generated
   config probe before probes/fingerprint.lua); `--no-profiles`, `--skip-addin`, `--no-addins`; `--mod` / `--no-mods`
   with a generated registry. Result.report reads host-report.json. DONE
4. realgame/session.py: start_game(fingerprint=...) injects the same files. DONE
5. modsdb.py: the mods registry from .modinfo files; run/queue/dbcache use it for explicit mods. DONE, validated:
   registry identical to the game's (all tables) for the 5 active mods; dbbuild identical (dbdiff); Tiny 30-turn
   games HHDIGEST identical (30 points), fingerprints identical (31 turns), host-report mods/addins/uiFiles/profiles
   identical; no-mods + stock DLL build identical to the captured main-menu database.
6. doctor: profiles/ and probes/fingerprint.lua. DONE
7. docs/user-guide.md: host options, host-report.json, fingerprint, hazards, modsdb, mod sets. TODO
8. Coordinator additions (after the verify merge, 22d209f): merge main; spec field `minorCivs` (resolve only,
   no Lua; keys index/slot/type/id, slot = MAX_MAJOR_CIVS from Defines + i); RealGameSession.replay_data()
   (the FINAL Lua's replay data). TODO
9. Tests; full suite; commit; report.

## State

- Committed: items 1-6 with tests (see git log).
- Next: merge main, items 8 and 7, then report.

## Next steps

Tests: `python -m unittest discover -s tests` from the worktree root.
Validation config (scratch, not committed): a toml with the pinned registry, loc db, fieldmap DLL and a scratch
db_cache; games: `c5h --config X run examples/specs/continents-tiny.json --turns 30 --fingerprint [--mod ...]`.
Host exe: `python tools/build_host.py` with C5H_TOOLCHAIN set to the toolchain folder.

## Uncommitted

Nothing beyond this file's latest edits.
