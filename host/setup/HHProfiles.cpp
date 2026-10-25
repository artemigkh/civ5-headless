#include "setup/HHProfiles.h"
#include "setup/HHVfs.h"
#include "lua/HHScriptSystem.h"
#include "lua/HHLuaGlobals.h"
#include "engine/HHRuntime.h"
#include "engine/HHSha256.h"
#include "setup/HHAddins.h"

namespace
{
	const char* kHooks[] = { "load-screen", "notification-added", "ui-frame", "popup" };

	bool IsHook(const std::string& s)
	{
		for(size_t i = 0; i < sizeof(kHooks) / sizeof(kHooks[0]); ++i)
			if(s == kHooks[i])
				return true;
		return false;
	}

	std::string DirOf(const std::string& strPath)
	{
		const size_t slash = strPath.find_last_of("\\/");
		return slash == std::string::npos ? std::string() : strPath.substr(0, slash);
	}

	bool IsDirectory(const std::string& strPath)
	{
		const DWORD attr = GetFileAttributesW(HHWiden(strPath).c_str());
		return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
	}

	std::vector<std::string> SubFolders(const std::string& strDir)
	{
		std::vector<std::string> out;
		WIN32_FIND_DATAW fd;
		HANDLE h = FindFirstFileW(HHWiden(strDir + "\\*").c_str(), &fd);
		if(h == INVALID_HANDLE_VALUE)
			return out;
		do
		{
			if((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && wcscmp(fd.cFileName, L".") && wcscmp(fd.cFileName, L".."))
				out.push_back(HHNarrow(fd.cFileName));
		} while(FindNextFileW(h, &fd));
		FindClose(h);
		std::sort(out.begin(), out.end());
		return out;
	}

	std::string Upper(std::string s)
	{
		for(size_t i = 0; i < s.size(); ++i)
			if(s[i] >= 'a' && s[i] <= 'z')
				s[i] = char(s[i] - 'a' + 'A');
		return s;
	}

	struct ByOrder
	{
		bool operator()(const HHProfile& a, const HHProfile& b) const
		{
			return a.order != b.order ? a.order < b.order : a.name < b.name;
		}
	};
}

HHProfiles& HHGetProfiles()
{
	static HHProfiles s_profiles;
	return s_profiles;
}

std::string HHDefaultProfilesDir()
{
	wchar_t sz[MAX_PATH];
	const DWORD n = GetModuleFileNameW(NULL, sz, MAX_PATH);
	if(!n)
		return std::string();
	std::string dir = DirOf(HHNarrow(std::wstring(sz, n)));
	for(int i = 0; i < 5 && !dir.empty(); ++i)
	{
		if(IsDirectory(dir + "\\profiles"))
			return dir + "\\profiles";
		dir = DirOf(dir);
	}
	return std::string();
}

bool HHProfiles::Load(const std::string& strDir)
{
	m_strDir = strDir;
	m_bLoaded = true;
	m_bKnownList = false;
	if(strDir.empty())
		return true;
	if(!IsDirectory(strDir))
	{
		m_loadErrors.push_back("profiles folder not found: " + strDir);
		return false;
	}
	// Files known not to need a profile (and the official DLC folders, whose UI is the base game's).
	{
		HHJson kKnown;
		std::string err;
		const std::string knownPath = strDir + "\\known-ui-files.json";
		if(HHFileExists(knownPath))
		{
			if(!HHJson::ParseFile(knownPath, kKnown, err))
				m_loadErrors.push_back("known-ui-files.json: " + err);
			else
			{
				m_bKnownList = true;
				const HHJson& dlc = kKnown["officialDlc"];
				for(size_t i = 0; i < dlc.Size(); ++i)
					m_officialDlc.insert(HHLower(dlc.At(i).AsString()));
				const HHJson& files = kKnown["files"];
				for(size_t i = 0; i < files.Size(); ++i)
					m_known.insert(std::make_pair(HHVfs::Key(files.At(i)["name"].AsString()),
					                              std::make_pair(Upper(files.At(i)["sha256"].AsString()), files.At(i)["note"].AsString())));
			}
		}
	}
	const std::vector<std::string> folders = SubFolders(strDir);
	for(size_t i = 0; i < folders.size(); ++i)
	{
		const std::string manifest = strDir + "\\" + folders[i] + "\\profile.json";
		if(!HHFileExists(manifest))
			continue;
		HHProfile p;
		p.dir = strDir + "\\" + folders[i];
		p.name = folders[i];
		std::string err;
		if(!HHJson::ParseFile(manifest, p.manifest, err))
		{
			m_loadErrors.push_back(folders[i] + "\\profile.json: " + err);
			continue;
		}
		const HHJson& m = p.manifest;
		if(m["name"].AsString().size())
			p.name = m["name"].AsString();
		p.description = m["description"].AsString();
		p.hook = m["hook"].AsString();
		p.luaFile = m["lua"].AsString();
		p.script = m["script"].AsString();
		p.function = m["function"].AsString();
		p.group = m["group"].AsString();
		p.order = m["order"].AsInt(100);
		p.staysUp = m["staysUp"].AsBool(false);
		for(size_t k = 0; k < m["popupTypes"].Size(); ++k)
			p.popupTypeNames.push_back(m["popupTypes"].At(k).AsString());
		if(!IsHook(p.hook))
			p.error = "unknown hook '" + p.hook + "'";
		else if(p.luaFile.empty() && p.script.empty() && !(p.hook == "popup" && p.staysUp))
			p.error = "neither lua nor script";
		else if(!p.luaFile.empty() && !HHFileExists(p.dir + "\\" + p.luaFile))
			p.error = "lua file not found: " + p.luaFile;
		else if(p.hook == "popup" && p.popupTypeNames.empty())
			p.error = "popup hook without popupTypes";
		if(p.function.empty())
		{
			if(p.hook == "load-screen") p.function = "OnLoadScreen";
			else if(p.hook == "notification-added") p.function = "OnNotificationAdded";
			else if(p.hook == "ui-frame") p.function = "OnUIFrame";
			else p.function = "OnPopup";
		}
		m_profiles.push_back(p);
	}
	std::sort(m_profiles.begin(), m_profiles.end(), ByOrder());
	return true;
}

std::string HHProfiles::FileHash(const std::string& strPath)
{
	std::map<std::string, std::string>::const_iterator it = m_hashCache.find(strPath);
	if(it != m_hashCache.end())
		return it->second;
	const std::string h = HHSha256File(strPath);
	m_hashCache[strPath] = h;
	return h;
}

// One selector: every condition it names must hold.
//   file      VFS name; the winner (best entry) is the file the other file conditions test
//   source    "base", "dlc" or "mod": the winner's tier
//   sha256    the winner's hash is one of these (strength 3)
//   contains  the winner contains every one of these strings (strength 2)
//   mod       an activated mod's id
//   dbQuery   SQL on the game database that returns at least one row
//   always    true
bool HHProfiles::EvaluateSelector(const HHJson& s, Database::Connection* pDb, int& iStrength, std::string& strReason,
                                  std::vector<std::pair<std::string, std::string> >& covered)
{
	iStrength = 1;
	std::vector<std::string> why;
	if(s["always"].AsBool(false))
		why.push_back("always");
	if(s.Has("file"))
	{
		const std::string name = s["file"].AsString();
		const std::vector<HHVfsEntry>* pFound = HHGetVfs().Find(name);
		HHVfsEntry e;
		if(pFound && !pFound->empty())
			e = pFound->front();
		else
		{
			// Not imported into the VFS: an InGameUIAddin's own script.
			std::string mod;
			e.path = HHFindAddinScript(name, mod);
			e.source = "addin:" + mod;
			e.tier = 3;
			if(e.path.empty())
			{
				strReason = name + " is neither in the VFS nor an InGameUIAddin script";
				return false;
			}
		}
		if(s.Has("source"))
		{
			const std::string want = s["source"].AsString();
			const char* tiers[] = { "base", "dlc", "mod", "addin" };
			if(e.tier < 0 || e.tier > 3 || want != tiers[e.tier])
			{
				strReason = name + " comes from " + e.source + ", not " + want;
				return false;
			}
		}
		const std::string hash = FileHash(e.path);
		if(s.Has("sha256"))
		{
			bool bMatch = false;
			for(size_t i = 0; i < s["sha256"].Size(); ++i)
				if(Upper(s["sha256"].At(i).AsString()) == hash)
					bMatch = true;
			if(!bMatch)
			{
				strReason = name + " (" + e.path + ") has an unlisted sha256 " + hash;
				return false;
			}
			iStrength = 3;
			why.push_back(name + " = " + e.source + " " + e.path + ", sha256 listed");
		}
		if(s.Has("contains"))
		{
			std::string text;
			HHReadTextFile(e.path, text);
			for(size_t i = 0; i < s["contains"].Size(); ++i)
				if(text.find(s["contains"].At(i).AsString()) == std::string::npos)
				{
					strReason = name + " (" + e.path + ") does not contain '" + s["contains"].At(i).AsString() + "'";
					return false;
				}
			if(iStrength < 2)
				iStrength = 2;
			why.push_back(name + " = " + e.source + " " + e.path + " (sha256 " + hash.substr(0, 12) + "... not listed), contains the listed code");
		}
		if(!s.Has("sha256") && !s.Has("contains"))
			why.push_back(name + " = " + e.source + " " + e.path);
		covered.push_back(std::make_pair(HHVfs::Key(name), hash));
	}
	if(s.Has("mod"))
	{
		const std::string id = s["mod"].AsString();
		bool bFound = false;
		for(size_t i = 0; i < HHGetVfs().GetMods().size(); ++i)
			if(_stricmp(HHGetVfs().GetMods()[i].id.c_str(), id.c_str()) == 0)
			{
				bFound = true;
				why.push_back("mod " + HHGetVfs().GetMods()[i].name + " activated");
			}
		if(!bFound)
		{
			strReason = "mod " + id + " not activated";
			return false;
		}
	}
	if(s.Has("dbQuery"))
	{
		const std::string sql = s["dbQuery"].AsString();
		Database::Results kResults;
		const bool bRow = pDb && pDb->Execute(kResults, sql.c_str()) && kResults.Step();
		if(!bRow)
		{
			strReason = "no row for " + sql;
			return false;
		}
		why.push_back("database: " + sql);
	}
	if(why.empty())
	{
		strReason = "empty selector";
		return false;
	}
	strReason.clear();
	for(size_t i = 0; i < why.size(); ++i)
		strReason += (i ? "; " : "") + why[i];
	return true;
}

void HHProfiles::Select(Database::Connection* pDb)
{
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		HHProfile& p = m_profiles[i];
		if(!p.error.empty())
		{
			p.reason = "manifest error: " + p.error;
			continue;
		}
		const HHJson& sel = p.manifest["select"];
		std::string lastReason = "no selector";
		for(size_t k = 0; k < sel.Size() && !p.selected; ++k)
		{
			int iStrength = 0;
			std::string reason;
			std::vector<std::pair<std::string, std::string> > covered;
			if(EvaluateSelector(sel.At(k), pDb, iStrength, reason, covered))
			{
				p.selected = true;
				p.strength = iStrength;
				p.reason = reason;
				p.coveredFiles = covered;
			}
			else
				lastReason = reason;
		}
		if(!p.selected)
			p.reason = lastReason;
	}
	// One profile per group: the strongest match, then the order.
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		HHProfile& p = m_profiles[i];
		if(!p.selected || p.group.empty())
			continue;
		for(size_t k = 0; k < m_profiles.size(); ++k)
		{
			HHProfile& q = m_profiles[k];
			if(k == i || !q.selected || q.group != p.group)
				continue;
			if(q.strength > p.strength || (q.strength == p.strength && k < i))
			{
				p.selected = false;
				p.reason = "group " + p.group + ": " + q.name + " matched first or better (" + p.reason + ")";
				break;
			}
		}
	}
	for(size_t i = 0; i < m_profiles.size(); ++i)
		HHLog("profile %s: %s (%s)", m_profiles[i].name.c_str(), m_profiles[i].selected ? "selected" : "not selected",
		      m_profiles[i].reason.c_str());
}

void HHProfiles::Start(HHScriptSystem& kScripts)
{
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		HHProfile& p = m_profiles[i];
		if(!p.selected)
			continue;
		if(!p.script.empty())
		{
			const std::vector<HHVfsEntry>* pFound = HHGetVfs().Find(p.script);
			p.scriptPath = pFound && !pFound->empty() ? pFound->front().path : std::string();
		}
		if(!p.luaFile.empty() || !p.script.empty())
		{
			p.L = HHLuaCreateUIContext(kScripts, p.name, true);
			bool bOk = p.L != NULL;
			if(bOk && !p.script.empty())
			{
				bOk = !p.scriptPath.empty() && kScripts.RunFile(p.L, p.scriptPath);
			}
			if(bOk && !p.luaFile.empty())
				bOk = kScripts.RunFile(p.L, p.dir + "\\" + p.luaFile);
			if(!bOk)
			{
				p.error = "Lua failed to load (see Lua errors)";
				HHLogError("profile %s: %s", p.name.c_str(), p.error.c_str());
				p.selected = false;
				p.reason += "; " + p.error;
				continue;
			}
		}
		for(size_t k = 0; k < p.popupTypeNames.size(); ++k)
		{
			const std::string& t = p.popupTypeNames[k];
			int id = -1;
			if(!t.empty() && isdigit((unsigned char)t[0]))
				id = atoi(t.c_str());
			else
			{
				lua_State* L = kScripts.GetMainState();
				lua_getglobal(L, "ButtonPopupTypes");
				if(lua_istable(L, -1))
				{
					lua_getfield(L, -1, t.c_str());
					if(lua_isnumber(L, -1))
						id = (int)lua_tointeger(L, -1);
					lua_pop(L, 1);
				}
				lua_pop(L, 1);
			}
			if(id < 0)
				HHLogError("profile %s: popup type %s unknown to this DLL", p.name.c_str(), t.c_str());
			else
				p.popupTypes.push_back(id);
		}
	}
}

int HHProfiles::RunHook(HHScriptSystem& kScripts, const char* szHook, std::vector<std::string>* pLog)
{
	int n = 0;
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		HHProfile& p = m_profiles[i];
		if(!p.selected || !p.L || p.hook != szHook)
			continue;
		++n;
		++p.calls;
		lua_State* L = p.L;
		lua_settop(L, 0);
		lua_getglobal(L, p.function.c_str());
		if(!lua_isfunction(L, -1))
		{
			lua_settop(L, 0);
			++p.failures;
			if(p.failures == 1)
				HHLogError("profile %s: no function %s", p.name.c_str(), p.function.c_str());
			continue;
		}
		if(!kScripts.CallFunction(L, 0, 1))
			++p.failures;
		else if(pLog)
		{
			const char* sz = lua_isstring(L, -1) ? lua_tostring(L, -1) : NULL;
			pLog->push_back(HHFormat("profile %s (%s): %s", p.name.c_str(), szHook, sz ? sz : (lua_toboolean(L, -1) ? "true" : "nil")));
		}
		lua_settop(L, 0);
	}
	return n;
}

int HHProfiles::RunPopup(HHScriptSystem& kScripts, const CvPopupInfo& kPopup, bool& bStaysUp, std::string& strLog)
{
	int n = 0;
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		HHProfile& p = m_profiles[i];
		if(!p.selected || p.hook != "popup" ||
		   std::find(p.popupTypes.begin(), p.popupTypes.end(), (int)kPopup.eButtonPopupType) == p.popupTypes.end())
			continue;
		++n;
		++p.calls;
		if(!p.L)
		{
			if(p.staysUp)
				bStaysUp = true;
			strLog += ": " + p.name + (p.staysUp ? " (stays up)" : "");
			continue;
		}
		lua_State* L = p.L;
		lua_settop(L, 0);
		lua_getglobal(L, p.function.c_str());
		if(!lua_isfunction(L, -1))
		{
			lua_settop(L, 0);
			++p.failures;
			continue;
		}
		lua_createtable(L, 0, 8);
		lua_pushinteger(L, (int)kPopup.eButtonPopupType); lua_setfield(L, -2, "Type");
		lua_pushinteger(L, kPopup.iData1); lua_setfield(L, -2, "Data1");
		lua_pushinteger(L, kPopup.iData2); lua_setfield(L, -2, "Data2");
		lua_pushinteger(L, kPopup.iData3); lua_setfield(L, -2, "Data3");
		lua_pushinteger(L, kPopup.iFlags); lua_setfield(L, -2, "Flags");
		lua_pushboolean(L, kPopup.bOption1 ? 1 : 0); lua_setfield(L, -2, "Option1");
		lua_pushboolean(L, kPopup.bOption2 ? 1 : 0); lua_setfield(L, -2, "Option2");
		lua_pushstring(L, kPopup.szText); lua_setfield(L, -2, "Text");
		if(!kScripts.CallFunction(L, 1, 2))
		{
			++p.failures;
			strLog += ": " + p.name + " failed";
		}
		else
		{
			// OnPopup returns: shown (the popup stays up), and an optional note for the log.
			const bool bShown = lua_toboolean(L, -2) != 0;
			const char* szNote = lua_isstring(L, -1) ? lua_tostring(L, -1) : NULL;
			if(bShown || p.staysUp)
				bStaysUp = true;
			strLog += ": " + p.name + (szNote ? std::string(" ") + szNote : std::string()) + (bShown ? " (stays up)" : "");
		}
		lua_settop(L, 0);
	}
	return n;
}

bool HHProfiles::IsKnownFile(const std::string& strName, const std::string& strSha256, std::string* pBy) const
{
	const std::string key = HHVfs::Key(strName);
	for(size_t i = 0; i < m_profiles.size(); ++i)
	{
		const HHProfile& p = m_profiles[i];
		if(!p.selected)
			continue;
		for(size_t k = 0; k < p.coveredFiles.size(); ++k)
			if(p.coveredFiles[k].first == key && p.coveredFiles[k].second == strSha256)
			{
				if(pBy)
					*pBy = "profile " + p.name;
				return true;
			}
	}
	typedef std::multimap<std::string, std::pair<std::string, std::string> >::const_iterator It;
	std::pair<It, It> range = m_known.equal_range(key);
	for(It it = range.first; it != range.second; ++it)
		if(it->second.first == strSha256)
		{
			if(pBy)
				*pBy = "known-ui-files.json: " + it->second.second;
			return true;
		}
	return false;
}

bool HHProfiles::IsOfficialDlc(const std::string& strFolder) const
{
	return m_officialDlc.count(HHLower(strFolder)) != 0;
}
