// New-game generation (M2): pregame from a resolved spec (H11), the start sequence (map
// generation through the DLL's own CvMapGenerator / world-builder loader) and the T000
// outputs. See work/headless/gamespec.py for the spec format.
#pragma once
#include "HHCommon.h"
#include "setup/HHJson.h"

class HHScriptSystem;
class HHEngineUtility;

struct HHNewGameInterfaces
{
	ICvGameContext1* pContext;
	ICvPreGame1* pPreGame;
	ICvPreGame2* pPreGame2;
	ICvGame1* pGame;
	ICvMap1* pMap;
	ICvWorldBuilderMapLoader1* pWBLoader;
	HHScriptSystem* pScripts;
	ICvDLLDatabaseUtility1* pDbUtil;
	HHEngineUtility* pEngine;
};

struct HHNewGameResult
{
	bool bPregameOk, bStarted, bOutputsOk;
	std::string error;
	std::vector<std::string> steps;                         // pregame/start calls, in order
	std::vector<std::pair<std::string, double> > timings;   // seconds per phase
	int iWidth, iHeight;
	std::string digestTotal;                                 // Game.GetHeadlessDigest().total, if the DLL has it
	std::string seedMode;                                    // how the spec seeds reached the game
	unsigned int uiExeSeed;                                  // pregame seeds before Game.Init (the engine's own)
	HHNewGameResult() : bPregameOk(false), bStarted(false), bOutputsOk(false), iWidth(0), iHeight(0), uiExeSeed(0) {}
};

// Pregame from the resolved spec (Task 1). Every engine call is appended to kResult.steps.
bool HHApplyPregame(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
// The engine's net loopback: delivers every queued send* as its Response*; returns the count.
size_t HHDeliverNetMessages(HHNewGameInterfaces& kIf);

// "Start game" (Task 4): close slots, preload a premade map, Init, Init2, game started.
bool HHStartNewGame(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
// T000 outputs (Task 5): t000-map.json, checkpoints/turn-0000.json, t000-digest.json.
// The load-screen state (the reference runs' dump-t000 point): pause player and UI Lua side effects.
bool HHLoadScreen(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);

bool HHWriteT000(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
// Leaves the started game so the DLL can be uninitialised (CvDllGame::Uninit traps while
// pregame says the game is started).
void HHEndNewGame(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
