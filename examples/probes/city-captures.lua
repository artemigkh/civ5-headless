-- A Lua probe (docs/probes.md):
--   c5h run examples\specs\continents-tiny.json --turns 150 --lua-probe examples\probes\city-captures.lua
-- Every city capture as it happens:
--   - a CAPTURE|... line in Logs\Lua.log (works in the real game too);
--   - a row in extra\city-captures.csv (host only: the file is written with Lua's io library);
--   - a count per capturing player in _G.C5H_CAPTURES, which extras can read (game-summary.lua does).
local captures = {}
_G.C5H_CAPTURES = captures            -- in _G: extras run in their own Lua threads and see _G, not this probe's globals

local csv = nil
if io and C5H_EXTRA_DIR then          -- C5H_EXTRA_DIR: set by c5h run (probe-settings.lua), nil elsewhere
	csv = C5H_EXTRA_DIR .. '/city-captures.csv'
	local f = io.open(csv, 'w')
	if f then
		f:write('turn,x,y,city,from,to,population,conquest\n')
		f:close()
	else
		csv = nil
	end
end

GameEvents.CityCaptureComplete.Add(function(oldOwner, isCapital, x, y, newOwner, population, conquest)
	local turn = Game.GetGameTurn()
	local city = Map.GetPlot(x, y):GetPlotCity()
	local name = city and city:GetName() or '?'
	print(string.format('CAPTURE|turn=%d|x=%d|y=%d|city=%s|from=%d|to=%d|population=%d|conquest=%s',
		turn, x, y, name, oldOwner, newOwner, population or -1, tostring(conquest)))
	captures[newOwner] = (captures[newOwner] or 0) + 1
	if csv then
		local f = io.open(csv, 'a')   -- open, append, close: nothing is lost if the game stops
		if f then
			f:write(string.format('%d,%d,%d,"%s",%d,%d,%d,%s\n', turn, x, y, name, oldOwner, newOwner, population or -1,
				tostring(conquest)))
			f:close()
		end
	end
end)
