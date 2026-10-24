// Host runtime: options, run folders, host log and the call registry that counts every
// engine-interface call the DLL makes (implemented methods and generated stubs).
#pragma once
#include "HHCommon.h"

struct HHModRef
{
	std::string id;   // mod GUID as the DLL passes it (case-insensitive compare)
	int version;      // -1: any version
};

struct HHOptions
{
	std::string command;
	std::string gameDir;   // game install folder (Firaxis DLLs, Assets, Locale)
	std::string dllPath;   // game DLL under test
	std::string dbPath;    // source game database (copied into the run folder)
	std::string locDbPath; // source localization database (copied into the run folder)
	std::string outDir;    // run folder
	std::string icuPath;   // ICU data file
	std::string language;  // localization language type
	bool strict;           // abort on the first unimplemented stub call
	bool verbose;          // echo every first call to stdout
	bool gameLogging;      // ICvGameContext1::SetLogging(true)
	bool freeLibrary;      // FreeLibrary the game DLL at shutdown
	std::vector<std::string> luaSearch; // folders LoadFile searches, in order
	std::vector<HHModRef> mods;          // activated mods (IsModActivated)
	std::vector<std::string> dlcs;       // valid DLC package GUIDs; empty: every DLC is valid
	HHOptions() : language("en_US"), strict(false), verbose(false), gameLogging(false), freeLibrary(true) {}
};

struct HHPaths
{
	std::string run;    // run folder, with trailing backslash
	std::string logs;   // <run>Logs\  .
	std::string cache;  // <run>cache\  (GetCacheFolderPath)
	std::string db;     // <run>db\  (per-run database copies)
};

HHOptions& HHGetOptions();
HHPaths& HHGetPaths();

// Run folder and logs.
bool HHEnsureDirectory(const std::string& strPath);
std::string HHFullPath(const std::string& strPath);
bool HHFileExists(const std::string& strPath);
std::string HHFormat(const char* szFormat, ...);
std::string HHFormatV(const char* szFormat, va_list args);
std::wstring HHWiden(const std::string& str, UINT uiCodePage = CP_UTF8);
std::string HHNarrow(const std::wstring& wstr, UINT uiCodePage = CP_UTF8);
std::string HHLower(const std::string& str);
void HHLogOpen(const std::string& strLogsDir);
void HHLogClose();
void HHFatal(const char* szFormat, ...);
double HHSeconds(); // seconds since process start

// Boot phase, recorded with the first call of every method.
void HHSetPhase(const char* szPhase);
const char* HHGetPhase();

// Call registry.
struct HHCallRecord
{
	std::string name;
	bool stub;
	long count;
	int order;          // order of first call
	std::string phase;  // boot phase of first call
};
std::vector<HHCallRecord> HHGetCallRecords();

// FireWorks export counters (engine/HHExports.cpp).
struct HHExportRecord
{
	const char* name;
	long count;
	std::string phase;
};
std::vector<HHExportRecord> HHGetExportRecords();
