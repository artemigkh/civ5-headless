-- VP's WhosWinningPopup.lua (MODS\(2) Vox Populi\Core Files\Overrides) OnPopup: it rolls the synced RNG (Game.Rand:
-- the presenter, then list modes until a new allowed one) and reads the scores of the mode (GetMilitaryMight is a lazy
-- cache; RefreshTourism changes cities). CvGame::doTurn queues it every PROGRESS_POPUP_TURN_FREQUENCY turns when the
-- active player is alive: the turn autoplay hands the game back (hh-m2-aa100-a T100: 2 more sync RNG calls, no unit
-- selected). The last list mode persists between popups, as in the game's context.
local Food, Production, Gold, Science, Culture, Happiness, Wonders, Power, Influence, Tourism = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

local g_iListMode = -1

local function industrial()
	for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
		local p = Players[i]
		if p:IsAlive() and p:GetCurrentEra() >= GameInfo.Eras['ERA_INDUSTRIAL'].ID then return true end
	end
	return false
end

local function allowed(m)
	if m == Culture then
		for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
			local p = Players[i]
			if p:IsAlive() and p:GetNumPolicies() < 2 then return false end
		end
		if industrial() then return false end
	elseif m == Influence then
		local use = false
		for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
			local p = Players[i]
			if p:IsAlive() and p:GetNumCivsInfluentialOn() > 0 then use = true end
		end
		if not use then return false end
	elseif m == Tourism then
		local none = true
		for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
			local p = Players[i]
			if p:IsAlive() and p:GetTourism() / 100 > 0 then none = false end
		end
		if none then return false end
	elseif m == Food or m == Production then
		if industrial() then return false end
	elseif m == Wonders then
		if Game.GetNumWorldWonders() < 2 then return false end
	elseif m == Happiness then
		if Game.IsOption(GameOptionTypes.GAMEOPTION_NO_HAPPINESS) then return false end
	elseif m == Science then
		if Game.IsOption(GameOptionTypes.GAMEOPTION_NO_SCIENCE) then return false end
	end
	return true
end

local function score(p, m)
	if m == Food or m == Production then
		local y = m == Food and YieldTypes.YIELD_FOOD or YieldTypes.YIELD_PRODUCTION
		for c in p:Cities() do c:GetYieldRateTimes100(y) end
	elseif m == Gold then p:GetGold()
	elseif m == Science then Teams[p:GetTeam()]:GetTeamTechs():GetNumTechsKnown()
	elseif m == Culture then p:GetNumPolicies()
	elseif m == Happiness then p:GetExcessHappiness()
	elseif m == Wonders then p:GetNumWorldWonders()
	elseif m == Power then p:GetMilitaryMight()
	elseif m == Influence then p:GetNumCivsInfluentialOn()
	end
end

-- Returns true (the popup is shown and stays up) and the list mode for the log.
function OnPopup(popupInfo)
	Game.Rand(25, 'Rolling to determine Progress Screen dude.')
	local last = g_iListMode
	local r, bad = last, false
	while r == last or bad do
		bad = false
		r = Game.Rand(10, 'Rolling to determine Progress Screen list type.')
		if not allowed(r) then bad = true end
	end
	g_iListMode = r
	if r == Tourism then
		for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
			local p = Players[i]
			if p:IsAlive() then
				for ci = 0, p:GetNumCities() - 1 do
					local c = p:GetCityByID(ci)
					if c ~= nil then c:RefreshTourism(); c:GetYieldRateTimes100(YieldTypes.YIELD_TOURISM) end
				end
			end
		end
	else
		for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
			local p = Players[i]
			if p:IsAlive() then score(p, r) end
		end
	end
	return true, 'WhosWinning list mode ' .. r
end
