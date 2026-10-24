#include "lua/HHScriptSystem.h"
#include "engine/HHRuntime.h"
#include "engine/HHLogFiles.h"

namespace
{
	// print(...) -> Lua.log, as "StateName: text".
	int HHLuaPrint(lua_State* L)
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
		lua_getglobal(L, "StateName");
		const char* szState = lua_tostring(L, -1);
		std::string state = szState ? szState : "Main";
		lua_pop(L, 1);
		HHScriptSystem::GetLuaLog()->Msg("%s: %s", state.c_str(), line.c_str());
		return 0;
	}

	int HHLuaTraceback(lua_State* L)
	{
		if(!lua_isstring(L, 1))
			return 1;
		lua_getglobal(L, "debug");
		if(!lua_istable(L, -1))
		{
			lua_pop(L, 1);
			return 1;
		}
		lua_getfield(L, -1, "traceback");
		if(!lua_isfunction(L, -1))
		{
			lua_pop(L, 2);
			return 1;
		}
		lua_pushvalue(L, 1);
		lua_pushinteger(L, 2);
		lua_call(L, 2, 1);
		return 1;
	}

	// include(name): loads a script from the search folders into the caller's environment.
	int HHLuaInclude(lua_State* L)
	{
		HHScriptSystem* pSystem = (HHScriptSystem*)lua_touserdata(L, lua_upvalueindex(1));
		const char* szName = luaL_checkstring(L, 1);
		std::string name(szName);
		if(name.find('.') == std::string::npos)
			name += ".lua";
		const bool bLoaded = pSystem->LoadFile(L, name.c_str());
		lua_pushboolean(L, bLoaded ? 1 : 0);
		return 1;
	}

	struct ThreadsSetArgs
	{
		int iThreadRef;
		bool bClear;
	};

	// Threads[thread] = env (or nil), through any __newindex the DLL's scripts installed.
	int HHLuaSetThreadEntry(lua_State* L)
	{
		ThreadsSetArgs* pArgs = (ThreadsSetArgs*)lua_touserdata(L, 1);
		// Stack: [1] args, [2] env (only when setting)
		lua_getglobal(L, "Threads");
		if(!lua_istable(L, -1))
			return 0;
		lua_rawgeti(L, LUA_REGISTRYINDEX, pArgs->iThreadRef);
		if(pArgs->bClear)
		{
			lua_pushnil(L);
			lua_rawset(L, -3);
		}
		else
		{
			lua_pushvalue(L, 2);
			lua_settable(L, -3);
		}
		return 0;
	}

	bool ReadWholeFile(const std::string& strPath, std::string& strOut)
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

	bool IsAbsolute(const std::string& s)
	{
		return (s.size() > 2 && s[1] == ':') || (s.size() > 1 && s[0] == '\\' && s[1] == '\\');
	}

	std::string BaseName(const std::string& s)
	{
		size_t slash = s.find_last_of("\\/");
		return slash == std::string::npos ? s : s.substr(slash + 1);
	}

	bool FindFileBelow(const std::wstring& wstrDir, const std::wstring& wstrName, std::wstring& wstrOut, int iDepth)
	{
		if(iDepth > 12)
			return false;
		std::wstring candidate = wstrDir + L"\\" + wstrName;
		DWORD attr = GetFileAttributesW(candidate.c_str());
		if(attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY))
		{
			wstrOut = candidate;
			return true;
		}
		WIN32_FIND_DATAW fd;
		HANDLE h = FindFirstFileW((wstrDir + L"\\*").c_str(), &fd);
		if(h == INVALID_HANDLE_VALUE)
			return false;
		std::vector<std::wstring> subdirs;
		do
		{
			if((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && wcscmp(fd.cFileName, L".") && wcscmp(fd.cFileName, L".."))
				subdirs.push_back(fd.cFileName);
		} while(FindNextFileW(h, &fd));
		FindClose(h);
		std::sort(subdirs.begin(), subdirs.end());
		for(size_t i = 0; i < subdirs.size(); ++i)
			if(FindFileBelow(wstrDir + L"\\" + subdirs[i], wstrName, wstrOut, iDepth + 1))
				return true;
		return false;
	}
}

//------------------------------------------------------------------------------
// HHScriptArgs
//------------------------------------------------------------------------------
// Assumption until the M0 trace: indices are 0-based and Push returns the new count.
unsigned int HHScriptArgs::Add(const Arg& a)
{
	m_args.push_back(a);
	return (unsigned int)m_args.size();
}

const HHScriptArgs::Arg* HHScriptArgs::At(unsigned int argIndex) const
{
	return argIndex < m_args.size() ? &m_args[argIndex] : NULL;
}

unsigned int HHScriptArgs::Push(bool bValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::Push");
	Arg a; a.eType = ARGTYPE_BOOL; a.b = bValue;
	return Add(a);
}

unsigned int HHScriptArgs::Push(const char* szValue, size_t lenValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::Push");
	Arg a; a.eType = ARGTYPE_STRING;
	if(szValue)
		a.s.assign(szValue, lenValue);
	return Add(a);
}

unsigned int HHScriptArgs::Push(int iValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::Push");
	Arg a; a.eType = ARGTYPE_INT; a.i = iValue;
	return Add(a);
}

unsigned int HHScriptArgs::Push(float fValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::Push");
	Arg a; a.eType = ARGTYPE_FLOAT; a.f = fValue;
	return Add(a);
}

unsigned int HHScriptArgs::PushNULL()
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::PushNULL");
	Arg a; a.eType = ARGTYPE_NULL;
	return Add(a);
}

unsigned int HHScriptArgs::Count()
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::Count");
	return (unsigned int)m_args.size();
}

ICvEngineScriptSystemArgs1::ArgType HHScriptArgs::GetType(unsigned int argIndex)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::GetType");
	const Arg* a = At(argIndex);
	return a ? a->eType : ARGTYPE_NONE;
}

bool HHScriptArgs::GetBool(unsigned int argIndex, bool& bValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::GetBool");
	const Arg* a = At(argIndex);
	if(!a || a->eType != ARGTYPE_BOOL)
		return false;
	bValue = a->b;
	return true;
}

bool HHScriptArgs::GetFloat(unsigned int argIndex, float& fValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::GetFloat");
	const Arg* a = At(argIndex);
	if(!a || a->eType != ARGTYPE_FLOAT)
		return false;
	fValue = a->f;
	return true;
}

bool HHScriptArgs::GetInt(unsigned int argIndex, int& iValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::GetInt");
	const Arg* a = At(argIndex);
	if(!a || a->eType != ARGTYPE_INT)
		return false;
	iValue = a->i;
	return true;
}

bool HHScriptArgs::GetString(unsigned int argIndex, char*& szValue)
{
	HH_IMPL_CALL("ICvEngineScriptSystemArgs1::GetString");
	Arg* a = const_cast<Arg*>(At(argIndex));
	if(!a || a->eType != ARGTYPE_STRING)
		return false;
	szValue = const_cast<char*>(a->s.c_str());
	return true;
}

int HHScriptArgs::PushAll(lua_State* L) const
{
	for(size_t i = 0; i < m_args.size(); ++i)
	{
		const Arg& a = m_args[i];
		switch(a.eType)
		{
		case ARGTYPE_BOOL: lua_pushboolean(L, a.b ? 1 : 0); break;
		case ARGTYPE_STRING: lua_pushlstring(L, a.s.c_str(), a.s.size()); break;
		case ARGTYPE_INT: lua_pushinteger(L, a.i); break;
		case ARGTYPE_FLOAT: lua_pushnumber(L, a.f); break;
		default: lua_pushnil(L); break;
		}
	}
	return (int)m_args.size();
}

//------------------------------------------------------------------------------
// HHScriptSystem
//------------------------------------------------------------------------------
FILogFile* HHScriptSystem::GetLuaLog()
{
	return HHLogFileMgr::Get().GetLog("Lua.log", 0);
}

HHScriptSystem::HHScriptSystem() : m_L(NULL), m_iErrors(0)
{
	m_L = luaL_newstate();
	luaL_openlibs(m_L);

	lua_pushcfunction(m_L, HHLuaPrint);
	lua_setglobal(m_L, "print");

	lua_newtable(m_L);
	lua_setglobal(m_L, "Threads");
	lua_newtable(m_L);
	lua_setglobal(m_L, "IncludeFileList");

	lua_pushlightuserdata(m_L, this);
	lua_pushcclosure(m_L, HHLuaInclude, 1);
	lua_setglobal(m_L, "include");
}

HHScriptSystem::~HHScriptSystem()
{
	Shutdown();
}

void HHScriptSystem::Shutdown()
{
	if(!m_L)
		return;
	if(!m_threads.empty())
		HHLog("Lua shutdown: %u thread(s) never freed", (unsigned)m_threads.size());
	m_threads.clear();
	lua_close(m_L);
	m_L = NULL;
}

lua_State* HHScriptSystem::CreateLuaThread(const char* szName)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CreateLuaThread");
	if(!m_L)
	{
		HHLogError("CreateLuaThread(%s) after Lua shutdown", szName ? szName : "");
		return NULL;
	}
	lua_State* T = lua_newthread(m_L);
	const int iRef = luaL_ref(m_L, LUA_REGISTRYINDEX);
	m_threads[T] = iRef;

	// env = setmetatable({StateName = name}, {__index = _G})
	lua_newtable(m_L);
	lua_pushstring(m_L, szName ? szName : "");
	lua_setfield(m_L, -2, "StateName");
	lua_newtable(m_L);
	lua_pushvalue(m_L, LUA_GLOBALSINDEX);
	lua_setfield(m_L, -2, "__index");
	lua_setmetatable(m_L, -2);

	// The thread's globals are the environment.
	lua_pushvalue(m_L, -1);
	lua_xmove(m_L, T, 1);
	lua_replace(T, LUA_GLOBALSINDEX);

	// Threads[T] = env
	ThreadsSetArgs args = { iRef, false };
	lua_pushcfunction(m_L, HHLuaSetThreadEntry);
	lua_pushlightuserdata(m_L, &args);
	lua_pushvalue(m_L, -3);
	if(lua_pcall(m_L, 2, 0, 0) != 0)
	{
		HHLogError("CreateLuaThread(%s): Threads registration failed: %s", szName, lua_tostring(m_L, -1));
		lua_pop(m_L, 1);
	}
	lua_pop(m_L, 1); // env
	return T;
}

void HHScriptSystem::FreeLuaThread(lua_State* L)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::FreeLuaThread");
	if(!L)
		return;
	std::map<lua_State*, int>::iterator it = m_threads.find(L);
	if(it == m_threads.end())
	{
		HHLogError("FreeLuaThread: unknown Lua thread %p", L);
		return;
	}
	ThreadsSetArgs args = { it->second, true };
	if(lua_cpcall(m_L, HHLuaSetThreadEntry, &args) != 0)
	{
		HHLogError("FreeLuaThread: Threads cleanup failed: %s", lua_tostring(m_L, -1));
		lua_pop(m_L, 1);
	}
	lua_settop(L, 0);
	luaL_unref(m_L, LUA_REGISTRYINDEX, it->second);
	m_threads.erase(it);
}

std::string HHScriptSystem::ResolveFile(const char* szFilename) const
{
	if(!szFilename || !*szFilename)
		return std::string();
	std::string name(szFilename);
	for(size_t i = 0; i < name.size(); ++i)
		if(name[i] == '/')
			name[i] = '\\';
	if(IsAbsolute(name))
		return HHFileExists(name) ? name : std::string();
	const std::vector<std::string>& folders = HHGetOptions().luaSearch;
	// 1. folder + relative name, 2. folder tree search by file name (first match in sorted order).
	for(size_t i = 0; i < folders.size(); ++i)
	{
		std::string candidate = folders[i] + "\\" + name;
		if(HHFileExists(candidate))
			return candidate;
	}
	const std::wstring wstrBase = HHWiden(BaseName(name));
	for(size_t i = 0; i < folders.size(); ++i)
	{
		std::wstring found;
		if(FindFileBelow(HHWiden(folders[i]), wstrBase, found, 0))
			return HHNarrow(found);
	}
	return std::string();
}

bool HHScriptSystem::ProtectedCall(lua_State* L, int nArgs, int nRet, const char* szWhat)
{
	const int base = lua_gettop(L) - nArgs;
	lua_pushcfunction(L, HHLuaTraceback);
	lua_insert(L, base);
	const int rc = lua_pcall(L, nArgs, nRet, base);
	lua_remove(L, base);
	if(rc != 0)
	{
		const char* szError = lua_tostring(L, -1);
		HHLogError("Lua error in %s: %s", szWhat, szError ? szError : "(no message)");
		GetLuaLog()->Msg("Runtime Error: %s", szError ? szError : "(no message)");
		lua_pop(L, 1);
		++m_iErrors;
		if(nRet != LUA_MULTRET)
			for(int i = 0; i < nRet; ++i)
				lua_pushnil(L);
		return false;
	}
	return true;
}

bool HHScriptSystem::LoadFile(lua_State* L, const char* szFilename)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::LoadFile");
	const std::string path = ResolveFile(szFilename);
	if(path.empty())
	{
		HHLogError("LoadFile: %s not found in the Lua search folders", szFilename ? szFilename : "(null)");
		return false;
	}
	std::string text;
	if(!ReadWholeFile(path, text))
	{
		HHLogError("LoadFile: cannot read %s", path.c_str());
		return false;
	}
	// Record the file the way the engine's include list does (full path).
	lua_getglobal(m_L, "IncludeFileList");
	if(lua_istable(m_L, -1))
	{
		lua_pushstring(m_L, path.c_str());
		lua_rawseti(m_L, -2, (int)lua_objlen(m_L, -2) + 1);
	}
	lua_pop(m_L, 1);

	const std::string chunk = "@" + path;
	if(luaL_loadbuffer(L, text.c_str(), text.size(), chunk.c_str()) != 0)
	{
		HHLogError("LoadFile: syntax error: %s", lua_tostring(L, -1));
		GetLuaLog()->Msg("Syntax Error: %s", lua_tostring(L, -1));
		lua_pop(L, 1);
		++m_iErrors;
		return false;
	}
	return ProtectedCall(L, 0, 0, path.c_str());
}

bool HHScriptSystem::RunString(lua_State* L, const char* szChunk, const char* szChunkName)
{
	if(luaL_loadbuffer(L, szChunk, strlen(szChunk), szChunkName) != 0)
	{
		HHLogError("Lua syntax error in %s: %s", szChunkName, lua_tostring(L, -1));
		lua_pop(L, 1);
		++m_iErrors;
		return false;
	}
	return ProtectedCall(L, 0, 0, szChunkName);
}

ICvEngineScriptSystemArgs1* HHScriptSystem::CreateArgs()
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CreateArgs");
	return new HHScriptArgs();
}

ICvEngineScriptSystemArgs1* HHScriptSystem::CreateArgs(uint)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CreateArgs");
	return new HHScriptArgs();
}

void HHScriptSystem::DestroyArgs(ICvEngineScriptSystemArgs1* pkArgs)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::DestroyArgs");
	delete pkArgs;
}

bool HHScriptSystem::CallCFunction(lua_State* L, lua_CFunction func, void* args)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallCFunction");
	if(lua_cpcall(L, func, args) != 0)
	{
		const char* szError = lua_tostring(L, -1);
		HHLogError("Lua error in CallCFunction: %s", szError ? szError : "(no message)");
		GetLuaLog()->Msg("Runtime Error: %s", szError ? szError : "(no message)");
		lua_pop(L, 1);
		++m_iErrors;
		return false;
	}
	return true;
}

bool HHScriptSystem::CallFunction(lua_State* L, unsigned int nArgs, unsigned int nRet)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallFunction");
	return ProtectedCall(L, (int)nArgs, (int)nRet, "CallFunction");
}

// GameEvents arrive in M3; until then no listener exists and every hook is "not handled".
bool HHScriptSystem::CallHook(const char*, ICvEngineScriptSystemArgs1*, bool&)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallHook");
	return false;
}

bool HHScriptSystem::CallAccumulator(const char*, ICvEngineScriptSystemArgs1*, int&)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallAccumulator");
	return false;
}

bool HHScriptSystem::CallAccumulator(const char*, ICvEngineScriptSystemArgs1*, float&)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallAccumulator");
	return false;
}

bool HHScriptSystem::CallTestAll(const char*, ICvEngineScriptSystemArgs1*, bool&)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallTestAll");
	return false;
}

bool HHScriptSystem::CallTestAny(const char*, ICvEngineScriptSystemArgs1*, bool&)
{
	HH_IMPL_CALL("ICvEngineScriptSystem1::CallTestAny");
	return false;
}
