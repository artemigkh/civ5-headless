// Host implementations of the engine interfaces the DLL calls: ICvEngineUtility4 and
// ICvUserInterface2. Everything not overridden here falls through to the generated stubs
// (gen/HHStubs.gen.h), which count the call and abort under --strict.
#pragma once
#include "HHCommon.h"
#include "gen/HHStubs.gen.h"

class HHEngineUtility : public HHStubEngineUtility
{
public:
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

private:
	ICvEngineScriptSystem1* m_pScriptSystem;
	std::string m_strCacheFolder;
	bool m_bDone;
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
};
