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
	: m_pScriptSystem(pScriptSystem), m_bDone(false)
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
	m_pendingOptions.push_back(std::make_pair(it->second.index, bValue));
}

void HHEngineUtility::DeliverPlayerOptions(ICvNetMessageHandler1* pHandler, PlayerTypes ePlayer)
{
	for(size_t i = 0; i < m_pendingOptions.size(); ++i)
		pHandler->ResponsePlayerOption(ePlayer, (PlayerOptionTypes)m_pendingOptions[i].first, m_pendingOptions[i].second);
	m_pendingOptions.clear();
}

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
bool HHEngineUtility::TunerEverConnected() { HH_IMPL_CALL("ICvEngineUtility1::TunerEverConnected"); return false; }

// Single-threaded host: the game core runs on the calling thread and the lock is never held,
// so code that yields to the UI while holding it skips the yield.
void HHEngineUtility::GetGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::GetGameCoreLock"); }
void HHEngineUtility::ReleaseGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::ReleaseGameCoreLock"); }
bool HHEngineUtility::TryGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::TryGameCoreLock"); return true; }
bool HHEngineUtility::HasGameCoreLock() { HH_IMPL_CALL("ICvEngineUtility1::HasGameCoreLock"); return false; }
bool HHEngineUtility::IsGameCoreThread() { HH_IMPL_CALL("ICvEngineUtility1::IsGameCoreThread"); return true; }
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
HHUserInterface::HHUserInterface() {}

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
ICvUnit1* HHUserInterface::GetHeadSelectedUnit() { HH_IMPL_CALL("ICvUserInterface1::GetHeadSelectedUnit"); return NULL; }
ICvCity1* HHUserInterface::getHeadSelectedCity() { HH_IMPL_CALL("ICvUserInterface1::getHeadSelectedCity"); return NULL; }
bool HHUserInterface::isPopupUp() { HH_IMPL_CALL("ICvUserInterface1::isPopupUp"); return false; }
bool HHUserInterface::isPopupQueued() { HH_IMPL_CALL("ICvUserInterface1::isPopupQueued"); return false; }
bool HHUserInterface::isDiploOrPopupWaiting() { HH_IMPL_CALL("ICvUserInterface1::isDiploOrPopupWaiting"); return false; }
bool HHUserInterface::isDiploActive() { HH_IMPL_CALL("ICvUserInterface1::isDiploActive"); return false; }
bool HHUserInterface::IsUnitSelected(PlayerTypes, int) { HH_IMPL_CALL("ICvUserInterface1::IsUnitSelected"); return false; }
bool HHUserInterface::isCitySelection() { HH_IMPL_CALL("ICvUserInterface1::isCitySelection"); return false; }
bool HHUserInterface::isCitySelected(ICvCity1*) { HH_IMPL_CALL("ICvUserInterface1::isCitySelected"); return false; }
int HHUserInterface::GetLengthSelectionList() { HH_IMPL_CALL("ICvUserInterface1::GetLengthSelectionList"); return 0; }
bool HHUserInterface::isCityScreenUp() { HH_IMPL_CALL("ICvUserInterface1::isCityScreenUp"); return false; }
bool HHUserInterface::isFocused() { HH_IMPL_CALL("ICvUserInterface1::isFocused"); return false; }
bool HHUserInterface::isFocusedWidget() { HH_IMPL_CALL("ICvUserInterface1::isFocusedWidget"); return false; }
bool HHUserInterface::IsPopupQueueEmpty() { HH_IMPL_CALL("ICvUserInterface1::IsPopupQueueEmpty"); return true; }
bool HHUserInterface::IsModalStackEmpty() { HH_IMPL_CALL("ICvUserInterface1::IsModalStackEmpty"); return true; }
bool HHUserInterface::IsDontShowPopups() const { HH_IMPL_CALL("ICvUserInterface1::IsDontShowPopups"); return true; }
bool HHUserInterface::IsOptionNoRewardPopups() { HH_IMPL_CALL("ICvUserInterface1::IsOptionNoRewardPopups"); return true; }
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
void HHEngineUtility::openSlot(PlayerTypes eID) { HH_IMPL_CALL("ICvEngineUtility1::openSlot"); }
void HHEngineUtility::closeSlot(PlayerTypes eID) { HH_IMPL_CALL("ICvEngineUtility1::closeSlot"); }
void HHEngineUtility::netMessageDebugLog(const std::string & logMessage) const { HH_IMPL_CALL("ICvEngineUtility1::netMessageDebugLog"); }
void HHEngineUtility::GameplayYieldMightHaveChanged(_In_ ICvPlot1* pThisPlot) { HH_IMPL_CALL("ICvEngineUtility1::GameplayYieldMightHaveChanged"); }
void HHEngineUtility::GameplayFeatureChanged(_In_ ICvPlot1* pThisPlot, FeatureTypes newFeature) { HH_IMPL_CALL("ICvEngineUtility1::GameplayFeatureChanged"); }
void HHEngineUtility::GameplayMetTeam(TeamTypes eMyTeam, TeamTypes eTheirTeam) { HH_IMPL_CALL("ICvEngineUtility1::GameplayMetTeam"); }
void HHEngineUtility::GameplayWarStateChanged(TeamTypes eTeam1, TeamTypes eTeam2, bool bWar) { HH_IMPL_CALL("ICvEngineUtility1::GameplayWarStateChanged"); }
void HHEngineUtility::GameplayTechAcquired(TeamTypes eTeam, TechTypes eTech) { HH_IMPL_CALL("ICvEngineUtility1::GameplayTechAcquired"); }
void HHEngineUtility::GameplayUnitShouldDimFlag(_In_ ICvUnit1* pThisUnit, bool bDim) { HH_IMPL_CALL("ICvEngineUtility1::GameplayUnitShouldDimFlag"); }
void HHUserInterface::PublishEndTurnDirty() const { HH_IMPL_CALL("ICvUserInterface1::PublishEndTurnDirty"); }
void HHUserInterface::PublishPlayerTurnStatus(CvDLLInterfaceIFaceBase::TURN_STATUS_TYPE eStatus, PlayerTypes ePlayer, const char* pszTag) { HH_IMPL_CALL("ICvUserInterface1::PublishPlayerTurnStatus"); }
void HHUserInterface::setCycleSelectionCounter(int iNewValue) { HH_IMPL_CALL("ICvUserInterface1::setCycleSelectionCounter"); }
void HHUserInterface::PublishActivePlayerTurnStart() { HH_IMPL_CALL("ICvUserInterface1::PublishActivePlayerTurnStart"); }
void HHUserInterface::PublishActivePlayerTurnEnd() { HH_IMPL_CALL("ICvUserInterface1::PublishActivePlayerTurnEnd"); }
void HHUserInterface::SetDontShowPopups(bool bValue) { HH_IMPL_CALL("ICvUserInterface1::SetDontShowPopups"); }
void HHUserInterface::SetEndTurnBlockingChanged(EndTurnBlockingTypes ePrevBlockingType, EndTurnBlockingTypes eNewBlockingType) { HH_IMPL_CALL("ICvUserInterface1::SetEndTurnBlockingChanged"); }
void HHUserInterface::UpdateEndTurn() { HH_IMPL_CALL("ICvUserInterface1::UpdateEndTurn"); }
