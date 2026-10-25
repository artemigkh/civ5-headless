#include "engine/HHEngineServices.h"
#include "engine/HHRuntime.h"

namespace
{
	std::string GuidToString(const GUID& g)
	{
		return HHFormat("%08lX-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X", g.Data1, g.Data2, g.Data3,
		                g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6], g.Data4[7]);
	}

	std::string NormaliseId(const char* sz)
	{
		std::string s = HHLower(sz ? sz : "");
		// Accept "{...}" as well as bare GUIDs.
		if(s.size() >= 2 && s[0] == '{' && s[s.size() - 1] == '}')
			s = s.substr(1, s.size() - 2);
		return s;
	}
}

//------------------------------------------------------------------------------
// HHEngineUtility
//------------------------------------------------------------------------------
HHEngineUtility::HHEngineUtility(ICvEngineScriptSystem1* pScriptSystem)
	: m_pScriptSystem(pScriptSystem), m_bDone(false), m_pPreGame(NULL), m_bAICivsProcessed(false), m_bAICivsProcessedPending(false),
	  m_iLockDepth(0), m_bInGameCoreUpdate(false)
{
	m_strCacheFolder = HHGetPaths().cache;
}

void* HHEngineUtility::QueryInterface(GUID guidInterface)
{
	HH_IMPL_CALL("ICvUnknown::QueryInterface");
	if(guidInterface == ICvUnknown::GetInterfaceId() ||
	   guidInterface == ICvEngineUtility1::GetInterfaceId() ||
	   guidInterface == ICvEngineUtility2::GetInterfaceId() ||
	   guidInterface == ICvEngineUtility3::GetInterfaceId() ||
	   guidInterface == ICvEngineUtility4::GetInterfaceId())
	{
		return this;
	}
	HHLog("ICvEngineUtility::QueryInterface: unsupported interface %s", GuidToString(guidInterface).c_str());
	return NULL;
}

void HHEngineUtility::Destroy()
{
	// The host owns the single instance; the DLL calls Destroy when it drops its pointer.
	HH_IMPL_CALL("ICvUnknown::Destroy");
}

ICvEngineScriptSystem1* HHEngineUtility::GetScriptSystem()
{
	HH_IMPL_CALL("ICvEngineUtility1::GetScriptSystem");
	return m_pScriptSystem;
}

bool HHEngineUtility::IsHost() const
{
	HH_IMPL_CALL("ICvEngineUtility1::IsHost");
	return true;
}

bool HHEngineUtility::IsModActivated(const char* szModID)
{
	HH_IMPL_CALL("ICvEngineUtility1::IsModActivated");
	const std::string id = NormaliseId(szModID);
	const std::vector<HHModRef>& mods = HHGetOptions().mods;
	for(size_t i = 0; i < mods.size(); ++i)
		if(NormaliseId(mods[i].id.c_str()) == id)
			return true;
	return false;
}

bool HHEngineUtility::IsModActivated(const char* szModID, int iVersion)
{
	HH_IMPL_CALL("ICvEngineUtility1::IsModActivated");
	const std::string id = NormaliseId(szModID);
	const std::vector<HHModRef>& mods = HHGetOptions().mods;
	for(size_t i = 0; i < mods.size(); ++i)
		if(NormaliseId(mods[i].id.c_str()) == id && (mods[i].version < 0 || mods[i].version == iVersion))
			return true;
	return false;
}

bool HHEngineUtility::IsDLCValid(const GUID& kID) const
{
	HH_IMPL_CALL("ICvEngineUtility1::IsDLCValid");
	const std::vector<std::string>& dlcs = HHGetOptions().dlcs;
	if(dlcs.empty())
		return true; // complete install: every DLC package is present
	const std::string id = HHLower(GuidToString(kID));
	for(size_t i = 0; i < dlcs.size(); ++i)
		if(NormaliseId(dlcs[i].c_str()) == id)
			return true;
	return false;
}

bool HHEngineUtility::IsPitbossHost() const
{
	HH_IMPL_CALL("ICvEngineUtility1::IsPitbossHost");
	return false;
}

void HHEngineUtility::InitGlobals()
{
	HH_IMPL_CALL("ICvEngineUtility1::InitGlobals");
}

void HHEngineUtility::UninitGlobals()
{
	HH_IMPL_CALL("ICvEngineUtility1::UninitGlobals");
}

void HHEngineUtility::SetDone(bool bDone)
{
	HH_IMPL_CALL("ICvEngineUtility1::SetDone");
	m_bDone = bDone;
}

bool HHEngineUtility::GetDone()
{
	HH_IMPL_CALL("ICvEngineUtility1::GetDone");
	return m_bDone;
}

bool HHEngineUtility::GetAutorun()
{
	HH_IMPL_CALL("ICvEngineUtility1::GetAutorun");
	return false;
}

bool HHEngineUtility::altKey() { HH_IMPL_CALL("ICvEngineUtility1::altKey"); return false; }
bool HHEngineUtility::shiftKey() { HH_IMPL_CALL("ICvEngineUtility1::shiftKey"); return false; }
bool HHEngineUtility::ctrlKey() { HH_IMPL_CALL("ICvEngineUtility1::ctrlKey"); return false; }

// Player options: the DLL asks by FStringHash(type) (= ~CRC32 of the type name, checked
// against the S1 trace) and sends each value back to the engine, which delivers it to the
// game as NetMessageHandler::ResponsePlayerOption(player, option index, value).
namespace
{
	unsigned int Crc32(const char* sz)
	{
		static unsigned int table[256];
		static bool bInit = false;
		if(!bInit)
		{
			for(unsigned int i = 0; i < 256; ++i)
			{
				unsigned int c = i;
				for(int k = 0; k < 8; ++k)
					c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
				table[i] = c;
			}
			bInit = true;
		}
		unsigned int crc = 0xFFFFFFFFu;
		for(const unsigned char* p = (const unsigned char*)sz; *p; ++p)
			crc = table[(crc ^ *p) & 0xFF] ^ (crc >> 8);
		return crc; // no final inversion: FStringHash
	}
}

void HHEngineUtility::AddPlayerOption(const char* szType, int iIndex, bool bValue)
{
	HHPlayerOption o;
	o.type = szType;
	o.index = iIndex;
	o.value = bValue;
	m_playerOptions[Crc32(szType)] = o;
}

bool HHEngineUtility::SetPlayerOptionValue(const std::string& strType, bool bValue)
{
	std::map<unsigned int, HHPlayerOption>::iterator it = m_playerOptions.find(Crc32(strType.c_str()));
	if(it == m_playerOptions.end())
		return false;
	it->second.value = bValue;
	return true;
}

bool HHEngineUtility::getPlayerOption(PlayerOptionTypes eOption)
{
	HH_IMPL_CALL("ICvEngineUtility1::getPlayerOption");
	std::map<unsigned int, HHPlayerOption>::const_iterator it = m_playerOptions.find((unsigned int)eOption);
	return it != m_playerOptions.end() && it->second.value;
}

void HHEngineUtility::sendPlayerOption(PlayerOptionTypes eOption, bool bValue)
{
	HH_IMPL_CALL("ICvEngineUtility1::sendPlayerOption");
	std::map<unsigned int, HHPlayerOption>::const_iterator it = m_playerOptions.find((unsigned int)eOption);
	if(it == m_playerOptions.end())
	{
		HHLogError("sendPlayerOption: unknown option hash %d", (int)eOption);
		return;
	}
	// Measured (S3b): the engine answers with its own option index for the 11 options it knows
	// (the base game's PlayerOptions rows 0..10) and with the type hash for any other row
	// (PLAYEROPTION_QUICK_SELECTION_ADVANCE, row 11, arrives as -542730216).
	const int iDelivered = (it->second.index >= 0 && it->second.index < kEngineKnownPlayerOptions) ? it->second.index : (int)eOption;
	// Delivered for the player that was active when it was sent (AA100: player 8 after SetAIAutoPlay).
	Queue(HHNetMessage::PLAYER_OPTION, "PlayerOption", (int)ActivePlayer(), iDelivered, bValue ? 1 : 0);
}

PlayerTypes HHEngineUtility::ActivePlayer() const
{
	return m_pPreGame ? m_pPreGame->activePlayer() : (PlayerTypes)0;
}

void HHEngineUtility::Queue(HHNetMessage::Kind eKind, const char* szName, int a0, int a1, int a2, int a3, int a4, int a5)
{
	HHNetMessage m;
	m.eKind = eKind;
	m.a[0] = a0; m.a[1] = a1; m.a[2] = a2; m.a[3] = a3; m.a[4] = a4; m.a[5] = a5;
	m_pendingNet.push_back(m);
	++m_netCounts[szName];
}

size_t HHEngineUtility::DeliverNetMessages(ICvNetMessageHandler1* pHandler)
{
	if(!pHandler || m_pendingNet.empty())
		return 0;
	ICvNetMessageHandler2* pHandler2 = pHandler->QueryInterface<ICvNetMessageHandler2>();
	ICvNetMessageHandler3* pHandler3 = pHandler->QueryInterface<ICvNetMessageHandler3>();
	// A Response can send again; the loop delivers that too (the engine would on its next frame,
	// still before the next Update).
	size_t n = 0;
	for(size_t i = 0; i < m_pendingNet.size(); ++i, ++n)
	{
		const HHNetMessage m = m_pendingNet[i];
		const int* a = m.a;
		switch(m.eKind)
		{
		case HHNetMessage::PLAYER_OPTION: pHandler->ResponsePlayerOption((PlayerTypes)a[0], (PlayerOptionTypes)a[1], a[2] != 0); break;
		case HHNetMessage::MINOR_GIFT_GOLD: pHandler->ResponseMinorCivGiftGold((PlayerTypes)a[0], (PlayerTypes)a[1], a[2]); break;
		case HHNetMessage::GREAT_PERSON_CHOICE: pHandler->ResponseGreatPersonChoice((PlayerTypes)a[0], (UnitTypes)a[1]); break;
		case HHNetMessage::PLEDGE_MINOR_PROTECTION: if(pHandler2) pHandler2->ResponsePledgeMinorProtection((PlayerTypes)a[0], (PlayerTypes)a[1], a[2] != 0, a[3] != 0); break;
		case HHNetMessage::MINOR_BULLY_GOLD: if(pHandler2) pHandler2->ResponseMinorCivBullyGold((PlayerTypes)a[0], (PlayerTypes)a[1], a[2]); break;
		case HHNetMessage::MINOR_BULLY_UNIT: if(pHandler2) pHandler2->ResponseMinorCivBullyUnit((PlayerTypes)a[0], (PlayerTypes)a[1], (UnitTypes)a[2]); break;
		case HHNetMessage::MINOR_GIFT_TILE_IMPROVEMENT: if(pHandler2) pHandler2->ResponseMinorCivGiftTileImprovement((PlayerTypes)a[0], (PlayerTypes)a[1], a[2], a[3]); break;
		case HHNetMessage::MINOR_BUYOUT: if(pHandler2) pHandler2->ResponseMinorCivBuyout((PlayerTypes)a[0], (PlayerTypes)a[1]); break;
		case HHNetMessage::MAYA_BONUS_CHOICE: if(pHandler2) pHandler2->ResponseMayaBonusChoice((PlayerTypes)a[0], (UnitTypes)a[1]); break;
		case HHNetMessage::FAITH_GREAT_PERSON_CHOICE: if(pHandler2) pHandler2->ResponseFaithGreatPersonChoice((PlayerTypes)a[0], (UnitTypes)a[1]); break;
		case HHNetMessage::GOODY_CHOICE: if(pHandler3) pHandler3->ResponseGoodyChoice((PlayerTypes)a[0], a[1], a[2], (GoodyTypes)a[3], a[4]); break;
		}
	}
	m_pendingNet.clear();
	if(pHandler3)
		pHandler3->Destroy();
	if(pHandler2)
		pHandler2->Destroy();
	return n;
}

void HHEngineUtility::sendMinorPledgeProtection(PlayerTypes eMajor, PlayerTypes eMinor, bool bProtect, bool bPledgeNowBroken)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorPledgeProtection"); Queue(HHNetMessage::PLEDGE_MINOR_PROTECTION, "PledgeMinorProtection", eMajor, eMinor, bProtect, bPledgeNowBroken); }
// The sender of a message without a player argument is the local (active) player.
void HHEngineUtility::sendMinorGiftGold(PlayerTypes eMinor, int iGold)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorGiftGold"); Queue(HHNetMessage::MINOR_GIFT_GOLD, "MinorGiftGold", ActivePlayer(), eMinor, iGold); }
void HHEngineUtility::sendMinorGiftTileImprovement(PlayerTypes eMajor, PlayerTypes eMinor, int iPlotX, int iPlotY)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorGiftTileImprovement"); Queue(HHNetMessage::MINOR_GIFT_TILE_IMPROVEMENT, "MinorGiftTileImprovement", eMajor, eMinor, iPlotX, iPlotY); }
void HHEngineUtility::sendMinorBullyGold(PlayerTypes eBully, PlayerTypes eMinor, int iGold)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorBullyGold"); Queue(HHNetMessage::MINOR_BULLY_GOLD, "MinorBullyGold", eBully, eMinor, iGold); }
void HHEngineUtility::sendMinorBullyUnit(PlayerTypes eBully, PlayerTypes eMinor, UnitTypes eUnitType)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorBullyUnit"); Queue(HHNetMessage::MINOR_BULLY_UNIT, "MinorBullyUnit", eBully, eMinor, eUnitType); }
void HHEngineUtility::sendMinorBuyout(PlayerTypes eMajor, PlayerTypes eMinor)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMinorBuyout"); Queue(HHNetMessage::MINOR_BUYOUT, "MinorBuyout", eMajor, eMinor); }
void HHEngineUtility::sendGreatPersonChoice(PlayerTypes ePlayer, UnitTypes eUnit)
{ HH_IMPL_CALL("ICvEngineUtility1::sendGreatPersonChoice"); Queue(HHNetMessage::GREAT_PERSON_CHOICE, "GreatPersonChoice", ePlayer, eUnit); }
void HHEngineUtility::sendMayaBonusChoice(PlayerTypes ePlayer, UnitTypes eUnit)
{ HH_IMPL_CALL("ICvEngineUtility1::sendMayaBonusChoice"); Queue(HHNetMessage::MAYA_BONUS_CHOICE, "MayaBonusChoice", ePlayer, eUnit); }
void HHEngineUtility::sendFaithGreatPersonChoice(PlayerTypes ePlayer, UnitTypes eUnit)
{ HH_IMPL_CALL("ICvEngineUtility1::sendFaithGreatPersonChoice"); Queue(HHNetMessage::FAITH_GREAT_PERSON_CHOICE, "FaithGreatPersonChoice", ePlayer, eUnit); }
void HHEngineUtility::sendGoodyChoice(PlayerTypes ePlayerID, int iPlotX, int iPlotY, GoodyTypes eGoody, int iUnitID)
{ HH_IMPL_CALL("ICvEngineUtility1::sendGoodyChoice"); Queue(HHNetMessage::GOODY_CHOICE, "GoodyChoice", ePlayerID, iPlotX, iPlotY, eGoody, iUnitID); }

// Turn gates (contract 6.3). CanAdvanceTurn: true (single player, nobody to wait for).
bool HHEngineUtility::CanAdvanceTurn() { HH_IMPL_CALL("ICvEngineUtility1::CanAdvanceTurn"); return true; }
// SendAICivsProcessed is seen by allAICivsProcessedThisTurn from the next Update on; a new turn clears it.
bool HHEngineUtility::allAICivsProcessedThisTurn() const { HH_IMPL_CALL("ICvEngineUtility3::allAICivsProcessedThisTurn"); return m_bAICivsProcessed; }
void HHEngineUtility::SendAICivsProcessed() const { HH_IMPL_CALL("ICvEngineUtility3::SendAICivsProcessed"); m_bAICivsProcessedPending = true; }
void HHEngineUtility::sendPlayerInitialAIProcessed() const { HH_IMPL_CALL("ICvEngineUtility1::sendPlayerInitialAIProcessed"); }
void HHEngineUtility::EndOfUpdate()
{
	if(m_bAICivsProcessedPending)
	{
		m_bAICivsProcessed = true;
		m_bAICivsProcessedPending = false;
	}
}
// ASSUMPTION (trace): the engine clears its "AI civs processed" flag when a new turn is published.
void HHEngineUtility::PublishNewGameTurn(int) { HH_IMPL_CALL("ICvEngineUtility1::PublishNewGameTurn"); m_bAICivsProcessed = false; m_bAICivsProcessedPending = false; }
// UI Lua asks on every update; nobody ends a turn through the network (contract 6.3).
bool HHEngineUtility::HasReceivedTurnComplete(PlayerTypes) { HH_IMPL_CALL("ICvEngineUtility1::HasReceivedTurnComplete"); return false; }
// ASSUMPTION (trace): measured true for the local human (player 0); only the human slot is connected.
bool HHEngineUtility::IsPlayerConnected(PlayerTypes ePlayer)
{
	HH_IMPL_CALL("ICvEngineUtility1::IsPlayerConnected");
	return m_pPreGame && ePlayer >= 0 && ePlayer < MAX_PLAYERS && m_pPreGame->slotStatus(ePlayer) == SS_TAKEN;
}
void HHEngineUtility::AutoSave(bool, bool) { HH_IMPL_CALL("ICvEngineUtility1::AutoSave"); }

const char* HHEngineUtility::GetCacheFolderPath()
{
	HH_IMPL_CALL("ICvEngineUtility1::GetCacheFolderPath");
	return m_strCacheFolder.c_str();
}

int HHEngineUtility::GetTutorialLevel()
{
	HH_IMPL_CALL("ICvEngineUtility1::GetTutorialLevel");
	return -1;
}

// No audio: every tag is unknown (-1). The DLL only stores the index for sound playback.
int HHEngineUtility::GetAudioTagIndex(const char*, int)
{
	HH_IMPL_CALL("ICvEngineUtility1::GetAudioTagIndex");
	return -1;
}

bool HHEngineUtility::TunerConnected() { HH_IMPL_CALL("ICvEngineUtility1::TunerConnected"); return false; }
// The reference runs drive the game through FireTuner (contract G12; the DLL stores it in a
// normalised field only).
bool HHEngineUtility::TunerEverConnected() { HH_IMPL_CALL("ICvEngineUtility1::TunerEverConnected"); return true; }

// Single-threaded host emulating the engine's roles (contract section 2): the game core lock is a
// recursive depth counter (the DLL's CvDll* wrappers take it in their constructors, so the exe
// holds it while it holds any wrapper), and the "game core thread" is whoever is inside
// ICvGame1::Update (SetInGameCoreUpdate); the new game and the UI run as the UI thread.
void HHEngineUtility::GetGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::GetGameCoreLock"); ++m_iLockDepth; }
void HHEngineUtility::ReleaseGameCoreLock()
{
	HH_IMPL_CALL("ICvEngineUtility1::ReleaseGameCoreLock");
	if(m_iLockDepth > 0)
		--m_iLockDepth;
	else
		HHLogError("ReleaseGameCoreLock without a matching GetGameCoreLock");
}
bool HHEngineUtility::TryGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::TryGameCoreLock"); ++m_iLockDepth; return true; }
bool HHEngineUtility::HasGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::HasGameCoreLock"); return m_iLockDepth > 0; }
bool HHEngineUtility::IsGameCoreThread() { HH_IMPL_CALL("ICvEngineUtility1::IsGameCoreThread"); return m_bInGameCoreUpdate; }
bool HHEngineUtility::IsGameCoreExecuting() { HH_IMPL_CALL("ICvEngineUtility1::IsGameCoreExecuting"); return false; }

bool HHEngineUtility::ShouldValidateGameDatabase() const
{
	HH_IMPL_CALL("ICvEngineUtility3::ShouldValidateGameDatabase");
	return false;
}

// NetInitInfo::Commit asks the engine for the best local candidate for the map script.
// ASSUMPTION (trace): the name comes back unchanged (S1/S3 pregame keeps the name the setup
// screen set, for a base script, a mod script and a premade map).
bool HHEngineUtility::GetEvaluatedMapScriptPath(const char* szPath, char* szEvaluatedPath, unsigned int szEvaluatedPathSize) const
{
	HH_IMPL_CALL("ICvEngineUtility4::GetEvaluatedMapScriptPath");
	if(!szPath || !szEvaluatedPath || szEvaluatedPathSize == 0)
		return false;
	const size_t n = strlen(szPath);
	if(n + 1 > szEvaluatedPathSize)
	{
		szEvaluatedPath[0] = 0;
		return false;
	}
	memcpy(szEvaluatedPath, szPath, n + 1);
	return true;
}

// Network bundle around closeInactiveSlots: single player, nothing to send.
void HHEngineUtility::sendPlayerInfo(PlayerTypes) { HH_IMPL_CALL("ICvEngineUtility1::sendPlayerInfo"); }
void HHEngineUtility::BeginSendBundle() { HH_IMPL_CALL("ICvEngineUtility3::BeginSendBundle"); }
void HHEngineUtility::EndSendBundle() { HH_IMPL_CALL("ICvEngineUtility3::EndSendBundle"); }

//------------------------------------------------------------------------------
// HHUserInterface
//------------------------------------------------------------------------------
HHUserInterface::HHUserInterface() : m_bNotificationAdded(false), m_pGame(NULL), m_eSelOwner(NO_PLAYER), m_iSelUnit(-1),
	m_bActivePlayerTurnStart(false), m_bPopupUp(false) {}

void HHUserInterface::AddPopup(const CvPopupInfo& kPopup)
{
	HH_IMPL_CALL("ICvUserInterface1::AddPopup");
	m_queuedPopups.push_back(kPopup);
}

bool HHUserInterface::DoAutoUnitCycle() { HH_IMPL_CALL("ICvUserInterface1::DoAutoUnitCycle"); return true; }
int HHUserInterface::getOriginalPlotIndex() { HH_IMPL_CALL("ICvUserInterface1::getOriginalPlotIndex"); return -1; }
int HHUserInterface::getOriginalPlotCount() { HH_IMPL_CALL("ICvUserInterface1::getOriginalPlotCount"); return 0; }

void HHUserInterface::AddNotification(int iID, NotificationTypes, const char*, const char*, int, int, PlayerTypes ePlayer, int, int)
{
	HH_IMPL_CALL("ICvUserInterface1::AddNotification");
	m_shownNotifications[iID] = ePlayer;
	m_bNotificationAdded = true;
}

void HHUserInterface::RemoveNotification(int iID, PlayerTypes)
{
	HH_IMPL_CALL("ICvUserInterface1::RemoveNotification");
	m_shownNotifications.erase(iID);
}

void* HHUserInterface::QueryInterface(GUID guidInterface)
{
	HH_IMPL_CALL("ICvUnknown::QueryInterface");
	if(guidInterface == ICvUnknown::GetInterfaceId() ||
	   guidInterface == ICvUserInterface1::GetInterfaceId() ||
	   guidInterface == ICvUserInterface2::GetInterfaceId())
	{
		return this;
	}
	HHLog("ICvUserInterface::QueryInterface: unsupported interface %s", GuidToString(guidInterface).c_str());
	return NULL;
}

void HHUserInterface::Destroy() { HH_IMPL_CALL("ICvUnknown::Destroy"); }

ICvPlot1* HHUserInterface::getSelectionPlot() { HH_IMPL_CALL("ICvUserInterface1::getSelectionPlot"); return NULL; }
ICvUnit1* HHUserInterface::GetHeadSelectedUnit()
{
	HH_IMPL_CALL("ICvUserInterface1::GetHeadSelectedUnit");
	if(m_eSelOwner == NO_PLAYER || !m_pGame)
		return NULL;
	ICvPlayer1* pPlayer = m_pGame->GetPlayer(m_eSelOwner);
	ICvUnit1* pUnit = pPlayer ? pPlayer->GetUnit(m_iSelUnit) : NULL;   // the caller releases it
	if(pPlayer)
		pPlayer->Destroy();
	if(!pUnit)
		ClearSelection();   // the unit is gone
	return pUnit;
}
ICvCity1* HHUserInterface::getHeadSelectedCity() { HH_IMPL_CALL("ICvUserInterface1::getHeadSelectedCity"); return NULL; }
bool HHUserInterface::isPopupUp() { HH_IMPL_CALL("ICvUserInterface1::isPopupUp"); return m_bPopupUp; }
bool HHUserInterface::isPopupQueued() { HH_IMPL_CALL("ICvUserInterface1::isPopupQueued"); return false; }
bool HHUserInterface::isDiploOrPopupWaiting() { HH_IMPL_CALL("ICvUserInterface1::isDiploOrPopupWaiting"); return false; }
bool HHUserInterface::isDiploActive() { HH_IMPL_CALL("ICvUserInterface1::isDiploActive"); return false; }
bool HHUserInterface::IsUnitSelected(PlayerTypes playerID, int unitID) { HH_IMPL_CALL("ICvUserInterface1::IsUnitSelected"); return playerID == m_eSelOwner && unitID == m_iSelUnit; }
bool HHUserInterface::isCitySelection() { HH_IMPL_CALL("ICvUserInterface1::isCitySelection"); return false; }
bool HHUserInterface::isCitySelected(ICvCity1*) { HH_IMPL_CALL("ICvUserInterface1::isCitySelected"); return false; }
int HHUserInterface::GetLengthSelectionList() { HH_IMPL_CALL("ICvUserInterface1::GetLengthSelectionList"); return m_eSelOwner != NO_PLAYER ? 1 : 0; }
bool HHUserInterface::isCityScreenUp() { HH_IMPL_CALL("ICvUserInterface1::isCityScreenUp"); return false; }
bool HHUserInterface::isFocused() { HH_IMPL_CALL("ICvUserInterface1::isFocused"); return false; }
bool HHUserInterface::isFocusedWidget() { HH_IMPL_CALL("ICvUserInterface1::isFocusedWidget"); return false; }
bool HHUserInterface::IsPopupQueueEmpty() { HH_IMPL_CALL("ICvUserInterface1::IsPopupQueueEmpty"); return true; }
bool HHUserInterface::IsModalStackEmpty() { HH_IMPL_CALL("ICvUserInterface1::IsModalStackEmpty"); return true; }
bool HHUserInterface::IsDontShowPopups() const { HH_IMPL_CALL("ICvUserInterface1::IsDontShowPopups"); return true; }
// The user setting is off in the reference profile (contract G10).
bool HHUserInterface::IsOptionNoRewardPopups() { HH_IMPL_CALL("ICvUserInterface1::IsOptionNoRewardPopups"); return false; }
bool HHUserInterface::IsLoadedGame() const { HH_IMPL_CALL("ICvUserInterface1::IsLoadedGame"); return false; }
bool HHUserInterface::isInAdvancedStart() const { HH_IMPL_CALL("ICvUserInterface1::isInAdvancedStart"); return false; }
bool HHUserInterface::IsDealInTransit() { HH_IMPL_CALL("ICvUserInterface1::IsDealInTransit"); return false; }
bool HHUserInterface::isDirty(InterfaceDirtyBits) { HH_IMPL_CALL("ICvUserInterface1::isDirty"); return false; }
void HHUserInterface::setDirty(InterfaceDirtyBits, bool) { HH_IMPL_CALL("ICvUserInterface1::setDirty"); }
void HHUserInterface::makeInterfaceDirty() { HH_IMPL_CALL("ICvUserInterface1::makeInterfaceDirty"); }

//------------------------------------------------------------------------------
// Notifications with no headless effect (graphics, sound, lobby, turn display)
//------------------------------------------------------------------------------
void HHEngineUtility::DoMapSetup(int iWorldNumPlots) { HH_IMPL_CALL("ICvEngineUtility1::DoMapSetup"); }
// Slots follow the players' lives: CvPlayer::setAlive calls closeSlot when a player dies and openSlot when it
// lives (again). The exe closes the slot (SS_CLOSED; CvPlayer::CheckForMurder's comment, M5 references: city-states
// and a major, e.g. hh-m5g-continents-s1 slot 5 at T277) and reopens a closed one as an AI slot (SS_COMPUTER;
// hh-m5z-continents-s1: city-state 36 died at T125 and was liberated at T140, the real pregame has SS_COMPUTER
// again from T141). openSlot at game start is for live slots, which are not closed, so it changes nothing there.
void HHEngineUtility::openSlot(PlayerTypes eID)
{
	HH_IMPL_CALL("ICvEngineUtility1::openSlot");
	if(m_pPreGame && eID >= 0 && eID < MAX_CIV_PLAYERS && m_pPreGame->slotStatus(eID) == SS_CLOSED)
	{
		HHLog("openSlot(%d): SS_CLOSED -> SS_COMPUTER", (int)eID);
		m_pPreGame->setSlotStatus(eID, SS_COMPUTER);
	}
}
void HHEngineUtility::closeSlot(PlayerTypes eID)
{
	HH_IMPL_CALL("ICvEngineUtility1::closeSlot");
	if(m_pPreGame && eID >= 0 && eID < MAX_CIV_PLAYERS)
	{
		const SlotStatus eStatus = m_pPreGame->slotStatus(eID);
		if(eStatus == SS_COMPUTER || eStatus == SS_TAKEN)
		{
			HHLog("closeSlot(%d): %d -> SS_CLOSED", (int)eID, (int)eStatus);
			m_pPreGame->setSlotStatus(eID, SS_CLOSED);
		}
	}
}
void HHEngineUtility::netMessageDebugLog(const std::string & logMessage) const { HH_IMPL_CALL("ICvEngineUtility1::netMessageDebugLog"); }
void HHEngineUtility::GameplayYieldMightHaveChanged(_In_ ICvPlot1* pThisPlot) { HH_IMPL_CALL("ICvEngineUtility1::GameplayYieldMightHaveChanged"); }
void HHEngineUtility::GameplayFeatureChanged(_In_ ICvPlot1* pThisPlot, FeatureTypes newFeature) { HH_IMPL_CALL("ICvEngineUtility1::GameplayFeatureChanged"); }
void HHEngineUtility::GameplayMetTeam(TeamTypes eMyTeam, TeamTypes eTheirTeam) { HH_IMPL_CALL("ICvEngineUtility1::GameplayMetTeam"); }
void HHEngineUtility::GameplayWarStateChanged(TeamTypes eTeam1, TeamTypes eTeam2, bool bWar) { HH_IMPL_CALL("ICvEngineUtility1::GameplayWarStateChanged"); }
void HHEngineUtility::GameplayTechAcquired(TeamTypes eTeam, TechTypes eTech) { HH_IMPL_CALL("ICvEngineUtility1::GameplayTechAcquired"); }
void HHEngineUtility::GameplayUnitShouldDimFlag(_In_ ICvUnit1* pThisUnit, bool bDim) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitShouldDimFlag"); }
// Graphics mode (SetGraphicsInitialized(true)) and the UI's SelectSettler: unit visuals and selection
void HHEngineUtility::GameplayUnitCreated(_In_ ICvUnit1*) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitCreated"); }
void HHEngineUtility::GameplayUnitDestroyed(_In_ ICvUnit1*) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitDestroyed"); }
void HHEngineUtility::GameplayUnitFortify(_In_ ICvUnit1*, bool) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitFortify"); }
void HHEngineUtility::GameplayUnitVisibility(_In_ ICvUnit1*, bool, bool, const float) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitVisibility"); }
void HHEngineUtility::GameplayMinimapUnitSelect(int, int) { HH_IMPL_CALL("ICvEngineUtility1::GameplayMinimapUnitSelect"); }
void HHEngineUtility::TradeVisuals_DeactivatePopupRoute() { HH_IMPL_CALL("ICvEngineUtility3::TradeVisuals_DeactivatePopupRoute"); }
void HHUserInterface::makeSelectionListDirty() { HH_IMPL_CALL("ICvUserInterface1::makeSelectionListDirty"); }
void HHUserInterface::ClearSelectionList() { HH_IMPL_CALL("ICvUserInterface1::ClearSelectionList"); ClearSelection(); }
void HHUserInterface::InsertIntoSelectionList(ICvUnit1* pUnit, bool, bool, bool, bool, bool)
{
	HH_IMPL_CALL("ICvUserInterface1::InsertIntoSelectionList");
	if(pUnit)
	{
		m_eSelOwner = pUnit->GetOwner();
		m_iSelUnit = pUnit->GetID();
	}
}
void HHUserInterface::clearSelectedCities() { HH_IMPL_CALL("ICvUserInterface1::clearSelectedCities"); }
void HHUserInterface::PublishEndTurnDirty() const { HH_IMPL_CALL("ICvUserInterface1::PublishEndTurnDirty"); }
void HHUserInterface::PublishPlayerTurnStatus(CvDLLInterfaceIFaceBase::TURN_STATUS_TYPE eStatus, PlayerTypes ePlayer, const char* pszTag) { HH_IMPL_CALL("ICvUserInterface1::PublishPlayerTurnStatus"); }
void HHUserInterface::setCycleSelectionCounter(int iNewValue) { HH_IMPL_CALL("ICvUserInterface1::setCycleSelectionCounter"); }
void HHUserInterface::PublishActivePlayerTurnStart() { HH_IMPL_CALL("ICvUserInterface1::PublishActivePlayerTurnStart"); m_bActivePlayerTurnStart = true; }
void HHUserInterface::PublishActivePlayerTurnEnd() { HH_IMPL_CALL("ICvUserInterface1::PublishActivePlayerTurnEnd"); }
void HHUserInterface::SetDontShowPopups(bool bValue) { HH_IMPL_CALL("ICvUserInterface1::SetDontShowPopups"); }
void HHUserInterface::SetEndTurnBlockingChanged(EndTurnBlockingTypes ePrevBlockingType, EndTurnBlockingTypes eNewBlockingType) { HH_IMPL_CALL("ICvUserInterface1::SetEndTurnBlockingChanged"); }
void HHUserInterface::UpdateEndTurn() { HH_IMPL_CALL("ICvUserInterface1::UpdateEndTurn"); }
