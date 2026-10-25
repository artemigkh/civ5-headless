-- C5H fingerprint probe (format 1): a per-turn snapshot of the game state through plain stored-value getters of the
-- stock Firaxis Lua API, hashed per section and printed to Lua.log. It runs identically in the real game (injected
-- through FireTuner into the InGame context) and in the host (civ5headless.exe --lua-probe probes\fingerprint.lua).
-- python/civ5headless/fingerprint.py reads and compares the lines; docs: that module's docstring.
--
-- The probe must never change a game: every call below is a getter whose C++ body only reads stored members, in the
-- stock DLL and in VP (vetted against both sources; no lazy cache: GetScore, GetMilitaryMight, CalculateGoldRate and
-- the happiness and yield getters are avoided). The host checks it: runs with and without the probe give identical
-- digests (DLLs with the digest additions), and dense against sparse sampling the same fingerprints (any DLL).
--
-- Configuration, as globals set before this file runs (an earlier --lua-probe file or tuner chunk, same context):
--   C5HFP_EVERY = k     fingerprint the turns that are multiples of k (default 1: every turn)
--   C5HFP_TURNS = {..}  fingerprint these turns too (a list of turn numbers)
--   C5HFP_SPLIT = n     sections per printed line (default 12)
--
-- Output, through print (Lua.log puts the context name and, in the game, a time stamp before it):
--   C5HFP|v=1|meta|turn=T|plots=N|width=W|height=H|maxMajors=M|maxCivs=C|every=K   (once, when the probe runs)
--   C5HFP|v=1|player|turn=T|player=ID|team=T|civ=CIVILIZATION_X|leader=LEADER_Y      (then one per ever-alive player;
--                                  minor=MINOR_CIV_Z instead of leader for city-states, neither for the barbarians)
--   C5HFP|v=1|turn=T|point=P|part=I/N|total=XXXXXXXX|game=...|map=...|players=...|techs=...|diplomacy=...|p00=...
--   C5HM|v=1|turn=T|player=ID|alive=..|score=..|gold=..|cities=..|population=..|techs=..|policies=..|units=..|...
--   C5HFP|v=1|turn=T|point=P|error=MESSAGE           (the snapshot failed; nothing else for that turn)
-- P is inject (the turn the probe runs in: 0 in a new game) or PlayerDoTurn (the first GameEvents.PlayerDoTurn of turn
-- T, when the turn's first player starts its turn). Hashes are 8 hex digits: h = (h * 31 + v) % 4294967291 over the
-- values in a fixed order (doubles; exact for the integers the getters return). Sections: game (turn, state, winner,
-- stored scores), map (every plot), pNN (one per ever-alive player: treasury, culture, faith, era, policies, religion,
-- city-state ties, every city with its buildings, every unit), tNN (one per team: techs and research progress), dNN
-- (one per team: war and contact with every other team), players / techs / diplomacy (the pNN / tNN / dNN hashes
-- combined) and total (every section).
if C5HFP_LOADED then return end
C5HFP_LOADED = true

local VERSION = 1
local P = 4294967291
local EVERY = tonumber(C5HFP_EVERY) or 1
local SPLIT = tonumber(C5HFP_SPLIT) or 12
local EXTRA = {}
if type(C5HFP_TURNS) == 'table' then for _, t in ipairs(C5HFP_TURNS) do EXTRA[tonumber(t)] = true end end

local floor = math.floor
local format = string.format
local byte = string.byte

local function H(h, v)
	local t = type(v)
	if t == 'number' then
		if v ~= floor(v) then v = floor(v * 1000 + 0.5) end
		return (h * 31 + v) % P
	elseif t == 'boolean' then
		return (h * 31 + (v and 1 or 2)) % P
	elseif t == 'string' then
		for i = 1, #v do h = (h * 31 + byte(v, i)) % P end
		return h
	end
	return (h * 31 + 3) % P   -- nil and anything else
end

local function Hex(h)
	return format('%04x%04x', floor(h / 65536), h % 65536)
end

-- Database IDs, sorted (the same database in the game and the host gives the same lists).
local function Ids(tbl, filter)
	local ids = {}
	for row in tbl() do
		if filter == nil or filter(row) then ids[#ids + 1] = row.ID end
	end
	table.sort(ids)
	return ids
end

local MAX_MAJOR = GameDefines.MAX_MAJOR_CIVS
local MAX_CIV = GameDefines.MAX_CIV_PLAYERS   -- the barbarians are player MAX_CIV_PLAYERS
local TECHS = Ids(GameInfo.Technologies)
local POLICIES = Ids(GameInfo.Policies)
local BUILDINGS = Ids(GameInfo.Buildings)
local WONDERS = {}
do
	local worldClass = {}
	for row in GameInfo.BuildingClasses() do
		if (row.MaxGlobalInstances or -1) > 0 then worldClass[row.Type] = true end
	end
	for row in GameInfo.Buildings() do
		if worldClass[row.BuildingClass] then WONDERS[row.ID] = true end
	end
end

local function EverAlive(i)
	local p = Players[i]
	return p ~= nil and p:IsEverAlive()
end

local function Team(i) return Players[i]:GetTeam() end

local function GameSection(turn)
	local h = H(0, turn)
	h = H(h, Game.GetElapsedGameTurns())
	h = H(h, Game.GetGameState())
	h = H(h, Game.GetWinner())
	for i = 0, MAX_CIV do
		if EverAlive(i) then h = H(h, Game.GetPlayerScore(i)) end
	end
	return h
end

local function MapSection()
	local h = 0
	for i = 0, Map.GetNumPlots() - 1 do
		local pl = Map.GetPlotByIndex(i)
		h = H(h, (pl:GetOwner()))
		h = H(h, pl:GetPlotType())
		h = H(h, pl:GetTerrainType())
		h = H(h, pl:GetFeatureType())
		h = H(h, pl:GetResourceType())
		h = H(h, pl:GetNumResource())
		h = H(h, pl:GetImprovementType())
		h = H(h, pl:IsImprovementPillaged())
		h = H(h, pl:GetRouteType())
		h = H(h, pl:IsRoutePillaged())
	end
	return h
end

-- Also returns the player's metrics (major civs).
local function PlayerSection(id)
	local p = Players[id]
	local h = H(0, id)
	h = H(h, p:IsAlive())
	h = H(h, p:GetTeam())
	h = H(h, p:GetCivilizationType())
	h = H(h, p:GetGold())
	h = H(h, p:GetJONSCulture())
	h = H(h, p:GetFaith())
	h = H(h, p:GetCurrentEra())
	h = H(h, p:GetGoldenAgeTurns())
	h = H(h, p:GetTotalPopulation())
	h = H(h, p:GetNumCities())
	h = H(h, p:GetNumUnits())
	h = H(h, p:GetNumMilitaryUnits())
	local policies = 0
	for _, pid in ipairs(POLICIES) do
		local has = p:HasPolicy(pid)
		if has then policies = policies + 1 end
		h = H(h, has)
	end
	h = H(h, p:HasCreatedPantheon())
	h = H(h, p:GetBeliefInPantheon())
	local religion = p:GetReligionCreatedByPlayer()
	h = H(h, religion)
	if p:IsMinorCiv() then
		h = H(h, p:GetAlly())
		for m = 0, MAX_MAJOR - 1 do
			if EverAlive(m) then h = H(h, p:GetMinorCivFriendshipWithMajor(m)) end
		end
	end
	local wonders, captured = 0, 0
	for city in p:Cities() do
		h = H(h, city:GetID())
		h = H(h, city:GetX())
		h = H(h, city:GetY())
		h = H(h, city:GetPopulation())
		h = H(h, city:GetFood())
		h = H(h, city:GetProduction())
		h = H(h, city:GetProductionUnit())
		h = H(h, city:GetProductionBuilding())
		h = H(h, city:GetProductionProject())
		h = H(h, city:GetDamage())
		local original = city:GetOriginalOwner()
		if original ~= id then captured = captured + 1 end
		h = H(h, original)
		h = H(h, city:IsCapital())
		h = H(h, city:IsPuppet())
		h = H(h, city:IsOccupied())
		h = H(h, city:IsRazing())
		h = H(h, city:GetReligiousMajority())
		for _, b in ipairs(BUILDINGS) do
			if city:IsHasBuilding(b) then
				h = H(h, b)
				if WONDERS[b] then wonders = wonders + 1 end
			end
		end
	end
	for unit in p:Units() do
		h = H(h, unit:GetID())
		h = H(h, unit:GetUnitType())
		h = H(h, unit:GetX())
		h = H(h, unit:GetY())
		h = H(h, unit:GetDamage())
		h = H(h, unit:GetExperience())
		h = H(h, unit:GetLevel())
		h = H(h, unit:IsEmbarked())
	end
	local m = nil
	if id < MAX_MAJOR and not p:IsMinorCiv() and not p:IsBarbarian() then
		local team = Teams[p:GetTeam()]
		local wars, warsMinor = 0, 0
		for j = 0, MAX_CIV - 1 do
			if j ~= id and EverAlive(j) and Players[j]:IsAlive() and team:IsAtWar(Team(j)) then
				if j < MAX_MAJOR and not Players[j]:IsMinorCiv() then wars = wars + 1 else warsMinor = warsMinor + 1 end
			end
		end
		m = {
			{'alive', p:IsAlive() and 1 or 0}, {'score', Game.GetPlayerScore(id)}, {'gold', p:GetGold()},
			{'cities', p:GetNumCities()}, {'population', p:GetTotalPopulation()},
			{'techs', team:GetTeamTechs():GetNumTechsKnown()}, {'policies', policies}, {'units', p:GetNumUnits()},
			{'military', p:GetNumMilitaryUnits()}, {'culture', p:GetJONSCulture()}, {'faith', p:GetFaith()},
			{'wonders', wonders}, {'religions', religion > 0 and 1 or 0}, {'pantheon', p:HasCreatedPantheon() and 1 or 0},
			{'wars', wars}, {'warsMinor', warsMinor}, {'captured', captured}, {'era', p:GetCurrentEra()},
		}
	end
	return h, m
end

local function TeamSections(t, teams)
	local team = Teams[t]
	local techs = team:GetTeamTechs()
	local h = H(0, t)
	for _, tech in ipairs(TECHS) do
		h = H(h, team:IsHasTech(tech))
		h = H(h, techs:GetResearchProgress(tech))
	end
	local d = H(0, t)
	for _, u in ipairs(teams) do
		if u ~= t then
			d = H(d, team:IsHasMet(u))
			d = H(d, team:IsAtWar(u))
		end
	end
	return h, d
end

local function Snapshot(turn)
	local sections = {}
	local function Add(name, h) sections[#sections + 1] = {name, h} end
	local metrics = {}
	Add('game', GameSection(turn))
	Add('map', MapSection())
	local players, playerList = 0, {}
	local teamSeen, teams = {}, {}
	for i = 0, MAX_CIV do
		if EverAlive(i) then
			local h, m = PlayerSection(i)
			players = H(players, h)
			playerList[#playerList + 1] = {format('p%02d', i), h}
			if m then metrics[#metrics + 1] = {i, m} end
			local t = Team(i)
			if not teamSeen[t] then teamSeen[t] = true; teams[#teams + 1] = t end
		end
	end
	table.sort(teams)
	local techs, diplomacy, teamList, diploList = 0, 0, {}, {}
	for _, t in ipairs(teams) do
		local h, d = TeamSections(t, teams)
		techs = H(techs, h)
		diplomacy = H(diplomacy, d)
		teamList[#teamList + 1] = {format('t%02d', t), h}
		diploList[#diploList + 1] = {format('d%02d', t), d}
	end
	Add('players', players)
	Add('techs', techs)
	Add('diplomacy', diplomacy)
	for _, s in ipairs(playerList) do Add(s[1], s[2]) end
	for _, s in ipairs(teamList) do Add(s[1], s[2]) end
	for _, s in ipairs(diploList) do Add(s[1], s[2]) end
	local total = 0
	for _, s in ipairs(sections) do total = H(H(total, s[1]), s[2]) end
	return total, sections, metrics
end

local function Emit(turn, point)
	local ok, total, sections, metrics = pcall(Snapshot, turn)
	local head = format('C5HFP|v=%d|turn=%d|point=%s', VERSION, turn, point)
	if not ok then
		print(head .. '|error=' .. string.gsub(tostring(total), '[|\r\n]', ' '))
		return
	end
	local parts = math.max(1, math.ceil(#sections / SPLIT))
	for part = 1, parts do
		local line = {format('%s|part=%d/%d', head, part, parts)}
		if part == 1 then line[#line + 1] = 'total=' .. Hex(total) end
		for i = (part - 1) * SPLIT + 1, math.min(#sections, part * SPLIT) do
			line[#line + 1] = sections[i][1] .. '=' .. Hex(sections[i][2])
		end
		print(table.concat(line, '|'))
	end
	for _, pm in ipairs(metrics) do
		local line = {format('C5HM|v=%d|turn=%d|player=%d', VERSION, turn, pm[1])}
		for _, kv in ipairs(pm[2]) do line[#line + 1] = kv[1] .. '=' .. tostring(kv[2]) end
		print(table.concat(line, '|'))
	end
end

local function Wanted(turn)
	return EXTRA[turn] or (EVERY > 0 and turn % EVERY == 0)
end

local function Meta(turn)
	local w, h = Map.GetGridSize()
	print(format('C5HFP|v=%d|meta|turn=%d|plots=%d|width=%d|height=%d|maxMajors=%d|maxCivs=%d|every=%d', VERSION, turn,
		Map.GetNumPlots(), w, h, MAX_MAJOR, MAX_CIV, EVERY))
	for i = 0, MAX_CIV do
		if EverAlive(i) then
			local p = Players[i]
			local civ = GameInfo.Civilizations[p:GetCivilizationType()]
			local line = format('C5HFP|v=%d|player|turn=%d|player=%d|team=%d|civ=%s', VERSION, turn, i, p:GetTeam(),
				civ and civ.Type or '?')
			if p:IsMinorCiv() then
				local info = GameInfo.MinorCivilizations[p:GetMinorCivType()]
				line = line .. '|minor=' .. (info and info.Type or '?')
			elseif not p:IsBarbarian() then
				local leader = GameInfo.Leaders[p:GetLeaderType()]
				line = line .. '|leader=' .. (leader and leader.Type or '?')
			end
			print(line)
		end
	end
end

local g_iLastTurn = Game.GetGameTurn()
Meta(g_iLastTurn)
if Wanted(g_iLastTurn) then Emit(g_iLastTurn, 'inject') end

GameEvents.PlayerDoTurn.Add(function(iPlayer)
	local turn = Game.GetGameTurn()
	if turn == g_iLastTurn then return end
	g_iLastTurn = turn
	if Wanted(turn) then Emit(turn, 'PlayerDoTurn') end
end)
