#include "setup/HHAddins.h"
#include "setup/HHVfs.h"
#include "setup/HHJson.h"
#include "lua/HHScriptSystem.h"
#include "lua/HHLuaGlobals.h"
#include "engine/HHEngineServices.h"
#include "engine/HHRuntime.h"
#include "engine/HHSha256.h"

namespace
{
	struct UIBindings
	{
		ICvGame1* pGame;
		ICvPreGame1* pPreGame;
		HHUserInterface* pUI;
	};
	UIBindings s_bindings = { NULL, NULL, NULL };

	// UI.RemoveNotification(id): the engine dismisses the active player's notification if the panel shows it and the
	// player may dismiss it. Returns true when dismissed.
	int HHLuaUIRemoveNotification(lua_State* L)
	{
		const int id = (int)luaL_checkinteger(L, 1);
		bool bDone = false;
		if(s_bindings.pGame && s_bindings.pPreGame && s_bindings.pUI)
		{
			const PlayerTypes eActive = s_bindings.pPreGame->activePlayer();
			const std::map<int, PlayerTypes>& shown = s_bindings.pUI->GetShownNotifications();
			std::map<int, PlayerTypes>::const_iterator it = shown.find(id);
			if(it != shown.end() && it->second == eActive)
			{
				if(ICvPlayer1* pPlayer = s_bindings.pGame->GetPlayer(eActive))
				{
					if(pPlayer->MayUserDismissNotification(id))
					{
						pPlayer->DismissNotification(id, true);
						bDone = true;
					}
					pPlayer->Destroy();
				}
			}
		}
		lua_pushboolean(L, bDone ? 1 : 0);
		return 1;
	}

	std::string Slashes(std::string s)
	{
		for(size_t i = 0; i < s.size(); ++i)
			if(s[i] == '/')
				s[i] = '\\';
		return s;
	}

	std::string BaseName(const std::string& path)
	{
		const size_t slash = path.find_last_of("\\/");
		return slash == std::string::npos ? path : path.substr(slash + 1);
	}

	std::string StripExtension(const std::string& path)
	{
		const size_t dot = path.find_last_of('.');
		const size_t slash = path.find_last_of("\\/");
		return dot == std::string::npos || (slash != std::string::npos && dot < slash) ? path : path.substr(0, dot);
	}

	std::string DirOf(const std::string& path)
	{
		const size_t slash = path.find_last_of("\\/");
		return slash == std::string::npos ? std::string() : path.substr(0, slash);
	}

	// Value of attribute szName in one XML start tag ("" if absent).
	std::string XmlAttr(const std::string& tag, const char* szName)
	{
		const std::string key = std::string(szName) + "=\"";
		size_t pos = 0;
		while((pos = tag.find(key, pos)) != std::string::npos)
		{
			if(pos == 0 || isspace((unsigned char)tag[pos - 1]))
			{
				const size_t start = pos + key.size();
				const size_t end = tag.find('"', start);
				return end == std::string::npos ? std::string() : tag.substr(start, end - start);
			}
			pos += key.size();
		}
		return std::string();
	}

	// The start tags <szElement ...> of an XML text, in document order.
	std::vector<std::string> XmlTags(const std::string& text, const char* szElement)
	{
		std::vector<std::string> tags;
		const std::string open = std::string("<") + szElement;
		size_t pos = 0;
		while((pos = text.find(open, pos)) != std::string::npos)
		{
			const size_t after = pos + open.size();
			if(after < text.size() && (isspace((unsigned char)text[after]) || text[after] == '/' || text[after] == '>'))
			{
				const size_t end = text.find('>', after);
				if(end == std::string::npos)
					break;
				tags.push_back(text.substr(pos, end - pos + 1));
				pos = end;
			}
			else
				pos = after;
		}
		return tags;
	}

	// Whether --skip-addin names the context at basePath (its path without extension): the file name, with or
	// without .lua or .xml, any folder in front ignored, case-insensitive.
	bool Skipped(const std::vector<std::string>& skip, const std::string& basePath)
	{
		const std::string stem = BaseName(basePath);
		for(size_t i = 0; i < skip.size(); ++i)
		{
			std::string name = BaseName(skip[i]);
			if(name.size() > 4 && (_stricmp(name.c_str() + name.size() - 4, ".lua") == 0 ||
			                       _stricmp(name.c_str() + name.size() - 4, ".xml") == 0))
				name.erase(name.size() - 4);
			if(_stricmp(name.c_str(), stem.c_str()) == 0)
				return true;
		}
		return false;
	}

	// A file next to the context's base path, else the VFS winner of that name.
	std::string FindSibling(const std::string& basePath, const char* szExt)
	{
		const std::string here = basePath + szExt;
		if(HHFileExists(here))
			return here;
		const std::vector<HHVfsEntry>* pFound = HHGetVfs().Find(BaseName(basePath) + szExt);
		return pFound && !pFound->empty() ? pFound->front().path : std::string();
	}

	// Loads one context (LoadNewContext(basePath)): its XML's child LuaContexts first (ASSUMPTION: the engine creates
	// the children while it reads the XML, before the parent's Lua runs), then its Lua file.
	void LoadContext(HHScriptSystem& kScripts, const std::vector<std::string>& skip, const std::string& mod, const std::string& entry,
	                 const std::string& basePath, const std::string& id, const std::string& parent, bool bHiddenAttr,
	                 int iDepth, std::vector<HHAddinContext>& out)
	{
		HHAddinContext c;
		c.mod = mod;
		c.entry = entry;
		c.context = id;
		c.parent = parent;
		c.hidden = bHiddenAttr;
		const std::string luaPath = FindSibling(basePath, ".lua");
		const std::string xmlPath = FindSibling(basePath, ".xml");
		if(Skipped(skip, basePath))
		{
			c.status = "skipped";
			c.error = "--skip-addin";
			c.path = luaPath;
			out.push_back(c);
			HHLog("UI add-in %s / %s: skipped (--skip-addin)", mod.c_str(), id.c_str());
			return;
		}
		std::vector<std::string> children;
		if(!xmlPath.empty())
		{
			std::string text;
			if(HHReadTextFile(xmlPath, text))
			{
				const std::vector<std::string> ctx = XmlTags(text, "Context");
				if(!ctx.empty() && XmlAttr(ctx[0], "Hidden") == "1")
					c.hidden = true;
				children = XmlTags(text, "LuaContext");
			}
		}
		if(iDepth < 4)
			for(size_t i = 0; i < children.size(); ++i)
			{
				const std::string file = Slashes(XmlAttr(children[i], "FileName"));
				if(file.empty())
					continue;
				std::string childId = XmlAttr(children[i], "ID");
				if(childId.empty())
					childId = BaseName(file);
				const std::string childBase = DirOf(luaPath.empty() ? xmlPath : luaPath) + "\\" + BaseName(file);
				LoadContext(kScripts, skip, mod, entry, childBase, childId, id, XmlAttr(children[i], "Hidden") == "1", iDepth + 1, out);
			}
		if(luaPath.empty())
		{
			c.status = xmlPath.empty() ? "missing" : "xml-only";
			c.error = xmlPath.empty() ? "no Lua or XML file for " + basePath : std::string();
			out.push_back(c);
			HHLog("UI add-in %s / %s: %s", mod.c_str(), id.c_str(), c.status.c_str());
			return;
		}
		c.path = luaPath;
		c.sha256 = HHSha256File(luaPath);
		const int iBefore = kScripts.GetErrorTotal();
		lua_State* L = HHLuaCreateUIContext(kScripts, id, c.hidden);
		if(!L)
		{
			c.status = "failed";
			c.error = "cannot create the Lua context";
		}
		else if(!kScripts.RunFile(L, luaPath))
		{
			c.status = "failed";
			const std::vector<HHLuaErrorRecord>& errors = kScripts.GetErrorRecords();
			if(kScripts.GetErrorTotal() > iBefore && !errors.empty())
				c.error = errors.back().file + HHFormat(":%d: ", errors.back().line) + errors.back().message;
			else
				c.error = "Lua error (see Lua.log)";
		}
		else
			c.status = "run";
		HHLog("UI add-in %s / %s: %s %s%s%s", mod.c_str(), id.c_str(), c.status.c_str(), luaPath.c_str(),
		      c.error.empty() ? "" : ": ", c.error.c_str());
		out.push_back(c);
	}
}

void HHRegisterUIBindings(HHScriptSystem& kScripts, ICvGame1* pGame, ICvPreGame1* pPreGame, HHUserInterface* pUI)
{
	s_bindings.pGame = pGame;
	s_bindings.pPreGame = pPreGame;
	s_bindings.pUI = pUI;
	lua_State* L = kScripts.GetMainState();
	lua_pushcfunction(L, HHLuaUIRemoveNotification);
	lua_setglobal(L, "__HHUIRemoveNotification");
}

bool HHAddinsSelfTest(std::vector<std::string>& checks)
{
	struct Case { const char* szSkip; bool bSkipped; };
	static const Case kCases[] = {
		{ "SmallResourceIcons", true }, { "SmallResourceIcons.lua", true }, { "smallresourceicons.XML", true },
		{ "LUA\\SmallResourceIcons.lua", true }, { "LUA/SmallResourceIcons", true },
		{ "SmallResourceIcons2.lua", false }, { "Small", false }, { "SmallResourceIcons.txt", false },
	};
	const std::string basePath = "C:\\MODS\\Some Mod\\LUA\\SmallResourceIcons";
	bool bOk = true;
	std::string failed;
	for(size_t i = 0; i < sizeof(kCases) / sizeof(kCases[0]); ++i)
	{
		const std::vector<std::string> skip(1, kCases[i].szSkip);
		if(Skipped(skip, basePath) != kCases[i].bSkipped)
		{
			bOk = false;
			failed += std::string(failed.empty() ? "" : ", ") + kCases[i].szSkip;
		}
	}
	const std::string line = std::string("--skip-addin matches a context by file name with or without extension")
		+ (bOk ? "" : " (wrong for " + failed + ")");
	checks.push_back(std::string(bOk ? "ok: " : "FAIL: ") + line);
	HHLog("  self-test %s %s", bOk ? "ok  " : "FAIL", line.c_str());
	return bOk;
}

std::vector<HHAddinContext> HHLoadUIAddins(HHScriptSystem& kScripts, const std::vector<std::string>& skip)
{
	std::vector<HHAddinContext> out;
	// Errors in the stub contexts are reported, not counted against the run.
	kScripts.SetCountErrors(false);
	const std::vector<HHActivatedMod>& mods = HHGetVfs().GetMods();
	for(size_t m = 0; m < mods.size(); ++m)
		for(size_t e = 0; e < mods[m].entryPoints.size(); ++e)
		{
			const HHModEntryPoint& ep = mods[m].entryPoints[e];
			if(_stricmp(ep.type.c_str(), "InGameUIAddin") != 0)
				continue;
			const std::string basePath = StripExtension(mods[m].folder + "\\" + Slashes(ep.file));
			LoadContext(kScripts, skip, mods[m].name, ep.file, basePath, BaseName(basePath), std::string(), false, 0, out);
		}
	kScripts.SetCountErrors(true);
	return out;
}

std::string HHFindAddinScript(const std::string& strName, std::string& strMod)
{
	const std::string want = StripExtension(BaseName(strName));
	const std::vector<HHActivatedMod>& mods = HHGetVfs().GetMods();
	for(size_t m = 0; m < mods.size(); ++m)
		for(size_t e = 0; e < mods[m].entryPoints.size(); ++e)
		{
			const HHModEntryPoint& ep = mods[m].entryPoints[e];
			if(_stricmp(ep.type.c_str(), "InGameUIAddin") != 0)
				continue;
			const std::string basePath = StripExtension(mods[m].folder + "\\" + Slashes(ep.file));
			if(_stricmp(BaseName(basePath).c_str(), want.c_str()) != 0)
				continue;
			const std::string path = FindSibling(basePath, ".lua");
			if(!path.empty())
			{
				strMod = mods[m].name;
				return path;
			}
		}
	return std::string();
}

int HHFireUIEvent(HHScriptSystem& kScripts, const char* szEvent, const std::string& strArgs)
{
	lua_State* L = kScripts.CreateLuaThread("Headless Events");
	if(!L)
		return 0;
	const std::string chunk = HHFormat("return __HHFireEvent('%s'%s%s)", szEvent, strArgs.empty() ? "" : ", ", strArgs.c_str());
	int n = 0;
	kScripts.SetCountErrors(false);
	if(luaL_loadbuffer(L, chunk.c_str(), chunk.size(), "=Headless Events") == 0 && kScripts.CallFunction(L, 0, 1))
		n = (int)lua_tointeger(L, -1);
	kScripts.SetCountErrors(true);
	kScripts.FreeLuaThread(L);
	if(n > 0)
		HHLog("Events.%s(%s): %d listener(s)", szEvent, strArgs.c_str(), n);
	return n;
}
