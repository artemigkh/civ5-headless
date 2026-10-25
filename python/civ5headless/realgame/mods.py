"""Mod activation in the real game: make the enabled mods exactly a given set, then activate them.

At the main menu the ModsBrowser context holds the game's mod list (enabled mods persist in Civ5ModsDatabase.db).
set_enabled_lua() disables every enabled mod that is not wanted (or has another version) and enables the wanted
ones, then reads the list back; ACTIVATE presses the browser's Next button (OnNextButtonClicked), which loads the
mods (their DLL and database) and opens ModsSinglePlayer, where a game is set up and started.

Versions come from the activated mods in the configuration (mods_db), else from the highest version of that mod in
the MODS folder.
"""
from __future__ import annotations
import re

from .tuner import lua_string

UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z')
DISMISS_LEGAL = 'UIManager:DequeuePopup(ContextPtr);return true'
ACTIVATE = "OnNextButtonClicked();return 'activated'"


class ModError(Exception):
    pass


def resolve(cfg, mod_ids):
    """[(id, version, name)] for the given ids, in the given order."""
    known = {m.id.lower(): (m.version, m.name) for m in cfg.active_mods}
    installed = None
    out, seen = [], set()
    for raw in mod_ids:
        mid, _, ver = str(raw).strip().strip('{}').partition(':')
        mid = mid.lower()
        if not UUID.fullmatch(mid):
            raise ModError(f'not a mod id: {raw!r}')
        if mid in seen:
            raise ModError(f'mod {mid} given twice')
        seen.add(mid)
        if ver:
            out.append((mid, int(ver), known.get(mid, (0, ''))[1]))
        elif mid in known:
            out.append((mid, known[mid][0], known[mid][1]))
        else:
            if installed is None:
                from ..dbbuild import scan_mods
                installed = list(scan_mods(cfg.mods_dir).values()) if cfg.mods_dir and cfg.mods_dir.is_dir() else []
            versions = [m for m in installed if m.id == mid]
            if not versions:
                raise ModError(f'mod {mid} is neither activated in mods_db nor installed in mods_dir')
            best = max(versions, key=lambda m: m.version)
            out.append((mid, best.version, best.name))
    return out


def set_enabled_lua(mods):
    """ModsBrowser Lua that leaves exactly these (id, version, name) mods enabled and returns
    {ok, before, after, disabled, enabled}."""
    wanted = ',\n'.join(' {ModID=' + lua_string(i) + ',Version=' + str(int(v)) + '}' for i, v, _ in mods)
    return 'local wanted={\n' + wanted + '\n}\n' + r'''
local function read()
 local ok,mods=pcall(Modding.GetEnabledModsByActivationOrder)
 if not ok or type(mods)~="table" then return nil,"enabled list unavailable" end
 local rows={}
 for _,m in ipairs(mods) do rows[#rows+1]={ModID=string.lower(tostring(m.ModID)),Version=tonumber(m.Version),raw=m.ModID} end
 return rows
end
local want={}
for _,m in ipairs(wanted) do want[m.ModID]=m.Version end
local before,err=read()
if not before then return {ok=false,error=err} end
local disabled,enabled,have=0,0,{}
for _,m in ipairs(before) do
 if want[m.ModID]~=m.Version then Modding.DisableMod(m.raw,m.Version);disabled=disabled+1 else have[m.ModID]=true end
end
for _,m in ipairs(wanted) do
 if not have[m.ModID] then Modding.EnableMod(m.ModID,m.Version);enabled=enabled+1 end
end
local after=read() or {}
local exact=#after==#wanted
for _,m in ipairs(after) do if want[m.ModID]~=m.Version then exact=false end end
return {ok=exact,before=before,after=after,disabled=disabled,enabled=enabled}
'''
