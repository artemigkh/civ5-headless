// civ5headless.exe: headless Civilization V host for the Vox Populi game DLL.
//
//   civ5headless.exe boot --game-dir <path> --dll <path> [--db <path>] [--loc-db <path>]
//                         --out <run dir> [--strict] [options]
//   civ5headless.exe newgame --spec <resolved.json> --out <run dir> [--dll <path>]
//                         [--game-dir <path>] [--mods-dir <path>] [options]
//
// M2 "newgame": boots as "boot" does, applies a resolved game spec to pregame, starts the
// game as the real game would (map generation by the DLL and the map script) and writes the
// T000 outputs (t000-map.json, checkpoints/turn-0000.json, t000-digest.json).
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
#include "setup/HHJson.h"
#include "setup/HHVfs.h"
#include "setup/HHNewGame.h"
#include "lua/HHLuaGlobals.h"
#include "setup/HHDbBuilder.h"
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
		"       civ5headless.exe newgame --spec <resolved.json> --out <run dir> [--dll <path>] [--game-dir <path>]\n"
		"                        [--mods-dir <path>] [options]\n"
		"  --spec <path>        resolved game spec (python work/headless/gamespec.py resolve SPEC --out FILE)\n"
		"  --game-dir <path>    game folder (newgame default: E:\\SteamLibrary\\steamapps\\common\\Sid Meier's Civilization V)\n"
		"  --dll <path>         game DLL (newgame default: CvGameCore_Expansion2.dll in MODS\\(1) Community Patch)\n"
		"  --mods-dir <path>    deployed MODS folder, read only (default: <Documents>\\My Games\\...\\MODS)\n"
		"  --mods-db <path>     mods database to copy (default: <Documents>\\My Games\\...\\cache\\Civ5ModsDatabase.db)\n"
		"  --no-mods            no activated mods (no mod files in the VFS, IsModActivated false)\n"
		"  --no-lua-debug       remove the debug library from Lua's globals\n"
		"  --exe-seed <n>       the engine's own pregame seeds before Game.Init (random civs and city-states);\n"
		"                       a real run's HHSEEDS exeMap reproduces its choice (default: the spec's map seed);\n"
		"                       a DLL that pins the seeds at setGameStarted uses the spec's map seed instead\n"
		"  --crt-srand <n>      srand(n) before the new game: Lua's math.random state for map scripts that use it\n"
		"  --player-option <TYPE=0|1>  engine user setting for a player option (repeatable; default: database defaults\n"
		"                       plus the reference profile's PLAYEROPTION_SAFE_AUTOMATION=1)\n"
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
			else if(a == "--no-mods") o.noMods = true;
			else if(a == "--no-lua-debug") o.luaDebugLibrary = false;
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
			else if(a == "--spec") { o.specPath = v; ++i; }
			else if(a == "--mods-dir") { o.modsDir = StripSlash(v); ++i; }
			else if(a == "--mods-db") { o.modsDbPath = v; ++i; }
			else if(a == "--player-option") { o.playerOptions.push_back(v); ++i; }
			else if(a == "--exe-seed") { o.exeSeed = _strtoi64(v.c_str(), NULL, 10); ++i; }
			else if(a == "--fpu-precision") { o.fpuPrecision = atoi(v.c_str()); ++i; }
			else if(a == "--crt-srand") { o.crtSrand = _strtoi64(v.c_str(), NULL, 10); ++i; }
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
		if(o.command != "boot" && o.command != "newgame")
		{
			fprintf(stderr, "unknown command %s\n", o.command.c_str());
			return false;
		}
		const std::string myGames = DocumentsFolder() + "\\My Games\\Sid Meier's Civilization 5\\";
		if(o.modsDir.empty()) o.modsDir = myGames + "MODS";
		if(o.modsDbPath.empty()) o.modsDbPath = myGames + "cache\\Civ5ModsDatabase.db";
		if(o.command == "newgame")
		{
			if(o.specPath.empty())
			{
				fprintf(stderr, "newgame needs --spec\n");
				return false;
			}
			o.specPath = HHFullPath(o.specPath);
			if(o.gameDir.empty()) o.gameDir = "E:\\SteamLibrary\\steamapps\\common\\Sid Meier's Civilization V";
			if(o.dllPath.empty()) o.dllPath = o.modsDir + "\\(1) Community Patch\\CvGameCore_Expansion2.dll";
		}
		if(o.gameDir.empty() || o.dllPath.empty() || o.outDir.empty())
		{
			fprintf(stderr, "--game-dir, --dll and --out are required\n");
			return false;
		}
		o.modsDir = HHFullPath(o.modsDir);
		o.modsDbPath = HHFullPath(o.modsDbPath);
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

	// Adds a "newgame" member to the report WriteReport wrote (its last line is "}").
	void WriteNewGameSection(const HHNewGameResult& ng, int iLuaErrors, const std::string& strPath)
	{
		std::string text;
		{
			FILE* f = _wfopen(HHWiden(strPath).c_str(), L"rb");
			if(!f)
				return;
			char buf[65536];
			size_t n;
			while((n = fread(buf, 1, sizeof(buf), f)) > 0)
				text.append(buf, n);
			fclose(f);
		}
		const size_t close = text.find_last_of('}');
		if(close == std::string::npos)
			return;
		const HHOptions& o = HHGetOptions();
		std::string add = ",\n  \"newgame\": {\n";
		add += HHFormat("    \"spec\": \"%s\",\n", HHJsonEscape(o.specPath).c_str());
		add += HHFormat("    \"mods_dir\": \"%s\",\n", HHJsonEscape(o.modsDir).c_str());
		add += HHFormat("    \"pregame_ok\": %s,\n    \"started\": %s,\n    \"outputs_ok\": %s,\n", ng.bPregameOk ? "true" : "false",
		                ng.bStarted ? "true" : "false", ng.bOutputsOk ? "true" : "false");
		add += HHFormat("    \"lua_errors\": %d,\n    \"map_width\": %d,\n    \"map_height\": %d,\n", iLuaErrors, ng.iWidth, ng.iHeight);
		add += HHFormat("    \"seed_mode\": \"%s\",\n    \"exe_seed\": %u,\n", ng.seedMode.c_str(), ng.uiExeSeed);
		add += HHFormat("    \"digest_total\": \"%s\",\n    \"error\": \"%s\",\n", ng.digestTotal.c_str(), HHJsonEscape(ng.error).c_str());
		add += "    \"timings_seconds\": {";
		for(size_t i = 0; i < ng.timings.size(); ++i)
			add += HHFormat("%s\"%s\": %.3f", i ? ", " : "", ng.timings[i].first.c_str(), ng.timings[i].second);
		add += "},\n    \"activated_mods\": [";
		for(size_t i = 0; i < HHGetVfs().GetMods().size(); ++i)
			add += HHFormat("%s\"%s\"", i ? ", " : "", HHJsonEscape(HHGetVfs().GetMods()[i].name).c_str());
		add += "],\n    \"steps\": [\n";
		for(size_t i = 0; i < ng.steps.size(); ++i)
			add += "      \"" + HHJsonEscape(ng.steps[i]) + "\"" + (i + 1 < ng.steps.size() ? ",\n" : "\n");
		add += "    ]\n  }\n}\n";
		std::string body = text.substr(0, close);
		while(!body.empty() && (body[body.size() - 1] == '\n' || body[body.size() - 1] == '\r' || body[body.size() - 1] == ' '))
			body.erase(body.size() - 1);
		HHWriteTextFile(strPath, body + add);
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
		const std::string reportPath = p.run + (o.command == "newgame" ? "newgame-report.json" : "boot-report.json");

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

		// newgame: the spec first, so a bad spec fails before anything is loaded.
		const bool bNewGame = o.command == "newgame";
		HHJson kSpec;
		if(bNewGame)
		{
			std::string err;
			if(!HHJson::ParseFile(o.specPath, kSpec, err))
			{
				s.error = "cannot read the spec " + o.specPath + ": " + err;
				HHLogError("%s", s.error.c_str());
				WriteReport(s, reportPath);
				return 2;
			}
			CopyFileW(HHWiden(o.specPath).c_str(), HHWiden(p.run + "spec.resolved.json").c_str(), FALSE);
			HHLog("  spec      %s", o.specPath.c_str());
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

		// Mods and the Lua VFS (H10), after the Firaxis database DLL is loaded: a per-run copy of the mods database (never opened in
		// place), the activated mods in activation order, and the file index for include.
		HHSetPhase("vfs");
		{
			std::string modsDbCopy;
			if(!o.noMods)
			{
				modsDbCopy = p.db + "Civ5ModsDatabase.db";
				if(!CopyFileW(HHWiden(o.modsDbPath).c_str(), HHWiden(modsDbCopy).c_str(), FALSE))
				{
					s.error = HHFormat("cannot copy the mods database %s (error %lu)", o.modsDbPath.c_str(), GetLastError());
					HHLogError("%s", s.error.c_str());
					WriteReport(s, reportPath);
					return 2;
				}
				HHLog("copied %s -> %s", o.modsDbPath.c_str(), modsDbCopy.c_str());
			}
			HHVfs& kVfs = HHGetVfs();
			if(!kVfs.Build(o.gameDir, modsDbCopy, o.modsDir))
			{
				s.error = "cannot build the VFS (mods database unreadable)";
				WriteReport(s, reportPath);
				return 2;
			}
			kVfs.WriteIndexLog(p.logs + "vfs-index.log");
			// The live cache database has been seen with no activated mods while the game was
			// running (the mods browser rewrites it); a modded run must not silently go vanilla.
			if(!o.noMods && kVfs.GetMods().empty())
			{
				s.error = "the mods database copy has no activated mods (is the game running?); use --mods-db <snapshot> or --no-mods";
				HHLogError("%s", s.error.c_str());
				WriteReport(s, reportPath);
				return 2;
			}
			// IsModActivated answers from the activated mods unless --mod lists them explicitly.
			if(o.mods.empty())
				for(size_t i = 0; i < kVfs.GetMods().size(); ++i)
				{
					HHModRef m;
					m.id = kVfs.GetMods()[i].id;
					m.version = kVfs.GetMods()[i].version;
					o.mods.push_back(m);
					HHLog("activated mod %u: %s v%d %s", (unsigned)i, m.id.c_str(), m.version, kVfs.GetMods()[i].name.c_str());
				}
		}
		HH_TIMING("vfs");


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
		pScripts->SetScriptUtility(pContext->GetScriptSystemUtility());
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
		// The engine's player options (user settings): PlayerOptions defaults, then
		// --player-option TYPE=0|1 overrides.
		{
			Database::Results kOptions;
			if(dbs.GetGame()->Execute(kOptions, "SELECT ID, Type, \"Default\" FROM PlayerOptions ORDER BY ID"))
				while(kOptions.Step())
					pEngine->AddPlayerOption(kOptions.GetText(1), kOptions.GetInt(0), kOptions.GetInt(2) != 0);
			// The reference profile's user setting (contract 1.4: getPlayerOption answers true for
			// WAIT_END_TURN, the DB default, and SAFE_AUTOMATION, a user setting); --player-option overrides.
			pEngine->SetPlayerOptionValue("PLAYEROPTION_SAFE_AUTOMATION", true);
			for(size_t i = 0; i < o.playerOptions.size(); ++i)
			{
				const std::string& v = o.playerOptions[i];
				const size_t eq = v.find('=');
				const std::string type = v.substr(0, eq);
				const bool bValue = eq != std::string::npos && atoi(v.c_str() + eq + 1) != 0;
				if(!pEngine->SetPlayerOptionValue(type, bValue))
					HHLogError("--player-option %s: unknown option", v.c_str());
				else
					HHLog("player option %s = %d", type.c_str(), bValue ? 1 : 0);
			}
		}

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
		// Trace S1: the exe sets its version string right after ICvGameContext1::Init.
		if(ICvPreGame1* pPreGame = pContext->GetPreGame())
			pPreGame->setVersionString(std::string("403694 FINAL_RELEASE"));
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
		// Trace S1 (hh-m0-s1-continents): the exe calls FlushGameDatabaseData,
		// PerformDatabasePostProcessing, CacheGameDatabaseData after activating mods.
		pDbUtil->FlushGameDatabaseData();
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
		const bool bGameData = HHLuaRegisterGameData(*pScripts, pContext->GetScriptSystemUtility(), *dbs.GetGame());
		// Engine globals for map and gameplay scripts (H7): Locale, Modding, Events, LuaEvents,
		// MapModData, PreGame (read-only), IncludeFileList.
		const bool bEngineGlobals = HHLuaRegisterEngineGlobals(*pScripts, HHGetVfs(), pContext->GetPreGame());
		if(!bEngineGlobals)
			HHLogError("engine Lua globals: registration failed");
		if(bGameData && !bNewGame)
		{
			s.bSelfTestRun = true;
			s.selfTest = HHLuaSelfTest(*pScripts, *dbs.GetGame(), iDllUnits);
		}
		else
			s.selfTest.bPassed = bGameData && bEngineGlobals;
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

		// newgame (M2): pregame, start, T000 outputs.
		HHNewGameResult ng;
		HHNewGameInterfaces nif;
		nif.pContext = pContext;
		nif.pPreGame = pContext->GetPreGame();
		nif.pPreGame2 = nif.pPreGame ? nif.pPreGame->QueryInterface<ICvPreGame2>() : NULL;
		nif.pGame = pContext->GetGame();
		nif.pMap = pContext->GetMap();
		nif.pWBLoader = pContext->GetWorldBuilderMapLoader();
		nif.pScripts = pScripts;
		nif.pDbUtil = pDbUtil;
		nif.pEngine = pEngine;
		const int iLuaErrorsBefore = pScripts->GetErrorCount();
		if(bNewGame && s.bPostOk && s.bCacheOk)
		{
			HHSetPhase("pregame");
			if(HHApplyPregame(kSpec, nif, ng))
			{
				HHSetPhase("start");
				// Lua's math.random is the CRT rand() of the calling thread (MSVCR90, per-thread state,
				// seeded 1); map scripts that use it (Continental_Drift) depend on that state, which in
				// the real game is whatever the UI thread's earlier rand() calls left.
				if(o.fpuPrecision)
				{
					unsigned int cw = 0;
					const unsigned int pc = o.fpuPrecision == 24 ? _PC_24 : o.fpuPrecision == 64 ? _PC_64 : _PC_53;
					_controlfp_s(&cw, pc, _MCW_PC);
					HHLog("x87 precision %d bits for the new game (--fpu-precision): control word %08x", o.fpuPrecision, cw);
				}
				if(o.crtSrand >= 0)
				{
					// lua51_Win32.dll has its own MSVCR90 instance: seed through Lua itself.
					const std::string chunk = HHFormat("math.randomseed(%u)", (unsigned int)o.crtSrand);
					if(lua_State* L = pScripts->CreateLuaThread("Headless randomseed"))
					{
						if(luaL_loadbuffer(L, chunk.c_str(), chunk.size(), "randomseed") == 0)
							pScripts->CallFunction(L, 0, 0);
						pScripts->FreeLuaThread(L);
					}
					HHLog("Lua math.randomseed(%u) (--crt-srand)", (unsigned int)o.crtSrand);
				}
				if(HHStartNewGame(kSpec, nif, ng))
				{
					HHSetPhase("t000");
					HHLoadScreen(nif, ng);
					HHWriteT000(kSpec, nif, ng);
				}
			}
			if(!ng.error.empty())
				HHLogError("newgame: %s", ng.error.c_str());
			for(size_t i = 0; i < ng.timings.size(); ++i)
				s.timings.push_back(ng.timings[i]);
			tPhase = HHSeconds();
		}
		const int iLuaErrors = pScripts->GetErrorCount() - iLuaErrorsBefore;

		// Shutdown order: Lua first (its __gc metamethods include DLL and database code), then
		// the game (newgame: pregame's started flag cleared first), the DLL's game data, the
		// database handles it holds, localization, the DLL itself, and the database
		// connections last.
		HHSetPhase("shutdown");
		pScripts->LogIncludeSummary();
		pScripts->Shutdown();
		if(bNewGame && ng.bPregameOk)
			HHEndNewGame(nif, ng);
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

		bool bOk = s.bPostOk && s.bCacheOk && s.bCountsOk && s.selfTest.bPassed;
		if(bNewGame)
		{
			bOk = bOk && ng.bPregameOk && ng.bStarted && ng.bOutputsOk && iLuaErrors == 0;
			s.status = bOk ? "passed" : "failed";
			if(s.error.empty())
				s.error = !ng.error.empty() ? ng.error : (iLuaErrors ? HHFormat("%d Lua error(s); see Logs\\Lua.log", iLuaErrors) : std::string());
		}
		else
			s.status = bOk ? "passed" : "failed";
		LogCallSummary();
		WriteReport(s, reportPath);
		if(bNewGame)
			WriteNewGameSection(ng, iLuaErrors, reportPath);
		HHLog("%s %s in %.2f s; report %s", o.command.c_str(), s.status.c_str(), HHSeconds() - t0, reportPath.c_str());
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
	if(argc >= 2 && wcscmp(argv[1], L"builddb") == 0)
		return HHBuildDbMain(argc, argv);
	HHOptions& o = HHGetOptions();
	if(!ParseArgs(argc, argv, o))
	{
		fputs(kUsage, stderr);
		return 2;
	}
	return Boot();
}
