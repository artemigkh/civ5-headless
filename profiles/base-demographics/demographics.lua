-- Demographics.lua BuildTables at load (base game, line "BuildTables();" at the end of the file; CP and VP keep it):
-- for players 0..MAX_MAJOR_CIVS inclusive, the getters behind the eight demographics columns. Literacy (team techs)
-- and the display code are left out: they keep no state.
-- ASSUMPTION (dump-t000 parity, M2): the same getters in the same order; only the might cache is stateful.
function OnLoadScreen()
	local n = 0
	for i = 0, GameDefines.MAX_MAJOR_CIVS do
		local p = Players[i]
		if p ~= nil then
			p:GetRealPopulation(); p:CalculateTotalYield(YieldTypes.YIELD_FOOD); p:CalculateTotalYield(YieldTypes.YIELD_PRODUCTION)
			p:CalculateGrossGold(); p:GetNumPlots(); p:GetMilitaryMight(); p:GetExcessHappiness()
			n = n + 1
		end
	end
	return n .. " players"
end
