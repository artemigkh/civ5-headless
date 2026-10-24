// Lua environment for gameplay scripts (H7, minimal for M1): the DLL's script libraries,
// GameInfo and DB (Firaxis's database exposures), GameDefines (from Defines).
#pragma once
#include "HHCommon.h"

class HHScriptSystem;

// Registers everything on the main state's globals (_G), which every thread inherits.
bool HHLuaRegisterGameData(HHScriptSystem& kScripts, ICvScriptSystemUtility1* pUtility, Database::Connection& kDb);

struct HHSelfTestResult
{
	bool bPassed;
	std::vector<std::string> checks; // "ok|FAIL: description"
};

// Runs the boot self-test in a new Lua thread and checks it against direct SQL.
HHSelfTestResult HHLuaSelfTest(HHScriptSystem& kScripts, Database::Connection& kDb, int iDllUnitInfos);
