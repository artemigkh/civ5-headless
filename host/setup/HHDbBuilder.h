// Database builder (plan section 4.5, milestone M4): civ5headless.exe builddb.
//
// Applies a build plan (written by work/headless/build_db.py) to a copy of the DLC snapshot
// with Firaxis's own loader code: XML through Database::XMLSerializer, SQL through
// Database::Connection::ExecuteMultiple, map scripts through their GetMapScriptInfo in Lua,
// then the game DLL's PerformDatabasePostProcessing.
#pragma once
#include "HHCommon.h"

// argv[1] is "builddb". Returns 0 when every step ran (mod errors the engine tolerates are
// reported, not fatal), 1 when a step the builder itself needs failed, 2 on usage errors.
int HHBuildDbMain(int argc, wchar_t** argv);
