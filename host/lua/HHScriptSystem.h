// ICvEngineScriptSystem1 on Lua 5.1 (lua51_Win32.dll from the game folder).
//
// One main state holds the shared globals (_G): the standard libraries, GameInfo, DB,
// GameDefines, the DLL's script libraries, Threads and IncludeFileList (which the DLL's
// embedded VP_LUAAPI script reads). CreateLuaThread makes a coroutine with its own
// environment table {StateName = name} whose metatable falls back to _G, the way the
// engine's contexts see shared globals; Threads[thread] = env.
#pragma once
#include "HHCommon.h"
#include "gen/HHStubs.gen.h"

class HHScriptArgs : public HHStubScriptArgs
{
public:
	HHScriptArgs() {}
	virtual ~HHScriptArgs() {}

	unsigned int Push(bool bValue);
	unsigned int Push(const char* szValue, size_t lenValue);
	unsigned int Push(int iValue);
	unsigned int Push(float fValue);
	unsigned int PushNULL();
	unsigned int Count();
	ArgType GetType(unsigned int argIndex);
	bool GetBool(unsigned int argIndex, bool& bValue);
	bool GetFloat(unsigned int argIndex, float& fValue);
	bool GetInt(unsigned int argIndex, int& iValue);
	bool GetString(unsigned int argIndex, char*& szValue);

	// Pushes every argument onto a Lua stack; returns the number pushed.
	int PushAll(lua_State* L) const;

private:
	struct Arg
	{
		ArgType eType;
		bool b;
		int i;
		float f;
		std::string s;
		Arg() : eType(ARGTYPE_NONE), b(false), i(0), f(0.f) {}
	};
	unsigned int Add(const Arg& a);
	const Arg* At(unsigned int argIndex) const;
	std::vector<Arg> m_args;
};

class HHScriptSystem : public HHStubScriptSystem
{
public:
	HHScriptSystem();
	~HHScriptSystem();

	lua_State* CreateLuaThread(_In_z_ const char* szName);
	void FreeLuaThread(_In_opt_ lua_State* L);
	bool LoadFile(_In_ lua_State* L, _In_z_ const char* szFilename);
	ICvEngineScriptSystemArgs1* CreateArgs();
	ICvEngineScriptSystemArgs1* CreateArgs(uint uiReserve);
	void DestroyArgs(_In_opt_ ICvEngineScriptSystemArgs1* pkArgs);
	bool CallCFunction(_In_ lua_State* L, lua_CFunction func, void* args);
	bool CallFunction(_In_ lua_State* L, unsigned int nArgs, unsigned int nRet);
	bool CallHook(_In_z_ const char* szName, _In_opt_ ICvEngineScriptSystemArgs1* args, bool& value);
	bool CallAccumulator(_In_z_ const char* szName, _In_opt_ ICvEngineScriptSystemArgs1* args, int& value);
	bool CallAccumulator(_In_z_ const char* szName, _In_opt_ ICvEngineScriptSystemArgs1* args, float& value);
	bool CallTestAll(_In_z_ const char* szName, _In_opt_ ICvEngineScriptSystemArgs1* args, bool& value);
	bool CallTestAny(_In_z_ const char* szName, _In_opt_ ICvEngineScriptSystemArgs1* args, bool& value);

	lua_State* GetMainState() const { return m_L; }
	// Closes the Lua state (runs every __gc, some of which are DLL code): call while the
	// game DLL, its game data and the databases are still alive.
	void Shutdown();
	// Resolves a script name against the search folders; empty if not found.
	std::string ResolveFile(const char* szFilename) const;
	// Runs a chunk of Lua in L with a traceback handler; logs and returns false on error.
	bool RunString(lua_State* L, const char* szChunk, const char* szChunkName);
	size_t GetThreadCount() const { return m_threads.size(); }
	int GetErrorCount() const { return m_iErrors; }

	static FILogFile* GetLuaLog();

	// include() implementation (pushes the result table; returns 1).
	int Include(lua_State* L, const char* szName, bool bPattern);
	// Loads and runs a file in L's environment; logs errors.
	bool RunFile(lua_State* L, const std::string& strPath);
	static std::string StateName(lua_State* L);
	const std::vector<std::string>& GetLoadedFiles() const { return m_loadedFiles; }
	void LogIncludeSummary() const;
	// The DLL's script utility: its libraries are registered in every new thread.
	void SetScriptUtility(ICvScriptSystemUtility1* pUtility) { m_pUtility = pUtility; }

private:
	bool ProtectedCall(lua_State* L, int nArgs, int nRet, const char* szWhat);
	lua_State* m_L;
	std::map<lua_State*, int> m_threads; // thread -> registry reference
	void RecordInclude(const std::string& strPath);
	int m_iErrors;
	ICvScriptSystemUtility1* m_pUtility;
	std::vector<std::string> m_loadedFiles;        // every file loaded, in order
	std::map<std::string, int> m_includeCounts;    // "context|name" -> include calls
};
