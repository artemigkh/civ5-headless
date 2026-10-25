// UI emulation profiles (docs/profiles.md): the stateful parts of the game's UI Lua that an autoplay game depends on,
// as data. Each profile is a folder below the profiles directory with a manifest (profile.json) and usually a Lua file.
// The manifest says which files or database facts select the profile and which host hook it attaches to:
//
//   load-screen         once, while the load screen is up (before the T000 outputs)
//   notification-added  on the UI frame after the DLL added a notification (AddNotification)
//   ui-frame            after every game core Update (the UI's frame with the core idle)
//   popup               on the UI frame after AddPopup of one of the manifest's popupTypes
//
// The hook points are in C++ (setup/HHNewGame.cpp); the behaviour is the profile's Lua, which runs in a stub UI
// context of its own (kept for the whole game, so its globals persist like a UI context's).
#pragma once
#include "HHCommon.h"
#include "setup/HHJson.h"

class HHScriptSystem;

struct HHProfile
{
	std::string name, dir, description, hook, luaFile, function, group;
	std::string script;            // a UI file of the VFS (its winner) run in the profile's context before luaFile
	std::string scriptPath;
	std::vector<std::string> popupTypeNames;
	std::vector<int> popupTypes;   // resolved through ButtonPopupTypes
	bool staysUp;                  // popup hook without Lua: the popup is shown and stays up
	int order;
	HHJson manifest;
	// Selection
	bool selected;
	int strength;                  // of the matching selector: 3 sha256, 2 contains, 1 other facts
	std::string reason;            // why it was (not) selected
	std::vector<std::pair<std::string, std::string> > coveredFiles; // VFS name -> sha256 of the file it was selected by
	// Run state
	lua_State* L;
	long calls, failures;
	std::string error;
	HHProfile() : staysUp(false), order(100), selected(false), strength(0), L(NULL), calls(0), failures(0) {}
};

class HHProfiles
{
public:
	HHProfiles() : m_bLoaded(false) {}

	// Reads every <dir>\*\profile.json; empty dir: none. Errors are kept per profile.
	bool Load(const std::string& strDir);
	// Evaluates the selectors against the VFS winners and the game database (pDb may be NULL).
	void Select(Database::Connection* pDb);
	// Creates the selected profiles' Lua contexts and resolves popup types (needs the game's Lua libraries).
	void Start(HHScriptSystem& kScripts);

	// Hooks. Each returns the number of profiles called.
	int RunHook(HHScriptSystem& kScripts, const char* szHook, std::vector<std::string>* pLog);
	// popup: bShowUp is set when a profile keeps the popup up.
	int RunPopup(HHScriptSystem& kScripts, const CvPopupInfo& kPopup, bool& bStaysUp, std::string& strLog);

	const std::vector<HHProfile>& GetProfiles() const { return m_profiles; }
	const std::string& GetDir() const { return m_strDir; }
	const std::vector<std::string>& GetLoadErrors() const { return m_loadErrors; }
	// Files a selected profile covers or the known-files list vouches for: lower-case VFS name -> sha256 list.
	bool IsKnownFile(const std::string& strName, const std::string& strSha256, std::string* pBy) const;
	bool IsOfficialDlc(const std::string& strFolder) const;
	bool HasKnownList() const { return m_bKnownList; }

private:
	bool EvaluateSelector(const HHJson& s, Database::Connection* pDb, int& iStrength, std::string& strReason,
	                      std::vector<std::pair<std::string, std::string> >& covered);
	std::string FileHash(const std::string& strPath);
	std::string m_strDir;
	std::vector<HHProfile> m_profiles;
	std::vector<std::string> m_loadErrors;
	std::map<std::string, std::string> m_hashCache;
	std::multimap<std::string, std::pair<std::string, std::string> > m_known; // name -> (sha256, note)
	std::set<std::string> m_officialDlc;
	bool m_bLoaded, m_bKnownList;
};

HHProfiles& HHGetProfiles();
// The default profiles folder: "profiles" next to the exe or up to four folders above it (a build in out\<Config>\<ts>).
std::string HHDefaultProfilesDir();
