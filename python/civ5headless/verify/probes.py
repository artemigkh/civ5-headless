"""Lua probes the suite injects into both the host (--lua-probe) and the real game (RealGameSession.start_game).

- pregame.lua (this module): every PreGame value the stock Lua API can read, printed once when the probe runs (game
  started, before turn 0 is processed) as "C5HPG|<key>|<value>" lines in Lua.log. Only numbers, strings and
  booleans are printed; a getter the DLL lacks is skipped. The nickname and passwords are never printed (the real
  game's nickname is the Steam name).
- fingerprint.lua: the any-DLL workstream's probe (plan 9.3), found through civ5headless.fingerprint (PROBE or
  probe_path()) or probes/fingerprint.lua in the repository.
"""
from __future__ import annotations
from pathlib import Path

PREGAME = r'''-- civ5headless verify: PreGame snapshot (C5HPG lines in Lua.log)
local function out(k, v)
 local t = type(v)
 if t == 'number' or t == 'string' or t == 'boolean' then print('C5HPG|' .. k .. '|' .. tostring(v)) end
end
local function get(name, ...)
 local f = PreGame[name]
 if type(f) ~= 'function' then return nil end
 local ok, v = pcall(f, ...)
 if ok then return v end
 return nil
end
for _, name in ipairs({'GetMapScript', 'GetWorldSize', 'GetGameSpeed', 'GetEra', 'GetClimate', 'GetSeaLevel',
  'GetNumMinorCivs', 'GetMaxTurns', 'GetMaxCityElimination', 'GetTargetScore', 'GetLoadWBScenario',
  'IsRandomMapScript', 'IsRandomWorldSize', 'GetGameType', 'GetTurnTimerType', 'GetQuickHandicap', 'GetQuickCombat',
  'GetQuickCombatDefault', 'GetQuickMovement', 'GetPrivateGame', 'IsHotSeatGame', 'IsMultiplayerGame',
  'IsInternetGame', 'GetActivePlayer', 'GetMapNoPlayers', 'GetOverrideScenarioHandicap', 'GetTransferredMap'}) do
 out(name, get(name))
end
for p = 0, 63 do
 for _, name in ipairs({'GetSlotStatus', 'GetSlotClaim', 'GetCivilization', 'GetLeaderHead', 'GetTeam', 'GetHandicap',
   'IsMinorCiv', 'GetMinorCivType', 'GetPlayerColor', 'GetCivilizationDescription', 'GetCivilizationShortDescription',
   'GetCivilizationAdjective', 'GetLeaderName', 'IsHuman', 'IsPlayable'}) do
  out(name .. '.' .. p, get(name, p))
 end
end
if GameInfo and GameInfo.GameOptions then
 for row in GameInfo.GameOptions() do out('GetGameOption.' .. row.Type, get('GetGameOption', row.Type)) end
end
if GameInfo and GameInfo.Victories then
 for row in GameInfo.Victories() do out('IsVictory.' .. row.Type, get('IsVictory', row.ID)) end
end
for i = 1, 32 do out('GetMapOption.' .. i, get('GetMapOption', i)) end
print('C5HPG|end|1')
'''


def write_pregame(folder):
    path = Path(folder) / 'pregame.lua'
    path.write_text(PREGAME, encoding='utf-8')
    return path


def fingerprint_probe(fingerprint, repository=None):
    """The fingerprint probe file, or None: the module's PROBE or probe_path(), else probes/fingerprint.lua."""
    if fingerprint is not None:
        p = getattr(fingerprint, 'PROBE', None)
        if p is None and callable(getattr(fingerprint, 'probe_path', None)):
            try:
                p = fingerprint.probe_path()
            except Exception:  # noqa: BLE001
                p = None
        if p and Path(p).is_file():
            return Path(p)
    if repository and (Path(repository) / 'probes/fingerprint.lua').is_file():
        return Path(repository) / 'probes/fingerprint.lua'
    return None
