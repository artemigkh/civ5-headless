// civ5headless.exe builddb: the database builder (plan section 4.5, milestone M4).
//
//   civ5headless.exe builddb --game-dir <path> --plan <plan.txt> --out <built.db>
//                            [--dll <CvGameCore_Expansion2.dll>] [--run <dir>]
//
// The plan is written by work/headless/build_db.py, which resolves the activated mods, their
// order and their files. One step per line, fields separated by tabs, '#' starts a comment:
//
//   snapshot  <db>                 copy the DLC snapshot to --out and open it (first step)
//   phase     <name>               label for the following steps in the report
//   mod       <id> <version> <name>  following steps belong to this mod (IsModActivated too)
//   attach    <db> <schema>        ATTACH DATABASE (the text database Language_* resolves to)
//   detach    <schema>
//   xml       <file>               Database::XMLSerializer::Load (one transaction per file)
//   sql       <file>               Database::Connection::ExecuteMultiple on the whole file
//   missing   <file>               an UpdateDatabase file that does not exist (logged)
//   vfs       <name> <file>        include() resolution for map scripts (lower-case file name)
//   mapscript <file> <FileName>    run GetMapScriptInfo, insert MapScripts, MapScriptOptions,
//                                  MapScriptOptionPossibleValues rows under FileName
//   postprocess                    load the game DLL and run PerformDatabasePostProcessing
//
// Errors inside mod files are logged (Logs\Database.log, as the engine does) and the build
// continues; the report (builddb-report.json in the run folder) lists them per step.
#include "setup/HHDbBuilder.h"
#include "engine/HHRuntime.h"
#include "engine/HHLogFiles.h"
#include "engine/HHEngineServices.h"
#include "lua/HHScriptSystem.h"

void HHExportsInit();
void HHExportsCheck();

namespace
{
	const char* kBuildUsage =
		"usage: civ5headless.exe builddb --game-dir <path> --plan <plan.txt> --out <built.db> [options]\n"
		"  --dll <path>   game DLL for the postprocess step (PerformDatabasePostProcessing)\n"
		"  --run <dir>    folder for Logs\\ and builddb-report.json (default: <out>.build\\)\n"
		"  --loc-db <db>  localization database for the DLL during postprocess (default: an empty one with en_US)\n"
		"  The plan is written by work/headless/build_db.py; see Civ5Headless/setup/HHDbBuilder.cpp.\n";

	struct BuildOptions
	{
		std::string gameDir, plan, out, run, dll, locDb;
	};

	struct PlanLine
	{
		int line;
		std::vector<std::string> f;
	};

	struct StepResult
	{
		int line;
		std::string kind, path, mod, phase;
		bool ok;
		double seconds;
		std::vector<std::string> errors;
		std::string note;
		StepResult() : line(0), ok(true), seconds(0) {}
	};

	// Database messages go to Logs\Database.log like the engine's; errors are also kept for the
	// current step's report entry.
	class BuilderLogger : public Database::IDatabaseLogger
	{
	public:
		BuilderLogger() : m_pCurrent(NULL), m_iErrors(0) {}
		virtual void Log(const char* szMessage, LogTypes eType)
		{
			const char* szText = szMessage ? szMessage : "";
			FILogFile* pLog = HHLogFileMgr::Get().GetLog("Database.log", 0);
			pLog->Msg("%s%s", eType == TYPE_ERROR ? "" : (eType == TYPE_WARNING ? "WARNING: " : ""), szText);
			if(eType == TYPE_ERROR)
			{
				++m_iErrors;
				if(m_pCurrent && m_pCurrent->errors.size() < 50)
					m_pCurrent->errors.push_back(szText);
			}
		}
		StepResult* m_pCurrent;
		int m_iErrors;
	};

	std::string JsonEscape(const std::string& s)
	{
		std::string out;
		for(size_t i = 0; i < s.size(); ++i)
		{
			const unsigned char c = (unsigned char)s[i];
			switch(c)
			{
			case '"': out += "\\\""; break;
			case '\\': out += "\\\\"; break;
			case '\n': out += "\\n"; break;
			case '\r': out += "\\r"; break;
			case '\t': out += "\\t"; break;
			default:
				if(c < 0x20)
					out += HHFormat("\\u%04x", c);
				else
					out += (char)c;
			}
		}
		return out;
	}

	std::string StripSlash(std::string s)
	{
		while(!s.empty() && (s[s.size() - 1] == '\\' || s[s.size() - 1] == '/'))
			s.erase(s.size() - 1);
		return s;
	}

	std::string BaseName(const std::string& s)
	{
		size_t slash = s.find_last_of("\\/");
		return slash == std::string::npos ? s : s.substr(slash + 1);
	}

	bool ReadFileBytes(const std::string& strPath, std::string& strOut)
	{
		HANDLE h = CreateFileW(HHWiden(strPath).c_str(), GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
		if(h == INVALID_HANDLE_VALUE)
			return false;
		LARGE_INTEGER size;
		GetFileSizeEx(h, &size);
		strOut.resize((size_t)size.QuadPart);
		DWORD n = 0;
		BOOL ok = strOut.empty() ? TRUE : ReadFile(h, &strOut[0], (DWORD)strOut.size(), &n, NULL);
		CloseHandle(h);
		return ok && n == strOut.size();
	}

	bool ParseBuildArgs(int argc, wchar_t** argv, BuildOptions& o)
	{
		for(int i = 2; i < argc; ++i)
		{
			const std::string a = HHNarrow(argv[i]);
			if(i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", a.c_str()); return false; }
			const std::string v = HHNarrow(argv[i + 1]);
			++i;
			if(a == "--game-dir") o.gameDir = StripSlash(v);
			else if(a == "--plan") o.plan = v;
			else if(a == "--out") o.out = v;
			else if(a == "--run") o.run = StripSlash(v);
			else if(a == "--dll") o.dll = v;
			else if(a == "--loc-db") o.locDb = HHFullPath(v);
			else { fprintf(stderr, "unknown option %s\n", a.c_str()); return false; }
		}
		if(o.gameDir.empty() || o.plan.empty() || o.out.empty())
		{
			fprintf(stderr, "--game-dir, --plan and --out are required\n");
			return false;
		}
		o.gameDir = HHFullPath(o.gameDir);
		o.plan = HHFullPath(o.plan);
		o.out = HHFullPath(o.out);
		if(o.run.empty())
			o.run = o.out + ".build";
		o.run = HHFullPath(o.run);
		if(!o.dll.empty())
			o.dll = HHFullPath(o.dll);
		return true;
	}

	bool ReadPlan(const std::string& strPath, std::vector<PlanLine>& lines)
	{
		std::string text;
		if(!ReadFileBytes(strPath, text))
			return false;
		if(text.size() >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB && (unsigned char)text[2] == 0xBF)
			text.erase(0, 3);
		size_t pos = 0;
		int iLine = 0;
		while(pos <= text.size())
		{
			size_t end = text.find('\n', pos);
			if(end == std::string::npos)
				end = text.size();
			std::string line = text.substr(pos, end - pos);
			pos = end + 1;
			++iLine;
			if(!line.empty() && line[line.size() - 1] == '\r')
				line.erase(line.size() - 1);
			if(line.empty() || line[0] == '#')
				continue;
			PlanLine p;
			p.line = iLine;
			size_t start = 0;
			for(;;)
			{
				size_t tab = line.find('\t', start);
				p.f.push_back(line.substr(start, tab == std::string::npos ? std::string::npos : tab - start));
				if(tab == std::string::npos)
					break;
				start = tab + 1;
			}
			lines.push_back(p);
		}
		return true;
	}

	// SQL text for a literal ('...' with quotes doubled).
	std::string SqlQuote(const std::string& s)
	{
		std::string out = "'";
		for(size_t i = 0; i < s.size(); ++i)
		{
			if(s[i] == '\'')
				out += '\'';
			out += s[i];
		}
		return out + "'";
	}

	//--------------------------------------------------------------------------
	// Map scripts: GetMapScriptInfo in a fresh Lua state, as the front end registers them.
	//--------------------------------------------------------------------------
	std::map<std::string, std::string> s_vfs; // lower-case file name -> file

	int MsPrint(lua_State* L)
	{
		std::string line;
		const int n = lua_gettop(L);
		lua_getglobal(L, "tostring");
		for(int i = 1; i <= n; ++i)
		{
			lua_pushvalue(L, -1);
			lua_pushvalue(L, i);
			lua_call(L, 1, 1);
			const char* s = lua_tostring(L, -1);
			if(i > 1)
				line += '\t';
			line += s ? s : "?";
			lua_pop(L, 1);
		}
		lua_pop(L, 1);
		HHLogFileMgr::Get().GetLog("Lua.log", 0)->Msg("MapScripts: %s", line.c_str());
		return 0;
	}

	// include(name): the VFS entry for the file name (mods' imported files override the game's).
	// Returns a table of the files it loaded, empty when none matched.
	int MsInclude(lua_State* L)
	{
		std::string name = luaL_checkstring(L, 1);
		std::string key = HHLower(BaseName(name));
		if(key.find('.') == std::string::npos)
			key += ".lua";
		std::map<std::string, std::string>::const_iterator it = s_vfs.find(key);
		if(it == s_vfs.end())
		{
			HHLogFileMgr::Get().GetLog("Lua.log", 0)->Msg("MapScripts: include(%s): not found", name.c_str());
			lua_newtable(L);
			return 1;
		}
		std::string text;
		if(!ReadFileBytes(it->second, text))
			return luaL_error(L, "include(%s): cannot read %s", name.c_str(), it->second.c_str());
		const std::string chunk = "@" + it->second;
		if(luaL_loadbuffer(L, text.c_str(), text.size(), chunk.c_str()) != 0)
			return lua_error(L);
		lua_call(L, 0, 0);
		// The engine's include returns the list of files it loaded (CP's CPK checks #result == 1).
		lua_newtable(L);
		lua_pushstring(L, it->second.c_str());
		lua_rawseti(L, -2, 1);
		return 1;
	}

	// DB.Query(sql, ...) -> row iterator, as in the host's game Lua environment (HHLuaEnv).
	int MsQueryStep(lua_State* L)
	{
		Database::Results* pResults = (Database::Results*)lua_touserdata(L, lua_upvalueindex(2));
		if(pResults && pResults->Step())
		{
			Database::Scripting::Lua::PushDatabaseRow(L, pResults);
			return 1;
		}
		return 0;
	}

	int MsQuery(lua_State* L)
	{
		Database::Connection* pDb = (Database::Connection*)lua_touserdata(L, lua_upvalueindex(1));
		const char* szSQL = luaL_checkstring(L, 1);
		const int nArgs = lua_gettop(L);
		Database::Results* pResults = Database::Scripting::Lua::PushDatabaseQuery(L, pDb, szSQL);
		if(!pResults)
			return luaL_error(L, "DB.Query: cannot prepare: %s", szSQL);
		for(int i = 2; i <= nArgs; ++i)
		{
			switch(lua_type(L, i))
			{
			case LUA_TNUMBER:
			{
				const lua_Number d = lua_tonumber(L, i);
				if((lua_Number)(int)d == d) pResults->Bind(i - 1, (int)d); else pResults->Bind(i - 1, (double)d);
				break;
			}
			case LUA_TBOOLEAN: pResults->Bind(i - 1, lua_toboolean(L, i) ? 1 : 0); break;
			case LUA_TSTRING:
			{
				size_t len = 0;
				const char* sz = lua_tolstring(L, i, &len);
				pResults->Bind(i - 1, sz, (int)len, true);
				break;
			}
			default: pResults->BindNULL(i - 1); break;
			}
		}
		lua_pushlightuserdata(L, pResults);
		lua_pushcclosure(L, MsQueryStep, 2);
		return 1;
	}

	int MsTraceback(lua_State* L)
	{
		if(!lua_isstring(L, 1))
			return 1;
		lua_getglobal(L, "debug");
		if(!lua_istable(L, -1)) { lua_pop(L, 1); return 1; }
		lua_getfield(L, -1, "traceback");
		if(!lua_isfunction(L, -1)) { lua_pop(L, 2); return 1; }
		lua_pushvalue(L, 1);
		lua_pushinteger(L, 2);
		lua_call(L, 2, 1);
		return 1;
	}

	bool MsCall(lua_State* L, int nArgs, int nRet, std::string& err)
	{
		const int base = lua_gettop(L) - nArgs;
		lua_pushcfunction(L, MsTraceback);
		lua_insert(L, base);
		const int rc = lua_pcall(L, nArgs, nRet, base);
		lua_remove(L, base);
		if(rc != 0)
		{
			const char* sz = lua_tostring(L, -1);
			err = sz ? sz : "(no message)";
			lua_pop(L, 1);
			return false;
		}
		return true;
	}

	// A Lua field converted the way it is bound into SQLite.
	struct SqlValue
	{
		enum Type { NIL, INT, REAL, TEXT } type;
		int i;
		double d;
		std::string s;
		SqlValue() : type(NIL), i(0), d(0) {}
	};

	SqlValue ReadField(lua_State* L, int t, const char* szField)
	{
		SqlValue v;
		lua_getfield(L, t, szField);
		switch(lua_type(L, -1))
		{
		case LUA_TBOOLEAN:
			v.type = SqlValue::INT;
			v.i = lua_toboolean(L, -1) ? 1 : 0;
			break;
		case LUA_TNUMBER:
		{
			const lua_Number d = lua_tonumber(L, -1);
			if((lua_Number)(int)d == d) { v.type = SqlValue::INT; v.i = (int)d; }
			else { v.type = SqlValue::REAL; v.d = d; }
			break;
		}
		case LUA_TSTRING:
			v.type = SqlValue::TEXT;
			v.s = lua_tostring(L, -1);
			break;
		default:
			break;
		}
		lua_pop(L, 1);
		return v;
	}

	SqlValue TextValue(const std::string& s)
	{
		SqlValue v;
		v.type = SqlValue::TEXT;
		v.s = s;
		return v;
	}

	SqlValue IntValue(int i)
	{
		SqlValue v;
		v.type = SqlValue::INT;
		v.i = i;
		return v;
	}

	// INSERT INTO table(columns given) VALUES(...): columns whose value is nil are left out, so
	// the table's defaults apply.
	bool InsertRow(Database::Connection& db, const char* szTable, const std::vector<std::pair<std::string, SqlValue> >& cols, std::string& err)
	{
		std::string names, marks;
		std::vector<const SqlValue*> values;
		for(size_t i = 0; i < cols.size(); ++i)
		{
			if(cols[i].second.type == SqlValue::NIL)
				continue;
			if(!names.empty()) { names += ", "; marks += ", "; }
			names += cols[i].first;
			marks += "?";
			values.push_back(&cols[i].second);
		}
		const std::string sql = HHFormat("INSERT INTO %s(%s) VALUES(%s)", szTable, names.c_str(), marks.c_str());
		Database::Results r;
		if(!db.Execute(r, sql.c_str()))
		{
			err = HHFormat("cannot prepare %s: %s", sql.c_str(), db.ErrorMessage());
			return false;
		}
		for(size_t i = 0; i < values.size(); ++i)
		{
			const SqlValue& v = *values[i];
			const int idx = (int)i + 1;
			if(v.type == SqlValue::INT) r.Bind(idx, v.i);
			else if(v.type == SqlValue::REAL) r.Bind(idx, v.d);
			else r.Bind(idx, v.s.c_str(), (int)v.s.size(), true);
		}
		if(!r.Execute())
		{
			err = HHFormat("%s: %s", sql.c_str(), db.ErrorMessage());
			return false;
		}
		return true;
	}

	bool RegisterMapScript(Database::Connection& db, const std::string& strFile, const std::string& strFileName, std::string& err)
	{
		std::string text;
		if(!ReadFileBytes(strFile, text))
		{
			err = "cannot read " + strFile;
			return false;
		}
		lua_State* L = luaL_newstate();
		luaL_openlibs(L);
		HHScriptSystem::InstallEngineIpairs(L);
		lua_pushcfunction(L, MsPrint);
		lua_setglobal(L, "print");
		lua_pushcfunction(L, MsInclude);
		lua_setglobal(L, "include");
		Database::Scripting::Lua::PushDatabase(L, db);
		lua_setglobal(L, "GameInfo");
		// What the shared map includes (CP/VP AssignStartingPlots and friends) touch at load time
		// in the front end: GameDefines, MapModData and Locale. Locale functions return their
		// first argument (text keys stay keys; nothing registered depends on translated text).
		lua_newtable(L);
		{
			Database::Results kDefines;
			if(db.Execute(kDefines, "SELECT Name, Value FROM Defines"))
			{
				while(kDefines.Step())
				{
					const char* szName = kDefines.GetText(0);
					if(!szName)
						continue;
					switch(kDefines.ColumnType(1))
					{
					case Database::COLTYPE_INT:
					case Database::COLTYPE_BOOL: lua_pushinteger(L, kDefines.GetInt(1)); break;
					case Database::COLTYPE_FLOAT: lua_pushnumber(L, kDefines.GetDouble(1)); break;
					case Database::COLTYPE_TEXT: lua_pushstring(L, kDefines.GetText(1)); break;
					default: lua_pushnil(L); break;
					}
					lua_setfield(L, -2, szName);
				}
			}
		}
		lua_setglobal(L, "GameDefines");
		lua_newtable(L);
		lua_pushlightuserdata(L, &db);
		lua_pushcclosure(L, MsQuery, 1);
		lua_setfield(L, -2, "Query");
		lua_setglobal(L, "DB");
		lua_newtable(L);
		lua_setglobal(L, "MapModData");
		if(luaL_dostring(L, "DB.CreateQuery = function(sql) return function(...) return DB.Query(sql, ...) end end") != 0)
			lua_pop(L, 1);
		// Locale.Lookup / ConvertTextKey read the text the mods added so far (the attached text
		// database, see build_db.py); other Locale functions and unknown keys return the key.
		if(luaL_dostring(L,
			"local function lookup(key) "
			"  if type(key) ~= 'string' then return key end "
			"  local ok, text = pcall(function() "
			"    for row in DB.Query('SELECT Text FROM Language_en_US WHERE Tag = ?', key) do return row.Text end "
			"  end) "
			"  if ok and text then return text end "
			"  return key "
			"end "
			"Locale = setmetatable({Lookup = lookup, ConvertTextKey = lookup}, "
			"  {__index = function(t, k) return function(s) return s end end})") != 0)
			lua_pop(L, 1);

		bool bOk = false;
		const std::string chunk = "@" + strFile;
		if(luaL_loadbuffer(L, text.c_str(), text.size(), chunk.c_str()) != 0)
		{
			err = lua_tostring(L, -1) ? lua_tostring(L, -1) : "syntax error";
			lua_close(L);
			return false;
		}
		if(!MsCall(L, 0, 0, err))
		{
			lua_close(L);
			return false;
		}
		lua_getglobal(L, "GetMapScriptInfo");
		if(!lua_isfunction(L, -1))
		{
			err = "no GetMapScriptInfo";
			lua_close(L);
			return false;
		}
		if(!MsCall(L, 0, 1, err))
		{
			lua_close(L);
			return false;
		}
		if(!lua_istable(L, -1))
		{
			err = "GetMapScriptInfo did not return a table";
			lua_close(L);
			return false;
		}
		const int info = lua_gettop(L);
		std::vector<std::pair<std::string, SqlValue> > row;
		row.push_back(std::make_pair(std::string("FileName"), TextValue(strFileName)));
		const char* kScriptFields[] = { "Name", "Description", "IsAdvancedMap", "SupportsSinglePlayer", "SupportsMultiplayer",
		                                "DefaultCityStates", "Hidden", "IconIndex", "IconAtlas", "FolderType" };
		for(size_t i = 0; i < sizeof(kScriptFields) / sizeof(kScriptFields[0]); ++i)
			row.push_back(std::make_pair(std::string(kScriptFields[i]), ReadField(L, info, kScriptFields[i])));
		// The engine's default for a missing IsAdvancedMap is true (the table's DEFAULT is 0):
		// every VP script without the field is stored with 1.
		if(row[3].second.type == SqlValue::NIL)
			row[3].second = IntValue(1);
		// The script table names the folder "Folder" (EMP scripts, China); the column is FolderType.
		if(row[10].second.type == SqlValue::NIL)
			row[10].second = ReadField(L, info, "Folder");
		bOk = InsertRow(db, "MapScripts", row, err);

		lua_getfield(L, info, "CustomOptions");
		if(bOk && lua_istable(L, -1))
		{
			const int options = lua_gettop(L);
			const int nOptions = (int)lua_objlen(L, options);
			for(int iOpt = 1; bOk && iOpt <= nOptions; ++iOpt)
			{
				lua_rawgeti(L, options, iOpt);
				if(!lua_istable(L, -1))
				{
					lua_pop(L, 1);
					continue;
				}
				const int opt = lua_gettop(L);
				const std::string optionId = HHFormat("%d", iOpt);
				std::vector<std::pair<std::string, SqlValue> > o;
				o.push_back(std::make_pair(std::string("FileName"), TextValue(strFileName)));
				o.push_back(std::make_pair(std::string("OptionID"), TextValue(optionId)));
				const char* kOptionFields[] = { "Name", "Description", "ReadOnly", "Hidden", "DefaultValue", "SortPriority" };
				for(size_t i = 0; i < sizeof(kOptionFields) / sizeof(kOptionFields[0]); ++i)
					o.push_back(std::make_pair(std::string(kOptionFields[i]), ReadField(L, opt, kOptionFields[i])));
				// A missing SortPriority is stored as 0 (base Ice_Age.lua's landmass option).
				if(o[7].second.type == SqlValue::NIL)
					o[7].second = IntValue(0);
				bOk = InsertRow(db, "MapScriptOptions", o, err);

				lua_getfield(L, opt, "Values");
				if(bOk && lua_istable(L, -1))
				{
					const int values = lua_gettop(L);
					const int nValues = (int)lua_objlen(L, values);
					for(int iVal = 1; bOk && iVal <= nValues; ++iVal)
					{
						lua_rawgeti(L, values, iVal);
						SqlValue name, desc;
						if(lua_isstring(L, -1))
							name = TextValue(lua_tostring(L, -1));
						else if(lua_istable(L, -1))
						{
							// {"TXT_KEY_NAME", "TXT_KEY_HELP"} or {Name = ..., Description = ...}
							const int t = lua_gettop(L);
							lua_rawgeti(L, t, 1);
							if(lua_isstring(L, -1))
								name = TextValue(lua_tostring(L, -1));
							lua_pop(L, 1);
							lua_rawgeti(L, t, 2);
							if(lua_isstring(L, -1))
								desc = TextValue(lua_tostring(L, -1));
							lua_pop(L, 1);
							if(name.type == SqlValue::NIL)
								name = ReadField(L, t, "Name");
							if(desc.type == SqlValue::NIL)
								desc = ReadField(L, t, "Description");
						}
						lua_pop(L, 1);
						std::vector<std::pair<std::string, SqlValue> > v;
						v.push_back(std::make_pair(std::string("FileName"), TextValue(strFileName)));
						v.push_back(std::make_pair(std::string("OptionID"), TextValue(optionId)));
						v.push_back(std::make_pair(std::string("Name"), name));
						v.push_back(std::make_pair(std::string("Description"), desc));
						v.push_back(std::make_pair(std::string("Value"), IntValue(iVal)));
						v.push_back(std::make_pair(std::string("SortIndex"), IntValue(iVal)));
						bOk = InsertRow(db, "MapScriptOptionPossibleValues", v, err);
					}
				}
				lua_pop(L, 2); // Values, option
			}
		}
		lua_pop(L, 1); // CustomOptions
		lua_close(L);
		return bOk;
	}

	//--------------------------------------------------------------------------
	// Post-processing: the game DLL's PerformDatabasePostProcessing on the built database
	// (ID remapping, PostDefines, ResourceUsage, hard-coded defines), as at game start.
	//--------------------------------------------------------------------------
	// The localization the DLL's Init may need: the stock DLL caches the game data inside ICvGameContext1::Init, and
	// that looks text up. --loc-db gives a localization database; without it an empty one (the game's schema, en_US
	// and no text) in the run folder. Returns the connection to close after the DLL is unloaded, or NULL.
	Database::Connection* InitBuildLocalization(const BuildOptions& o)
	{
		std::string path = o.locDb;
		if(path.empty())
		{
			path = o.run + "\\localization-empty.db";
			DeleteFileW(HHWiden(path).c_str());
			Database::Connection kNew;
			const char* szSchema =
				"CREATE TABLE Languages(\"ID\" INTEGER PRIMARY KEY AUTOINCREMENT, \"Type\" TEXT NOT NULL UNIQUE, \"Name\" TEXT NOT NULL,"
				" \"TableName\" TEXT NOT NULL, \"TagColumnName\" TEXT DEFAULT \"Tag\", \"TextColumnName\" TEXT DEFAULT \"Text\","
				" \"PluralityColumnName\" TEXT DEFAULT \"Plurality\", \"GenderColumnName\" TEXT DEFAULT \"Gender\", \"PluralRule\" INTEGER DEFAULT 1,"
				" \"UseExtendedFont\" INTEGER DEFAULT 0, \"FontName\" TEXT DEFAULT \"MS PGothic\", \"FontWidthScale\" FLOAT DEFAULT 0.4,"
				" \"FontHeightScale\" FLOAT DEFAULT 0.8);\n"
				"CREATE TABLE LocalizedText(\"Language\" TEXT, \"Tag\" TEXT, \"Text\" TEXT, \"Gender\" TEXT, \"Plurality\" TEXT, PRIMARY KEY(Language, Tag));\n"
				"CREATE TABLE LanguagePriorities(\"LanguageSet\" TEXT, \"Language\" TEXT, \"Priority\" INT, PRIMARY KEY(LanguageSet, Language));\n"
				"CREATE VIEW Language_en_US AS SELECT Tag, Text, Gender, Plurality FROM LocalizedText WHERE Language = 'en_US';\n"
				"INSERT INTO Languages VALUES(0, 'en_US', 'English', 'Language_en_US', 'Tag', 'Text', 'Plurality', 'Gender', 2, 0, 'MS PGothic', 0.4, 0.8);\n"
				"INSERT INTO LanguagePriorities VALUES('en_US', 'en_US', 100);\n";
			if(!kNew.Open(path.c_str(), Database::OPEN_READWRITE | Database::OPEN_CREATE) || !kNew.ExecuteMultiple(szSchema))
			{
				HHLogError("cannot create %s", path.c_str());
				return NULL;
			}
			kNew.Close();
		}
		Database::Connection* pLoc = new Database::Connection();
		if(!pLoc->Open(path.c_str(), Database::OPEN_READWRITE))
		{
			HHLogError("cannot open localization database %s", path.c_str());
			delete pLoc;
			return NULL;
		}
		const std::wstring icu = HHWiden(o.gameDir + "\\Locale\\icudt44l.dat");
		if(!Localization::Initialize(icu.c_str(), *pLoc, "Languages", "en_US", false))
		{
			HHLogError("Localization::Initialize failed (%s)", path.c_str());
			pLoc->Close();
			delete pLoc;
			return NULL;
		}
		HHLog("localization: %s", path.c_str());
		return pLoc;
	}

	bool RunPostProcessing(const BuildOptions& o, Database::Connection& db, std::string& err)
	{
		if(o.dll.empty())
		{
			err = "postprocess needs --dll";
			return false;
		}
		Database::Connection* pLoc = InitBuildLocalization(o);
		HHScriptSystem* pScripts = new HHScriptSystem();
		HHEngineUtility* pEngine = new HHEngineUtility(pScripts);
		HHUserInterface* pUI = new HHUserInterface();
		HMODULE hGame = LoadLibraryExW(HHWiden(o.dll).c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
		if(!hGame)
		{
			err = HHFormat("cannot load %s (error %lu)", o.dll.c_str(), GetLastError());
			return false;
		}
		typedef ICvGameContext1* (*PFNGetContext)();
		PFNGetContext pfnGetContext = (PFNGetContext)GetProcAddress(hGame, "DllGetGameContext");
		ICvGameContext1* pContext = pfnGetContext ? pfnGetContext() : NULL;
		if(!pContext || !pContext->SetDLLIFace(pEngine))
		{
			err = "DllGetGameContext/SetDLLIFace failed";
			return false;
		}
		ICvGameContext2* pContext2 = pContext->QueryInterface<ICvGameContext2>();
		if(pContext2)
			pContext2->SetEngineUserInterface(pUI);
		pContext->SetGameDatabase(&db);
		HHSetPhase("init");
		pContext->Init();
		ICvDLLDatabaseUtility1* pDbUtil = pContext->GetDatabaseLoadUtility();
		bool bOk = false;
		if(pDbUtil)
		{
			HHSetPhase("post-processing");
			bOk = pDbUtil->PerformDatabasePostProcessing();
			if(!bOk)
				err = "PerformDatabasePostProcessing returned false";
		}
		else
			err = "GetDatabaseLoadUtility returned NULL";
		HHSetPhase("shutdown");
		pScripts->Shutdown();
		if(pDbUtil)
			pDbUtil->Destroy();
		pContext->Uninit();
		pContext->SetGameDatabase(NULL);
		HHExportsCheck();
		pContext->SetDLLIFace(NULL);
		FreeLibrary(hGame);
		if(pLoc)
		{
			Localization::Shutdown();
			pLoc->Close();
			delete pLoc;
		}
		// pEngine and pUI stay alive, as in boot.
		UNUSED_VARIABLE(pEngine);
		UNUSED_VARIABLE(pUI);
		return bOk;
	}

	void WriteReport(const std::string& strPath, const BuildOptions& o, const std::vector<StepResult>& steps,
	                 const std::string& status, const std::string& error, double seconds, int iDbErrors)
	{
		FILE* f = _wfopen(HHWiden(strPath).c_str(), L"w");
		if(!f)
			return;
		int nFailed = 0;
		for(size_t i = 0; i < steps.size(); ++i)
			if(!steps[i].ok)
				++nFailed;
		fprintf(f, "{\n");
		fprintf(f, "  \"status\": \"%s\",\n", JsonEscape(status).c_str());
		fprintf(f, "  \"error\": \"%s\",\n", JsonEscape(error).c_str());
		fprintf(f, "  \"plan\": \"%s\",\n", JsonEscape(o.plan).c_str());
		fprintf(f, "  \"out\": \"%s\",\n", JsonEscape(o.out).c_str());
		fprintf(f, "  \"dll\": \"%s\",\n", JsonEscape(o.dll).c_str());
		fprintf(f, "  \"seconds\": %.3f,\n", seconds);
		fprintf(f, "  \"database_errors_logged\": %d,\n", iDbErrors);
		fprintf(f, "  \"steps_failed\": %d,\n", nFailed);
		fprintf(f, "  \"steps\": [\n");
		for(size_t i = 0; i < steps.size(); ++i)
		{
			const StepResult& s = steps[i];
			fprintf(f, "    {\"line\": %d, \"kind\": \"%s\", \"phase\": \"%s\", \"mod\": \"%s\", \"path\": \"%s\", \"ok\": %s, \"seconds\": %.4f",
			        s.line, s.kind.c_str(), JsonEscape(s.phase).c_str(), JsonEscape(s.mod).c_str(), JsonEscape(s.path).c_str(),
			        s.ok ? "true" : "false", s.seconds);
			if(!s.note.empty())
				fprintf(f, ", \"note\": \"%s\"", JsonEscape(s.note).c_str());
			if(!s.errors.empty())
			{
				fprintf(f, ", \"errors\": [");
				for(size_t e = 0; e < s.errors.size(); ++e)
					fprintf(f, "%s\"%s\"", e ? ", " : "", JsonEscape(s.errors[e]).c_str());
				fprintf(f, "]");
			}
			fprintf(f, "}%s\n", i + 1 < steps.size() ? "," : "");
		}
		fprintf(f, "  ]\n}\n");
		fclose(f);
	}
}

int HHBuildDbMain(int argc, wchar_t** argv)
{
	BuildOptions o;
	if(!ParseBuildArgs(argc, argv, o))
	{
		fputs(kBuildUsage, stderr);
		return 2;
	}
	const double t0 = HHSeconds();
	HHOptions& ho = HHGetOptions();
	ho.command = "builddb";
	ho.gameDir = o.gameDir;
	ho.dllPath = o.dll;
	ho.outDir = o.run;
	HHPaths& p = HHGetPaths();
	p.run = o.run + "\\";
	p.logs = p.run + "Logs\\";
	p.cache = p.run + "cache\\";
	p.db = p.run + "db\\";
	if(!HHEnsureDirectory(p.logs) || !HHEnsureDirectory(p.cache) || !HHEnsureDirectory(p.db) || !HHEnsureDirectory(p.run + "crashlogs"))
	{
		fprintf(stderr, "cannot create the run folder %s\n", p.run.c_str());
		return 2;
	}
	FILE* pMarker = _wfopen(HHWiden(p.run + "crashlogs\\nopopups.please").c_str(), L"w");
	if(pMarker)
		fclose(pMarker);
	HHLogOpen(p.logs);
	HHLogFileMgr::Get().SetFolder(p.logs);
	SetCurrentDirectoryW(HHWiden(p.run).c_str());
	const std::string reportPath = p.run + "builddb-report.json";
	HHLog("civ5headless builddb");
	HHLog("  game dir  %s", o.gameDir.c_str());
	HHLog("  plan      %s", o.plan.c_str());
	HHLog("  out       %s", o.out.c_str());
	HHLog("  dll       %s", o.dll.empty() ? "(none)" : o.dll.c_str());
	HHLog("  run       %s", p.run.c_str());

	std::vector<StepResult> steps;
	std::vector<PlanLine> plan;
	if(!ReadPlan(o.plan, plan) || plan.empty())
	{
		HHLogError("cannot read the plan %s", o.plan.c_str());
		WriteReport(reportPath, o, steps, "failed", "cannot read the plan", HHSeconds() - t0, 0);
		return 2;
	}
	if(plan[0].f[0] != "snapshot" || plan[0].f.size() < 2)
	{
		HHLogError("the plan must start with a snapshot step");
		WriteReport(reportPath, o, steps, "failed", "plan does not start with snapshot", HHSeconds() - t0, 0);
		return 2;
	}
	// Every mod line activates the mod for IsModActivated (the DLL's post-processing and
	// custom mod options read it).
	for(size_t i = 0; i < plan.size(); ++i)
	{
		if(plan[i].f[0] == "mod" && plan[i].f.size() >= 3)
		{
			HHModRef m;
			m.id = plan[i].f[1];
			m.version = atoi(plan[i].f[2].c_str());
			ho.mods.push_back(m);
		}
		else if(plan[i].f[0] == "vfs" && plan[i].f.size() >= 3)
			s_vfs[HHLower(plan[i].f[1])] = plan[i].f[2];
	}

	HHSetPhase("load");
	HHExportsInit();
	SetDllDirectoryW(HHWiden(o.gameDir).c_str());
	const char* kFiraxis[] = { "CvGameDatabaseWin32Final Release.dll", "CvLocalizationWin32Final Release.dll", "lua51_Win32.dll" };
	for(size_t i = 0; i < 3; ++i)
	{
		const std::string path = o.gameDir + "\\" + kFiraxis[i];
		if(!LoadLibraryExW(HHWiden(path).c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH))
		{
			HHLogError("cannot load %s (error %lu)", path.c_str(), GetLastError());
			WriteReport(reportPath, o, steps, "failed", "cannot load the Firaxis DLLs", HHSeconds() - t0, 0);
			return 2;
		}
	}

	HHSetPhase("snapshot");
	const std::string snapshot = HHFullPath(plan[0].f[1]);
	DeleteFileW(HHWiden(o.out + "-journal").c_str());
	if(!CopyFileW(HHWiden(snapshot).c_str(), HHWiden(o.out).c_str(), FALSE))
	{
		HHLogError("cannot copy %s to %s (error %lu)", snapshot.c_str(), o.out.c_str(), GetLastError());
		WriteReport(reportPath, o, steps, "failed", "cannot copy the snapshot", HHSeconds() - t0, 0);
		return 2;
	}
	SetFileAttributesW(HHWiden(o.out).c_str(), FILE_ATTRIBUTE_NORMAL);
	BuilderLogger* pLogger = new BuilderLogger(); // the connection may own it (auto_ptr)
	Database::Connection* pDb = new Database::Connection();
	pDb->SetLogger(pLogger);
	if(!pDb->Open(o.out.c_str(), Database::OPEN_READWRITE))
	{
		HHLogError("cannot open %s: %s", o.out.c_str(), pDb->ErrorMessage());
		WriteReport(reportPath, o, steps, "failed", "cannot open the output database", HHSeconds() - t0, 0);
		return 2;
	}
	// Build-time durability is not needed: the file is rebuilt from scratch on failure.
	pDb->Execute("PRAGMA synchronous = OFF");
	pDb->Execute("PRAGMA journal_mode = MEMORY");
	HHLog("copied %s -> %s", snapshot.c_str(), o.out.c_str());

	std::string phase = "builder", mod;
	std::string fatal;
	int nXml = 0, nSql = 0, nMapScripts = 0, nFailed = 0;
	for(size_t i = 1; i < plan.size() && fatal.empty(); ++i)
	{
		const PlanLine& pl = plan[i];
		const std::string& kind = pl.f[0];
		if(kind == "vfs")
			continue;
		if(kind == "phase")
		{
			phase = pl.f.size() > 1 ? pl.f[1] : "";
			mod.clear();
			continue;
		}
		if(kind == "mod")
		{
			mod = pl.f.size() > 3 ? pl.f[3] : (pl.f.size() > 1 ? pl.f[1] : "");
			phase = "mods";
			HHLog("mod %s (%s v%s)", mod.c_str(), pl.f.size() > 1 ? pl.f[1].c_str() : "", pl.f.size() > 2 ? pl.f[2].c_str() : "");
			continue;
		}
		StepResult s;
		s.line = pl.line;
		s.kind = kind;
		s.phase = phase;
		s.mod = mod;
		s.path = pl.f.size() > 1 ? pl.f[1] : "";
		pLogger->m_pCurrent = &s;
		const double ts = HHSeconds();
		HHSetPhase(kind.c_str());
		if(kind == "xml")
		{
			++nXml;
			Database::XMLSerializer kSerializer(*pDb);
			s.ok = kSerializer.Load(HHWiden(s.path).c_str());
			if(!s.ok)
			{
				const char* szErr = kSerializer.ErrorMessage();
				s.note = szErr ? szErr : "";
			}
		}
		else if(kind == "sql")
		{
			++nSql;
			std::string text;
			if(!ReadFileBytes(s.path, text))
			{
				s.ok = false;
				s.note = "cannot read the file";
			}
			else
			{
				// A UTF-8 byte order mark is not SQL (no current mod file has one).
				if(text.size() >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB && (unsigned char)text[2] == 0xBF)
				{
					text.erase(0, 3);
					s.note = "UTF-8 BOM skipped";
				}
				s.ok = pDb->ExecuteMultiple(text.c_str(), (int)text.size());
			}
		}
		else if(kind == "missing")
		{
			s.ok = false;
			s.note = "file does not exist; skipped";
			pDb->LogError(HHFormat("UpdateDatabase file not found: %s", s.path.c_str()).c_str());
		}
		else if(kind == "attach" && pl.f.size() >= 3)
		{
			const std::string sql = "ATTACH DATABASE " + SqlQuote(pl.f[1]) + " AS " + pl.f[2];
			s.ok = pDb->Execute(sql.c_str());
			if(!s.ok)
				fatal = "cannot attach " + pl.f[1];
		}
		else if(kind == "detach" && pl.f.size() >= 2)
		{
			s.ok = pDb->Execute(("DETACH DATABASE " + pl.f[1]).c_str());
		}
		else if(kind == "mapscript" && pl.f.size() >= 3)
		{
			++nMapScripts;
			std::string err;
			s.ok = RegisterMapScript(*pDb, s.path, pl.f[2], err);
			if(!s.ok)
			{
				s.note = err;
				HHLogFileMgr::Get().GetLog("Lua.log", 0)->Msg("MapScripts: %s: %s", s.path.c_str(), err.c_str());
			}
		}
		else if(kind == "postprocess")
		{
			std::string err;
			s.ok = RunPostProcessing(o, *pDb, err);
			if(!s.ok)
			{
				s.note = err;
				fatal = "post-processing failed: " + err;
			}
		}
		else
		{
			s.ok = false;
			fatal = HHFormat("plan line %d: unknown or incomplete step '%s'", pl.line, kind.c_str());
		}
		s.seconds = HHSeconds() - ts;
		pLogger->m_pCurrent = NULL;
		if(!s.ok)
		{
			++nFailed;
			HHLog("  %s %s: FAILED%s%s%s", kind.c_str(), s.path.c_str(), s.note.empty() ? "" : " (", s.note.c_str(), s.note.empty() ? "" : ")");
			for(size_t e = 0; e < s.errors.size() && e < 4; ++e)
				HHLog("      %s", s.errors[e].c_str());
		}
		steps.push_back(s);
	}

	HHSetPhase("close");
	pDb->Close();
	const int iDbErrors = pLogger->m_iErrors;
	delete pDb;
	const double seconds = HHSeconds() - t0;
	const std::string status = fatal.empty() ? "built" : "failed";
	HHLog("builddb %s in %.2f s: %d XML, %d SQL, %d map scripts, %d step(s) reported errors, %d database errors logged",
	      status.c_str(), seconds, nXml, nSql, nMapScripts, nFailed, iDbErrors);
	if(!fatal.empty())
		HHLogError("%s", fatal.c_str());
	WriteReport(reportPath, o, steps, status, fatal, seconds, iDbErrors);
	HHLog("report %s", reportPath.c_str());
	HHLogFileMgr::Get().CloseAll();
	HHLogClose();
	return fatal.empty() ? 0 : 1;
}
