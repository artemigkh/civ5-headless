-- CP's CityEventPopup.lua (Core Files\New UI) OnPopup for BUTTONPOPUP_MODDER_7, the single-choice city event result
-- (CvCity::DoStartEvent queues it for a human owner): outside the spy branch (Option1) it adds the owner's
-- NOTIFICATION_GENERIC "City Event: <title>" (game state) and shows the popup. Data1 is the event choice, Data2 the
-- city ID, Data3 the owner. M5 options-5 (events on): the real p00 has the notification.
local function AddCityEventNotification(iChoice, iCity, iOwner)
	local info = GameInfo.CityEventChoices[iChoice]
	local owner = Players[iOwner]
	if not info or not owner then return 0 end
	local city = owner:GetCityByID(iCity)
	if city == nil then return 0 end
	local name = Locale.ConvertTextKey(city:GetNameKey())
	local title = Locale.Lookup('TXT_KEY_CITY_EVENT_TITLE', name, info.Description)
	local help = Locale.Lookup('TXT_KEY_CITY_EVENT_HELP', name, city:GetScaledEventChoiceValue(iChoice))
	owner:AddNotification(NotificationTypes.NOTIFICATION_GENERIC, help, Locale.ConvertTextKey('TXT_KEY_CITY_EVENT_NOTIFICATION') .. title,
		city:Plot():GetX(), city:Plot():GetY())
	return 1
end

-- Returns true (shown, stays up) unless it is the spy branch.
function OnPopup(popupInfo)
	if popupInfo.Option1 then return false end
	local n = AddCityEventNotification(popupInfo.Data1, popupInfo.Data2, popupInfo.Data3)
	return true, 'CityEventPopup notification ' .. n
end
