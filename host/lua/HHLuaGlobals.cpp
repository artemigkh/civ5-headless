#include "lua/HHLuaGlobals.h"
#include "lua/HHScriptSystem.h"
#include "setup/HHVfs.h"
#include "engine/HHRuntime.h"

namespace
{
	//--------------------------------------------------------------------------
	// Locale
	//--------------------------------------------------------------------------
	// Locale.Lookup(key, ...) / Locale.ConvertTextKey(key, ...): CvLocalization lookup with the
	// extra arguments pushed as {1}, {2}, ... Numbers that are integral are pushed as ints.
	int HHLuaLocaleLookup(lua_State* L)
	{
		const char* szKey = luaL_checkstring(L, 1);
		Localization::String str = Localization::Lookup(szKey);
		const int n = lua_gettop(L);
		for(int i = 2; i <= n; ++i)
		{
			switch(lua_type(L, i))
			{
			case LUA_TNUMBER:
			{
				const lua_Number d = lua_tonumber(L, i);
				if((lua_Number)(int)d == d)
					str.PushArgument((int)d);
				else
					str.PushArgument((double)d);
				break;
			}
			case LUA_TBOOLEAN:
				str.PushArgument(lua_toboolean(L, i) ? 1 : 0);
				break;
			case LUA_TSTRING:
			{
				size_t len = 0;
				const char* s = lua_tolstring(L, i, &len);
				str.PushArgument(s, len);
				break;
			}
			default:
				str.PushArgument("");
				break;
			}
		}
		size_t bytes = 0;
		const char* szText = str.toUTF8(bytes);
		if(szText)
			lua_pushlstring(L, szText, bytes);
		else
			lua_pushstring(L, szKey);
		return 1;
	}

	int HHLuaLocaleHasTextKey(lua_State* L)
	{
		const char* szKey = luaL_checkstring(L, 1);
		Localization::String str = Localization::Lookup(szKey);
		const char* szText = str.toUTF8();
		// ASSUMPTION: a missing key looks up to the key itself (or nothing).
		lua_pushboolean(L, szText && *szText && strcmp(szText, szKey) != 0);
		return 1;
	}

	//--------------------------------------------------------------------------
	// Modding
	//--------------------------------------------------------------------------
	HHVfs* GetVfs(lua_State* L)
	{
		return (HHVfs*)lua_touserdata(L, lua_upvalueindex(1));
	}

	// Modding.GetActivatedMods(): array of {ID = guid, Version = n}, in activation order.
	int HHLuaModdingGetActivatedMods(lua_State* L)
	{
		const std::vector<HHActivatedMod>& mods = GetVfs(L)->GetMods();
		lua_createtable(L, (int)mods.size(), 0);
		for(size_t i = 0; i < mods.size(); ++i)
		{
			lua_createtable(L, 0, 2);
			lua_pushstring(L, mods[i].id.c_str());
			lua_setfield(L, -2, "ID");
			lua_pushinteger(L, mods[i].version);
			lua_setfield(L, -2, "Version");
			lua_rawseti(L, -2, (int)i + 1);
		}
		return 1;
	}

	int HHLuaEntryPointIterator(lua_State* L)
	{
		// upvalue 1: array of entries, upvalue 2: next index
		const int i = (int)lua_tointeger(L, lua_upvalueindex(2));
		lua_rawgeti(L, lua_upvalueindex(1), i);
		if(lua_isnil(L, -1))
			return 1;
		lua_pushinteger(L, i + 1);
		lua_replace(L, lua_upvalueindex(2));
		return 1;
	}

	// Modding.GetActivatedModEntryPoints(type): iterator over {ModID, Version, Name,
	// Description, Type, File} of every activated mod, in activation order.
	int HHLuaModdingGetActivatedModEntryPoints(lua_State* L)
	{
		const char* szType = luaL_checkstring(L, 1);
		const std::vector<HHActivatedMod>& mods = GetVfs(L)->GetMods();
		lua_newtable(L);
		int n = 0;
		for(size_t i = 0; i < mods.size(); ++i)
			for(size_t j = 0; j < mods[i].entryPoints.size(); ++j)
			{
				const HHModEntryPoint& e = mods[i].entryPoints[j];
				if(e.type != szType)
					continue;
				lua_createtable(L, 0, 6);
				lua_pushstring(L, mods[i].id.c_str()); lua_setfield(L, -2, "ModID");
				lua_pushinteger(L, mods[i].version); lua_setfield(L, -2, "Version");
				lua_pushstring(L, e.name.c_str()); lua_setfield(L, -2, "Name");
				lua_pushstring(L, e.description.c_str()); lua_setfield(L, -2, "Description");
				lua_pushstring(L, e.type.c_str()); lua_setfield(L, -2, "Type");
				lua_pushstring(L, e.file.c_str()); lua_setfield(L, -2, "File");
				lua_rawseti(L, -2, ++n);
			}
		lua_pushinteger(L, 1);
		lua_pushcclosure(L, HHLuaEntryPointIterator, 2);
		return 1;
	}

	const HHActivatedMod* FindMod(lua_State* L, int iIdArg)
	{
		const char* szId = luaL_checkstring(L, iIdArg);
		const int iVersion = lua_isnumber(L, iIdArg + 1) ? (int)lua_tointeger(L, iIdArg + 1) : -1;
		const std::vector<HHActivatedMod>& mods = GetVfs(L)->GetMods();
		for(size_t i = 0; i < mods.size(); ++i)
			if(_stricmp(mods[i].id.c_str(), szId) == 0 && (iVersion < 0 || mods[i].version == iVersion))
				return &mods[i];
		return NULL;
	}

	// Modding.GetModProperty(id, version, name)
	int HHLuaModdingGetModProperty(lua_State* L)
	{
		const HHActivatedMod* pMod = FindMod(L, 1);
		const char* szName = luaL_checkstring(L, 3);
		if(pMod)
			for(size_t i = 0; i < pMod->properties.size(); ++i)
				if(pMod->properties[i].first == szName)
				{
					lua_pushstring(L, pMod->properties[i].second.c_str());
					return 1;
				}
		return 0;
	}

	// Modding.IsModActivated(id[, version])
	int HHLuaModdingIsModActivated(lua_State* L)
	{
		lua_pushboolean(L, FindMod(L, 1) != NULL);
		return 1;
	}

	// Modding.GetEvaluatedFilePath(id, version, file) -> {EvaluatedPath = absolute}
	int HHLuaModdingGetEvaluatedFilePath(lua_State* L)
	{
		const HHActivatedMod* pMod = FindMod(L, 1);
		const char* szFile = luaL_checkstring(L, 3);
		if(!pMod || pMod->folder.empty())
			return 0;
		std::string path = pMod->folder + "\\" + szFile;
		for(size_t i = 0; i < path.size(); ++i)
			if(path[i] == '/')
				path[i] = '\\';
		lua_createtable(L, 0, 1);
		lua_pushstring(L, path.c_str());
		lua_setfield(L, -2, "EvaluatedPath");
		return 1;
	}

	//--------------------------------------------------------------------------
	// PreGame (read-only subset over ICvPreGame1)
	//--------------------------------------------------------------------------
	ICvPreGame1* GetPreGame(lua_State* L)
	{
		return (ICvPreGame1*)lua_touserdata(L, lua_upvalueindex(1));
	}

	PlayerTypes ArgPlayer(lua_State* L)
	{
		return (PlayerTypes)luaL_checkint(L, 1);
	}

	void PushCvString(lua_State* L, const CvString& s)
	{
		lua_pushlstring(L, s.c_str(), s.size());
	}

#define HH_PREGAME_INT0(fn, expr) int fn(lua_State* L) { ICvPreGame1* p = GetPreGame(L); lua_pushinteger(L, (int)(expr)); return 1; }
#define HH_PREGAME_BOOL0(fn, expr) int fn(lua_State* L) { ICvPreGame1* p = GetPreGame(L); lua_pushboolean(L, (expr) ? 1 : 0); return 1; }
#define HH_PREGAME_INT1(fn, expr) int fn(lua_State* L) { ICvPreGame1* p = GetPreGame(L); PlayerTypes e = ArgPlayer(L); lua_pushinteger(L, (int)(expr)); return 1; }
#define HH_PREGAME_BOOL1(fn, expr) int fn(lua_State* L) { ICvPreGame1* p = GetPreGame(L); PlayerTypes e = ArgPlayer(L); lua_pushboolean(L, (expr) ? 1 : 0); return 1; }
#define HH_PREGAME_STR1(fn, expr) int fn(lua_State* L) { ICvPreGame1* p = GetPreGame(L); PlayerTypes e = ArgPlayer(L); PushCvString(L, expr); return 1; }

	HH_PREGAME_INT0(PGGetWorldSize, p->worldSize())
	HH_PREGAME_INT0(PGGetGameSpeed, p->gameSpeed())
	HH_PREGAME_INT0(PGGetEra, p->era())
	HH_PREGAME_INT0(PGGetNumMinorCivs, p->numMinorCivs())
	HH_PREGAME_INT0(PGGetMaxTurns, p->maxTurns())
	HH_PREGAME_INT0(PGGetGameType, p->gameType())
	HH_PREGAME_INT0(PGGetActivePlayer, p->activePlayer())
	HH_PREGAME_INT0(PGGetClimate, p->climate())
	HH_PREGAME_INT0(PGGetSeaLevel, p->seaLevel())
	HH_PREGAME_BOOL0(PGGetLoadWBScenario, p->loadWBScenario())
	HH_PREGAME_BOOL0(PGIsRandomMapScript, p->randomMapScript())
	HH_PREGAME_BOOL0(PGIsRandomWorldSize, p->randomWorldSize())
	HH_PREGAME_BOOL0(PGIsMultiplayerGame, p->isNetworkMultiplayerGame())
	HH_PREGAME_BOOL0(PGIsHotSeatGame, p->isHotSeatGame())
	HH_PREGAME_BOOL0(PGIsInternetGame, p->isInternetGame())
	HH_PREGAME_BOOL0(PGGameStarted, p->gameStarted())
	HH_PREGAME_INT1(PGGetCivilization, p->civilization(e))
	HH_PREGAME_INT1(PGGetLeaderType, p->leaderHead(e))
	HH_PREGAME_INT1(PGGetSlotStatus, p->slotStatus(e))
	HH_PREGAME_INT1(PGGetSlotClaim, p->slotClaim(e))
	HH_PREGAME_INT1(PGGetTeam, p->teamType(e))
	HH_PREGAME_INT1(PGGetHandicap, p->handicap(e))
	HH_PREGAME_INT1(PGGetCivilizationColor, p->playerColor(e))
	HH_PREGAME_INT1(PGGetMinorCivType, p->minorCivType(e))
	HH_PREGAME_BOOL1(PGIsHuman, p->isHuman(e))
	HH_PREGAME_BOOL1(PGIsMinorCiv, p->isMinorCiv(e))
	HH_PREGAME_STR1(PGGetLeaderName, p->leaderName(e))
	HH_PREGAME_STR1(PGGetCivilizationDescription, p->civilizationDescription(e))
	HH_PREGAME_STR1(PGGetCivilizationShortDescription, p->civilizationShortDescription(e))
	HH_PREGAME_STR1(PGGetCivilizationAdjective, p->civilizationAdjective(e))
	HH_PREGAME_STR1(PGGetNickName, p->nickname(e))

	int PGGetMapScript(lua_State* L) { PushCvString(L, GetPreGame(L)->mapScriptName()); return 1; }
	int PGIsVictory(lua_State* L) { lua_pushboolean(L, GetPreGame(L)->isVictory((VictoryTypes)luaL_checkint(L, 1)) ? 1 : 0); return 1; }

	int PGGetMapOption(lua_State* L)
	{
		const char* szName = luaL_checkstring(L, 1);
		int iValue = 0;
		if(GetPreGame(L)->GetMapOption(szName, iValue))
		{
			lua_pushinteger(L, iValue);
			return 1;
		}
		return 0;
	}

	int PGGetGameOption(lua_State* L)
	{
		int iValue = 0;
		bool bFound = lua_type(L, 1) == LUA_TNUMBER ? GetPreGame(L)->GetGameOption((GameOptionTypes)lua_tointeger(L, 1), iValue)
		                                            : GetPreGame(L)->GetGameOption(luaL_checkstring(L, 1), iValue);
		if(bFound)
		{
			lua_pushinteger(L, iValue);
			return 1;
		}
		return 0;
	}

	const luaL_Reg kPreGame[] =
	{
		{ "GetWorldSize", PGGetWorldSize },
		{ "GetGameSpeed", PGGetGameSpeed },
		{ "GetEra", PGGetEra },
		{ "GetNumMinorCivs", PGGetNumMinorCivs },
		{ "GetMaxTurns", PGGetMaxTurns },
		{ "GetGameType", PGGetGameType },
		{ "GetActivePlayer", PGGetActivePlayer },
		{ "GetClimate", PGGetClimate },
		{ "GetSeaLevel", PGGetSeaLevel },
		{ "GetLoadWBScenario", PGGetLoadWBScenario },
		{ "IsRandomMapScript", PGIsRandomMapScript },
		{ "IsRandomWorldSize", PGIsRandomWorldSize },
		{ "IsMultiplayerGame", PGIsMultiplayerGame },
		{ "IsHotSeatGame", PGIsHotSeatGame },
		{ "IsInternetGame", PGIsInternetGame },
		{ "GameStarted", PGGameStarted },
		{ "GetCivilization", PGGetCivilization },
		{ "GetLeaderType", PGGetLeaderType },
		{ "GetSlotStatus", PGGetSlotStatus },
		{ "GetSlotClaim", PGGetSlotClaim },
		{ "GetTeam", PGGetTeam },
		{ "GetHandicap", PGGetHandicap },
		{ "GetCivilizationColor", PGGetCivilizationColor },
		{ "GetMinorCivType", PGGetMinorCivType },
		{ "IsHuman", PGIsHuman },
		{ "IsMinorCiv", PGIsMinorCiv },
		{ "GetLeaderName", PGGetLeaderName },
		{ "GetCivilizationDescription", PGGetCivilizationDescription },
		{ "GetCivilizationShortDescription", PGGetCivilizationShortDescription },
		{ "GetCivilizationAdjective", PGGetCivilizationAdjective },
		{ "GetNickName", PGGetNickName },
		{ "GetMapScript", PGGetMapScript },
		{ "IsVictory", PGIsVictory },
		{ "GetMapOption", PGGetMapOption },
		{ "GetGameOption", PGGetGameOption },
		{ NULL, NULL }
	};

	void RegisterWithUpvalue(lua_State* L, const char* szTable, const luaL_Reg* pFuncs, void* pUpvalue)
	{
		lua_newtable(L);
		for(const luaL_Reg* r = pFuncs; r->name; ++r)
		{
			lua_pushlightuserdata(L, pUpvalue);
			lua_pushcclosure(L, r->func, 1);
			lua_setfield(L, -2, r->name);
		}
		lua_setglobal(L, szTable);
	}

	// Lua-side parts: Events/LuaEvents proxies, the simple Locale helpers.
	const char* kLuaPrelude =
		"local function eventTable(dispatch)\n"
		"  return setmetatable({}, {__index = function(t, name)\n"
		"    local listeners = {}\n"
		"    local ev = {\n"
		"      Add = function(f) listeners[#listeners + 1] = f end,\n"
		"      Remove = function(f) for i = #listeners, 1, -1 do if listeners[i] == f then table.remove(listeners, i) end end end,\n"
		"      RemoveAll = function() listeners = {} end,\n"
		"      Count = function() return #listeners end,\n"
		"    }\n"
		"    setmetatable(ev, {__call = function(self, ...)\n"
		"      if dispatch then for _, f in ipairs(listeners) do f(...) end end\n"
		"    end})\n"
		"    rawset(t, name, ev)\n"
		"    return ev\n"
		"  end})\n"
		"end\n"
		"-- Events: engine (UI/graphics) events; nothing listens headless, every member is a callable no-op.\n"
		"Events = eventTable(false)\n"
		"-- LuaEvents: script-to-script events; dispatched to listeners.\n"
		"LuaEvents = eventTable(true)\n"
		"MapModData = MapModData or {}\n"
		"-- Firaxis extensions of the standard libraries used by map scripts.\n"
		"-- table.fill(value, n) -> {value x n} (1-based); table.fill(t, value, n) fills t[1..n] and returns t.\n"
		"-- ASSUMPTION (trace): semantics inferred from the scripts (MapGenerator: 'incoming plot tables are indexed from 1').\n"
		"table.fill = table.fill or function(a, b, c)\n"
		"  if type(a) == 'table' and c ~= nil then for i = 1, c do a[i] = b end return a end\n"
		"  local t = {} for i = 1, b do t[i] = a end return t\n"
		"end\n"
		"math.clamp = math.clamp or function(x, lo, hi) if x < lo then return lo elseif x > hi then return hi end return x end\n"
		"-- DB.CreateQuery(sql) -> callable(...) returning the row iterator of DB.Query(sql, ...).\n"
		"DB.CreateQuery = DB.CreateQuery or function(sql) return function(...) return DB.Query(sql, ...) end end\n"
		"Locale.IsNilOrWhitespace = function(s) return s == nil or tostring(s):match('^%s*$') ~= nil end\n"
		"Locale.IsNilOrEmpty = function(s) return s == nil or s == '' end\n"
		"Locale.ToUpper = function(s) return string.upper(tostring(s)) end\n"
		"Locale.ToLower = function(s) return string.lower(tostring(s)) end\n"
		"Locale.Length = function(s) return string.len(tostring(s)) end\n"
		"Locale.Compare = function(a, b) if a == b then return 0 elseif a < b then return -1 else return 1 end end\n"
		"Locale.ToNumber = function(n, fmt) return tostring(n) end\n"
		"Locale.GetCurrentLanguage = function() return {Type = 'en_US'} end\n";
}

bool HHLuaRegisterEngineGlobals(HHScriptSystem& kScripts, HHVfs& kVfs, ICvPreGame1* pPreGame)
{
	lua_State* L = kScripts.GetMainState();

	lua_newtable(L);
	lua_pushcfunction(L, HHLuaLocaleLookup);
	lua_setfield(L, -2, "Lookup");
	lua_pushcfunction(L, HHLuaLocaleLookup);
	lua_setfield(L, -2, "ConvertTextKey");
	lua_pushcfunction(L, HHLuaLocaleHasTextKey);
	lua_setfield(L, -2, "HasTextKey");
	lua_setglobal(L, "Locale");

	static const luaL_Reg kModding[] =
	{
		{ "GetActivatedMods", HHLuaModdingGetActivatedMods },
		{ "GetActivatedModEntryPoints", HHLuaModdingGetActivatedModEntryPoints },
		{ "GetModProperty", HHLuaModdingGetModProperty },
		{ "IsModActivated", HHLuaModdingIsModActivated },
		{ "GetEvaluatedFilePath", HHLuaModdingGetEvaluatedFilePath },
		{ NULL, NULL }
	};
	RegisterWithUpvalue(L, "Modding", kModding, &kVfs);
	if(pPreGame)
		RegisterWithUpvalue(L, "PreGame", kPreGame, pPreGame);

	// IncludeFileList: every Lua file the VFS can reach (the winner per name), sorted by name.
	// ASSUMPTION (trace): the engine's list holds the full paths of every VFS Lua file.
	lua_getglobal(L, "IncludeFileList");
	if(lua_istable(L, -1))
	{
		std::vector<std::string> paths = kVfs.AllPaths();
		for(size_t i = 0; i < paths.size(); ++i)
		{
			lua_pushstring(L, paths[i].c_str());
			lua_rawseti(L, -2, (int)lua_objlen(L, -2) + 1);
		}
	}
	lua_pop(L, 1);

	return kScripts.RunString(L, kLuaPrelude, "=HHLuaGlobals");
}
