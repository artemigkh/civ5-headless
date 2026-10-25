# Civilization V SDK subset

The headers and import libraries `civ5headless.exe` compiles and links against, and nothing else: the engine
interfaces the game DLL calls (`CvGameCoreDLLUtil`), the game database and localization libraries, the FireWorks
types that cross those interfaces, and the Lua 5.1 headers.

## Where it comes from

The files are copied unchanged from the Community Patch / Vox Populi DLL repository
([LoneGazebo/Community-Patch-DLL](https://github.com/LoneGazebo/Community-Patch-DLL)), which redistributes the Firaxis
Civilization V SDK DLL sources under the GNU GPL v3 (see that repository's `License.rtf`). The copy was taken from the
fork `ruskyandrei/Community-Patch-DLL` at commit `df9d682d4` (2026-10-25).

- Firaxis' copyright notices stay in the headers that carry them.
- The Lua headers keep Lua's own copyright notice (MIT licence) at the end of `lua.h`.
- `CvGameCoreDLLUtil/include/CustomModsGlobal.h` is Vox Populi's file. It only holds commented-out options, so these
  headers describe the SDK's 22 major civs. DLLs built with more (the 43-civ variants) keep the same engine
  interfaces; the host must take the major civ count from the loaded game, never from these headers.

## Updating

The list is what the compiler reports with `/showIncludes` for every host source, plus the three import libraries
named in `tools/build_host.py`. When the host starts including another SDK header, copy it here from the same
source and keep the folder layout.

| Folder | Contents |
|---|---|
| `CvGameCoreDLLUtil/include` | Engine interfaces (`ICvDLLUtility.h`, `ICvDLLUserInterface.h`, `ICvDLLScriptSystem.h`, `CvDllInterfaces.h`), enums and structs |
| `CvGameDatabase/include`, `lib` | Game database classes; import library for `CvGameDatabaseWin32Final Release.dll` |
| `CvLocalization/include`, `lib` | Localization; import library for `CvLocalizationWin32Final Release.dll` |
| `FirePlace/include/FireWorks` | FireWorks types (strings, streams, allocators, file interfaces) |
| `ThirdPartyLibs/Lua51/include`, `lib` | Lua 5.1 headers; import library for the game's `lua51_Win32.dll` |
