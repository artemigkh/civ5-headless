# Saved games

The host reads and writes the game's own saved games, `.Civ5Save` files. A save the real game wrote continues in the
host, and a save the host wrote opens in the real game's Load menu, at any turn. This page covers how to use saves,
the file format, what the host does when it saves and loads, and what has been checked against the real game.
[running.md](running.md) section 3.6 is the short version.

## 1. Using saves

### Saving

Every save the host writes stays in the run folder, `<run>\saves\`; nothing goes to the game's own save folders. A
save serializes the whole game and compresses it: about 0.1 s and 240 KB on a Tiny map at turn 5.

| `c5h run` option | Host option | Saves |
|---|---|---|
| (default) | (default) | the last turn, once autoplay has ended: `Final_<turn and date>` |
| `--no-save-final` | `--no-save-final` | not the last turn |
| `--autosave none` | (none) | no autosaves (the default, as autosaves slow a game down) |
| `--autosave game` | `--autosave game` | the real game's setting: `UserSettings.ini` `[AutoSave] TurnsBetweenAutosave` (10 unless changed) |
| `--autosave N` | `--autosave N` | every N turns |
| `--save-at T` | `--save-at T` | at turn T (repeatable): `Turn_<turn and date>` |

Names are the real game's: `<prefix>_<turn and date>.Civ5Save`, the date as the game formats it
(`ICvGame1::SetTimeStr`, e.g. `0050 BC-2000`). Autosaves go to `saves\auto\`: `AutoSave_Initial_0000 BC-4000` and
`AutoSave_Post_0000 BC-4000` at turn 0, then `AutoSave_Post_<turn and date>` on every N-th turn. All are kept.

Lua in the game can save too: `UI.SaveGame(name)`, the in-game Save menu's call, writes `saves\<name>.Civ5Save`
(probes, add-ins).

`status.json` lists what was written (`saves`: kind, turn, path, bytes; `finalSave`), `host-report.json` and
`newgame-report.json` add the time each took, and the report has a Saves row. A save that fails fails the run.

### Loading

```
c5h run SAVE.Civ5Save --turns T [any other c5h run option]
c5h run --load SAVE.Civ5Save --turns T [...]
```

A `.Civ5Save` given where the spec goes is loaded, the same as `--load`. Any save works: the real game's (its
`Saves\single` or `ModdedSaves\single`, autosaves included) or one a host run wrote.

- `--turns` is the turn to play to; it must be after the save's turn.
- **Mods:** the save's, unless `--mod`, `--no-mods` or `--mods-db` is given. A save lists only the mods that affect
  saved games (`AffectsSavedGames`, section 2), so when the configured registry's active mods that affect saved games
  are exactly the save's, that registry is used as it is, with its other mods (EUI compatibility files, for
  example) and the cached game database that new games use. Otherwise a registry is generated for the save's mods,
  as for `--mod`. The mods must be in the MODS folder; the game need not have them active.
- **DLL:** chosen as for any game (`--dll`, a `dll` in `civ5headless.toml`, else the mod set's).
- **Seeds:** `--seeds` is refused, because the save holds the random number generators' state.
- **Run folder:** without `--run`, it is named after the save. `save-header.json` holds the save's header;
  `status.json` has `loadedFrom`, `loadWarnings` and `startTurn` (the save's turn), and `save` is
  `loaded-<save name>-t<turn>-<file hash>`, so runs from one save group together. The run ends with its own final
  save, so a game can be continued run after run.

The host checks the save before loading it:

- The save must be a single-player game.
- The DLL's GUID (`GetDLLGUID`) must be the save's. This only tells DLL families apart: Vox Populi builds share one
  GUID, so a save loads into another VP build. That is useful for A/B runs from one save, and it is the user's job to
  know whether the builds' saved data is compatible.
- The active mods that affect saved games (ID and version) must be the save's mods. A different activation order is a
  warning.
- A save from another game version is a warning.
- After reading, the DLL must have consumed the body exactly; otherwise the save is reported as written by another
  DLL.

`c5h save FILE...` shows a save's header: turn, game type, civilization, handicap, map script, world size, speed,
eras, DLL GUID and version, mods and DLC (`--json` prints all of it).

### From Python and queues

- `run.play(SAVE, turns, autosave='game', save_at=[50], save_final=False)`: a save given as the spec is loaded (or
  `run.play(None, turns, load=SAVE)`); `save_final` is True by default.
- Queue jobs take a save as `spec` or as `load`, and `autosave`, `saveAt` and `saveFinal` (default true). A job that
  loads a save gets the save's mod set unless it names one.
- `savegame.read_header(path)` returns a `SaveHeader`; its `mod_set` is the save's mods as `--mod` values.
  `savegame.is_save(path)` tells a save from a spec.
- The real-game session (`realgame/session.py`):
  - `load_game(save, lua_probes, fingerprint)` loads a save as the game's Load menu does: the mods are activated in
    the Mods menu, then `Events.PlayerChoseToLoadGame` runs in `ModsSinglePlayer`. The mods are those of
    `set_mods`, else the save's (only those that affect saved games, so the others stay off). The game is left
    behind the load screen, as `start_game` leaves a new one; `autoplay` then continues it.
  - `save_game(name)` saves as the in-game Save menu does (`UI.SaveGame`), then moves the file the game wrote out of
    its `ModdedSaves\single` (or `Saves\single`) into `<run>\saves\`.

## 2. The file

Values are little-endian. A string is a u32 length followed by its bytes; a GUID is its 16 bytes as in memory. The
layout was decoded from real saves (128 of them, unmodded and VP) and is checked by `savegame.py` and
`setup/HHSaveGame.cpp`.

1. **Header (uncompressed).**
   1. `"CIV5"`, u32 8 (save version), the game version `"1.0.3.279 (403694)"`, the build `"403694"`.
   2. u32 game turn (the pregame's), u8 game type (0: single player).
   3. Type names: the active player's civilization and handicap, the start era, the active player's current era,
      the game speed, the world size, the map script (a path).
   4. The DLC: u32 n, then n × (GUID, u32 1, name).
   5. The mods that affect saved games, in activation order: u32 n, then n × (ID, u32 version, name). These are the
      activated mods whose `ModProperties` `AffectsSavedGames` is not 0. When it loads a save, the real game activates
      exactly this list if the active list differs (section 6).
   6. The leader and civilization names (empty unless the player set them), the player colour.
   7. The DLL's GUID and version string.
   8. A constant GUID `{0d41152c-948e-498f-8cdf-699d04c98a95}`, then u32 0.
2. **Pregame:** `ICvPreGame1::write`, as the DLL writes it.
3. **Marker:** u32 2.
4. **Body:** one zlib stream in 64 KiB pieces, each a u32 length and its bytes. The stream comes from the game's
   `zlib1.dll` (1.2.3) at the default level: `Z_NO_FLUSH` until the last input, then one `Z_SYNC_FLUSH`, with no final
   block and no Adler checksum. The host deflates and inflates with that same `zlib1.dll`. Uncompressed, the body is:
   1. `Game::Write`, which embeds `<cache>\Civ5SavedGameDatabase.db` (u32 size and the file);
   2. `Map::Write`;
   3. `Team::Write` for teams 0–63;
   4. `Player::Write` for players 0–63;
   5. `Game::WriteSupportingClassData`.

The DLC list is the keyed packages of `Assets\DLC\*\*.Civ5Pkg` without `<Upgrade>`, in folder-name order, minus
the DLC the activated mods block (`DlcRelationships` type -1 in the mods registry; VP blocks `DLC_SP_Maps`).
Unmodded saves list 12 DLC, VP saves 11.

## 3. Saving in the host

`setup/HHSaveGame.cpp`, `WriteSave`:

1. The header from the pregame, the active player (`GetCurrentEra`, `GetPlayerColor`), the database's type names, the
   DLC list above and the activated mods.
2. `PreGame::write`, then the body in the order above, into memory.
3. Deflate, then write `<name>.tmp` and rename it over the target, so a run never leaves half a save.

Autosaves and `--save-at` hang on the DLL's `gDLL->AutoSave(bInitial, bPostTurn)` calls (engine contract 6.5):
`(true, false)` in the first unpaused update of a new game, and `(false, true)` once per turn, when the first
living player's turn ends. The real game does the same in autoplay. Its `ModdedSaves\single\auto` after a 50-turn
VP autoplay game held `AutoSave_Initial_0000`, then `AutoSave_Post_0000` to `AutoSave_Post_0050` every 10 turns;
that is `TurnsBetweenAutosave = 10`, and all seven were kept although `NumAutosavesKept` is 5.

- `--autosave N` saves at the initial call and at the post-turn call of every turn divisible by N, named
  `AutoSave_Initial_` and `AutoSave_Post_` as the real game names them.
- `--save-at T` saves at the first post-turn call of turn T.
- The final save (unless `--no-save-final`) comes once autoplay has ended, after the final checkpoint, the final Lua
  and the dump have read the game, so it is the game they describe.
- `UI.SaveGame(name)` saves at once, from whatever Lua calls it.

Each save goes to `<run>\saves\` (autosaves to `saves\auto\`). The mod list in the header is the activated mods whose
`AffectsSavedGames` property is not 0, in activation order, as the real game writes it: Community Patch and Vox
Populi have it, EUI compatibility files, Squads and Small Resource Icons do not.

The real game's other autosave, `AutoSave_<turn and date>` at the start of a human player's turn, cannot happen in
autoplay, which has no human turns.

Saving does not change the game: a 12-turn game saved at turn 6 has the same state digest on all 12 turns as the
same game unsaved.

## 4. Loading in the host

`host loadgame --load SAVE` boots as `newgame` does: the DLL, the mods' files, the database and the UI emulation.
Then `HHLoadSavedGame` runs:

1. **Header and checks** (section 1).
2. **Pregame:** `resetGame`, `resetPlayers`, `clearDLCAllowed`, `setDLCAllowed` for each of the save's DLC,
   `PreGame::read(stream, true)`, `setGameType(type, GAME_LOADED)`, `setLoadFileName(path)`.
3. **Body:** inflate; `CacheGameDatabaseData`; `Game::Read`, `Map::Read`, teams 0–63 `Read`, players 0–63 `Read`,
   `ReadSupportingClassData`; the body must be used up exactly. From here on `IsLoadedGame` is true, for the DLL
   (`ICvUserInterface1::IsLoadedGame`) and for Lua (`UI.IsLoadedGame()`).
4. **Start**, as for a new game (`HHGameStartedSteps`):
   - `LaterInit` for players 0–63 (`CvPlayer::gameStartInit`, which checks `IsLoadedGame`);
   - the tactical map, the game options, `SetGraphicsInitialized`, `SetupGraphical`, `DoGameStarted`;
   - the net message reset, the player options, the delivered net messages;
   - the selection list (no settler is selected);
   - the notifications.

   A new game's own steps are left out: closing dead city-state slots, selecting the settler.
5. **Digest logging** on for DLLs with the digest additions, which otherwise start it in `CvGame::init`. A load does
   not run `CvGame::init`.

Then the load screen, the UI add-ins, the probes and autoplay, as for a new game. Autoplay is armed with the same
Lua as the real-game session's (`Game.SetAIAutoPlay(n, 0)`). The checkpoint the host writes at the start is named
after the save's turn.

**Assumption (not traced):** the real game's load sequence was not recorded with the trace DLL. Steps 2 and 4
follow the DLL's own code and what the engine does for a new game. Section 6 says how far the result has been
checked against the real game.

## 5. Save data and Lua

- `Modding.OpenSaveData()` is the game's save data: `<run>\cache\Civ5SavedGameDatabase.db`. The DLL creates it for
  a new game, embeds it in every save and restores it from a loaded one.
  - `GetValue(name)` and `SetValue(name, value)` use its `SimpleValues` table.
  - `Query(sql, ...)` is `DB.Query` on it. TableSaverLoader (Squads) uses it, called both as `Query(...)` and as
    `:Query(...)`.
- `UI.IsLoadedGame()` is true in a loaded game.
- `Modding.OpenUserData` is still an in-memory store, empty at every start.

## 6. Checks against the real game

Run on 2026-10-26, on a Tiny Continents fixed-seed game.

- **Host alone (field-map VP build, digest additions):**
  - A game saved at turn 6 and the same game unsaved have identical state digests on all 12 turns.
  - Loading the turn-6 save and continuing does not reproduce the continuous game. The random number generators
    are identical after the load, but the state differs from the first digest on. One cause is in VP itself:
    `CvPlayer::Read` calls `reset()`, which fills the espionage AI's per-civ lists (22 entries each), and the
    espionage AI's `operator>>` then appends the 22 saved entries. After every load the first 22 entries are the
    defaults, the saved values are never read again, and each list grows by 22 per save and load. The other cause
    is where a save resumes: at the first player's post-turn point, so the rest of that turn is played again after
    the load. Both happen in the real game too, since the host runs the DLL's own `Read`. So a loaded game is
    compared with the same save loaded in the real game, not with the game that wrote the save.
- **Real game (Vox Populi, DLL `E8E58D95` as installed; the host ran the same DLL):**
  - A host save of turn 5 loads in the real game, which plays on from it (turns 5 to 8).
  - That save loaded in the host and in the real game, then played to turn 8: fingerprints identical on all 4 turns.
    The two turn-8 saves have bodies of the same size (13,003,632 bytes uncompressed) that differ in 67 bytes, in
    13 runs: two update counters, the end of the embedded save database, 6 map bytes and 1 player byte. Their
    pregame records differ in length by 94 bytes.
  - A real-game save of turn 8, taken after the real game's autoplay ended (player 0 human again), loaded in both and
    played to turn 10: identical at turn 8, then player 0 has 50 gold in the real game and 51 in the host at turn 9.
    Saved again right after the load, the two bodies differ only in two swapped bytes in player 0's data, so the
    loaded state is all but the same and the difference is likely an ordering the real game's load sequence sets up
    differently. **Open:** finding it needs the real game's load traced (section 4).
  - Loading needs the save's mod list to be the active one (header item 5). With a different list the real game
    re-activates the mods during the load; with Vox Populi's front end active that rebuild fails ("database table is
    locked") and the game crashes on the half-built database. Loading from the main menu with no mods active
    crashed too (VP's DLL in `CvGame::Read`). So the host writes only the mods that affect saved games, as the real
    game does, and the session loads from the Mods menu.
- **A long game:** the Tiny Continents game played in the host to turn 330 (9.4 min, no winner yet; host DLL
  `E8E58D95` with the installed mods). Its final save (764 KB; 17.2 MB uncompressed; written in 0.21 s) loaded in the
  real game in 16 s from the Mods menu, at turn 330 with player 0 (Sweden) human again, ready to play on.

## 7. Limits

- Single-player saves only. Hotseat, network and cloud saves are refused or not read.
- The load sequence is reconstructed, not traced (section 4).
- A save's DLL check is by GUID only (section 1).
- A real save loaded in the host and in the real game can differ after the first turn (section 6: 1 gold at the next
  turn, in one test).
- A loaded game resumes where the save was taken. For an autosave or `--save-at` save that is the post-turn point of
  the first player, so part of that turn is played again. That is the real game's behaviour too.
- The game option `GAMEOPTION_NEW_RANDOM_SEED`, if a save has it, reseeds the random number generators on load, so
  continuing that save is not repeatable. The host does what the DLL does.
