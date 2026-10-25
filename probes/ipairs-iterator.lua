-- The engine's ipairs iterator called directly (see ipairs-semantics.lua).
local function call(f, t, i)
	local ok, a, b = pcall(f, t, i)
	return ok and (tostring(a) .. "," .. tostring(b)) or ("error: " .. tostring(a))
end
local t = {[0] = "z", "a", "b"}
local u = {"a", "b"}
local f, s, init = ipairs(t)
local r = {}
r.nret = select("#", ipairs(t))
r.initType = type(init)
r.initIsZero = tostring(init == 0)
r.initMinusOne = tostring(init == -1)
r.f_t_init = call(f, t, init)
r.f_t_0 = call(f, t, 0)
r.f_t_m1 = call(f, t, -1)
r.f_t_1 = call(f, t, 1)
r.f_u_0 = call(f, u, 0)
r.f_u_m1 = call(f, u, -1)
r.f_t_nil = call(f, t, nil)
r.sameAsStateIdentity = tostring(s == t)
return r
