// civ5headless.exe: headless Civilization V host for the Vox Populi game DLL.
//
//   civ5headless.exe boot --game-dir <path> --dll <path> [--db <path>] [--loc-db <path>]
//                         --out <run dir> [--strict] [options]
//
// M1 "boot": loads the Firaxis support DLLs from the game folder and the game DLL under
// test, hands it the host's engine services, opens per-run copies of the game-built
// databases, initialises localization, caches the whole game database in the DLL,
// registers the Lua environment, runs a self-test and shuts down. See
// docs/headless-host-plan.md (M1) and docs/headless-host-ledger.md.
#include "HHCommon.h"
#include "engine/HHRuntime.h"
#include "engine/HHLogFiles.h"
#include "engine/HHEngineServices.h"
#include "lua/HHScriptSystem.h"
#include "lua/HHLuaEnv.h"
#include "setup/HHDatabase.h"
#include <float.h>

// From shlobj.h, which does not compile after the Firaxis Win32 header's NO* switches.
extern "C" __declspec(dllimport) HRESULT __stdcall SHGetFolderPathW(HWND hwnd, int csidl, HANDLE hToken, DWORD dwFlags, LPWSTR pszPath);
const int HH_CSIDL_PERSONAL = 0x0005;

void HHExportsInit();
void HHExportsCheck();

namespace
{
	const char* kUsage =
		"usage: civ5headless.exe boot --game-dir <path> --dll <path> --out <run dir> [options]\n"
		"  --db <path>          game database to copy (default: <Documents>\\My Games\\Sid Meier's\n"
		"                       Civilization 5\\cache\\Civ5DebugDatabase.db)\n"
		"  --loc-db <path>      localization database to copy (default: Localization-Merged.db\n"
		"                       next to the default game database)\n"
		"  --icu <path>         ICU data (default: <game>\\Locale\\icudt44l.dat)\n"
		"  --language <type>    localization language (default: en_US)\n"
		"  --lua-path <dir>     folder LoadFile/include search (repeatable; default <game>\\Assets)\n"
		"  --mod <guid[:ver]>   activated mod for IsModActivated (repeatable)\n"
		"  --dlc <guid>         valid DLC for IsDLCValid (repeatable; default: every DLC valid)\n"
		"  --game-logging       ICvGameContext1::SetLogging(true) (the DLL's own logs)\n"
		"  --strict             abort on the first unimplemented engine call\n"
		"  --verbose            log the first call of every implemented engine method too\n"
		"  --keep-dll-loaded    skip FreeLibrary of the game DLL at shutdown\n";

	struct InfoCount
	{
		const char* szWhat;
		const char* szTable;   // table the DLL caches it from
		bool bCore;            // must match for the boot to pass
		int (DLLCALL ICvGameContext1::*pfnCount)();
	};

	const InfoCount kInfoCounts[] =
	{
		{ "Units",              "Units",                true,  &ICvGameContext1::GetNumUnitInfos },
		{ "Buildings",          "Buildings",            true,  &ICvGameContext1::GetNumBuildingInfos },
		{ "Technologies",       "Technologies",         true,  &ICvGameContext1::GetNumTechInfos },
		{ "Policies",           "Policies",             true,  &ICvGameContext1::GetNumPolicyInfos },
		{ "Civilizations",      "Civilizations",        true,  &ICvGameContext1::GetNumCivilizationInfos },
		{ "Promotions",         "UnitPromotions",       true,  &ICvGameContext1::GetNumPromotionInfos },
		{ "Improvements",       "Improvements",         true,  &ICvGameContext1::GetNumImprovementInfos },
		{ "Resources",          "Resources",            true,  &ICvGameContext1::GetNumResourceInfos },
		{ "Leaders",            "Leaders",              true,  &ICvGameContext1::GetNumLeaderHeadInfos },
		{ "Eras",               "Eras",                 true,  &ICvGameContext1::GetNumEraInfos },
		{ "Builds",             "Builds",               true,  &ICvGameContext1::GetNumBuildInfos },
		{ "MinorCivilizations", "MinorCivilizations",   true,  &ICvGameContext1::GetNumMinorCivInfos },
		{ "Terrains",           "Terrains",             true,  &ICvGameContext1::GetNumTerrainInfos },
		{ "Features",           "Features",             false, &ICvGameContext1::GetNumFeatureInfos },
		{ "Victories",          "Victories",            true,  &ICvGameContext1::GetNumVictoryInfos },
		{ "Worlds",             "Worlds",               true,  &ICvGameContext1::GetNumWorldInfos },
		{ "GameSpeeds",         "GameSpeeds",           true,  &ICvGameContext1::GetNumGameSpeedInfos },
		{ "Handicaps",          "HandicapInfos",        true,  &ICvGameContext1::GetNumHandicapInfos },
		{ "GameOptions",        "GameOptions",          false, &ICvGameContext1::GetNumGameOptionInfos },
		{ "Climates",           "Climates",             true,  &ICvGameContext1::GetNumClimateInfos },
		{ "SeaLevels",          "SeaLevels",            true,  &ICvGameContext1::GetNumSeaLevelInfos },
		{ "Colors",             "Colors",               true,  &ICvGameContext1::GetNumColorInfos },
		{ "PlayerColors",       "PlayerColors",         true,  &ICvGameContext1::GetNumPlayerColorInfos },
		{ "UnitCombatClasses",  "UnitCombatInfos",      true,  &ICvGameContext1::GetNumUnitCombatClassInfos },
	};

	struct CountResult
	{
		std::string what, table;
		int dll, sql;
		bool core;
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

	std::string DocumentsFolder()
	{
		wchar_t sz[MAX_PATH];
		if(SUCCEEDED(SHGetFolderPathW(NULL, HH_CSIDL_PERSONAL, NULL, 0, sz)))
			return HHNarrow(sz);
		return std::string();
	}

	std::string StripSlash(std::string s)
	{
		while(!s.empty() && (s[s.size() - 1] == '\\' || s[s.size() - 1] == '/'))
			s.erase(s.size() - 1);
		return s;
	}

	bool ParseArgs(int argc, wchar_t** argv, HHOptions& o)
	{
		if(argc < 2)
			return false;
		o.command = HHNarrow(argv[1]);
		for(int i = 2; i < argc; ++i)
		{
			const std::string a = HHNarrow(argv[i]);
			const bool bHasValue = i + 1 < argc;
			const std::string v = bHasValue ? HHNarrow(argv[i + 1]) : std::string();
			if(a == "--strict") o.strict = true;
			else if(a == "--verbose") o.verbose = true;
			else if(a == "--game-logging") o.gameLogging = true;
			else if(a == "--keep-dll-loaded") o.freeLibrary = false;
			else if(!bHasValue) { fprintf(stderr, "missing value for %s\n", a.c_str()); return false; }
			else if(a == "--game-dir") { o.gameDir = StripSlash(v); ++i; }
			else if(a == "--dll") { o.dllPath = v; ++i; }
			else if(a == "--db") { o.dbPath = v; ++i; }
			else if(a == "--loc-db") { o.locDbPath = v; ++i; }
			else if(a == "--out") { o.outDir = StripSlash(v); ++i; }
			else if(a == "--icu") { o.icuPath = v; ++i; }
			else if(a == "--language") { o.language = v; ++i; }
			else if(a == "--lua-path") { o.luaSearch.push_back(StripSlash(HHFullPath(v))); ++i; }
			else if(a == "--dlc") { o.dlcs.push_back(v); ++i; }
			else if(a == "--mod")
			{
				HHModRef m;
				size_t colon = v.find(':');
				m.id = v.substr(0, colon);
				m.version = colon == std::string::npos ? -1 : atoi(v.c_str() + colon + 1);
				o.mods.push_back(m);
				++i;
			}
			else { fprintf(stderr, "unknown option %s\n", a.c_str()); return false; }
		}
		if(o.command != "boot")
		{
			fprintf(stderr, "unknown command %s\n", o.command.c_str());
			return false;
		}
		if(o.gameDir.empty() || o.dllPath.empty() || o.outDir.empty())
		{
			fprintf(stderr, "--game-dir, --dll and --out are required\n");
			return false;
		}
		o.gameDir = HHFullPath(o.gameDir);
		o.dllPath = HHFullPath(o.dllPath);
		o.outDir = HHFullPath(o.outDir);
		const std::string cache = DocumentsFolder() + "\\My Games\\Sid Meier's Civilization 5\\cache\\";
		if(o.dbPath.empty()) o.dbPath = cache + "Civ5DebugDatabase.db";
		if(o.locDbPath.empty()) o.locDbPath = cache + "Localization-Merged.db";
		if(o.icuPath.empty()) o.icuPath = o.gameDir + "\\Locale\\icudt44l.dat";
		o.dbPath = HHFullPath(o.dbPath);
		o.locDbPath = HHFullPath(o.locDbPath);
		o.icuPath = HHFullPath(o.icuPath);
		if(o.luaSearch.empty()) o.luaSearch.push_back(o.gameDir + "\\Assets");
		return true;
	}

	HMODULE LoadFiraxisDll(const std::string& strGameDir, const char* szName)
	{
		const std::string path = strGameDir + "\\" + szName;
		HMODULE h = LoadLibraryExW(HHWiden(path).c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
		if(!h)
			HHLogError("cannot load %s (error %lu)", path.c_str(), GetLastError());
		else
			HHLog("loaded %s", path.c_str());
		return h;
	}

	std::string ModulePath(HMODULE h)
	{
		wchar_t sz[MAX_PATH];
		DWORD n = GetModuleFileNameW(h, sz, MAX_PATH);
		return n ? HHNarrow(std::wstring(sz, n)) : std::string("?");
	}

	struct BootState
	{
		std::string status;
		std::string dllVersion;
		std::string error;
		std::vector<CountResult> counts;
		HHSelfTestResult selfTest;
		std::vector<std::pair<std::string, double> > timings;
		bool bCacheOk, bPostOk, bCountsOk, bSelfTestRun;
		int iPlayableCivs, iAIPlayableCivs, iPlayableMinors;
		std::string crtModule;
		BootState() : bCacheOk(false), bPostOk(false), bCountsOk(false), bSelfTestRun(false),
			iPlayableCivs(-1), iAIPlayableCivs(-1), iPlayableMinors(-1) { selfTest.bPassed = false; }
	};

	void WriteReport(const BootState& s, const std::string& strPath)
	{
		const HHOptions& o = HHGetOptions();
		FILE* f = _wfopen(HHWiden(strPath).c_str(), L"w");
		if(!f)
			return;
		fprintf(f, "{\n");
		fprintf(f, "  \"status\": \"%s\",\n", JsonEscape(s.status).c_str());
		fprintf(f, "  \"error\": \"%s\",\n", JsonEscape(s.error).c_str());
		fprintf(f, "  \"dll\": \"%s\",\n", JsonEscape(o.dllPath).c_str());
		fprintf(f, "  \"dll_version\": \"%s\",\n", JsonEscape(s.dllVersion).c_str());
		fprintf(f, "  \"game_dir\": \"%s\",\n", JsonEscape(o.gameDir).c_str());
		fprintf(f, "  \"db_source\": \"%s\",\n", JsonEscape(o.dbPath).c_str());
		fprintf(f, "  \"loc_db_source\": \"%s\",\n", JsonEscape(o.locDbPath).c_str());
		fprintf(f, "  \"crt_module\": \"%s\",\n", JsonEscape(s.crtModule).c_str());
		fprintf(f, "  \"strict\": %s,\n", o.strict ? "true" : "false");
		fprintf(f, "  \"post_processing_ok\": %s,\n", s.bPostOk ? "true" : "false");
		fprintf(f, "  \"cache_ok\": %s,\n", s.bCacheOk ? "true" : "false");
		fprintf(f, "  \"counts_ok\": %s,\n", s.bCountsOk ? "true" : "false");
		fprintf(f, "  \"playable\": {\"civs\": %d, \"ai_civs\": %d, \"minor_civs\": %d},\n",
		        s.iPlayableCivs, s.iAIPlayableCivs, s.iPlayableMinors);
		fprintf(f, "  \"counts\": [\n");
		for(size_t i = 0; i < s.counts.size(); ++i)
			fprintf(f, "    {\"what\": \"%s\", \"table\": \"%s\", \"dll\": %d, \"sql\": %d, \"core\": %s}%s\n",
			        s.counts[i].what.c_str(), s.counts[i].table.c_str(), s.counts[i].dll, s.counts[i].sql,
			        s.counts[i].core ? "true" : "false", i + 1 < s.counts.size() ? "," : "");
		fprintf(f, "  ],\n");
		fprintf(f, "  \"self_test\": {\"run\": %s, \"passed\": %s, \"checks\": [\n", s.bSelfTestRun ? "true" : "false",
		        s.selfTest.bPassed ? "true" : "false");
		for(size_t i = 0; i < s.selfTest.checks.size(); ++i)
			fprintf(f, "    \"%s\"%s\n", JsonEscape(s.selfTest.checks[i]).c_str(), i + 1 < s.selfTest.checks.size() ? "," : "");
		fprintf(f, "  ]},\n");
		fprintf(f, "  \"timings_seconds\": {");
		for(size_t i = 0; i < s.timings.size(); ++i)
			fprintf(f, "%s\"%s\": %.3f", i ? ", " : "", s.timings[i].first.c_str(), s.timings[i].second);
		fprintf(f, "},\n");
		std::vector<HHCallRecord> calls = HHGetCallRecords();
		struct ByOrder { bool operator()(const HHCallRecord& a, const HHCallRecord& b) const { return a.order < b.order; } };
		std::sort(calls.begin(), calls.end(), ByOrder());
		fprintf(f, "  \"engine_calls\": [\n");
		for(size_t i = 0; i < calls.size(); ++i)
			fprintf(f, "    {\"method\": \"%s\", \"stub\": %s, \"count\": %ld, \"first_phase\": \"%s\"}%s\n",
			        JsonEscape(calls[i].name).c_str(), calls[i].stub ? "true" : "false", calls[i].count,
			        calls[i].phase.c_str(), i + 1 < calls.size() ? "," : "");
		fprintf(f, "  ],\n");
		std::vector<HHExportRecord> exports = HHGetExportRecords();
		fprintf(f, "  \"exports\": [\n");
		for(size_t i = 0; i < exports.size(); ++i)
			fprintf(f, "    {\"name\": \"%s\", \"count\": %ld, \"first_phase\": \"%s\"}%s\n", exports[i].name, exports[i].count,
			        exports[i].phase.c_str(), i + 1 < exports.size() ? "," : "");
		fprintf(f, "  ]\n}\n");
		fclose(f);
	}

	void LogCallSummary()
	{
		std::vector<HHCallRecord> calls = HHGetCallRecords();
		int nStub = 0, nImpl = 0;
		for(size_t i = 0; i < calls.size(); ++i)
			(calls[i].stub ? nStub : nImpl)++;
		HHLog("engine methods called: %d implemented, %d stubs", nImpl, nStub);
		for(size_t i = 0; i < calls.size(); ++i)
			HHLog("  %-5s %-60s x%-8ld (first in %s)", calls[i].stub ? "STUB" : "impl", calls[i].name.c_str(),
			      calls[i].count, calls[i].phase.c_str());
		std::vector<HHExportRecord> exports = HHGetExportRecords();
		HHLog("exports used:");
		for(size_t i = 0; i < exports.size(); ++i)
			HHLog("  %-40s x%-10ld %s", exports[i].name, exports[i].count, exports[i].count ? exports[i].phase.c_str() : "(unused)");
	}

	int Boot()
	{
		HHOptions& o = HHGetOptions();
		HHPaths& p = HHGetPaths();
		BootState s;
		s.status = "failed";
		double t0 = HHSeconds();
		double tPhase = t0;
		#define HH_TIMING(name) do { double _t = HHSeconds(); s.timings.push_back(std::make_pair(std::string(name), _t - tPhase)); tPhase = _t; } while(0)

		// Run folders. The working directory is the run folder: the DLL resolves its
		// crashlogs\ markers and minidumps relative to it.
		p.run = o.outDir + "\\";
		p.logs = p.run + "Logs\\";
		p.cache = p.run + "cache\\";
		p.db = p.run + "db\\";
		if(!HHEnsureDirectory(p.logs) || !HHEnsureDirectory(p.cache) || !HHEnsureDirectory(p.db) ||
		   !HHEnsureDirectory(p.run + "crashlogs"))
		{
			fprintf(stderr, "cannot create the run folder %s\n", p.run.c_str());
			return 2;
		}
		// Unattended: assertion failures are logged and auto-ignored instead of a dialog.
		FILE* pMarker = _wfopen(HHWiden(p.run + "crashlogs\\nopopups.please").c_str(), L"w");
		if(pMarker)
			fclose(pMarker);
		HHLogOpen(p.logs);
		HHLogFileMgr::Get().SetFolder(p.logs);
		SetCurrentDirectoryW(HHWiden(p.run).c_str());
		const std::string reportPath = p.run + "boot-report.json";

		HHLog("civ5headless boot");
		HHLog("  game dir  %s", o.gameDir.c_str());
		HHLog("  dll       %s", o.dllPath.c_str());
		HHLog("  db        %s", o.dbPath.c_str());
		HHLog("  loc db    %s", o.locDbPath.c_str());
		HHLog("  icu       %s", o.icuPath.c_str());
		HHLog("  run       %s", p.run.c_str());
		for(size_t i = 0; i < o.luaSearch.size(); ++i)
			HHLog("  lua path  %s", o.luaSearch[i].c_str());
		{
			unsigned int cw = 0;
			_controlfp_s(&cw, 0, 0);
			HHLog("  x87/SSE control word at start: %08x (game-core values come from the M0 trace)", cw);
		}

		HHSetPhase("load");
		HHExportsInit();
		SetDllDirectoryW(HHWiden(o.gameDir).c_str());
		// The host imports these three with delay loading, so they resolve from the game folder.
		if(!LoadFiraxisDll(o.gameDir, "CvGameDatabaseWin32Final Release.dll") ||
		   !LoadFiraxisDll(o.gameDir, "CvLocalizationWin32Final Release.dll") ||
		   !LoadFiraxisDll(o.gameDir, "lua51_Win32.dll"))
		{
			s.error = "cannot load the Firaxis DLLs from the game folder";
			WriteReport(s, reportPath);
			return 2;
		}

		HHScriptSystem* pScripts = new HHScriptSystem();
		HHEngineUtility* pEngine = new HHEngineUtility(pScripts);
		HHUserInterface* pUI = new HHUserInterface();

		HMODULE hGame = LoadLibraryExW(HHWiden(o.dllPath).c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
		if(!hGame)
		{
			s.error = HHFormat("cannot load the game DLL (error %lu)", GetLastError());
			HHLogError("%s", s.error.c_str());
			WriteReport(s, reportPath);
			return 2;
		}
		HHLog("loaded %s", ModulePath(hGame).c_str());
		s.crtModule = ModulePath(GetModuleHandleW(L"msvcr90.dll"));
		HHLog("CRT: %s", s.crtModule.c_str());
		typedef ICvGameContext1* (*PFNGetContext)();
		PFNGetContext pfnGetContext = (PFNGetContext)GetProcAddress(hGame, "DllGetGameContext");
		ICvGameContext1* pContext = pfnGetContext ? pfnGetContext() : NULL;
		if(!pContext)
		{
			s.error = "DllGetGameContext missing or returned NULL";
			HHLogError("%s", s.error.c_str());
			WriteReport(s, reportPath);
			return 2;
		}
		ICvGameContext2* pContext2 = pContext->QueryInterface<ICvGameContext2>();
		ICvGameContext3* pContext3 = pContext->QueryInterface<ICvGameContext3>();
		s.dllVersion = pContext->GetDLLVersion() ? pContext->GetDLLVersion() : "";
		HHLog("game context: %s, interfaces 1%s%s", s.dllVersion.c_str(), pContext2 ? ", 2" : "", pContext3 ? ", 3" : "");
		HH_TIMING("load");

		HHSetPhase("interfaces");
		if(!pContext->SetDLLIFace(pEngine))
		{
			s.error = "SetDLLIFace rejected the engine utility";
			HHLogError("%s", s.error.c_str());
			WriteReport(s, reportPath);
			return 2;
		}
		if(pContext2)
			pContext2->SetEngineUserInterface(pUI);
		else
			HHLog("warning: no ICvGameContext2, user interface not set");
		pContext->SetLogging(o.gameLogging);

		HHSetPhase("database");
		HHDatabases dbs;
		if(!dbs.OpenGameDatabase(o.dbPath))
		{
			s.error = "cannot open the game database copy";
			WriteReport(s, reportPath);
			return 2;
		}
		pContext->SetGameDatabase(dbs.GetGame());

		HHSetPhase("localization");
		if(!dbs.InitLocalization(o.locDbPath, o.icuPath, o.language))
		{
			s.error = "localization initialisation failed";
			WriteReport(s, reportPath);
			return 2;
		}
		HH_TIMING("database_and_localization");

		HHSetPhase("init");
		pContext->Init();
		HH_TIMING("init");

		ICvDLLDatabaseUtility1* pDbUtil = pContext->GetDatabaseLoadUtility();
		if(!pDbUtil)
		{
			s.error = "GetDatabaseLoadUtility returned NULL";
			HHLogError("%s", s.error.c_str());
			WriteReport(s, reportPath);
			return 2;
		}
		// Assumed order (plan M1, to be confirmed by the M0 trace): post-processing runs on the
		// loaded database first (ICvDLLDatabaseUtility1 documents it as running after mods are
		// applied and after the database is built or read from cache), then caching.
		HHSetPhase("post-processing");
		s.bPostOk = pDbUtil->PerformDatabasePostProcessing();
		HHLog("PerformDatabasePostProcessing: %s", s.bPostOk ? "ok" : "FAILED");
		HH_TIMING("post_processing");

		HHSetPhase("cache");
		s.bCacheOk = pDbUtil->CacheGameDatabaseData();
		HHLog("CacheGameDatabaseData: %s", s.bCacheOk ? "ok" : "FAILED");
		HH_TIMING("cache");
		HHExportsCheck();

		HHSetPhase("counts");
		s.bCountsOk = true;
		HHLog("%-20s %-22s %6s %6s", "info", "table", "dll", "sql");
		for(size_t i = 0; i < sizeof(kInfoCounts) / sizeof(kInfoCounts[0]); ++i)
		{
			const InfoCount& c = kInfoCounts[i];
			CountResult r;
			r.what = c.szWhat;
			r.table = c.szTable;
			r.core = c.bCore;
			r.dll = (pContext->*c.pfnCount)();
			r.sql = dbs.CountRows(c.szTable);
			const bool bMatch = r.dll == r.sql;
			if(!bMatch && r.core)
				s.bCountsOk = false;
			HHLog("%-20s %-22s %6d %6d %s", c.szWhat, c.szTable, r.dll, r.sql, bMatch ? "" : (r.core ? "MISMATCH" : "differs (not core)"));
			s.counts.push_back(r);
		}
		s.iPlayableCivs = pContext->GetNumPlayableCivilizationInfos();
		s.iAIPlayableCivs = pContext->GetNumAIPlayableCivilizationInfos();
		s.iPlayableMinors = pContext->GetNumPlayableMinorCivs();
		HHLog("playable civilizations %d, AI-playable %d, playable minor civs %d", s.iPlayableCivs, s.iAIPlayableCivs, s.iPlayableMinors);

		HHSetPhase("lua");
		int iDllUnits = pContext->GetNumUnitInfos();
		if(HHLuaRegisterGameData(*pScripts, pContext->GetScriptSystemUtility(), *dbs.GetGame()))
		{
			s.bSelfTestRun = true;
			s.selfTest = HHLuaSelfTest(*pScripts, *dbs.GetGame(), iDllUnits);
		}
		// Localization: the dictionary must answer like the text database.
		{
			const char* szKey = "TXT_KEY_UNIT_WARRIOR";
			Localization::String strText = Localization::Lookup(szKey);
			const char* szText = strText.toUTF8();
			std::string expected;
			Database::Results kText;
			if(dbs.GetLocalization() && dbs.GetLocalization()->Execute(kText, "SELECT Text FROM Language_en_US WHERE Tag = ?"))
			{
				kText.Bind(1, szKey);
				if(kText.Step() && kText.GetText(0))
					expected = kText.GetText(0);
			}
			const bool bOk = szText && !expected.empty() && expected == szText;
			const std::string line = HHFormat("Localization::Lookup(%s) = '%s'; Language_en_US '%s'", szKey, szText ? szText : "(null)", expected.c_str());
			s.selfTest.checks.push_back(std::string(bOk ? "ok: " : "FAIL: ") + line);
			if(!bOk)
				s.selfTest.bPassed = false;
			HHLog("  self-test %s %s", bOk ? "ok  " : "FAIL", line.c_str());
		}
		HHLog("Lua self-test: %s", s.selfTest.bPassed ? "passed" : "FAILED");
		HH_TIMING("lua");

		// Shutdown order: Lua first (its __gc metamethods include DLL and database code), then
		// the DLL's game data, the database handles it holds, localization, the DLL itself,
		// and the database connections last.
		HHSetPhase("shutdown");
		pScripts->Shutdown();
		pDbUtil->Destroy();
		pContext->Uninit();
		pContext->SetGameDatabase(NULL);
		dbs.ShutdownLocalization();
		HHExportsCheck();
		if(o.freeLibrary)
		{
			pContext->SetDLLIFace(NULL);
			if(!FreeLibrary(hGame))
				HHLogError("FreeLibrary failed (error %lu)", GetLastError());
			else
				HHLog("game DLL unloaded");
		}
		dbs.Close();
		HH_TIMING("shutdown");
		s.timings.push_back(std::make_pair(std::string("total"), HHSeconds() - t0));

		const bool bOk = s.bPostOk && s.bCacheOk && s.bCountsOk && s.selfTest.bPassed;
		s.status = bOk ? "passed" : "failed";
		LogCallSummary();
		WriteReport(s, reportPath);
		HHLog("boot %s in %.2f s; report %s", s.status.c_str(), HHSeconds() - t0, reportPath.c_str());
		HHLogFileMgr::Get().CloseAll();
		HHLogClose();
		// pEngine and pUI stay alive: the DLL may still reference them from static destructors.
		UNUSED_VARIABLE(pEngine);
		UNUSED_VARIABLE(pUI);
		return bOk ? 0 : 1;
		#undef HH_TIMING
	}
}

int wmain(int argc, wchar_t** argv)
{
	HHOptions& o = HHGetOptions();
	if(!ParseArgs(argc, argv, o))
	{
		fputs(kUsage, stderr);
		return 2;
	}
	return Boot();
}
