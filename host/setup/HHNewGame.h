// New-game generation (M2): pregame from a resolved spec (H11), the start sequence (map
// generation through the DLL's own CvMapGenerator / world-builder loader) and the T000
// outputs. See work/headless/gamespec.py for the spec format.
#pragma once
#include "HHCommon.h"
#include "setup/HHJson.h"
#include "setup/HHAddins.h"

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
	class HHUserInterface* pUI;
	Database::Connection* pDb;   // the game database (profile selection)
	int iMaxMajorCivs;           // Defines.MAX_MAJOR_CIVS (HHQueryMaxMajorCivs)
	HHNewGameInterfaces() : pContext(NULL), pPreGame(NULL), pPreGame2(NULL), pGame(NULL), pMap(NULL), pWBLoader(NULL), pScripts(NULL),
		pDbUtil(NULL), pEngine(NULL), pUI(NULL), pDb(NULL), iMaxMajorCivs(22) {}
};

// A city-state slot once the game has started, with the spec's pin (minorCivs) if any.
struct HHMinorCivSlot
{
	int slot;
	int id;                  // its city-state (MinorCivilizations.ID), -1 for none
	std::string type;
	int pinnedId;            // the spec's city-state for the slot, -1 when not pinned
	std::string pinnedType;
	HHMinorCivSlot() : slot(-1), id(-1), pinnedId(-1) {}
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
	bool hostChoseCivs;                                      // random civilizations or city-states chosen by the host
	bool hostChoseMinors;                                    // the DLL left the city-states to the host (pins or draws)
	std::vector<HHMinorCivSlot> minorCivs;                   // every city-state slot after Init2
	// Autoplay (M3)
	bool bAutoplayOk;
	int iTurnsPlayed, iUpdates;
	std::vector<std::pair<int, double> > turnSeconds;        // game turn -> wall seconds spent in it
	std::vector<std::pair<int, int> > turnUpdates;           // game turn -> Update calls
	std::vector<std::string> addins;                         // UI add-in Lua files run
	std::vector<HHAddinContext> uiAddins;                    // every UI add-in context: run, failed, skipped
	std::vector<std::string> probeErrors;                    // --lua-probe files that failed
	std::map<std::string, int> netMessages;                  // send* counts by kind
	HHNewGameResult() : bPregameOk(false), bStarted(false), bOutputsOk(false), iWidth(0), iHeight(0), uiExeSeed(0),
		hostChoseCivs(false), hostChoseMinors(false), bAutoplayOk(false), iTurnsPlayed(0), iUpdates(0) {}
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

// Defines.MAX_MAJOR_CIVS of the game database (22 when missing): the setup screen's major slots.
int HHQueryMaxMajorCivs(Database::Connection& kDb);
// The in-game UI after the game started: engine bindings for the stub UI contexts, the UI emulation profiles
// selected and started (setup/HHProfiles.h).
void HHStartUI(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
// Every InGameUIAddin of the activated mods in a stub UI context (setup/HHAddins.h), then
// Events.SequenceGameInitComplete.
void HHLoadUIAddinsStep(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
// --lua-probe files, in order, in one InGame context, before autoplay is armed.
void HHRunLuaProbes(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);

// M3: arms autoplay for nTurns the way the reference runs do (game_probe: ARM, then the load screen's
// CONTINUE) and drives ICvGame1::Update until autoplay ends at turn nTurns; writes dump-tNNN.
bool HHRunAutoplay(HHNewGameInterfaces& kIf, HHNewGameResult& kResult, int nTurns, int nIdleUpdates);
// Leaves the started game so the DLL can be uninitialised (CvDllGame::Uninit traps while
// pregame says the game is started).
void HHEndNewGame(HHNewGameInterfaces& kIf, HHNewGameResult& kResult);
