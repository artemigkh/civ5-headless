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

// A stub UI context (HHLuaGlobals.cpp kUIContextLua): a new Lua thread named strName whose environment has the
// UI-only globals (ContextPtr, Controls, UI, UIManager, ...). NULL on failure. The caller keeps the thread for as
// long as its functions can be called (listeners close over its environment).
lua_State* HHLuaCreateUIContext(HHScriptSystem& kScripts, const std::string& strName, bool bHidden);
