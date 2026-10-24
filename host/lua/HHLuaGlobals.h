// Engine-provided Lua globals that map scripts and gameplay scripts expect (H7):
// Locale (CvLocalization), Modding (the run's copy of the mods database), Events/LuaEvents,
// a shared MapModData, a read-only PreGame subset and IncludeFileList (every VFS Lua file).
// The DLL's own libraries (Game, Map, Players, ...) come from RegisterScriptLibraries.
#pragma once
#include "HHCommon.h"

class HHScriptSystem;
class HHVfs;

// Registers everything on the main state's globals. pPreGame may be NULL (boot).
bool HHLuaRegisterEngineGlobals(HHScriptSystem& kScripts, HHVfs& kVfs, ICvPreGame1* pPreGame);
