# Changelog

Every release of civ5-headless. Each GitHub release has the kit (`civ5-headless-<version>-<commit>.zip`) attached.

## 0.1.0 (2026-10-26)

First release.

- **`civ5headless.exe`** plays Civilization V: Brave New World AI autoplay games without the game. It uses any game
  DLL built from the Civ V SDK (the stock DLL, Community Patch, Vox Populi or your own) with your mods, map scripts
  and their options, premade maps and setup options.
  - Several games run at once.
  - The same spec, seeds, DLL, mods and database give the same game every time.
- **`c5h` tools:**
  - `doctor`: what was found (game, My Games, mods, DLL, host) and what is missing.
  - `run`: one game from a JSON spec, with progress every 10 turns.
    - `--detail summary|standard|full` sets what the run folder keeps.
    - Every run gets a `report.html`: setup, result, players, charts, maps, timeline, health.
  - `queue`: many games in parallel, resumable, with variants for A/B tests and a summary page.
  - `compare`, `fingerprint`, `dbdiff`: games and databases side by side.
  - `report`: rebuild run reports, and a summary page over several runs.
  - `dbcache`, `dbbuild`, `modsdb`: the game database and mods registry, built from the game's files and the mods
    without running the game.
  - `hazards`: UI code that changes the game state.
  - `verify`: the verification suite. The host against itself (A/A, frame skew, heap perturbation, probes), and
    against the real game: the same setups and a seeded game turn by turn, the database, and an ensemble for the
    statistics. Modes: `--host-only` (about 5 minutes), quick (about 10), `--full` (about 22).
- **UI emulation profiles** stand in for the game's UI where it changes the game state (popups, choices). Mod UI
  add-ins run in the host.
- **Example specs** for 8 setups (Continents, Continental Drift, Pangaea, Communitu with options, Earth), each with
  and without fixed seeds, and example queues.
- **The release kit** has the prebuilt exe, the tools with a bundled Python 3.12 (nothing to install), the profiles,
  probes, examples and docs. Running needs no compiler.
- **Checked against the real game** with `c5h verify` (Tiny maps, 150 turns of AI autoplay), with turn-by-turn
  identical games:

  | DLL and mods | Turns identical | Host speed |
  |---|---|---|
  | Vox Populi 5.4.8 (release); full mode also a Standard map, 60 turns | 150 of 150; 60 of 60 | 13x the real game |
  | The stock DLL, no mods | 150 of 150 | 22x |
  | A Vox Populi fork with the host's optional state digests | 148 of 148 (full state digests) | 7x |
