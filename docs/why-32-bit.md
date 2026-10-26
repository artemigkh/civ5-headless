# Why the host is 32-bit

`civ5headless.exe` is a 32-bit (x86) program, built with MSVC 2008 (VC9) like the game DLL. This is not a choice
that could easily go the other way: the host's job is to run the unchanged game DLL inside its own process, and
everything it loads is 32-bit. This page explains why, what a 64-bit host would take, and why it is not worth it.

## Why 32-bit

- **A Windows process can only load DLLs of its own bitness.** The host loads these into its own process, and every
  one of them is 32-bit (checked in the PE headers of a Steam install):

  | File | What it is |
  |---|---|
  | `CvGameCore_Expansion2.dll` | the game DLL: the stock one, Community Patch, Vox Populi or your own |
  | `CvGameDatabaseWin32Final Release.dll` | Firaxis's database layer (closed source) |
  | `CvLocalizationWin32Final Release.dll` | Firaxis's localization (closed source) |
  | `lua51_Win32.dll` | the game's Lua 5.1 |

  Civ V itself (`CivilizationV.exe`, `CivilizationV_DX11.exe`) is 32-bit only.
- **The host must use the DLL's compiler.** C++ objects such as `std::string`, `std::vector`, `CvString` and the
  FireWorks types cross the engine interfaces, so their layout has to match: VC9, 32-bit.
- **Memory is not a reason to switch.** The host links with `/LARGEADDRESSAWARE`, so on 64-bit Windows it can use
  4 GB. Measured peaks with Vox Populi:
  - Tiny games: about 350 MB.
  - A Standard game to turn 281: 442 MB.
  - The real game: 1.5–1.7 GB.
- **Parallelism is not either.** It comes from running many host processes at once (`c5h queue`, the verification
  suite), not from one large process.
- **Speed:** a 64-bit build might be somewhat faster per game (more registers), but it has not been measured. The
  32-bit host is already 7–22 times faster than the real game ([verification.md](verification.md)).

## What a 64-bit host would take

1. **A 64-bit build of every game DLL to be played.** Released DLL binaries (the ones users have installed) would
   not run in it.
   - Rebuilding is possible where the source is available: Vox Populi and Community Patch are open, and the Civ V
     SDK includes the stock DLL's source.
   - Porting the source means fixing pointer-to-integer casts (about 19 rough hits in a Vox Populi fork's DLL) and
     any inline assembly. In that fork the only inline assembly is in its headless digest additions.
2. **Replacements for the Firaxis DLLs, which exist only as 32-bit binaries.** The SDK has only their headers and
   32-bit import libraries.
   - The database and localization DLLs would have to be rewritten against their interfaces. The game DLL uses the
     database layer heavily, so this is the bulk of the work.
   - Lua 5.1 would need a 64-bit build that behaves like the game's copy.
3. **Host changes, the small part:**
   - 64-bit build flags and a 64-bit toolchain (`tools/build_host.py` links with `/MACHINE:X86` today);
   - rewriting the one 32-bit assembly file, `host/engine/HHInitLocks.asm` (a `__thiscall` export);
   - re-checking the 22 FireWorks exports the host implements for pointer sizes.
4. **The real cost: the games would stop matching the real game.**
   - 64-bit code always uses SSE2 floating point. A 32-bit DLL built with VC9's defaults uses the x87 unit instead:
     Vox Populi builds with `/fp:precise` and no `/arch`.
   - Game logic uses `float` and `double` widely (roughly 700 uses in a Vox Populi fork's DLL), so rounding would
     differ and games would drift away from the real game's after some turns.
   - `c5h verify` against the real game would then fail by design: only the host against itself could be checked.

## Conclusion

A 64-bit host would be weeks of work, mostly the database layer. It would also lose the host's main property: what
it plays is what the real game would play, turn for turn. The first real-game runs showed exactly that for Vox Populi
5.4.8, the stock DLL and a Vox Populi fork. A 64-bit build would only make sense as a separate simulator for DLLs
built from source, with no claim of matching the real game, and since memory is not a limit there is little to gain.
