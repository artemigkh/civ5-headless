// Host implementations of the engine interfaces the DLL calls: ICvEngineUtility4 and
// ICvUserInterface2. Everything not overridden here falls through to the generated stubs
// (gen/HHStubs.gen.h), which count the call and abort under --strict.
#pragma once
#include "HHCommon.h"
#include "gen/HHStubs.gen.h"

// A net message the engine loops back to the DLL as NetMessageHandler::Response* (contract 6.4).
struct HHNetMessage
{
	enum Kind
	{
		PLAYER_OPTION, PLEDGE_MINOR_PROTECTION, MINOR_BULLY_GOLD, MINOR_BULLY_UNIT, MINOR_GIFT_GOLD,
		MINOR_GIFT_TILE_IMPROVEMENT, MINOR_BUYOUT, GREAT_PERSON_CHOICE, MAYA_BONUS_CHOICE,
		FAITH_GREAT_PERSON_CHOICE, GOODY_CHOICE
	};
	Kind eKind;
	int a[6];
};

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
	// The engine's net loopback: every queued send* is delivered as its Response*, in send order,
	// after the inbound call that sent it returns (contract 6.4). Returns the number delivered.
	size_t DeliverNetMessages(ICvNetMessageHandler1* pHandler);
	size_t GetPendingNetMessageCount() const { return m_pendingNet.size(); }
	const std::map<std::string, int>& GetNetMessageCounts() const { return m_netCounts; }
	// Pregame (active player, slot status) for the loopback and IsPlayerConnected.
	void SetPreGame(ICvPreGame1* pPreGame) { m_pPreGame = pPreGame; }
	// End of an Update: a SendAICivsProcessed of this update becomes visible (contract 6.3).
	void EndOfUpdate();
	// Engine roles: IsGameCoreThread answers true only inside ICvGame1::Update.
	void SetInGameCoreUpdate(bool bInUpdate) { m_bInGameCoreUpdate = bInUpdate; }
	int GetGameCoreLockDepth() const { return m_iLockDepth; }
	static const int kEngineKnownPlayerOptions = 11;

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
	void GameplayUnitCreated(_In_ ICvUnit1* pThisUnit);
	void GameplayUnitDestroyed(_In_ ICvUnit1* pThisUnit);
	void GameplayUnitFortify(_In_ ICvUnit1* pThisUnit, bool bFortify);
	void GameplayUnitVisibility(_In_ ICvUnit1* pThisUnit, bool bVisible, bool bChangeInvisibility, const float fBlendTime);
	void GameplayMinimapUnitSelect(int iX, int iY);
	void TradeVisuals_DeactivatePopupRoute();

	// Turn gates (contract 6.3)
	bool CanAdvanceTurn();
	bool allAICivsProcessedThisTurn() const;
	void SendAICivsProcessed() const;
	void sendPlayerInitialAIProcessed() const;
	bool HasReceivedTurnComplete(PlayerTypes ePlayer);
	bool IsPlayerConnected(PlayerTypes playerId);
	void PublishNewGameTurn(int gameTurn);
	// Autosaves: the engine writes the game only on turn 0 and every 10th turn; every Write side effect
	// is normalised in the digest, so the host writes nothing (contract 6.5).
	void AutoSave(bool bInitial, bool bPostTurn);

	// Net messages with a Response* (queued, see DeliverNetMessages)
	void sendMinorPledgeProtection(PlayerTypes eMajor, PlayerTypes eMinor, bool bProtect, bool bPledgeNowBroken);
	void sendMinorGiftGold(PlayerTypes eMinor, int iGold);
	void sendMinorGiftTileImprovement(PlayerTypes eMajor, PlayerTypes eMinor, int iPlotX, int iPlotY);
	void sendMinorBullyGold(PlayerTypes eBully, PlayerTypes eMinor, int iGold);
	void sendMinorBullyUnit(PlayerTypes eBully, PlayerTypes eMinor, UnitTypes eUnitType);
	void sendMinorBuyout(PlayerTypes eMajor, PlayerTypes eMinor);
	void sendGreatPersonChoice(PlayerTypes ePlayer, UnitTypes eUnit);
	void sendMayaBonusChoice(PlayerTypes ePlayer, UnitTypes eUnit);
	void sendFaithGreatPersonChoice(PlayerTypes ePlayer, UnitTypes eUnit);
	void sendGoodyChoice(PlayerTypes ePlayerID, int iPlotX, int iPlotY, GoodyTypes eGoody, int iUnitID);

	// Network (single player: no-ops)
	void sendPlayerInfo(PlayerTypes eActivePlayer);
	void BeginSendBundle();
	void EndSendBundle();

private:
	ICvEngineScriptSystem1* m_pScriptSystem;
	std::string m_strCacheFolder;
	bool m_bDone;
	std::map<unsigned int, HHPlayerOption> m_playerOptions;   // FStringHash(type) -> option
	std::vector<HHNetMessage> m_pendingNet;                  // sent, not yet delivered
	std::map<std::string, int> m_netCounts;
	ICvPreGame1* m_pPreGame;
	mutable bool m_bAICivsProcessed;                         // allAICivsProcessedThisTurn
	mutable bool m_bAICivsProcessedPending;                  // set by SendAICivsProcessed, visible after the Update
	void Queue(HHNetMessage::Kind eKind, const char* szName, int a0 = 0, int a1 = 0, int a2 = 0, int a3 = 0, int a4 = 0, int a5 = 0);
	PlayerTypes ActivePlayer() const;
	int m_iLockDepth;
	bool m_bInGameCoreUpdate;
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
	void makeSelectionListDirty();
	void ClearSelectionList();
	void InsertIntoSelectionList(ICvUnit1* pUnit, bool bClear, bool bToggle, bool bGroup, bool bSound, bool bMinimalChange);
	void clearSelectedCities();
	void PublishPlayerTurnStatus(CvDLLInterfaceIFaceBase::TURN_STATUS_TYPE eStatus, PlayerTypes ePlayer, const char* pszTag);
	void setCycleSelectionCounter(int iNewValue);
	void PublishActivePlayerTurnStart();
	void PublishActivePlayerTurnEnd();
	void SetDontShowPopups(bool bValue);
	void SetEndTurnBlockingChanged(EndTurnBlockingTypes ePrevBlockingType, EndTurnBlockingTypes eNewBlockingType);
	void UpdateEndTurn();

	// The notification panel's shown notifications (NotificationPanel.lua g_ActiveNotifications):
	// AddNotification is the engine's NotificationAdded event, RemoveNotification its NotificationRemoved.
	void AddNotification(int iID, NotificationTypes type, const char* cTooltip, const char* cSummary, int iGameData, int iExtraGameData, PlayerTypes ePlayer, int iX, int iY);
	void RemoveNotification(int iID, PlayerTypes ePlayer);
	const std::map<int, PlayerTypes>& GetShownNotifications() const { return m_shownNotifications; }
	void ClearShownNotifications() { m_shownNotifications.clear(); }
	// True once per NotificationAdded since the last call (the panel's handlers run on the next UI frame).
	bool TakeNotificationAdded() { const bool b = m_bNotificationAdded; m_bNotificationAdded = false; return b; }

	// The unit selection list (head unit only) and the engine's auto unit cycle (option on in the
	// reference profile): the human turn after autoplay selects a unit (CvGame::updateSelectionList).
	void SetGame(ICvGame1* pGame) { m_pGame = pGame; }
	bool DoAutoUnitCycle();
	int getOriginalPlotIndex();
	int getOriginalPlotCount();
	void ClearSelection() { m_eSelOwner = NO_PLAYER; m_iSelUnit = -1; }
	// True once per PublishActivePlayerTurnStart since the last call.
	bool TakeActivePlayerTurnStart() { const bool b = m_bActivePlayerTurnStart; m_bActivePlayerTurnStart = false; return b; }

	// Popups: AddPopup queues (SerialEventGameMessagePopup on the next UI frame); a shown popup stays up
	// (nobody closes it in an autoplay run).
	void AddPopup(const CvPopupInfo& kPopup);
	std::vector<CvPopupInfo> TakeQueuedPopups() { std::vector<CvPopupInfo> v; v.swap(m_queuedPopups); return v; }
	void SetPopupUp(bool bUp) { m_bPopupUp = bUp; }
	bool IsPopupShown() const { return m_bPopupUp; }

private:
	std::map<int, PlayerTypes> m_shownNotifications;
	bool m_bNotificationAdded;
	ICvGame1* m_pGame;
	PlayerTypes m_eSelOwner;
	int m_iSelUnit;
	bool m_bActivePlayerTurnStart;
	std::vector<CvPopupInfo> m_queuedPopups;
	bool m_bPopupUp;
};
