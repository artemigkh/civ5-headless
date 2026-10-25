# UI emulation profiles

The real game runs its UI: Lua contexts that react to game events, popups and every frame. Most UI code only reads
the game, but some of it changes game state: it rolls the synchronised random number generator, fills a lazy cache,
dismisses notifications, or answers a popup. The host does not run the game's UI screens. A **profile** does, for one
piece of UI code, the same calls at the same point, so that a host game stays identical to the real one.

The host also runs every activated mod's InGameUIAddin in a stub UI context (engine-contract.md, "UI contexts in the
host"); profiles are for the UI that is not an add-in (base screens and the mods' overrides of them) and for add-ins
whose effect depends on UI the host does not have (popups).

## Layout

    profiles/
      known-ui-files.json            UI files that need no profile (see "Unknown UI files")
      <name>/profile.json            the manifest
      <name>/<file>.lua              the emulation (optional)

The host loads the profiles folder given by `--profiles DIR`; by default the `profiles` folder next to
civ5headless.exe or up to four folders above it (the repository's). `--no-profiles` runs without any. The run report
(`<run>/host-report.json`, `profiles`) lists the selected profiles with the reason, the number of calls and failures,
and the profiles not selected with the reason.

## The manifest

```json
{
 "name": "eui-civ-ribbon",
 "description": "What the UI code does and why it matters.",
 "hook": "ui-frame",
 "lua": "civ-ribbon.lua",
 "order": 30,
 "select": [
  {"file": "NotificationPanel.lua", "sha256": ["56f5...", "18f8..."]},
  {"file": "NotificationPanel.lua", "contains": ["UpdateCivListNow", "CalculateGoldRate"]}
 ],
 "covers": [{"file": "NotificationPanel.lua", "methods": ["CalculateGoldRate"]}]
}
```

| Field | Meaning |
|---|---|
| `name` | Defaults to the folder name. |
| `description` | Shown in the run report. Say which file, which function, which game state. |
| `hook` | When the profile runs: `load-screen`, `notification-added`, `ui-frame` or `popup` (below). |
| `lua` | The emulation, relative to the profile folder. |
| `script` | A UI file of the game or a mod (a VFS name, e.g. `WhosWinningPopup.lua`) run in the profile's context before `lua`: the profile can then call the file's own functions. |
| `function` | The Lua function the hook calls. Defaults: `OnLoadScreen`, `OnNotificationAdded`, `OnUIFrame`, `OnPopup`. |
| `popupTypes` | For `popup`: `ButtonPopupTypes` names (resolved in the loaded DLL; numbers are accepted). |
| `staysUp` | For `popup`: the popup stays up (the human turn's unit cycle and end-of-turn test stop, as behind a real popup). A popup profile with `staysUp` and no Lua only keeps the popup up. |
| `group` | At most one selected profile per group: the strongest match, then the lowest `order`. |
| `order` | Run order within a hook (default 100), then the name. |
| `select` | Alternatives; the first that matches selects the profile. |
| `covers` | The UI files and methods the profile emulates: the hazard scan marks those calls as covered, and a covered file with the matched hash counts as known in the run report. |

### Selectors

Every condition a selector names must hold.

| Condition | Holds when |
|---|---|
| `file` | The VFS has the file (the winner: the highest tier, mods over DLC over base), or an activated mod's InGameUIAddin has a script of that name. The other file conditions test that file. |
| `source` | The file's tier: `base`, `dlc`, `mod` or `addin`. |
| `sha256` | The file's hash is one of these. Strength 3. |
| `contains` | The file contains every one of these strings. Strength 2. |
| `mod` | A mod with this id is activated. |
| `dbQuery` | This SQL returns at least one row on the game database (for example a table a mod adds). |
| `always` | `true`: always. |

Put the exact hashes first and a `contains` fallback after them: a new version of the mod still selects the profile,
and the report says the hash was not listed, so the profile can be checked against the new file.

## Hooks

The hooks follow the real game's UI timing (engine-contract.md sections 1 and 2):

| Hook | When | Function |
|---|---|---|
| `load-screen` | Once, after the game is initialised and `Game.SetPausePlayer` (the load screen), before the T000 checkpoint and the add-ins. | `OnLoadScreen()`; the return value is logged in the run's steps. |
| `notification-added` | On the UI frame after the DLL added a notification (`NotificationAdded`). | `OnNotificationAdded()` |
| `ui-frame` | Every update frame of the turn loop (not with `--no-ui-frame`). | `OnUIFrame()` |
| `popup` | On the UI frame after the DLL queued a popup of one of `popupTypes`. | `OnPopup(popupInfo)` with `Type`, `Data1`, `Data2`, `Data3`, `Flags`, `Option1`, `Option2`, `Text`; returns `shown` (true: the popup stays up) and an optional note for the log. |

Each profile runs in its own hidden UI context, like an add-in: the game's Lua API, `Controls` and `ContextPtr`
stubs, and the host's `UI.RemoveNotification` (the engine's dismiss: `MayUserDismissNotification`, then
`DismissNotification`). Globals persist between calls, so a profile can keep the UI's own state (for example the
WhosWinning list mode). Errors are counted as profile failures and listed with the Lua errors in the run report.

## Does a mod's UI code need a profile?

1. Run a short game with the mod set. The run report lists the UI files that are neither base game nor known
   (`uiFiles.unknown`: add-ins, overrides of base UI files, DLC UI such as EUI).
2. Scan them: `python -m civ5headless.hazards scan --report RUN/host-report.json` (add `--dll-source` with the
   DLL's sources to derive the method list from them, `--all` for calls that only reach a lazy cache). Each call to a
   state-changing method is listed with its function and what runs it: `load`, an event (`Events.X`,
   `GameEvents.X`, `LuaEvents.X`), a ContextPtr handler (`SetUpdate`: every frame while shown), a control callback,
   or `via` the function that calls it.
3. For each call decide whether it runs in an AI autoplay game without user input:
   - **No** (clicks, tooltips, screens autoplay never opens, input handlers): no profile. The trade screen's deal
     calls and the city screen's citizen changes are examples.
   - **Yes, and it does nothing in the host already**: an add-in's listener for an event the host fires runs in the
     host as it is (the host fires `SequenceGameInitComplete` and `LoadScreenClose`; `GameEvents` are the DLL's).
     Everything else (popups, `SetUpdate`, `NotificationAdded`, events the host does not fire) needs a profile.
   - Calls of kind `cache` change only a cache; they matter when the cache is saved or read by the AI before it is
     recomputed (the military might cache was such a case). Check the DLL source.
4. Write the profile: the same calls, in the same order, at the matching hook, reading the same game state. Copy the
   mod's code where possible, or run the mod's file itself with `script` and call its function.
5. Verify: the per-turn fingerprints (`probes/fingerprint.lua`) or digests of a host game and a real game must match
   (verification suite); a profile that is wrong shows up as a divergence a few turns after the UI code runs.
6. Files that need no profile go into `known-ui-files.json`: `python -m civ5headless.hazards known --report
   RUN/host-report.json --note "how they were checked" --write` adds the run's unknown files with their hashes and
   a hazard summary.

The hazard scan is a static check: it does not see calls made through a function stored under another name, and it
cannot tell whether a screen is shown. The comparison with the real game is the proof.

## Unknown UI files

`known-ui-files.json` holds `officialDlc` (DLC folders whose UI is the base game's) and `files`: `name`, `sha256`,
`source` and `note` of each UI file that needs no profile beyond the selected ones. The run report lists every other
UI file a mod or non-official DLC brings as unknown, with its path and hash, so a new mod version or a new mod is
visible before its games are trusted. Files covered by a selected profile (its matched file and hash) count as known.

## The profiles

| Profile | Hook | Emulates |
|---|---|---|
| `base-demographics` | load-screen | Demographics.lua `BuildTables` at context load (military might and the other demographics getters). |
| `stacking-observer-notification-aging` | notification-added | VP's EUI NotificationPanel.lua observer sweep: dismisses the active player's notifications older than `UIObserverNotificationLifetimeTurns`. |
| `eui-civ-ribbon` | ui-frame | EUI NotificationPanel.lua civ ribbon: `CalculateGoldRate` for the listed civilizations (a write in DLLs before the 2026 determinism fix). |
| `cp-city-event-popup` | popup | Community Patch CityEventPopup (`BUTTONPOPUP_MODDER_7`): the notification the add-in adds. |
| `vp-whos-winning` | popup | VP's WhosWinningPopup.lua: the synchronised random rolls and the scores of the list mode; stays up. |
| `base-whos-winning` | popup | The base WhosWinningPopup.lua, run as it is (`script`); same group as vp-whos-winning. |
| `base-great-person-reward` | popup | The great person reward popup stays up. |
