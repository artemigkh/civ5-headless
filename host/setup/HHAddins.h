// The activated mods' InGameUIAddin scripts, each in a stub UI context of its own (plan C.1).
//
// In the game, InGame.lua loads every InGameUIAddin entry point with ContextPtr:LoadNewContext(path without
// extension): the context's XML (if any) and its Lua file. Child <LuaContext> elements of the XML are contexts of
// their own. Whatever the scripts register then works as in the game: GameEvents listeners run when the DLL calls
// the hooks, LuaEvents dispatch between scripts, Events listeners are kept and run only for the engine events the
// host emulates (HHFireUIEvent). A script that fails in the stub context is logged and the game goes on.
#pragma once
#include "HHCommon.h"

class HHScriptSystem;
class HHUserInterface;

struct HHAddinContext
{
	std::string mod;       // mod name
	std::string entry;     // entry point file as the modinfo names it
	std::string context;   // context name (the file name without extension, or the LuaContext ID)
	std::string parent;    // parent context of a <LuaContext> child; empty for an entry point
	std::string path;      // Lua file run; empty for an XML-only context
	std::string sha256;
	std::string status;    // run, failed, skipped, xml-only, missing
	std::string error;
	bool hidden;
	HHAddinContext() : hidden(false) {}
};

// The engine functions the stub UI contexts can call for real: UI.RemoveNotification (the notification panel's
// right-click dismiss: MayUserDismissNotification, then DismissNotification, for a notification the panel shows).
void HHRegisterUIBindings(HHScriptSystem& kScripts, ICvGame1* pGame, ICvPreGame1* pPreGame, HHUserInterface* pUI);

// Loads every InGameUIAddin of the activated mods in activation and entry order. skip: file names (with or without
// extension, case-insensitive) not to run. Returns the contexts in load order.
std::vector<HHAddinContext> HHLoadUIAddins(HHScriptSystem& kScripts, const std::vector<std::string>& skip);

// The Lua file of the activated mods' InGameUIAddin entry points named strName (with or without ".lua"; the
// entry's file or its .lua sibling); strMod gets the mod's name. Empty when no entry point has it.
std::string HHFindAddinScript(const std::string& strName, std::string& strMod);

// Fires an engine event (Events.<name>) to the listeners the stub contexts registered; szArgs is a Lua argument
// list ("" for none). Returns the number of listeners called.
int HHFireUIEvent(HHScriptSystem& kScripts, const char* szEvent, const std::string& strArgs);
