-- A final extra (docs/probes.md):
--   c5h run examples\specs\continents-tiny.json --turns 150 --final-extra examples\probes\game-summary.lua
-- Once, after the last turn: every major civilization's cities (name, position, population, number of buildings,
-- founder), its wonders and policies by name, its techs, and the cities it captured when city-captures.lua ran too.
-- Output: extra\game-summary-final.json.
local ctx = ...
local wonderClass = {}
for row in GameInfo.BuildingClasses() do
	if (row.MaxGlobalInstances or -1) > 0 then wonderClass[row.Type] = true end
end
local captures = _G.C5H_CAPTURES or {}

local out = {turn = ctx.turn, winningTeam = Game.GetWinner(), players = {}}
for id = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
	local p = Players[id]
	if p and p:IsEverAlive() and not p:IsMinorCiv() then
		local civ = GameInfo.Civilizations[p:GetCivilizationType()]
		local e = {player = id, civ = civ and civ.Type, alive = p:IsAlive(), captures = captures[id] or 0,
			techs = Teams[p:GetTeam()]:GetTeamTechs():GetNumTechsKnown(), cities = {}, wonders = {}, policies = {}}
		for city in p:Cities() do
			local buildings = 0
			for b in GameInfo.Buildings() do
				if city:IsHasBuilding(b.ID) then
					buildings = buildings + 1
					if wonderClass[b.BuildingClass] then e.wonders[#e.wonders + 1] = b.Type end
				end
			end
			e.cities[#e.cities + 1] = {name = city:GetName(), x = city:GetX(), y = city:GetY(),
				population = city:GetPopulation(), buildings = buildings, capital = city:IsCapital(),
				founder = city:GetOriginalOwner()}
		end
		for row in GameInfo.Policies() do
			if p:HasPolicy(row.ID) then e.policies[#e.policies + 1] = row.Type end
		end
		out.players[#out.players + 1] = e
	end
end
return out
