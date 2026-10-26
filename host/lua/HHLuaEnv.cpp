#include "lua/HHLuaEnv.h"
#include "lua/HHScriptSystem.h"
#include "engine/HHRuntime.h"

namespace
{
	void BindLuaValue(lua_State* L, Database::Results* pResults, int iLuaIndex, int iBindIndex)
	{
		switch(lua_type(L, iLuaIndex))
		{
		case LUA_TNUMBER:
		{
			const lua_Number d = lua_tonumber(L, iLuaIndex);
			const int i = (int)d;
			if((lua_Number)i == d)
				pResults->Bind(iBindIndex, i);
			else
				pResults->Bind(iBindIndex, (double)d);
			break;
		}
		case LUA_TBOOLEAN:
			pResults->Bind(iBindIndex, lua_toboolean(L, iLuaIndex) ? 1 : 0);
			break;
		case LUA_TSTRING:
		{
			size_t len = 0;
			const char* s = lua_tolstring(L, iLuaIndex, &len);
			pResults->Bind(iBindIndex, s, (int)len, true);
			break;
		}
		default:
			pResults->BindNULL(iBindIndex);
			break;
		}
	}

	// Iterator returned by DB.Query: upvalue 1 is the query userdata (owns the statement),
	// upvalue 2 the Results* inside it.
	int HHLuaDBQueryStep(lua_State* L)
	{
		Database::Results* pResults = (Database::Results*)lua_touserdata(L, lua_upvalueindex(2));
		if(pResults && pResults->Step())
		{
			Database::Scripting::Lua::PushDatabaseRow(L, pResults);
			return 1;
		}
		return 0;
	}

	// DB.Query(sql, ...): Firaxis's PushDatabaseQuery prepares the statement and pushes a
	// userdata that owns it (not callable); the extra arguments are bound as parameters
	// 1..n and a row iterator is returned, so "for row in DB.Query(sql, ...)" works.
	int HHLuaDBQuery(lua_State* L)
	{
		Database::Connection* pDb = (Database::Connection*)lua_touserdata(L, lua_upvalueindex(1));
		const char* szSQL = luaL_checkstring(L, 1);
		const int nArgs = lua_gettop(L);
		Database::Results* pResults = Database::Scripting::Lua::PushDatabaseQuery(L, pDb, szSQL);
		if(!pResults)
			return luaL_error(L, "DB.Query: cannot prepare: %s", szSQL);
		for(int i = 2; i <= nArgs; ++i)
			BindLuaValue(L, pResults, i, i - 1);
		lua_pushlightuserdata(L, pResults);
		lua_pushcclosure(L, HHLuaDBQueryStep, 2);
		return 1;
	}

	void PushDefineValue(lua_State* L, Database::Results& kResults, int iColumn)
	{
		switch(kResults.ColumnType(iColumn))
		{
		case Database::COLTYPE_INT:
		case Database::COLTYPE_BOOL:
			lua_pushinteger(L, kResults.GetInt(iColumn));
			break;
		case Database::COLTYPE_FLOAT:
			lua_pushnumber(L, kResults.GetDouble(iColumn));
			break;
		case Database::COLTYPE_TEXT:
			lua_pushstring(L, kResults.GetText(iColumn));
			break;
		default:
			lua_pushnil(L);
			break;
		}
	}

	int s_iDefines = 0;

	struct RegisterArgs
	{
		ICvScriptSystemUtility1* pUtility;
		Database::Connection* pDb;
	};

	int HHLuaRegister(lua_State* L)
	{
		RegisterArgs* pArgs = (RegisterArgs*)lua_touserdata(L, 1);
		lua_settop(L, 0);

		// GameInfo: the database object (GameInfo.Units, GameInfo.Units(), GameInfo.Units[id]).
		Database::Scripting::Lua::PushDatabase(L, *pArgs->pDb);
		lua_setglobal(L, "GameInfo");

		// DB: Query plus the memory statistics functions.
		lua_newtable(L);
		lua_pushlightuserdata(L, pArgs->pDb);
		lua_pushcclosure(L, HHLuaDBQuery, 1);
		lua_setfield(L, -2, "Query");
		lua_pushcfunction(L, Database::Scripting::Lua::lGetMemoryUsage);
		lua_setfield(L, -2, "GetMemoryUsage");
		lua_pushcfunction(L, Database::Scripting::Lua::lCollectMemoryUsage);
		lua_setfield(L, -2, "CollectMemoryUsage");
		lua_setglobal(L, "DB");

		// GameDefines: Defines.Name -> Defines.Value.
		lua_newtable(L);
		Database::Results kDefines;
		s_iDefines = 0;
		if(pArgs->pDb->Execute(kDefines, "SELECT Name, Value FROM Defines"))
		{
			while(kDefines.Step())
			{
				const char* szName = kDefines.GetText(0);
				if(!szName)
					continue;
				PushDefineValue(L, kDefines, 1);
				lua_setfield(L, -2, szName);
				++s_iDefines;
			}
		}
		lua_setglobal(L, "GameDefines");

		// The DLL's libraries (enums, GameInfoActions/Types, Game, Map, Players, Teams, ...).
		pArgs->pUtility->RegisterScriptLibraries(L);
		return 0;
	}

	// The save data (Modding.OpenSaveData): one connection for the run, opened on first use, after the DLL has
	// created the file for a new game (CvGame::init) or restored it from a save (CvGame::readSaveGameDB).
	Database::Connection* SaveDatabase()
	{
		static Database::Connection* s_pDb = NULL;
		if(!s_pDb)
		{
			const std::string path = HHGetPaths().cache + "Civ5SavedGameDatabase.db";
			Database::Connection* pDb = new Database::Connection();
			if(!pDb->Open(path.c_str(), Database::OPEN_READWRITE | Database::OPEN_CREATE | Database::OPEN_FULLMUTEX))
			{
				HHLogError("Modding.OpenSaveData: cannot open %s", path.c_str());
				delete pDb;
				return NULL;
			}
			pDb->Execute("CREATE TABLE IF NOT EXISTS SimpleValues(Name TEXT Primary Key, Value VARIANT)");
			s_pDb = pDb;
		}
		return s_pDb;
	}

	// Query(sql, ...) of the save data: DB.Query on it. Mods call it as a plain function (TableSaverLoader:
	// local DBQuery = Modding.OpenSaveData().Query) or as a method.
	int HHLuaSaveDataQuery(lua_State* L)
	{
		if(lua_istable(L, 1))
			lua_remove(L, 1);
		return HHLuaDBQuery(L);
	}

	// GetValue(name) / SetValue(name, value) of the save data: the SimpleValues table.
	int HHLuaSaveDataGetValue(lua_State* L)
	{
		Database::Connection* pDb = (Database::Connection*)lua_touserdata(L, lua_upvalueindex(1));
		const char* szName = luaL_checkstring(L, lua_istable(L, 1) ? 2 : 1);
		Database::Results r;
		if(pDb && pDb->Execute(r, "SELECT Value FROM SimpleValues WHERE Name = ?"))
		{
			r.Bind(1, szName);
			if(r.Step())
			{
				PushDefineValue(L, r, 0);
				return 1;
			}
		}
		lua_pushnil(L);
		return 1;
	}

	int HHLuaSaveDataSetValue(lua_State* L)
	{
		Database::Connection* pDb = (Database::Connection*)lua_touserdata(L, lua_upvalueindex(1));
		const int iName = lua_istable(L, 1) ? 2 : 1;
		const char* szName = luaL_checkstring(L, iName);
		Database::Results r;
		if(pDb && pDb->Execute(r, "INSERT OR REPLACE INTO SimpleValues(Name, Value) VALUES(?, ?)"))
		{
			r.Bind(1, szName);
			BindLuaValue(L, &r, iName + 1, 2);
			r.Step();
		}
		return 0;
	}

	int QueryInt(Database::Connection& kDb, const char* szSQL, const char* szBind = NULL)
	{
		Database::Results kResults;
		if(!kDb.Execute(kResults, szSQL))
			return -1;
		if(szBind)
			kResults.Bind(1, szBind);
		return kResults.Step() ? kResults.GetInt(0) : -1;
	}

	const char* kSelfTest =
		"local r = {}\n"
		"local n = 0\n"
		"for row in GameInfo.Units() do n = n + 1 end\n"
		"r.UnitsIterated = n\n"
		"local warrior = GameInfo.Units.UNIT_WARRIOR\n"
		"r.WarriorID = warrior and warrior.ID or -1\n"
		"local byId = GameInfo.Units[r.WarriorID]\n"
		"r.WarriorTypeById = byId and byId.Type or ''\n"
		"r.WarriorCombat = warrior and warrior.Combat or -1\n"
		"local q = -1\n"
		"for row in DB.Query('SELECT COUNT(*) AS N FROM Units') do q = row.N end\n"
		"r.DBQueryUnits = q\n"
		"local t = 0\n"
		"for row in DB.Query('SELECT Type FROM Technologies WHERE Era = ?', 'ERA_ANCIENT') do t = t + 1 end\n"
		"r.DBQueryAncientTechs = t\n"
		"local filtered = 0\n"
		"for row in GameInfo.Buildings{BuildingClass = 'BUILDINGCLASS_MONUMENT'} do filtered = filtered + 1 end\n"
		"r.MonumentBuildings = filtered\n"
		"r.MaxMajorCivs = GameDefines.MAX_MAJOR_CIVS or -1\n"
		"r.MoveDenominator = GameDefines.MOVE_DENOMINATOR or -1\n"
		"r.HasGame = type(Game) == 'table'\n"
		"r.HasMap = type(Map) == 'table'\n"
		"r.HasPlayers = type(Players) == 'table'\n"
		"r.GameInfoTypesWarrior = (GameInfoTypes and GameInfoTypes.UNIT_WARRIOR) or -1\n"
		"r.StateName = StateName or ''\n"
		"print('self-test: units', n, 'warrior', r.WarriorID, 'defines MAX_MAJOR_CIVS', r.MaxMajorCivs)\n"
		"HeadlessSelfTest = r\n";

	int GetIntField(lua_State* L, int t, const char* szField)
	{
		lua_getfield(L, t, szField);
		int v = lua_isnumber(L, -1) ? (int)lua_tointeger(L, -1) : (lua_isboolean(L, -1) ? lua_toboolean(L, -1) : -999999);
		lua_pop(L, 1);
		return v;
	}

	std::string GetStringField(lua_State* L, int t, const char* szField)
	{
		lua_getfield(L, t, szField);
		const char* s = lua_isstring(L, -1) ? lua_tostring(L, -1) : NULL;
		std::string v = s ? s : "";
		lua_pop(L, 1);
		return v;
	}

	void Check(HHSelfTestResult& r, bool bOk, const std::string& strText)
	{
		r.checks.push_back(std::string(bOk ? "ok: " : "FAIL: ") + strText);
		if(!bOk)
			r.bPassed = false;
		HHLog("  self-test %s %s", bOk ? "ok  " : "FAIL", strText.c_str());
	}
}

int HHLuaModdingOpenSaveData(lua_State* L)
{
	Database::Connection* pDb = SaveDatabase();
	if(!pDb)
	{
		lua_pushnil(L);
		return 1;
	}
	lua_createtable(L, 0, 3);
	lua_pushlightuserdata(L, pDb);
	lua_pushcclosure(L, HHLuaSaveDataQuery, 1);
	lua_setfield(L, -2, "Query");
	lua_pushlightuserdata(L, pDb);
	lua_pushcclosure(L, HHLuaSaveDataGetValue, 1);
	lua_setfield(L, -2, "GetValue");
	lua_pushlightuserdata(L, pDb);
	lua_pushcclosure(L, HHLuaSaveDataSetValue, 1);
	lua_setfield(L, -2, "SetValue");
	return 1;
}

bool HHLuaRegisterGameData(HHScriptSystem& kScripts, ICvScriptSystemUtility1* pUtility, Database::Connection& kDb)
{
	lua_State* L = kScripts.GetMainState();
	RegisterArgs args = { pUtility, &kDb };
	if(lua_cpcall(L, HHLuaRegister, &args) != 0)
	{
		HHLogError("Lua registration failed: %s", lua_tostring(L, -1));
		lua_pop(L, 1);
		return false;
	}
	HHLog("Lua: GameInfo, DB, GameDefines (%d defines) and the DLL's script libraries registered", s_iDefines);
	return true;
}

HHSelfTestResult HHLuaSelfTest(HHScriptSystem& kScripts, Database::Connection& kDb, int iDllUnitInfos)
{
	HHSelfTestResult r;
	r.bPassed = true;
	lua_State* T = kScripts.CreateLuaThread("HeadlessSelfTest");
	if(!kScripts.RunString(T, kSelfTest, "=HeadlessSelfTest"))
	{
		Check(r, false, "self-test script ran without errors");
		kScripts.FreeLuaThread(T);
		return r;
	}
	lua_getglobal(T, "HeadlessSelfTest");
	if(!lua_istable(T, -1))
	{
		lua_pop(T, 1);
		Check(r, false, "self-test result table exists");
		kScripts.FreeLuaThread(T);
		return r;
	}
	const int t = lua_gettop(T);

	const int iUnits = QueryInt(kDb, "SELECT COUNT(*) FROM Units");
	const int iWarrior = QueryInt(kDb, "SELECT ID FROM Units WHERE Type = 'UNIT_WARRIOR'");
	const int iWarriorCombat = QueryInt(kDb, "SELECT Combat FROM Units WHERE Type = 'UNIT_WARRIOR'");
	const int iAncient = QueryInt(kDb, "SELECT COUNT(*) FROM Technologies WHERE Era = ?", "ERA_ANCIENT");
	const int iMonuments = QueryInt(kDb, "SELECT COUNT(*) FROM Buildings WHERE BuildingClass = ?", "BUILDINGCLASS_MONUMENT");
	const int iMaxMajor = QueryInt(kDb, "SELECT Value FROM Defines WHERE Name = 'MAX_MAJOR_CIVS'");
	const int iMoveDenom = QueryInt(kDb, "SELECT Value FROM Defines WHERE Name = 'MOVE_DENOMINATOR'");

	const int luaUnits = GetIntField(T, t, "UnitsIterated");
	Check(r, luaUnits == iUnits, HHFormat("GameInfo.Units() iterates %d rows; SQL COUNT(*) %d", luaUnits, iUnits));
	Check(r, luaUnits == iDllUnitInfos, HHFormat("GameInfo.Units() rows %d = DLL GetNumUnitInfos %d", luaUnits, iDllUnitInfos));
	Check(r, GetIntField(T, t, "WarriorID") == iWarrior && iWarrior >= 0,
	      HHFormat("GameInfo.Units.UNIT_WARRIOR.ID %d; SQL %d", GetIntField(T, t, "WarriorID"), iWarrior));
	Check(r, GetStringField(T, t, "WarriorTypeById") == "UNIT_WARRIOR",
	      HHFormat("GameInfo.Units[%d].Type = '%s'", iWarrior, GetStringField(T, t, "WarriorTypeById").c_str()));
	Check(r, GetIntField(T, t, "WarriorCombat") == iWarriorCombat,
	      HHFormat("UNIT_WARRIOR.Combat %d; SQL %d", GetIntField(T, t, "WarriorCombat"), iWarriorCombat));
	Check(r, GetIntField(T, t, "DBQueryUnits") == iUnits,
	      HHFormat("DB.Query COUNT(*) Units %d; SQL %d", GetIntField(T, t, "DBQueryUnits"), iUnits));
	Check(r, GetIntField(T, t, "DBQueryAncientTechs") == iAncient && iAncient > 0,
	      HHFormat("DB.Query with bound argument: %d ancient techs; SQL %d", GetIntField(T, t, "DBQueryAncientTechs"), iAncient));
	Check(r, GetIntField(T, t, "MonumentBuildings") == iMonuments && iMonuments > 0,
	      HHFormat("GameInfo.Buildings{BuildingClass=...} %d rows; SQL %d", GetIntField(T, t, "MonumentBuildings"), iMonuments));
	Check(r, GetIntField(T, t, "MaxMajorCivs") == iMaxMajor && iMaxMajor > 0,
	      HHFormat("GameDefines.MAX_MAJOR_CIVS %d; Defines %d", GetIntField(T, t, "MaxMajorCivs"), iMaxMajor));
	Check(r, GetIntField(T, t, "MoveDenominator") == iMoveDenom && iMoveDenom > 0,
	      HHFormat("GameDefines.MOVE_DENOMINATOR %d; Defines %d", GetIntField(T, t, "MoveDenominator"), iMoveDenom));
	Check(r, GetIntField(T, t, "HasGame") == 1, "DLL library table Game exists");
	Check(r, GetIntField(T, t, "HasMap") == 1, "DLL library table Map exists");
	Check(r, GetIntField(T, t, "HasPlayers") == 1, "DLL library table Players exists");
	Check(r, GetStringField(T, t, "StateName") == "HeadlessSelfTest", "thread environment StateName");
	const int iTypes = GetIntField(T, t, "GameInfoTypesWarrior");
	HHLog("  self-test info GameInfoTypes.UNIT_WARRIOR = %d (informational)", iTypes);
	lua_pop(T, 1);
	kScripts.FreeLuaThread(T);
	return r;
}
