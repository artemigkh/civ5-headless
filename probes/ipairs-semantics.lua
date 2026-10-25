-- How the engine's ipairs iterates (the Continental Drift height maps start at index 0 and the real game visits it).
local function keys(t)
	local out = {}
	for i, v in ipairs(t) do out[#out + 1] = tostring(i) .. "=" .. tostring(v) end
	return table.concat(out, ",")
end
local r = {}
r.zeroAndOne = keys({[0] = "z", "a", "b"})
r.oneOnly = keys({"a", "b"})
r.zeroOnly = keys({[0] = "z"})
r.zeroHoleTwo = keys({[0] = "z", [2] = "b"})
r.negative = keys({[-1] = "n", [0] = "z", "a"})
r.falseAtZero = keys({[0] = false, "a"})
r.ipairsIsStock = tostring(ipairs)
r.pairsIsStock = tostring(pairs)
r.debug = type(debug)
local f, s, init = ipairs({"a"})
r.ipairsInit = tostring(init)
r.ipairsIterSame = tostring(f == ipairs({"b"}))
return r
