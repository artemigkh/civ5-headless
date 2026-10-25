# Headless host: DLL additions (D2–D5)

Reference for the parity tools in the game DLL (plan: [headless-host-plan.md](headless-host-plan.md), sections 3
and 4.2). Code: `CvGameCoreDLL_Expansion2/Headless/HHDigest.{h,cpp}`, `HHDigestNorm.h`, Lua bindings in
`Lua/CvLuaGame.cpp`, helpers in `tools/headless/`.

Everything ships in normal builds, is off by default and leaves game state unchanged (see "Result neutrality").

## Log files

Both files are in the engine's `Logs` folder and are recreated at each game launch. The folder is located
through `LOGFILEMGR` (an empty `HeadlessHost-path.log` serves as the locator, as the stacking diagnostics do);
lines are written with stdio and flushed per write, so long lines are never truncated. The headless host's log
manager must return a real path from `FILogFile::GetFileName()`.

- `HeadlessDigest.log`: seeds, pregame snapshot and initial RNG states at every game init (always on);
  per-turn digests when digest logging is on; digests requested from Lua.
- `HeadlessRuntime.log`: one line at the first `CvGame::update` of the process (game core thread) and one at every
  `CvGame::init` (`point=gameInit`, the thread that generates the map), always on.

Every line is `KIND|key=value|...`. In values, `|`, `%`, `=` and control characters are percent-encoded
(`%7C`, `%25`, `%3D`, ...).

### Game init (always, once per `CvGame::init`, before reset, RNG init and map generation)

```
HHSEEDS|point=gameInit|game=1|startType=0|source=file|exeMap=12345|exeSync=6789|map=123456|sync=654321|pinnedMap=1|pinnedSync=1|digest=1|normalise=1|error=
HHPREGAME|begin|point=gameInit|game=1
HHPREGAME|map|script=Assets\Maps\Continents.lua|isWBMap=0|mapNoPlayers=0|loadWBScenario=0|...
HHPREGAME|game|worldSize=3|climate=..|seaLevel=..|gameSpeed=..|era=..|maxTurns=0|numMinorCivs=16|...
HHPREGAME|session|gameType=0|gameMode=..|gameStartType=0|...|quickCombat=..|mpOptions=0000...
HHPREGAME|seeds|map=..|sync=..
HHPREGAME|text|gameName=..|version=..|loadFile=..
HHPREGAME|mapOptionList|count=0|order=
HHPREGAME|mapOption|name=SeaLevel|set=0|value=unset|default=2
HHPREGAME|mapOption|name=X|set=1|value=3|default=2|index=0
HHPREGAME|gameOptionList|count=..|order=GAMEOPTION_A,GAMEOPTION_B
HHPREGAME|gameOption|name=GAMEOPTION_RAGING_BARBARIANS|set=1|value=1|default=0|index=4
HHPREGAME|gameOption|name=GAMEOPTION_NO_BARBARIANS|set=0|value=unset|default=0
HHPREGAME|gameOptionEnum|values=0,1,0,...        (the enum-indexed copy the game core reads)
HHPREGAME|victory|index=0|type=VICTORY_TIME|value=1
HHPREGAME|slot|id=0|status=..|claim=..|civ=..|civKey=..|leader=..|leaderKey=..|team=..|handicap=..|lastHumanHandicap=..|minorCiv=..|isMinor=..|color=..|artStyle=..|human=..|playable=..|netID=..|whiteFlag=..
HHPREGAME|slotText|id=0|leaderName=..|civDescription=..|civShortDescription=..|civAdjective=..|nickname=..
HHPREGAME|dlcAllowed|id=XXXXXXXX-XXXX-...
HHPREGAME|end|point=gameInit|lines=N
HHRNG|turn=0|point=gameInit|game=1|map=<seed>:<calls>:<resets>|sync=...|async=...
```

- `exeMap`/`exeSync` are the pregame seeds as the engine left them; `map`/`sync` are the ones the game uses.
- Map and game options list every database option (map options: `MapScriptOptions` rows whose `FileName` equals
  the pregame map script name, which is the lookup the game itself uses), set or unset, plus any set name the
  database doesn't know (`default=none`). `index` is the position in pregame's list.
- **Unset map options:** `Map.GetCustomOption` → `CvPreGame::GetMapOption` returns
  `MapScriptOptions.DefaultValue` for an unset option and **stores it** in pregame's list at that moment. So the
  setup screen's untouched options do resolve to the database default when the map script reads them; the
  snapshot at game init shows them as `unset`, and they appear in the list after map generation. The by-name
  `GetGameOption` does the same for game options, but only after turn 0.
- The snapshot is taken with side-effect-free accessors only (the by-name option getters and `worldInfo()` are
  avoided because they change pregame state).

### Per turn (digest logging on), at the start of `CvGame::doTurn`, before any processing

```
HHDIGEST|turn=12|point=doTurnBegin|total=<hex>|pregame=<hex>|game=<hex>|support=<hex>|map=<hex>|p00=<hex>|...|playersRest=<hex>|t00=<hex>|...|teamsRest=<hex>|savedb=<hex>
HHDIGESTSIZE|turn=12|point=doTurnBegin|normalise=1|pregame=<bytes>|game=<bytes>|...
HHRNG|turn=12|point=doTurnBegin|map=<seed>:<calls>:<resets>|sync=...|async=...
HHENV|turn=12|point=doTurnBegin|thread=<id>|control87=0x...|mxcsr=0x...
```

`turn` is the turn that is ending (`doTurn` increments it later). Hashes are xxHash64 (seed 0), 16 hex digits.

### Runtime facts (always, once per process, first `CvGame::update`)

```
HHRUNTIME|point=firstUpdate|process=..|thread=..|fpcw=0x027F|precision=53bit|rounding=nearest|control87=0x...|control87x87=0x...|control87sse=0x...|mxcsr=0x00001F80|timeBeginPeriod=0|gameTurn=0
```

`fpcw` is the raw x87 control word (`fnstcw`); `control87*` are the CRT's abstract words (`_control87`,
`__control87_2`); `mxcsr` from `_mm_getcsr`. `timeBeginPeriod` is the `MMRESULT` of `timeBeginPeriod(1)` in
`DllMain` (0 = applied, -1 = not recorded). The host (H13) must load the same x87 word and MXCSR on its game
thread; the DLL is x87 code built with `/fp:precise`, so precision and rounding bits matter. `HHENV` repeats the
x87/MXCSR check every logged turn to catch a change (Direct3D without `FPU_PRESERVE` changes the word of the
thread that creates the device).

## State digest (D2)

### Sections and the Write paths they use

| Section | Write path | In total |
|---|---|---|
| `pregame` | `CvPreGame::write` (what `CvDllPreGame::write` calls) | yes |
| `game` | `CvGame::WriteHeadlessDigest`: the header and `CvGame::Serialize` exactly as `CvGame::Write`, without its side effects and without the embedded save database | yes |
| `support` | `CvGame::WriteSupportingClassData` (barbarians, goody huts) | yes |
| `map` | `CvMap::Write` (plots, areas, landmasses, rivers) | yes |
| `pNN` | `CvPlayerAI::Write` (virtual `Write` as called by `CvDllPlayer::Write`) for each player that `isEverAlive()` | yes |
| `playersRest` | the same for all other player slots, concatenated in index order | yes |
| `tNN` / `teamsRest` | `CvTeam::Write`, split the same way by `CvTeam::isEverAlive()` | yes |
| `savedb` | `CvGame::writeSaveGameDB`: `<cache>\Civ5SavedGameDatabase.db` as a save embeds it | **no** (a file outside the DLL; shown for diagnosis) |

Total = xxHash64 over, for each section in the total in the order listed, its name, a NUL byte and its 8-byte
little-endian hash (`tools/headless/hhdigest.py` reimplements it).

Write entry points the exe uses that are **not** hashed:

- `CvDllGame::WriteReplay` → `CvGame::writeReplay` → `CvReplayInfo::createInfo`, which calls
  `CvPlayer::GatherPerTurnReplayStats` for every ever-alive player: it runs the `GatherPerTurnReplayStats` Lua
  hook and writes replay data that gameplay reads (espionage reads `REPLAYDATASET_MILITARYMIGHT` 10 turns back).
  Not side-effect free, so no replay section. Its content is derived from state that is hashed anyway (pregame,
  game options, players' `m_ReplayData`, plots, replay messages).
- `CvDllDeal::Write`, `CvDllRandom::Write`, `CvDllNetInitInfo::Write`, `CvDllNetLoadGameInfo::Write`: engine-side
  objects (scratch deals, the engine's own RNGs, MP handshakes), not game state. Game deals and the map and sync
  RNGs are inside the `game` section.

The engine's save has other parts the DLL doesn't produce (its container, the embedded save database); they are
not game state the DLL reads, except the save database (the `savedb` section).

### Lua API (InGame context)

| Call | Returns / effect |
|---|---|
| `Game.GetHeadlessDigest()` | `{turn=N, total="hex", line="HHDIGEST|...", sections={name="hex"}, sizes={name=bytes}, order={names...}, excluded={"savedb"}}`; nothing logged |
| `Game.LogHeadlessDigest([point])` | the same table; also appends the `HHDIGEST`/`HHDIGESTSIZE`/`HHRNG`/`HHENV` lines with `point` (default `lua`) |
| `Game.SetHeadlessDigestLogging(bool)` / `Game.IsHeadlessDigestLogging()` | per-turn logging at `doTurnBegin`; returns the new state |
| `Game.SetHeadlessDigestNormalise(bool)` / `Game.IsHeadlessDigestNormalise()` | field normalisation (default on); off gives the raw save bytes, for investigating A/A differences |
| `Game.DumpHeadlessState(folder)` | writes `<folder>\<section>.bin` (raw bytes of each section) and `digest.txt` (the line and sizes); creates missing folders; returns the line, or `nil, error` |
| `Game.GetHeadlessPregameSnapshot([point])` | array of the `HHPREGAME` lines for the current pregame state |

Call the on-demand functions only while the game core is idle (between turns or while autoplay is paused): the
UI thread can call into the DLL while the game core thread runs (see the comment in `TContainer.h`), and a
digest taken mid-update reads a moving state. The per-turn log runs on the game core thread and is safe.

`tools/headless/hhdigest.py`:

- `verify DUMP_FOLDER`: recomputes each `.bin` hash and the total against `digest.txt`.
- `compare LOG_A LOG_B`: first turn and sections where two `HeadlessDigest.log` files differ.
- `hash FILE...`: xxHash64 of files.

Binary diffs of two dumps (same turn, same section) locate the first differing byte; the serializers write fields
in declaration order of the `Serialize` functions, so the offset maps to a field by walking the visitor.

### Side-effect audit

Checked every `Write`/`write`/`Serialize`/`operator<<(FDataStream&, ...)` reachable from the sections above
(a script scanned all 374 stream operators and every `bSaving` branch for non-const calls, `const_cast`, events,
RNG, time, logging, caches and allocation). Findings:

| Where | Side effect | Handling |
|---|---|---|
| `CvDllGame::Write` | sets `CvGame::m_bSavedOnce` (serialized) | digest calls `CvGame` directly; field normalised |
| `CvGame::Write` | fires `GAMEEVENT_GameSave` when `m_bSavedOnce` and `EVENTS_GAME_SAVE` (0 in CP) | `WriteHeadlessDigest` omits it |
| `CvGame::Write` | `GC.setSaveVersion(SAVE_VERSION_LATEST)` (only matters after loading an old save) | digest writes the constant without setting it |
| `CvPreGame::saveSlotHints` | `GetGameOption("GAMEOPTION_KEEP_UNMET_PLAYERS_UNKNOWN")` by name stores the default in pregame's list after turn 0; `updateKnownPlayersTable` when it's set | skipped while the digest writes (thread-checked) |
| `CvGame::writeReplay` | `GatherPerTurnReplayStats`: Lua hook plus replay data | not hashed |
| `CvMap`, `CvPlot`, `CvPlayer`, `CvUnit`, `CvCity` serializers | `const_cast` only in loading branches; saving branches only read | none needed |
| `CvSyncArchive` delta tracking | only touched by the MP sync code (`collectDeltas`, `clearDelta`), never by `Write` | none |
| RNG | no `Write` path draws; `getSeed`/`getCallCount` only read | none |
| Lazy caches | `mutable` members exist (unit path cache, city/player caches) but the save path reads members directly and calls only trivial const getters | none |

Exe-side consequences for the host (not handled in the DLL): the real game's autosave calls these same paths. Each
autosave sets `m_bSavedOnce`, adds `GAMEOPTION_KEEP_UNMET_PLAYERS_UNKNOWN` to pregame's game-option list after
turn 0 (value unchanged), and, **if** the exe calls `WriteReplay` during saves (check in the D1 trace), runs
`GatherPerTurnReplayStats` early for the current turn. That last one can change state: the regular end-of-turn
gather overwrites the values, but a player who dies before its own gather keeps an entry it would not otherwise
have. If the trace shows `WriteReplay` in autosaves, the host must call it at the same point.

### Unstable bytes and normalisation

Normalised fields are written as their zero value (`T()`) while the digest serializes with normalisation on, through
`visitor(HH_DIGEST_NORM(visitor, member))` at the field's `Serialize` line. Normal saves are unaffected: the
substitution needs `HHDigest::g_bWriting` on the current thread.

| Field | Why it varies | Gameplay use |
|---|---|---|
| `CvGame::m_strGameId` | `CoCreateGuid` at game init | stats database id only |
| `CvMap::m_guid` | `CoCreateGuid` in `CvMap::init` | none |
| `CvPlayer::m_uiStartTime` | set by the exe (`SetStartTime`, wall clock) | `getTotalTimePlayed` only |
| `CvGame::m_iTurnSlice` | +1 per `CvGame::update`, i.e. per engine frame | see "Frame-count dependence" |
| `CvUnit::m_uiLastPathTurnSlice` | turn slice of the unit's last path | path cache validity |
| `CvGame::m_bTunerEverConnected` | FireTuner connection | none |
| `CvGame::m_bSavedOnce` | set by each save (`CvDllGame::Write`) | `GameSave` event gate |
| pregame game/map option lists | defaults are stored on first by-name query (map script, UI calls of `Game.IsOption`/`GetCustomOption` after T0, autosaves) | none: same value as unset |
| `CvTeam` arrays sized `REALLY_MAX_TEAMS`/`REALLY_MAX_PLAYERS` (80): entries 64..79 of `m_aiTechShareCount`, `m_aiNumTurnsLockedIntoWar`, `m_paiTurnMadePeaceTreatyWithTeam`, `m_aiIgnoreWarningCount`, `m_abHasFoundPlayersTerritory`, `m_abHasMet`, `m_abAtWar`, `m_abAggressorPacifier`, `m_abPermanentWarPeace`, `m_abEmbassy`, `m_abOpenBorders`, `m_abDefensivePact`, `m_abResearchAgreement`, `m_abForcePeace`, `m_abWonLatestWar`, `m_aiTurnTeamMet`, `m_aiTurnWarStarted`, `m_aiNumTurnsSinceVassalEnded` (`HH_DIGEST_NORM_TAIL`) | `Reset` initialises only `[0, MAX_TEAMS)`; the tail is heap garbage | none: every access is a team/player index below 64 |
| `CvNotifications::m_aNotifications` slots outside the active ring `[begin, end)` (written as cleared slots) | `Notification::Clear` leaves `m_iExtraGameData` and `m_ePlayerID` uninitialised | none: every reader walks the ring; `Add` assigns a fully set notification |
| `CvPlayerTraits::m_bHasYieldFromTileCultureBomb`, `m_bHasYieldFromTileEarn`, `m_bHasYieldFromTilePurchase` | never initialised (only ever set to true in `InitPlayerTraits`) | none: the getters have no callers |
| `CvGameTrade::m_aaiTechDifference`, `m_aaiPolicyDifference`, while `getElapsedGameTurns() == 0` | uninitialised until the first `CvGameTrade::DoTurn` (in `CvGame::doTurn`, end of the first turn) | read only through trade-route values, which need a trade route or a trade unit: unreachable before the first `doTurn` in an ancient start. **Risk** in later-era starts (a trade unit is buildable on turn 0; see below) |
| `CvPlayerCulture::m_eOpinion`, `m_ePreferredIdeology`, `m_eOpinionBiggestInfluence`, while the player has no ideology (`GetLateGamePolicyTree() == NO_POLICY_BRANCH_TYPE`) | never initialised; first written by `DoPublicOpinion`, which returns early without an ideology | **real nondeterminism risk**, see below |

Real nondeterminism risks found with the digest (gameplay can read the uninitialised value; not changed, since a fix
changes gameplay; normalised so that the digest stays usable):

- `CvPlayerCulture::m_eOpinion`, `m_ePreferredIdeology`, `m_eOpinionBiggestInfluence` are never initialised
  (`CvPlayerCulture::Init` skips them) and stay heap garbage until the player's first `DoPublicOpinion` with an
  ideology. Readers that do not check for an ideology first: `CvMinorCivAI::SpawnRebels` (the ally's
  `GetPublicOpinionType() >= PUBLIC_OPINION_CIVIL_RESISTANCE`), `CvMinorCivAI` rebellion quest text,
  `CvDiplomacyAI` ideology statements (28670 ff.), `CvPolicyAI` (preferred ideology, biggest influence), Lua
  `Player.GetPublicOpinionType`/`GetPublicOpinionPreferredIdeology`. Measured: the real game had −1 in all three for
  the majors and the observer, 0 for most city-states, 15 in one city-state's `m_ePreferredIdeology` (S3b dump-t000);
  the host has 0 or garbage. Proposed fix (gameplay-visible, for the maintainers to decide): set them to
  `NO_PUBLIC_OPINION`, `NO_POLICY_BRANCH_TYPE`, `NO_PLAYER` in `CvPlayerCulture::Init`.
- `CvGameTrade::m_aaiTechDifference`/`m_aaiPolicyDifference` before the first `doTurn`: `CvGameTrade::Init`
  (`Reset`) does not call `ResetTechDifference`/`ResetPolicyDifference`. In a later-era start a city founded on
  turn 0 can evaluate trade units (`GetTradeConnectionValueTimes100` → `GetTechDifference`) before the tables are
  built. Proposed fix: call both resets in `CvGameTrade::Reset`.

How these were found: `tools/headless/fieldmap_transform.py` builds a DLL whose dumps also write
`<section>.fields.txt` (the offset of every `visitor(...)` call while the digest writes, with its file, line and
argument), so a differing byte offset maps to the member that wrote it (`tools/headless/parity_t000.py --fields`).

The option lists are normalised in `CvPreGame::writeArchive` (digest only): entries equal to the database default
are dropped and the rest sorted by name. Everything else is written exactly as a save writes it.

Padding: no raw struct dumps. The catch-all raw `operator<<` is disabled in `FDataStream.h`; the only raw writes
(`CvBitfield`, `CvFixedBitfield`) write zero-initialised byte arrays. Pointers are never serialized
(`IDInfo`/indices instead). Hashed containers that are serialized (`CvGame::m_AdvisorMessagesViewed`,
`CvCity::m_miInstantYieldsTotal`, `std::tr1::unordered_*`) iterate in hash order, which is deterministic for the same
insertion sequence and the same CRT.

Candidates to watch in the first A/A runs (not normalised, because they are deterministic in autoplay or because
they can matter):

- UI-driven game fields: `m_AdvisorMessagesViewed`, `m_bTutorialEverAttacked`, `m_bStaticTutorialActive`,
  `m_bEverRightClickMoved`, `m_eObserverUIOverridePlayer`.
- The rest of the unit path cache (`m_kLastPath`, `m_uiLastPathCacheOrigin/Destination/Flags`) changes if the UI
  makes a unit generate a path.
- Pregame identity fields the host must copy rather than invent: nicknames, net IDs, `s_alias`, game name,
  version string, DLC lists, `s_gameUpdateTime`, `s_loadFileName`.
- `savedb`: excluded from the total until an A/A shows it stable.

To normalise another top-level or nested field: wrap its `visitor(...)` call with `HH_DIGEST_NORM` (include
`Headless/HHDigestNorm.h` in that `.cpp`) and add it to the table above. For a field written with `<<` instead of
the visitor, guard it with `HHDigest::IsNormalisedWrite()`.

## Seeds (D3)

### How a new game gets its seeds (from the DLL source)

- `CvGame::init` seeds the two synchronous RNGs from pregame: `m_mapRand.init(mapRandomSeed % 73637381)`,
  `m_jonRand.init(syncRandomSeed % 52319761)`, then generates the map (`InitMap`), so the map script's `Map.Rand`
  draws from `m_mapRand`.
- `CvPreGame::mapRandomSeed()` is also read all game long by `CvGame::randCore` (the hash-based `urand*`
  functions): pinning must set the pregame seed, not only the RNG objects.
- Setters: `CvDllPreGame::setMapRandomSeed`/`setSyncRandomSeed` (exe), `CvDllNetInitInfo` (MP),
  `CvPreGame::loadFromIni` (reads `CONFIG` `SyncRandSeed`/`MapRandSeed`, and uses `timeGetTime()` for 0),
  `CvPreGame::resetGame` (sets both to 0). Which of these the exe calls when the setup screen starts a game is not
  visible in the DLL source: `HHSEEDS exeMap/exeSync` records the result. If a run with `config.ini` seeds shows
  them in `exeMap`/`exeSync`, `config.ini` works for menu-started games; the mechanism below works either way.
- `GAMEOPTION_NEW_RANDOM_SEED` only matters on load: `CvGame::Read` reseeds `m_jonRand` with `timeGetTime()`.

### Pinning the seeds of the next new game

At the start of `CvGame::init`, before anything consumes the seeds, and only when
`CvPreGame::gameStartType() == GAME_NEW` (a loaded game is never pinned; a pending request then stays pending):

1. **File (recommended for drivers):** `<cache folder>\HeadlessSeeds.txt`, where the cache folder is
   `gDLL->GetCacheFolderPath()` (normally `Documents\My Games\Sid Meier's Civilization 5\cache\`):

   ```
   map=123456
   sync=654321
   digest=1
   normalise=1
   ```

   All keys are optional: `map`/`sync` pin that seed; `digest=1` turns per-turn digest logging on from this game's
   first turn; `normalise` sets normalisation. The DLL reads and **deletes** the file at the next new game.
2. **Lua:** `Game.SetHeadlessPendingSeeds(map, sync)` (both), `Game.GetHeadlessPendingSeeds()` →
   `pending, map, sync`, `Game.ClearHeadlessPendingSeeds()`. Consumed by the next new game. This only helps if the
   `Game` table is available in the context that starts the game; whether the engine registers the DLL's Lua
   libraries in front-end contexts is not visible in the source. The file needs no Lua.

The file is also read, without being consumed, when the exe calls `CvPreGame::setGameStarted(true)` for a new
game, just before `onGameStarted` draws the random civilizations and city-states through `CvGame::randCore` (which
reads the pregame map seed). Without that the clock seed the engine sets would pick them. This logs
`HHSEEDS|point=gameStarted|source=file|exeMap=..|exeSync=..|map=..|sync=..` with the engine's own seeds; the
`gameInit` line that follows then shows the pinned values as `exeMap`/`exeSync`.

A file request wins over a Lua request. The result is in `HHSEEDS` (`source=file|lua|none|skipped`,
`pinnedMap`, `pinnedSync`, `error` for parse problems or a failed delete).

Driver procedure (`vpbench newgame --spec`): write `HeadlessSeeds.txt` with the spec's seeds and `digest=1` in the
game's cache folder, set up pregame as today, call `Events.SerialEventStartGame()`, then check `HHSEEDS` in
`HeadlessDigest.log` (`source=file`, `map`/`sync` as requested) before arming autoplay. The host sets the same
seeds through `CvDllPreGame` before `Init`.

### Other randomness and run-dependent inputs

- **Async RNG** (`GC.getASyncRand()`, "UiRng"): used by the DLL only for AI responses to human demands and for AI
  greeting/insult text (`CvDealAI`, `CvDiplomacyAI`). No effect in autoplay without humans. Logged in `HHRNG`.
- **`CoCreateGuid`**: game id and map GUID (normalised, no gameplay use).
- **Wall clock**: `m_uiStartTime` (exe), `NEW_RANDOM_SEED` on load, `loadFromIni` seed fallback; stacking
  diagnostics and the pathfinder statistics read clocks only for logs.
- **Frame-count dependence** (`m_iTurnSlice`, +1 per `CvGame::update`): the unit path cache is valid only within one
  slice (`CvUnit::HaveCachedPathTo`), `CvDealAI` and the culture influence-trend cache clear per slice, stuck AI units
  have their turn ended after 10 slices without moves (`CvGame::updateMoves`), and
  `calculateSyncChecksum` (MP only) uses it. A cache hit should equal a recomputation, so results should not depend
  on frame count, but the host's number of `update` calls per turn need not match the real game's; if a divergence
  appears, compare the AI phase where it starts with these.
- **Lua**: `math.random` in Communitu and Continental Drift is seeded from `Map.Rand`; DiploCorner (UI) only
  otherwise. `os.clock` only in Communitu's debug timing.
- **Heap addresses**: containers ordered by pointer (plan M5). The digest allocates memory while it runs, so a run
  with digest logging on and one with it off can differ only if results depend on heap addresses; A/A runs must
  use the same digest setting.
- **UI-thread calls** into the DLL while the game core runs (comment in `TContainer.h`): UI getters with side
  effects show up as digest differences.
- **Autosaves**: see the side-effect audit (exe-side consequences).

## Hook probe (D5)

`Game.HeadlessProbeHook(kind, name, ...)` calls `LuaSupport::CallHook`, `CallTestAll`, `CallTestAny` or
`CallAccumulator(int)` (`kind` = `"hook"`, `"testall"`, `"testany"`, `"accumulator"`) for event `name`, pushing
the extra arguments as integers, with the same initial value the DLL's own callers use (`false`, or `0` for the
accumulator). Returns `handled, value, hooksDisabled` (the last one is `MOD_API_DISABLE_LUA_HOOKS`).
`Game.HeadlessProbeHookInit(kind, name, init, ...)` is the same with a chosen initial value (boolean or integer),
to see whether the dispatcher overwrites it.

`tools/headless/hook-probe.lua` (run in `InGame` through FireTuner:
`python tools/civ5_tuner.py exec --context InGame --file tools/headless/hook-probe.lua`) checks that custom
`GameEvents` names can be indexed and given listeners (`pcall`), lists the members of an event object, then for each
kind runs: no listener; one listener returning true / false / nil / 5 / 0; two listeners (true+false, false+true,
true+nil, nil+false, 3+4, 3+true); a listener that raises (alone, before and after another); initial-value variants;
a never-indexed name; and a listener added then removed. Each case records `handled`, `value`, and which listeners
ran with which arguments (expect `7, 8, 9`), so short-circuiting and argument passing are visible. Listener errors
also appear in `Lua.log`. The probe never touches game state; the listeners use their own `HHProbe_*` names.

## Result neutrality

**Off (default):**

- Normalisation: `HH_DIGEST_NORM` evaluates `IsNormalisedWrite()` (false: `g_bNormalise && g_bWriting && thread`),
  so saves write the same bytes; cost is one branch per normalised field during saves only.
- Pregame: `saveSlotHints` and `writeArchive` take the original branch when no digest is being written.
- `CvGame::doTurn`: one bool test. `CvGame::update`: one bool test (after the first update).
- `CvGame::init`: reads pregame through side-effect-free accessors, runs read-only database queries, tries to open
  `<cache>\HeadlessSeeds.txt` (absent), reads RNG seed/call counters without drawing, and writes log files. No
  game or pregame state changes unless a pin is requested. Extra engine call: `GetCacheFolderPath` (new games only).
- First update: reads the FPU control words; logs.
- `DllMain`: stores the `timeBeginPeriod` result.

**On:**

- Per-turn digest: serializes through the audited write paths (side effects removed as listed), on the game core
  thread at a fixed point before any turn processing. It reads the save database file, queries the database
  read-only, allocates and frees memory, and writes the log. No events, no RNG draws, no engine calls besides
  `GetCacheFolderPath`.
- Seed pinning changes exactly what it should: the two pregame seeds of a new game, before their first use.
- Hook probe: runs Lua listeners the probe script registers on its own event names.

The main session should confirm on the real game (below).

## To test in the real game

1. Deploy, start a game normally (no seeds file): `HeadlessDigest.log` has `HHSEEDS source=none`, a complete
   `HHPREGAME` block and `HHRNG point=gameInit`; `HeadlessRuntime.log` has one `HHRUNTIME` line. Record the x87 word
   and MXCSR for H13.
2. Seeds: with `config.ini` `MapRandSeed`/`SyncRandSeed` set, does `exeMap`/`exeSync` show them for a
   `vpbench newgame`? Then with `HeadlessSeeds.txt`: `source=file`, the file deleted, the same map twice.
3. Front end: does `Game` exist in the `ModsSinglePlayer` (or setup) context? (`return type(Game)`)
4. A/A: two games from the same `HeadlessSeeds.txt` with `digest=1`, autoplay 100 turns, then
   `python tools/headless/hhdigest.py compare A.log B.log`. For a difference, `Game.DumpHeadlessState` at the same
   turn in both (autoplay paused) and diff the section files; check `HHDIGESTSIZE` first.
5. `python tools/headless/hhdigest.py verify DUMP` on one dump (cross-checks the hash implementation in-game).
6. Run `hook-probe.lua` and keep its JSON for the engine contract (H6).
7. Check whether autosaves call `WriteReplay` (D1 trace), and whether a run with digest logging off reaches the
   same final checkpoint as one with it on (same seeds).
