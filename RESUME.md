# Platform workstream: resume point

Branch `c5h-platform` in this worktree. Main (d3bc856, verify merged) is merged in. Never push.

## Milestone 3: complete

Integrated anydll's pieces and the coordinator's additions; everything committed:

- e5d9c51 mods registry generator (`c5h modsdb`, modsdb.py), dbcache `--mod` / `--no-mods`.
- 44b484b config keys `profiles` / `probes`; run/queue `--profiles`, `--no-profiles`, `--skip-addin`, `--no-addins`,
  `--fingerprint[-every|-turns|-split]`, `--mod`, `--no-mods`; probes.py; start_game(fingerprint=...);
  `c5h fingerprint`, `c5h hazards`; doctor checks; package data.
- d0193a1 merge of main (verify workstream).
- 00d6336 spec `minorCivs`; RealGameSession.replay_data(); a run without a configured profiles folder leaves the
  choice to the host (verify's tests build a Config without one).
- cc31bb0 user guide, README, database-builder note, example config.

Validation (host-only, scratch config): generated registry identical to the game's for the 5 active mods (all
tables); dbbuild from it identical (dbdiff); Tiny 30-turn games with the game's and the generated registry: HHDIGEST
identical on 30 points, fingerprints identical on 31 turns, host-report mods/addins/uiFiles/profiles/stubs identical;
`--no-mods` with the stock DLL: database identical to the captured main-menu database, game passes; a two-job queue
(mod set, stock no-mods) completes.

## Open (outside this branch)

- Host `--skip-addin` matches only the name without extension (HHAddins.cpp Skipped() is given the base path's
  name, already without extension), though its usage says "with or without extension".

## Next steps

Wait for the coordinator. Tests: `python -m unittest discover -s tests`.

## Uncommitted

Nothing.
