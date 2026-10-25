-- VP's EUI NotificationPanel.lua (MODS\(3a) VP - EUI Compatibility Files), "STACKING OBSERVER NOTIFICATION AGING": while
-- autoplay runs (observer mode), every NotificationAdded forces a sweep that right-clicks away (UI.RemoveNotification)
-- each shown, undismissed notification of the active player created at least UIObserverNotificationLifetimeTurns
-- (Stacking_Settings, default 3) turns ago. UI.RemoveNotification is the engine's dismiss: MayUserDismissNotification,
-- then DismissNotification (sets the serialized Notification::m_bDismissed; hh-m2-aa100-a playersRest from turn 22),
-- for a notification the panel shows (the host's UI.RemoveNotification checks that).
-- ASSUMPTION (per-turn digests): only the forced sweep on NotificationAdded has an effect; the once-per-turn sweeps on
-- SerialEventGameDataDirty / AIProcessingStartedForPlayer do not.
local function Expired()
	if Game.GetAIAutoPlay() <= 0 then return {} end
	local lifetime = 3
	if GameInfo.Stacking_Settings then
		for row in GameInfo.Stacking_Settings() do
			if row.Name == 'UIObserverNotificationLifetimeTurns' then lifetime = tonumber(row.Value) or 3 end
		end
	end
	lifetime = math.max(0, math.min(10000, math.floor(lifetime)))
	if lifetime == 0 then return {} end
	local player = Players[Game.GetActivePlayer()]
	local turn = Game.GetGameTurn()
	local t = {}
	for index = 0, player:GetNumNotifications() - 1 do
		local created = player:GetNotificationTurn(index)
		if not player:GetNotificationDismissed(index) and created >= 0 and turn - created >= lifetime then
			t[#t + 1] = player:GetNotificationIndex(index)
		end
	end
	return t
end

function OnNotificationAdded()
	-- The ids first, then the dismisses (a dismiss changes the notification list).
	local ids = Expired()
	local n = 0
	for _, id in ipairs(ids) do
		if UI.RemoveNotification(id) then n = n + 1 end
	end
	return n
end
