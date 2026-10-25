-- The stateful part of one in-game UI frame with EUI (DLC\UI_bc1, or a mod's copy of its NotificationPanel.lua), run
-- after every game core Update, when the real UI gets a frame with the core idle.
-- NotificationPanel.lua UpdateCivListNow (the civ ribbon; refreshed on AIProcessingStarted/Ended,
-- SerialEventCityInfoDirty and so on, i.e. every turn): for every ever-alive major in the ribbon that is alive, met by
-- the active team and not at war with it, player:CalculateGoldRate(), which recomputes
-- CvTreasury::m_iExpensePerTurnUnitMaintenance (serialized). Without it that field lags behind the reference whenever
-- units or cities change after the player's DoGold (first seen at the turn-0 doTurnBegin digest of every major that
-- founded its capital in turn 0; hh-m2-aa100-a T100).
-- ASSUMPTION: the ribbon is shown (EUI option CivRibbon, default on) and no other UI getter is stateful.
function OnUIFrame()
	local a = Game.GetActivePlayer()
	local at = Teams[Players[a]:GetTeam()]
	local n = 0
	for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
		local p = Players[i]
		if p and p:IsEverAlive() and not p:IsMinorCiv() and i ~= a and p:IsAlive() and at:IsHasMet(p:GetTeam())
		   and not Teams[p:GetTeam()]:IsAtWar(at:GetID()) then
			p:CalculateGoldRate(); n = n + 1
		end
	end
	return n
end
