// Host implementations of the engine interfaces the DLL calls: ICvEngineUtility4 and
// ICvUserInterface2. Everything not overridden here falls through to the generated stubs
// (gen/HHStubs.gen.h), which count the call and abort under --strict.
#pragma once
#include "HHCommon.h"
#include "gen/HHStubs.gen.h"

struct HHPlayerOption
{
	std::string type;
	int index;
	bool value;
};

class HHEngineUtility : public HHStubEngineUtility
{
public:
	// Player options (the engine's user settings): filled from the PlayerOptions table.
	void AddPlayerOption(const char* szType, int iIndex, bool bValue);
	bool SetPlayerOptionValue(const std::string& strType, bool bValue);
	// The engine's loopback of sendPlayerOption: ResponsePlayerOption for each sent value.
	void DeliverPlayerOptions(ICvNetMessageHandler1* pHandler, PlayerTypes ePlayer);
	size_t GetPendingPlayerOptionCount() const { return m_pendingOptions.size(); }

	explicit HHEngineUtility(ICvEngineScriptSystem1* pScriptSystem);

	// ICvUnknown
	void* DLLCALL QueryInterface(GUID guidInterface);
	void DLLCALL Destroy();

	// ICvEngineUtility1
	ICvEngineScriptSystem1* GetScriptSystem();
	bool IsHost() const;
	bool IsModActivated(_In_z_ const char* szModID);
	bool IsModActivated(_In_z_ const char* szModID, int iVersion);
	bool IsDLCValid(const GUID& kID) const;
	bool IsPitbossHost() const;
	void InitGlobals();
	void UninitGlobals();
	void SetDone(bool bDone);
	bool GetDone();
	bool GetAutorun();
	bool altKey();
	bool shiftKey();
	bool ctrlKey();
	bool getPlayerOption(PlayerOptionTypes ePlayerOption);
	void sendPlayerOption(PlayerOptionTypes eOption, bool bValue);
	const char* GetCacheFolderPath();
	int GetTutorialLevel();
	int GetAudioTagIndex(const char* szTag, int iScriptType);
	bool TunerConnected();
	bool TunerEverConnected();

	// ICvEngineUtility2-4
	void GetGameCoreLock();
	void ReleaseGameCoreLock();
	bool TryGameCoreLock();
	bool HasGameCoreLock();
	bool IsGameCoreThread();
	bool IsGameCoreExecuting();
	bool ShouldValidateGameDatabase() const;

	bool DLLCALL GetEvaluatedMapScriptPath(_In_z_ const char* szPath, _Inout_z_cap_(szEvaluatedPathSize) char* szEvaluatedPath, unsigned int szEvaluatedPathSize) const;

	// Graphics, sound and lobby notifications: nothing to show headless (counted no-ops).
	void DoMapSetup(int iWorldNumPlots);
	void openSlot(PlayerTypes eID);
	void closeSlot(PlayerTypes eID);
	void netMessageDebugLog(const std::string & logMessage) const;
	void GameplayYieldMightHaveChanged(_In_ ICvPlot1* pThisPlot);
	void GameplayFeatureChanged(_In_ ICvPlot1* pThisPlot, FeatureTypes newFeature);
	void GameplayMetTeam(TeamTypes eMyTeam, TeamTypes eTheirTeam);
	void GameplayWarStateChanged(TeamTypes eTeam1, TeamTypes eTeam2, bool bWar);
	void GameplayTechAcquired(TeamTypes eTeam, TechTypes eTech);
	void GameplayUnitShouldDimFlag(_In_ ICvUnit1* pThisUnit, bool bDim);

	// Network (single player: no-ops)
	void sendPlayerInfo(PlayerTypes eActivePlayer);
	void BeginSendBundle();
	void EndSendBundle();

private:
	ICvEngineScriptSystem1* m_pScriptSystem;
	std::string m_strCacheFolder;
	bool m_bDone;
	std::map<unsigned int, HHPlayerOption> m_playerOptions;   // FStringHash(type) -> option
	std::vector<std::pair<int, bool> > m_pendingOptions;     // sent, not yet delivered
};

class HHUserInterface : public HHStubUserInterface
{
public:
	HHUserInterface();

	void* DLLCALL QueryInterface(GUID guidInterface);
	void DLLCALL Destroy();

	// No selection, no popups, no diplomacy screen, no city screen.
	ICvPlot1* getSelectionPlot();
	ICvUnit1* GetHeadSelectedUnit();
	ICvCity1* getHeadSelectedCity();
	bool isPopupUp();
	bool isPopupQueued();
	bool isDiploOrPopupWaiting();
	bool isDiploActive();
	bool IsUnitSelected(PlayerTypes playerID, int unitID);
	bool isCitySelection();
	bool isCitySelected(ICvCity1* pCity);
	int GetLengthSelectionList();
	bool isCityScreenUp();
	bool isFocused();
	bool isFocusedWidget();
	bool IsPopupQueueEmpty();
	bool IsModalStackEmpty();
	bool IsDontShowPopups() const;
	bool IsOptionNoRewardPopups();
	bool IsLoadedGame() const;
	bool isInAdvancedStart() const;
	bool IsDealInTransit();
	bool isDirty(InterfaceDirtyBits eDirtyItem);
	void setDirty(InterfaceDirtyBits eDirtyItem, bool bNewValue);
	void makeInterfaceDirty();

	// Turn and end-turn notifications for the screen: counted no-ops.
	void PublishEndTurnDirty() const;
	void PublishPlayerTurnStatus(CvDLLInterfaceIFaceBase::TURN_STATUS_TYPE eStatus, PlayerTypes ePlayer, const char* pszTag);
	void setCycleSelectionCounter(int iNewValue);
	void PublishActivePlayerTurnStart();
	void PublishActivePlayerTurnEnd();
	void SetDontShowPopups(bool bValue);
	void SetEndTurnBlockingChanged(EndTurnBlockingTypes ePrevBlockingType, EndTurnBlockingTypes eNewBlockingType);
	void UpdateEndTurn();
};
