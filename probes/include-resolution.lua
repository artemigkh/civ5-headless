-- Which file does the engine's include() pick when several activated mods or DLC ship the same name?
-- Distinguishing functions (from the deployed files): VP's AssignStartingPlots defines
-- AddStrategicBalanceResources; the base game's defines CanBeCrater; CP's MapmakerUtilities defines
-- CivNeedsMountainStart.
local out = {}
local function try(name)
	local ok, a, b, c = pcall(include, name)
	local ret = {}
	for _, v in ipairs({a, b, c}) do
		if type(v) == 'table' then
			local t = {}
			for k, x in pairs(v) do t[#t + 1] = tostring(k) .. '=' .. tostring(x) end
			ret[#ret + 1] = t
		else
			ret[#ret + 1] = tostring(v)
		end
	end
	return {ok = ok, ret = ret}
end
out.mapmakerUtilities = try("MapmakerUtilities")
out.mmuIsCP = (CivNeedsMountainStart ~= nil)
out.assignStartingPlots = try("AssignStartingPlots")
out.aspIsVP = (AssignStartingPlots ~= nil and AssignStartingPlots.AddStrategicBalanceResources ~= nil)
out.aspIsBase = (AssignStartingPlots ~= nil and AssignStartingPlots.CanBeCrater ~= nil)
out.missing = try("NoSuchFileHeadlessProbe")
out.withExtension = try("MapmakerUtilities.lua")
out.debugLibrary = (debug ~= nil and debug.getinfo ~= nil)
if out.debugLibrary and AssignStartingPlots and AssignStartingPlots.Create then
	out.aspSource = debug.getinfo(AssignStartingPlots.Create, 'S').source
end
return out
