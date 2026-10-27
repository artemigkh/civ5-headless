-- A checkpoint extra (docs/probes.md):
--   c5h run examples\specs\continents-tiny.json --turns 100 --checkpoint-extra examples\probes\turn-stats.lua
-- At every checkpoint, one entry per living major civilization, read through getters that only return stored values
-- (the game plays the same with and without this file), plus the change in gold since the previous checkpoint.
-- Output: extra\turn-stats.jsonl, one row per checkpoint: {"turn": T, "final": false, "seconds": S, "value": {...}}.
local ctx = ...                       -- name, kind, turn, state (kept between checkpoints), runDir, extraDir
local lastGold = ctx.state.gold or {}
local players = {}
for id = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
	local p = Players[id]
	if p and p:IsAlive() and not p:IsMinorCiv() then
		local civ = GameInfo.Civilizations[p:GetCivilizationType()]
		local era = GameInfo.Eras[p:GetCurrentEra()]
		local gold = p:GetGold()
		players[#players + 1] = {
			player = id,
			civ = civ and civ.Type,
			era = era and era.Type,
			score = Game.GetPlayerScore(id),
			gold = gold,
			goldChange = lastGold[id] and gold - lastGold[id],   -- nil (left out) at the first checkpoint
			culture = p:GetJONSCulture(),
			faith = p:GetFaith(),
			cities = p:GetNumCities(),
			population = p:GetTotalPopulation(),
			techs = Teams[p:GetTeam()]:GetTeamTechs():GetNumTechsKnown(),
			units = p:GetNumUnits(),
			military = p:GetNumMilitaryUnits(),
		}
		lastGold[id] = gold
	end
end
ctx.state.gold = lastGold
return {players = players}
