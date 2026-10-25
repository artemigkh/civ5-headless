#include "setup/HHNewGame.h"
#include "lua/HHScriptSystem.h"
#include "engine/HHEngineServices.h"
#include "engine/HHRuntime.h"

// Every engine-side call that changes DLL state is recorded in kResult.steps, so the run
// folder documents the exact sequence (newgame-report.json "steps").
#define HH_STEP(text, call) do { call; kResult.steps.push_back(text); } while(0)

namespace
{
	const int kMaxMajorCivs = 22; // MAX_MAJOR_CIVS

	unsigned int SeedValue(const HHJson& j)
	{
		const double d = j.AsDouble(0.0);
		return (unsigned int)(__int64)d;
	}

	bool IsAbsolutePath(const std::string& s)
	{
		return (s.size() > 2 && s[1] == ':') || (s.size() > 1 && s[0] == '\\' && s[1] == '\\');
	}

	std::string Slashes(std::string s)
	{
		for(size_t i = 0; i < s.size(); ++i)
			if(s[i] == '/')
				s[i] = '\\';
		return s;
	}

	double Now() { return HHSeconds(); }

	// DLC the real game allows in single player (HHPREGAME dlcAllowed in S1 and S3, in this
	// order): the gameplay DLC and expansions, without DLC_SP_Maps and Tablet.
	const char* kDlcAllowed[] =
	{
		"293C1EE3-1176-44F6-AC1F-59663826DE74", // DLC_01 Mongols
		"B685D5DE-7CCA-4E75-81B4-2F60754E6330", // DLC_02 Spain and Inca
		"ECF7C605-BA11-4CAC-8D80-D71306AAC471", // DLC_03 Polynesia
		"B3030D39-C0D8-4BC7-91B1-7AD1CAF585AB", // DLC_04 Denmark
		"112C22B2-5308-42B6-B734-171CCAB3037B", // DLC_05 Korea
		"BBB0D085-A0B1-4475-B007-3E549CF3ADC3", // DLC_06 Ancient Wonders
		"EA67AED5-5859-4875-BF3A-360FE9E55D1B", // DLC_07 Civilization 5 Complete
		"7459BA32-5764-44AE-8E95-01AD0E0EFD48", // DLC_Deluxe Babylon
		"0E3751A1-F840-4E1B-9706-519BF484E59D", // Expansion (Gods and Kings)
		"6DA07636-4123-4018-B643-6575B4EC336B", // Expansion2 (Brave New World)
		"8871E748-29A4-4910-8C57-8C99E32D0167", // Shared (Upgrade 1)
	};

	bool ParseGuid(const char* sz, GUID& g)
	{
		unsigned int d1 = 0, d2 = 0, d3 = 0, b[8] = {0};
		if(sscanf(sz, "%8x-%4x-%4x-%2x%2x-%2x%2x%2x%2x%2x%2x", &d1, &d2, &d3, &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &b[6], &b[7]) != 11)
			return false;
		g.Data1 = d1;
		g.Data2 = (unsigned short)d2;
		g.Data3 = (unsigned short)d3;
		for(int i = 0; i < 8; ++i)
			g.Data4[i] = (unsigned char)b[i];
		return true;
	}
}

//------------------------------------------------------------------------------
// Task 1: pregame
//------------------------------------------------------------------------------
bool HHApplyPregame(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult)
{
	ICvPreGame1* pg = kIf.pPreGame;
	const double t0 = Now();
	if(kSpec["specVersion"].AsInt(0) != 1 || !kSpec["map"].IsObject() || !kSpec["slots"].IsArray())
	{
		kResult.error = "not a resolved spec (specVersion 1 with map and slots); run work/headless/gamespec.py resolve";
		return false;
	}
	const HHJson& kMap = kSpec["map"];
	const std::string mapFile = kMap["file"].AsString();
	const bool bCiv5Map = kMap["kind"].AsString() == "civ5map";

	// --- A. Entering the single-player setup screen -------------------------------------
	// ASSUMPTION (trace): the exe starts the single-player setup from a reset pregame:
	// resetGame + resetPlayers, a single-player new game, the local player in slot 0
	// (taken, assigned). The setup screen's Lua then runs the sequence in B.
	HH_STEP("resetGame()", pg->resetGame());
	HH_STEP("resetPlayers()", pg->resetPlayers());
	// Trace S1/S3: the exe's per-slot setup load calls setPlayable(p, true) for every slot;
	// setWorldSize's slot reset later clears it for the slots beyond the world's default
	// (S3 dump-t000 pregame: playable 1 for the 6 active majors only).
	// The barbarian slot stays unplayable (S3 dump-t000 pregame: playable[63] = 0).
	for(int i = 0; i < MAX_CIV_PLAYERS; ++i)
		pg->setPlayable((PlayerTypes)i, true);
	kResult.steps.push_back(HHFormat("for i = 0..%d: setPlayable(i, true)", MAX_CIV_PLAYERS - 1));
	HH_STEP("setGameType(GAME_SINGLE_PLAYER, GAME_NEW)", pg->setGameType(GAME_SINGLE_PLAYER, GAME_NEW));
	// The engine's own seeds (trace S1/S3: map == sync, one clock value): pregame holds them
	// until CvGame::init pins the spec seeds. closeInactiveSlots draws the random civs and
	// city-states from them. --exe-seed sets it (a real run's HHSEEDS exeMap reproduces its
	// civ and city-state choice); the default is the spec's map seed.
	{
		const __int64 iExe = HHGetOptions().exeSeed;
		kResult.uiExeSeed = iExe >= 0 ? (unsigned int)iExe : SeedValue(kSpec["seeds"]["map"]);
		HH_STEP(HHFormat("setMapRandomSeed(%u)", kResult.uiExeSeed), pg->setMapRandomSeed(kResult.uiExeSeed));
		HH_STEP(HHFormat("setSyncRandomSeed(%u)", kResult.uiExeSeed), pg->setSyncRandomSeed(kResult.uiExeSeed));
	}
	HH_STEP("setActivePlayer(0)", pg->setActivePlayer((PlayerTypes)0));
	// Session values the real game has from its configuration (S1/S3 HHPREGAME): game name,
	// the local player's nickname and the allowed DLC.
	HH_STEP("setGameName(\"My Game\")", pg->setGameName(CvString("My Game")));
	HH_STEP("setNickname(0, \"Player 1\")", pg->setNickname((PlayerTypes)0, CvString("Player 1")));
	HH_STEP("clearDLCAllowed()", pg->clearDLCAllowed());
	for(size_t i = 0; i < sizeof(kDlcAllowed) / sizeof(kDlcAllowed[0]); ++i)
	{
		GUID g;
		if(ParseGuid(kDlcAllowed[i], g))
			pg->setDLCAllowed(g, true);
	}
	kResult.steps.push_back(HHFormat("setDLCAllowed(..., true) x%u", (unsigned)(sizeof(kDlcAllowed) / sizeof(kDlcAllowed[0]))));
	HH_STEP("setSlotStatus(0, SS_TAKEN)", pg->setSlotStatus((PlayerTypes)0, SS_TAKEN));
	HH_STEP("setSlotClaim(0, SLOTCLAIM_ASSIGNED)", pg->setSlotClaim((PlayerTypes)0, SLOTCLAIM_ASSIGNED));

	// --- B. The setup screen (gamespec.py pregame_lua, same order) ----------------------
	HH_STEP("setLeaderName(0, \"\")", pg->setLeaderName((PlayerTypes)0, CvString("")));
	HH_STEP("setCivilizationDescription(0, \"\")", pg->setCivilizationDescription((PlayerTypes)0, CvString("")));
	HH_STEP("setCivilizationShortDescription(0, \"\")", pg->setCivilizationShortDescription((PlayerTypes)0, CvString("")));
	HH_STEP("setCivilizationAdjective(0, \"\")", pg->setCivilizationAdjective((PlayerTypes)0, CvString("")));
	for(int i = 0; i < kMaxMajorCivs; ++i)
	{
		pg->setCivilization((PlayerTypes)i, NO_CIVILIZATION);
		pg->setTeamType((PlayerTypes)i, (TeamTypes)i);
	}
	kResult.steps.push_back("for i = 0..21: setCivilization(i, -1); setTeamType(i, i)");

	const int iWorldSize = kSpec["worldSize"]["id"].AsInt(-1);
	HH_STEP("setRandomWorldSize(false)", pg->setRandomWorldSize(false));
	// setWorldSize resets the slots (CvPreGame::resetSlots): the world's default player count
	// become computer slots with a random civ, the rest are reset and closed.
	HH_STEP(HHFormat("setWorldSize(%d)", iWorldSize), pg->setWorldSize((WorldSizeTypes)iWorldSize));
	HH_STEP(HHFormat("setNumMinorCivs(%d)", kSpec["cityStates"].AsInt()), pg->setNumMinorCivs(kSpec["cityStates"].AsInt()));
	HH_STEP("setLoadWBScenario(false)", pg->setLoadWBScenario(false));
	HH_STEP("setRandomMapScript(false)", pg->setRandomMapScript(false));
	// The script name is stored exactly as the MapScripts / Map_Sizes FileName (absolute for
	// mod scripts, game-relative for base scripts and premade maps): the DLL looks up
	// MapScriptOptions defaults by this string, and LoadFile resolves it.
	HH_STEP(HHFormat("setMapScriptName(\"%s\")", mapFile.c_str()), pg->setMapScriptName(CvString(mapFile.c_str())));
	HH_STEP(HHFormat("setGameSpeed(%d)", kSpec["speed"]["id"].AsInt()), pg->setGameSpeed((GameSpeedTypes)kSpec["speed"]["id"].AsInt()));
	HH_STEP(HHFormat("setEra(%d)", kSpec["era"]["id"].AsInt()), pg->setEra((EraTypes)kSpec["era"]["id"].AsInt()));
	HH_STEP(HHFormat("setHandicap(0, %d)", kSpec["difficulty"]["id"].AsInt()),
	        pg->setHandicap((PlayerTypes)0, (HandicapTypes)kSpec["difficulty"]["id"].AsInt()));
	{
		const std::vector<std::pair<std::string, HHJson> >& v = kSpec["victories"].Members();
		for(size_t i = 0; i < v.size(); ++i)
		{
			const int id = v[i].second["id"].AsInt();
			const bool b = v[i].second["enabled"].AsBool(true);
			HH_STEP(HHFormat("setVictory(%d /* %s */, %s)", id, v[i].first.c_str(), b ? "true" : "false"), pg->setVictory((VictoryTypes)id, b));
		}
	}
	HH_STEP(HHFormat("setMaxTurns(%d)", kSpec["maxTurns"].AsInt()), pg->setMaxTurns(kSpec["maxTurns"].AsInt()));
	HH_STEP("ResetGameOptions()", pg->ResetGameOptions());
	HH_STEP("ResetMapOptions()", pg->ResetMapOptions());
	// Options: only those the spec sets; everything else stays unset (the DLL then reads
	// MapScriptOptions.DefaultValue on first use, as in the real game).
	{
		const std::vector<std::pair<std::string, HHJson> >& v = kSpec["gameOptions"].Members();
		for(size_t i = 0; i < v.size(); ++i)
		{
			// PreGame.SetGameOption(type, bool) in the setup screen: the value is 0/1.
			const int iValue = v[i].second["value"].AsInt() ? 1 : 0;
			HH_STEP(HHFormat("SetGameOption(\"%s\", %d)", v[i].first.c_str(), iValue), pg->SetGameOption(v[i].first.c_str(), iValue));
		}
	}
	{
		// Map options are keyed by OptionID ("1", "4", ...): Map.GetCustomOption(n) and the
		// setup screen's PreGame.SetMapOption(n, value) both pass the number as a string.
		const std::vector<std::pair<std::string, HHJson> >& v = kMap["options"].Members();
		for(size_t i = 0; i < v.size(); ++i)
		{
			const int iValue = v[i].second["value"].AsInt();
			HH_STEP(HHFormat("SetMapOption(\"%s\" /* %s */, %d)", v[i].first.c_str(), v[i].second["name"].AsString().c_str(), iValue),
			        pg->SetMapOption(v[i].first.c_str(), iValue));
		}
	}
	// Slots: status, claim, civilization, team.
	const HHJson& kSlots = kSpec["slots"];
	for(size_t i = 0; i < kSlots.Size(); ++i)
	{
		const HHJson& s = kSlots.At(i);
		const PlayerTypes p = (PlayerTypes)s["slot"].AsInt();
		const std::string status = s["status"].AsString();
		const SlotStatus eStatus = status == "taken" ? SS_TAKEN : (status == "computer" ? SS_COMPUTER : SS_CLOSED);
		const char* szStatus = eStatus == SS_TAKEN ? "SS_TAKEN" : (eStatus == SS_COMPUTER ? "SS_COMPUTER" : "SS_CLOSED");
		HH_STEP(HHFormat("setSlotStatus(%d, %s)", (int)p, szStatus), pg->setSlotStatus(p, eStatus));
		// ASSUMPTION (trace): the setup screen leaves active slots assigned and closed slots
		// unassigned (resetSlots does this for the world's default slots; the advanced setup
		// adds AI players the same way).
		const SlotClaim eClaim = eStatus == SS_CLOSED ? SLOTCLAIM_UNASSIGNED : SLOTCLAIM_ASSIGNED;
		if(pg->slotClaim(p) != eClaim)
			HH_STEP(HHFormat("setSlotClaim(%d, %s)", (int)p, eClaim == SLOTCLAIM_ASSIGNED ? "SLOTCLAIM_ASSIGNED" : "SLOTCLAIM_UNASSIGNED"),
			        pg->setSlotClaim(p, eClaim));
	}
	for(size_t i = 0; i < kSlots.Size(); ++i)
	{
		const HHJson& s = kSlots.At(i);
		const PlayerTypes p = (PlayerTypes)s["slot"].AsInt();
		const int iCiv = s["civId"].AsInt(-1);
		if(iCiv >= 0)
			HH_STEP(HHFormat("setCivilization(%d, %d /* %s */)", (int)p, iCiv, s["civ"].AsString().c_str()),
			        pg->setCivilization(p, (CivilizationTypes)iCiv));
		const int iTeam = s["team"].AsInt((int)p);
		if(iTeam != (int)p)
			HH_STEP(HHFormat("setTeamType(%d, %d)", (int)p, iTeam), pg->setTeamType(p, (TeamTypes)iTeam));
	}

	// --- C. After the setup screen (trace S1/S3, hh-m0-s1-continents) ---------------------
	// vpbench: PreGame.SetPersistSettings(false), then Events.SerialEventStartGame(); the exe
	// then verifies the local player's handicap and re-sets the active player.
	HH_STEP("setPersistSettings(false)", pg->setPersistSettings(false));
	if(kIf.pPreGame2)
		HH_STEP("VerifyHandicap(0)", kIf.pPreGame2->VerifyHandicap((PlayerTypes)0));
	HH_STEP("setActivePlayer(0)", pg->setActivePlayer((PlayerTypes)0));
	// The exe round-trips pregame through a NetInitInfo (Create, Write; Create, Read, Commit).
	// The host commits one built from the current pregame: Commit re-applies the map script
	// (through ICvEngineUtility4::GetEvaluatedMapScriptPath), world size (no slot reset),
	// options, victories, seeds and the other session settings.
	{
		const unsigned int uiInfo = kIf.pContext->CreateNetInitInfo();
		ICvNetInitInfo1* pInfo = kIf.pContext->GetNetInitInfo(uiInfo);
		bool bCommitted = false;
		if(pInfo)
		{
			HH_STEP("NetInitInfo.Commit()", bCommitted = pInfo->Commit());
			pInfo->Destroy();
		}
		kIf.pContext->DestroyNetInitInfo(uiInfo);
		if(!bCommitted)
			HHLogError("NetInitInfo commit failed");
	}
	// The exe re-applies world size (without a slot reset), climate, sea level and era.
	HH_STEP(HHFormat("setWorldSize(%d, false)", (int)pg->worldSize()), pg->setWorldSize(pg->worldSize(), false));
	HH_STEP(HHFormat("setClimate(%d)", (int)pg->climate()), pg->setClimate(pg->climate()));
	HH_STEP(HHFormat("setSeaLevel(%d)", (int)pg->seaLevel()), pg->setSeaLevel(pg->seaLevel()));
	HH_STEP(HHFormat("setEra(%d)", (int)pg->era()), pg->setEra(pg->era()));
	// Already cached: a no-op unless the database was flushed (kept for the call order).
	if(kIf.pDbUtil)
		HH_STEP("CacheGameDatabaseData()", kIf.pDbUtil->CacheGameDatabaseData());

	// Checks.
	bool bOk = true;
	if(pg->worldSize() != (WorldSizeTypes)iWorldSize)
	{
		kResult.error = HHFormat("world size %d did not stick (pregame says %d)", iWorldSize, (int)pg->worldSize());
		bOk = false;
	}
	if(pg->isWBMapScript() != bCiv5Map)
	{
		kResult.error = HHFormat("isWBMapScript() = %d for map kind %s", pg->isWBMapScript() ? 1 : 0, kMap["kind"].AsString().c_str());
		bOk = false;
	}
	for(size_t i = 0; i < kSlots.Size(); ++i)
	{
		const HHJson& s = kSlots.At(i);
		const PlayerTypes p = (PlayerTypes)s["slot"].AsInt();
		const int iCiv = s["civId"].AsInt(-1);
		if(iCiv >= 0 && pg->civilization(p) != (CivilizationTypes)iCiv)
		{
			kResult.error = HHFormat("slot %d: civilization %d did not stick (%d)", (int)p, iCiv, (int)pg->civilization(p));
			bOk = false;
		}
	}
	kResult.timings.push_back(std::make_pair(std::string("pregame"), Now() - t0));
	kResult.bPregameOk = bOk;
	return bOk;
}

//------------------------------------------------------------------------------
// Task 4: start sequence
//------------------------------------------------------------------------------
namespace
{
	// True when the DLL implements seed pinning through <cache>\HeadlessSeeds.txt (hh-digest).
	bool DllHasSeedPinning(const std::string& strDll)
	{
		FILE* f = _wfopen(HHWiden(strDll).c_str(), L"rb");
		if(!f)
			return false;
		std::string data;
		char buf[1 << 16];
		size_t n;
		while((n = fread(buf, 1, sizeof(buf), f)) > 0)
			data.append(buf, n);
		fclose(f);
		return data.find("HeadlessSeeds.txt") != std::string::npos;
	}

	// The exe's leader choice (trace S1, between ICvGame1::Init and Init2): a DLL random
	// number generator seeded with the pregame sync seed; for every active major slot one
	// Get(10000, "Choosing Leader") per leader of its civilization, then setLeaderHead.
	// ASSUMPTION (trace): with several leaders the highest draw wins (every civilization in
	// the VP database has exactly one leader, so the choice cannot be observed).
	void ChooseLeaders(HHNewGameInterfaces& kIf, HHNewGameResult& kResult)
	{
		ICvPreGame1* pg = kIf.pPreGame;
		const unsigned int uiRng = kIf.pContext->CreateRandomNumberGenerator();
		ICvRandom1* pRng = kIf.pContext->GetRandomNumberGenerator(uiRng);
		if(!pRng)
		{
			HHLogError("CreateRandomNumberGenerator failed; leaders not chosen");
			return;
		}
		pRng->Init(pg->syncRandomSeed());
		const int nLeaders = kIf.pContext->GetNumLeaderHeadInfos();
		for(int i = 0; i < kMaxMajorCivs; ++i)
		{
			const PlayerTypes p = (PlayerTypes)i;
			const SlotStatus eStatus = pg->slotStatus(p);
			if(eStatus != SS_TAKEN && eStatus != SS_COMPUTER)
				continue;
			const CivilizationTypes eCiv = pg->civilization(p);
			if(eCiv == NO_CIVILIZATION || pg->leaderHead(p) != NO_LEADER)
				continue;
			ICvCivilizationInfo1* pCiv = kIf.pContext->GetCivilizationInfo(eCiv);
			if(!pCiv)
				continue;
			int iBest = -1, iBestDraw = -1;
			for(int l = 0; l < nLeaders; ++l)
			{
				if(!pCiv->IsLeaders(l))
					continue;
				const int iDraw = pRng->Get(10000, "Choosing Leader");
				if(iDraw > iBestDraw)
				{
					iBestDraw = iDraw;
					iBest = l;
				}
			}
			pCiv->Destroy();
			if(iBest >= 0)
				HH_STEP(HHFormat("setLeaderHead(%d, %d)", i, iBest), pg->setLeaderHead(p, (LeaderHeadTypes)iBest));
		}
		pRng->Destroy();
		kIf.pContext->DestroyRandomNumberGenerator(uiRng);
	}
}

bool HHStartNewGame(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult)
{
	ICvPreGame1* pg = kIf.pPreGame;
	double t0 = Now();

	// 1. Premade map (trace S3, hh-m0-s3s4-earth): Preload(path, loadWBScenario), map info,
	//    setMapNoPlayers, the map's world size (no slot reset), all before closeInactiveSlots.
	//    The exe passes the game-relative name; the host passes the full path (its working
	//    directory is the run folder).
	if(pg->isWBMapScript())
	{
		std::string path = Slashes(kSpec["map"]["file"].AsString());
		if(!IsAbsolutePath(path))
			path = HHGetOptions().gameDir + "\\" + path;
		bool bLoaded = false;
		HH_STEP(HHFormat("WorldBuilderMapLoader.Preload(\"%s\", false)", path.c_str()), bLoaded = kIf.pWBLoader->Preload(HHWiden(path).c_str(), pg->loadWBScenario()));
		if(!bLoaded)
		{
			kResult.error = "Preload failed for " + path;
			return false;
		}
		const CvWorldBuilderMapLoaderMapInfo& info = kIf.pWBLoader->GetCurrentMapInfo();
		HHLog("premade map %s: %ux%u, %u players, %u city-states, %u/%u start positions, wrap %d, random resources %d", path.c_str(),
		      info.uiWidth, info.uiHeight, info.uiPlayers, info.uiCityStates, info.uiMajorCivStartingPositions,
		      info.uiMinorCivStartingPositions, info.bWorldWrap ? 1 : 0, info.bRandomResources ? 1 : 0);
		// ASSUMPTION (trace): the flag is "the map file has no players" (Earth: true in S3).
		const bool bNoPlayers = info.uiPlayers == 0;
		HH_STEP(HHFormat("setMapNoPlayers(%s)", bNoPlayers ? "true" : "false"), pg->setMapNoPlayers(bNoPlayers));
		ICvWorldBuilderMapLoader2* pWB2 = kIf.pWBLoader->QueryInterface<ICvWorldBuilderMapLoader2>();
		if(pWB2)
		{
			const WorldSizeTypes eSize = pWB2->GetWorldSizeType();
			HH_STEP(HHFormat("setWorldSize(%d, false)", (int)eSize), pg->setWorldSize(eSize, false));
		}
	}

	// 2. closeInactiveSlots marks the game started, which runs VP's CvPreGame::onGameStarted:
	//    random civilizations for slots without one and the city-state selection, drawn with
	//    the pregame map seed (CvGame::urandLimitExclusive) - in the real game the engine's
	//    own seed, before the spec seeds are pinned. Then open slots are closed and player
	//    info is sent (no-op single player).
	HH_STEP("closeInactiveSlots()", pg->closeInactiveSlots());
	kResult.timings.push_back(std::make_pair(std::string("launch"), Now() - t0));

	// 3. Seeds. The real driver writes <cache>\HeadlessSeeds.txt and the DLL pins the spec
	//    seeds at the start of CvGame::init (HHSEEDS source=file). A DLL without seed pinning
	//    gets them in pregame directly, just before Init.
	const unsigned int uiMapSeed = SeedValue(kSpec["seeds"]["map"]);
	const unsigned int uiSyncSeed = SeedValue(kSpec["seeds"]["sync"]);
	if(DllHasSeedPinning(HHGetOptions().dllPath))
	{
		const std::string seedFile = HHGetPaths().cache + "HeadlessSeeds.txt";
		// Same keys as vpbench's driver (digest=1: per-turn digest logging from turn 0).
		HHWriteTextFile(seedFile, HHFormat("map=%u\nsync=%u\ndigest=1\n", uiMapSeed, uiSyncSeed));
		kResult.steps.push_back(HHFormat("write %s: map=%u sync=%u", seedFile.c_str(), uiMapSeed, uiSyncSeed));
		kResult.seedMode = "HeadlessSeeds.txt";
	}
	else
	{
		HH_STEP(HHFormat("setMapRandomSeed(%u)", uiMapSeed), pg->setMapRandomSeed(uiMapSeed));
		HH_STEP(HHFormat("setSyncRandomSeed(%u)", uiSyncSeed), pg->setSyncRandomSeed(uiSyncSeed));
		kResult.seedMode = "pregame";
	}

	// 4. ICvGame1::Init(handicap of the active player): reset, RNGs from the pregame seeds,
	//    game id, start turn and max turns.
	t0 = Now();
	const HandicapTypes eHandicap = pg->handicap(pg->activePlayer());
	HH_STEP(HHFormat("Game.Init(%d)", (int)eHandicap), kIf.pGame->Init(eHandicap));
	if(pg->mapRandomSeed() != uiMapSeed || pg->syncRandomSeed() != uiSyncSeed)
		HHLogError("seeds after Game.Init: map %u sync %u, expected %u/%u", pg->mapRandomSeed(), pg->syncRandomSeed(), uiMapSeed, uiSyncSeed);
	if(kIf.pDbUtil)
		HH_STEP("CacheGameDatabaseData()", kIf.pDbUtil->CacheGameDatabaseData());
	ChooseLeaders(kIf, kResult);
	for(int i = 0; i < kMaxMajorCivs; ++i)
	{
		const PlayerTypes p = (PlayerTypes)i;
		if(pg->slotStatus(p) == SS_TAKEN || pg->slotStatus(p) == SS_COMPUTER)
			HHLog("  slot %2d: status %d civ %d leader %d team %d handicap %d", i, (int)pg->slotStatus(p), (int)pg->civilization(p),
			      (int)pg->leaderHead(p), (int)pg->teamType(p), (int)pg->handicap(p));
	}
	kResult.timings.push_back(std::make_pair(std::string("game_init"), Now() - t0));

	// 5. ICvGame1::Init2: players (colours, AI handicaps, city-state slots), map
	//    (CvMapGenerator: the map script's GetMapInitData and GenerateMap, start positions;
	//    or the premade map), diplomacy, initial units, score, final initialisation.
	t0 = Now();
	bool bInit2 = false;
	HH_STEP("Game.Init2()", bInit2 = kIf.pGame->Init2());
	kResult.timings.push_back(std::make_pair(std::string("game_init2_mapgen"), Now() - t0));
	if(!bInit2)
	{
		kResult.error = "ICvGame1::Init2 returned false";
		return false;
	}

	// 6. After Init2 (trace S1): LaterInit for every player slot, InitTacticalAnalysisMap
	//    (a no-op in VP), the in-game UI's SetGameOption calls, then DoGameStarted (and
	//    InitExeStuff: BIN_UNKNOWN for this exe). The exe's SetInitialTime/SetStartTime (wall
	//    clock) are not called.
	t0 = Now();
	for(int i = 0; i < MAX_PLAYERS; ++i)
	{
		ICvPlayer1* pPlayer = kIf.pGame->GetPlayer((PlayerTypes)i);
		if(pPlayer)
		{
			pPlayer->LaterInit();
			pPlayer->Destroy();
		}
	}
	kResult.steps.push_back(HHFormat("for i = 0..%d: Game.GetPlayer(i).LaterInit()", MAX_PLAYERS - 1));
	const int iPlots = kIf.pMap->NumPlots();
	HH_STEP(HHFormat("Game.InitTacticalAnalysisMap(%d)", iPlots), kIf.pGame->InitTacticalAnalysisMap(iPlots));
	// ASSUMPTION (trace): the in-game UI's start-up sets these three options to 0 (S1 shows
	// the calls between InitTacticalAnalysisMap and DoGameStarted).
	HH_STEP("SetGameOption(\"GAMEOPTION_DYNAMIC_TURNS\", 0)", pg->SetGameOption("GAMEOPTION_DYNAMIC_TURNS", 0));
	HH_STEP("SetGameOption(\"GAMEOPTION_SIMULTANEOUS_TURNS\", 0)", pg->SetGameOption("GAMEOPTION_SIMULTANEOUS_TURNS", 0));
	HH_STEP("SetGameOption(\"GAMEOPTION_PITBOSS\", 0)", pg->SetGameOption("GAMEOPTION_PITBOSS", 0));
	HH_STEP("Game.DoGameStarted()", kIf.pGame->DoGameStarted());
	// Trace S1, before the first ICvGame1::Update: NetMessageStaticsReset, then
	// SendPlayerOptions(true) (the DLL reads each option from the engine and sends it), and
	// the engine delivers the sent values back as NetMessageHandler::ResponsePlayerOption
	// for the active player. (The network-sync delta clears and the UI's SelectSettler and
	// RebroadcastNotifications that follow do not change saved state and are skipped.)
	if(ICvGame2* pGame2 = kIf.pGame->QueryInterface<ICvGame2>())
		HH_STEP("Game.NetMessageStaticsReset()", pGame2->NetMessageStaticsReset());
	HH_STEP("Game.SendPlayerOptions(true)", kIf.pGame->SendPlayerOptions(true));
	if(kIf.pEngine)
	{
		ICvNetMessageHandler1* pHandler = kIf.pContext->GetNetMessageHandler();
		const size_t nOptions = kIf.pEngine->GetPendingPlayerOptionCount();
		if(pHandler)
			kIf.pEngine->DeliverPlayerOptions(pHandler, pg->activePlayer());
		kResult.steps.push_back(HHFormat("NetMessageHandler.ResponsePlayerOption(%d, i, value) x%u", (int)pg->activePlayer(), (unsigned)nOptions));
	}
	kResult.timings.push_back(std::make_pair(std::string("game_started"), Now() - t0));

	kResult.iWidth = kIf.pMap->GetGridWidth();
	kResult.iHeight = kIf.pMap->GetGridHeight();
	HHLog("game started: map %dx%d (%d plots), turn %d, final initialised %d", kResult.iWidth, kResult.iHeight, iPlots,
	      kIf.pGame->GetGameTurn(), kIf.pGame->IsFinalInitialized() ? 1 : 0);
	kResult.bStarted = true;
	return true;
}

//------------------------------------------------------------------------------
// Task 5: T000 outputs
//------------------------------------------------------------------------------
namespace
{
	// Map summary: everything map generation decided, by type name.
	const char* kMapLua =
		"local function T(tbl, id) if id == nil or id < 0 then return nil end local r = tbl[id] return r and r.Type or id end\n"
		"local w, h = Map.GetGridSize()\n"
		"local out = {format = 'civ5headless-t000-map/1', width = w, height = h, wrapX = Map.IsWrapX(), wrapY = Map.IsWrapY(),\n"
		"  numPlots = Map.GetNumPlots(), turn = Game.GetGameTurn(), players = {}, cityStates = {}, plots = {}}\n"
		"for i = 0, 63 do\n"
		"  local p = Players[i]\n"
		"  if p and p:IsEverAlive() then\n"
		"    local sp = p:GetStartingPlot()\n"
		"    local e = {slot = i, civilization = T(GameInfo.Civilizations, p:GetCivilizationType()), leader = T(GameInfo.Leaders, p:GetLeaderType()),\n"
		"      team = p:GetTeam(), minor = p:IsMinorCiv(), barbarian = p:IsBarbarian(), human = p:IsHuman(),\n"
		"      handicap = T(GameInfo.HandicapInfos, p:GetHandicapType()), startX = sp and sp:GetX() or nil, startY = sp and sp:GetY() or nil,\n"
		"      units = p:GetNumUnits(), cities = p:GetNumCities()}\n"
		"    if p:IsMinorCiv() then e.minorCiv = T(GameInfo.MinorCivilizations, p:GetMinorCivType()); out.cityStates[#out.cityStates + 1] = e.minorCiv end\n"
		"    local units = {}\n"
		"    for u in p:Units() do units[#units + 1] = {T(GameInfo.Units, u:GetUnitType()), u:GetX(), u:GetY()} end\n"
		"    e.unitList = units\n"
		"    out.players[#out.players + 1] = e\n"
		"  end\n"
		"end\n"
		"for i = 0, Map.GetNumPlots() - 1 do\n"
		"  local pl = Map.GetPlotByIndex(i)\n"
		"  local res = pl:GetResourceType(-1)\n"
		"  out.plots[#out.plots + 1] = {i = i, x = pl:GetX(), y = pl:GetY(), plotType = pl:GetPlotType(), terrain = T(GameInfo.Terrains, pl:GetTerrainType()),\n"
		"    feature = T(GameInfo.Features, pl:GetFeatureType()), resource = T(GameInfo.Resources, res), resourceAmount = res >= 0 and pl:GetNumResource() or 0,\n"
		"    riverW = pl:IsWOfRiver(), riverNW = pl:IsNWOfRiver(), riverNE = pl:IsNEOfRiver(),\n"
		"    flowE = pl:GetRiverEFlowDirection(), flowSE = pl:GetRiverSEFlowDirection(), flowSW = pl:GetRiverSWFlowDirection(),\n"
		"    improvement = T(GameInfo.Improvements, pl:GetImprovementType()), owner = pl:GetOwner(), area = pl:GetArea(), landmass = pl:GetLandmass(),\n"
		"    continentArt = pl:GetContinentArtType(), naturalWonder = pl:IsNaturalWonder() or nil}\n"
		"end\n"
		"return out\n";

	// Verbatim copy of vpbench.py CHECKPOINT (work/vpbench/vpbench.py); keep in sync.
	const char* kCheckpointLua =
		"local active=Game.GetActivePlayer()\n"
		"local out={turn=Game.GetGameTurn(),activePlayer=active,autoplay=Game.GetAIAutoPlay(),observer=Players[active]:IsObserver(),human=Players[active]:IsHuman(),pausePlayer=Game.GetPausePlayer(),replayCount=Game.GetNumReplayMessages(),winner=Game.GetWinner(),players={},cities={},wars={},livingMajors={}}\n"
		"for owner=0,63 do\n"
		" local p=Players[owner]\n"
		" if p and p:IsAlive() and not p:IsObserver() then\n"
		"  local civ=GameInfo.Civilizations[p:GetCivilizationType()]\n"
		"  out.players[#out.players+1]={owner=owner,team=p:GetTeam(),civilization=civ and civ.Type or '',minor=p:IsMinorCiv(),barbarian=p:IsBarbarian(),unitCount=p:GetNumUnits(),cityCount=p:GetNumCities(),military=p:GetNumMilitaryUnits(),score=(not p:IsMinorCiv() and not p:IsBarbarian()) and p:GetScore() or 0,techs=Teams[p:GetTeam()]:GetTeamTechs():GetNumTechsKnown()}\n"
		"  if not p:IsMinorCiv() and not p:IsBarbarian() then out.livingMajors[#out.livingMajors+1]=owner end\n"
		"  for city in p:Cities() do\n"
		"   out.cities[#out.cities+1]={plot=city:Plot():GetPlotIndex(),owner=owner,name=city:GetName(),originalOwner=city:GetOriginalOwner(),foundedTurn=city:GetGameTurnFounded(),acquiredTurn=city:GetGameTurnAcquired(),hp=city:GetMaxHitPoints()-city:GetDamage(),maxHP=city:GetMaxHitPoints(),population=city:GetPopulation()}\n"
		"  end\n"
		"  if not p:IsBarbarian() then\n"
		"   for other=owner+1,63 do local q=Players[other];if q and q:IsAlive() and not q:IsObserver() and not q:IsBarbarian() and Teams[p:GetTeam()]:IsAtWar(q:GetTeam()) then out.wars[#out.wars+1]={owner,other} end end\n"
		"  end\n"
		" end\n"
		"end\n"
		"local camp=GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP;out.barbCamps=0\n"
		"for i=0,Map.GetNumPlots()-1 do if Map.GetPlotByIndex(i):GetImprovementType()==camp then out.barbCamps=out.barbCamps+1 end end\n"
		"return out\n";

	// Game.GetHeadlessDigest (hh-digest, docs/headless-dll-additions.md): the DLL's state digest
	// at T000. Absent from DLLs built without the headless additions.
	const char* kDigestLua =
		"if Game.GetHeadlessDigest == nil then return nil end\n"
		"return Game.GetHeadlessDigest()\n";

	// Runs a chunk that returns one value in a fresh thread; leaves the value on the thread
	// stack (index -1) and returns the thread, or NULL on error.
	lua_State* RunReturning(HHScriptSystem& kScripts, const char* szName, const char* szChunk)
	{
		lua_State* L = kScripts.CreateLuaThread(szName);
		if(!L)
			return NULL;
		if(luaL_loadbuffer(L, szChunk, strlen(szChunk), szName) != 0)
		{
			HHLogError("%s: %s", szName, lua_tostring(L, -1));
			kScripts.FreeLuaThread(L);
			return NULL;
		}
		if(!kScripts.CallFunction(L, 0, 1))
		{
			kScripts.FreeLuaThread(L);
			return NULL;
		}
		return L;
	}

	std::string UtcNow()
	{
		SYSTEMTIME st;
		GetSystemTime(&st);
		return HHFormat("%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
	}

	// Writes the map table: top level pretty-printed, one plot per line.
	std::string MapJson(lua_State* L, int idx)
	{
		std::vector<std::string> keys;
		lua_pushnil(L);
		while(lua_next(L, idx) != 0)
		{
			if(lua_type(L, -2) == LUA_TSTRING)
				keys.push_back(lua_tostring(L, -2));
			lua_pop(L, 1);
		}
		std::sort(keys.begin(), keys.end());
		std::string out = "{";
		for(size_t i = 0; i < keys.size(); ++i)
		{
			out += i ? ",\n " : "\n ";
			out += "\"" + HHJsonEscape(keys[i]) + "\": ";
			lua_getfield(L, idx, keys[i].c_str());
			if((keys[i] == "plots" || keys[i] == "players") && lua_istable(L, -1))
			{
				const int t = lua_gettop(L);
				const int n = (int)lua_objlen(L, t);
				out += "[";
				for(int k = 1; k <= n; ++k)
				{
					lua_rawgeti(L, t, k);
					out += k > 1 ? ",\n  " : "\n  ";
					out += HHLuaToJson(L, -1, 0);
					lua_pop(L, 1);
				}
				out += n ? "\n ]" : "]";
			}
			else
				out += HHLuaToJson(L, -1, 0);
			lua_pop(L, 1);
		}
		out += "\n}\n";
		return out;
	}
}

bool HHWriteT000(const HHJson& kSpec, HHNewGameInterfaces& kIf, HHNewGameResult& kResult)
{
	UNUSED_VARIABLE(kSpec);
	const double t0 = Now();
	const std::string run = HHGetPaths().run;
	bool bOk = true;

	// t000-map.json: deterministic (no times); identical across runs of the same spec.
	if(lua_State* L = RunReturning(*kIf.pScripts, "Headless T000 map", kMapLua))
	{
		if(lua_istable(L, -1))
			bOk &= HHWriteTextFile(run + "t000-map.json", MapJson(L, lua_gettop(L)));
		else
			bOk = false;
		kIf.pScripts->FreeLuaThread(L);
	}
	else
		bOk = false;

	// checkpoints/turn-0000.json: vpbench's CHECKPOINT result, wrapped as vpbench writes it.
	HHEnsureDirectory(run + "checkpoints");
	if(lua_State* L = RunReturning(*kIf.pScripts, "Headless checkpoint", kCheckpointLua))
	{
		const std::string json = "{\n \"utc\": \"" + UtcNow() + "\",\n \"data\": " + HHLuaToJson(L, -1, 0) + "\n}\n";
		bOk &= HHWriteTextFile(run + "checkpoints\\turn-0000.json", json);
		kIf.pScripts->FreeLuaThread(L);
	}
	else
		bOk = false;

	// ------------------------------------------------------------------------------------
	// HEADLESS DIGEST: Game.GetHeadlessDigest() at T000 (DLL additions D2). Written to
	// t000-digest.json when the DLL provides it; the total goes into newgame-report.json.
	// ------------------------------------------------------------------------------------
	if(lua_State* L = RunReturning(*kIf.pScripts, "Headless digest", kDigestLua))
	{
		if(lua_istable(L, -1))
		{
			bOk &= HHWriteTextFile(run + "t000-digest.json", HHLuaToJson(L, -1, 1) + "\n");
			lua_getfield(L, -1, "total");
			if(lua_isstring(L, -1))
				kResult.digestTotal = lua_tostring(L, -1);
			lua_pop(L, 1);
		}
		else
			HHLog("Game.GetHeadlessDigest is not available in this DLL; no t000-digest.json");
		kIf.pScripts->FreeLuaThread(L);
	}
	// Raw section bytes (<run>\dump-t000\<section>.bin + digest.txt), the same layout as the
	// real-game probe dumps, for byte-level comparison (tools/headless/hhdigest.py).
	{
		std::string folder = run + "dump-t000";
		std::string chunk = "if Game.DumpHeadlessState == nil then return nil end\nreturn Game.DumpHeadlessState([==[" + folder + "]==])\n";
		if(lua_State* L = RunReturning(*kIf.pScripts, "Headless dump", chunk.c_str()))
			kIf.pScripts->FreeLuaThread(L);
	}

	kResult.timings.push_back(std::make_pair(std::string("t000_outputs"), Now() - t0));
	kResult.bOutputsOk = bOk;
	return bOk;
}

void HHEndNewGame(HHNewGameInterfaces& kIf, HHNewGameResult& kResult)
{
	// ASSUMPTION (trace): leaving a game, the exe clears pregame's started flag before
	// ICvGame1::Uninit (CvDllGame::Uninit traps while it is set).
	HH_STEP("setGameStarted(false)", kIf.pPreGame->setGameStarted(false));
	HH_STEP("Game.Uninit()", kIf.pGame->Uninit());
}
