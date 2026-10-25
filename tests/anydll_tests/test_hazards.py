"""civ5headless.hazards: method derivation from DLL sources and the UI Lua scan (synthetic sources)."""
import json
from pathlib import Path
import tempfile
import unittest

from civ5headless import hazards

LUA_PLAYER = '''
#define Method(Name) lua_pushcclosure(L, l##Name, 0); lua_setfield(L, t, #Name);
void CvLuaPlayer::PushMethods(lua_State* L, int t)
{
	Method(ChangeGold);
	Method(GetGold);
	Method(GetMight);
	Method(GetTurnString);
	Method(GetDealValue);
	Method(GetScore);
}
int CvLuaPlayer::lChangeGold(lua_State* L)
{
	CvPlayerAI* pkPlayer = GetInstance(L);
	pkPlayer->GetTreasury()->ChangeGold(lua_tointeger(L, 2));
	return 1;
}
int CvLuaPlayer::lGetGold(lua_State* L)
{
	return BasicLuaMethod(L, &CvPlayerAI::GetGold);
}
int CvLuaPlayer::lGetMight(lua_State* L)
{
	return BasicLuaMethod(L, &CvPlayerAI::GetMight);
}
int CvLuaPlayer::lGetTurnString(lua_State* L)
{
	CvString strString;
	CvGameTextMgr::setDateStr(strString, 1);
	lua_pushstring(L, strString);
	return 1;
}
int CvLuaPlayer::lGetDealValue(lua_State* L)
{
	TradeConnection kConnection;
	kConnection.SetCities(1, 2);
	lua_pushinteger(L, kConnection.Value());
	return 1;
}
int CvLuaPlayer::lGetScore(lua_State* L)
{
	CvPlayerAI* pkPlayer = GetInstance(L);
	lua_pushinteger(L, pkPlayer->GetScore());
	return 1;
}
'''

PLAYER = '''
int CvPlayer::GetGold() const
{
	return m_iGold;
}
int CvPlayer::GetMight() const
{
	if (m_iTurn < 5)
		const_cast<CvPlayer*>(this)->updateMight();
	return m_iMight;
}
void CvPlayer::updateMight()
{
	m_iMight = 3;
}
int CvPlayer::GetScore() const
{
	const std::map<int, int>& m_localCopy = GetTable();
	return GetScoreFromMight() + m_localCopy.size();
}
int CvPlayer::GetScoreFromMight() const
{
	return GetMight() * 2;
}
'''

LUA_UI = '''
-- Players[0]:ChangeGold(1) in a comment is not a call
local s = "Players[0]:ChangeGold(2)"
Players[0]:ChangeGold(3)
local function OnTurn()
	local pPlayer = Players[Game.GetActivePlayer()]
	pPlayer:ChangeGold(4)
	Controls.Label:ChangeGold(5)
end
Events.ActivePlayerTurnStart.Add(OnTurn)
function ToolTip(control)
	local x = Players[0]:GetMight()
	return Game.Rand(10, "roll")
end
Controls.Button:SetToolTipCallback(ToolTip)
local rand = Game.Rand
Events.SerialEventGameMessagePopup.Add(function(popupInfo)
	Network.SendDoTask(1, 2, 3)
	Helper()
end)
function Helper()
	Players[1]:GetScore()
end
'''


class DeriveTest(unittest.TestCase):
    def test_derive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Lua').mkdir()
            (root / 'Lua' / 'CvLuaPlayer.cpp').write_text(LUA_PLAYER, encoding='latin-1')
            (root / 'CvPlayer.cpp').write_text(PLAYER, encoding='latin-1')
            (root / 'CvPlayer.h').write_text('class CvPlayer { mutable int m_iCache; };\n', encoding='latin-1')
            got = hazards.derive_methods(root)['Player']
        self.assertEqual(got['ChangeGold'], {'kind': 'writes', 'calls': ['ChangeGold']})
        self.assertNotIn('GetGold', got)
        self.assertEqual(got['GetMight']['kind'], 'cache')
        self.assertIn('const_cast(this)->updateMight', got['GetMight']['chain'][-1])
        self.assertNotIn('GetTurnString', got)  # writes a local string only
        self.assertNotIn('GetDealValue', got)  # a local value's setter
        self.assertEqual(got['GetScore']['kind'], 'cache')
        self.assertEqual(got['GetScore']['chain'][:2], ['CvPlayer::GetScore', 'CvPlayer::GetScoreFromMight'])

    def test_shipped_data(self):
        methods, source, curated = hazards.load_methods()
        self.assertIn('lua-state-methods.json', source)
        self.assertIn('Player', {e['class'] for e in methods['ChangeGold']})
        self.assertEqual({e['kind'] for e in methods['Rand']}, {'curated'})
        self.assertIn('curated', {e['kind'] for e in methods['CalculateGoldRate']})
        self.assertNotIn('CreateFreeLuxuryCheck', methods)  # vetted: not a hazard
        self.assertNotIn('GetGold', methods)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.methods = {
            'ChangeGold': [{'class': 'Player', 'kind': 'writes', 'why': 'calls ChangeGold'}],
            'GetMight': [{'class': 'Player', 'kind': 'curated', 'why': 'lazy'}],
            'GetScore': [{'class': 'Player', 'kind': 'cache', 'why': 'chain'}],
            'Rand': [{'class': 'Game', 'kind': 'curated', 'why': 'rng'}, {'class': 'Map', 'kind': 'curated', 'why': 'rng'}],
        }
        self.engine = [(__import__('re').compile(r'\bNetwork\s*\.\s*(Send\w+)\s*\('), 'net')]

    def test_scan(self):
        hits = hazards.scan_text(LUA_UI, self.methods, self.engine)
        got = [(h['line'], h['method'], h['kind'], h['triggers']) for h in hits]
        self.assertEqual(got, [
            (4, 'ChangeGold', 'writes', ['load']),
            (7, 'ChangeGold', 'writes', ['Events.ActivePlayerTurnStart']),
            (12, 'GetMight', 'curated', ['passed to Controls.Button:SetToolTipCallback']),
            (13, 'Rand', 'curated', ['passed to Controls.Button:SetToolTipCallback']),
            (16, 'Rand', 'curated', ['load']),
            (18, 'SendDoTask', 'engine', ['Events.SerialEventGameMessagePopup']),
            (22, 'GetScore', 'cache', ['via Events.SerialEventGameMessagePopup']),
        ])
        self.assertEqual(hits[0]['call'], 'Players[0]:ChangeGold(')
        self.assertEqual(hits[3]['classes'], ['Game'])
        self.assertTrue(hits[4]['call'].endswith('(reference)'))
        self.assertEqual(hits[1]['function'], 'OnTurn')

    def test_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'p').mkdir()
            (root / 'p' / 'profile.json').write_text(json.dumps(
                {'name': 'p', 'covers': [{'file': 'Panel.lua', 'methods': ['GetMight']}]}), encoding='utf-8')
            ui = root / 'Panel.lua'
            ui.write_text(LUA_UI, encoding='utf-8')
            covers = hazards.load_covers(root)
            _, hits = hazards.scan([('Panel.lua', str(ui), 'path', '')], self.methods, {'engine': []}, covers)
            self.assertEqual([h['method'] for h in hits if h['covered']], ['GetMight'])
            self.assertEqual(hazards.load_covers(root, selected=[]), {})


# How UI code reaches a call: the shapes found in the game's and the mods' UI files.
LUA_REACH = '''
CommitItems = {}
CommitItems["Choices"] = function(selection)
	Players[0]:ChangeGold(1)
end
Controls.ConfirmButton:RegisterCallback(Mouse.eLClick, function()
	CommitItems[g_class](g_selection)
end)
local Behavior = {
	[Mouse.eLClick] = function(focus)
		Players[0]:ChangeGold(2)
	end,
}
PopupLayouts[1] = function(popupInfo)
	local OnYesClicked = function()
		Players[0]:ChangeGold(3)
	end
	AddButton(Locale.ConvertTextKey("TXT_KEY_YES"), OnYesClicked)
end
function AddButton(text, func)
	g_buttons[text] = func
end
g_Plopper = {
	Plop = function(plot)
		Players[0]:ChangeGold(4)
	end,
}
InterfaceModeMessageHandler[DEBUG][MouseEvents.LButtonUp] = function()
	if type(g_Plopper.Plop) == "function" then
		g_Plopper.Plop(plot)
	end
end
local function Filter(row)
	return Players[0]:CountNumBuildings(row.ID) > 0 or Players[0]:CountNumBuildings(row.ID, true) > 0
end
local function insertChanges(tips, filter)
	if filter(1) then tips[1] = 1 end
end
ContextPtr:SetUpdate(function()
	pcall(function() Players[0]:ChangeGold(5) end)
	insertChanges({}, Filter)
end)
LuaEvents.MOD_CLICK.Add(function() Players[0]:ChangeGold(6) end)
LuaEvents.MOD_TURN.Add(function() Players[0]:ChangeGold(7) end)
Controls.B:RegisterCallback(Mouse.eLClick, function() LuaEvents.MOD_CLICK() end)
Events.ActivePlayerTurnStart.Add(function() LuaEvents.MOD_TURN() end)
local t = { function() Players[0]:ChangeGold(8) end }
if (x) then Players[0]:ChangeGold(9) end
'''


class ReachTest(unittest.TestCase):
    def setUp(self):
        self.methods = {
            'ChangeGold': [{'class': 'Player', 'kind': 'writes', 'why': 'calls ChangeGold'}],
            'CountNumBuildings': [{'class': 'Player', 'kind': 'writes', 'why': 'calls UpdateNumBuildings', 'minArgs': 2}],
        }

    def test_trigger_reach(self):
        r = hazards.trigger_reach
        self.assertEqual(r('load'), 'load')
        self.assertEqual(r('via load'), 'load')
        self.assertEqual(r('callback Mouse.eLClick'), 'input')
        self.assertEqual(r('passed to Controls.B:SetToolTipCallback'), 'input')
        self.assertEqual(r('passed to Foo'), 'game')
        self.assertEqual(r('assigned to [Mouse.eLClick]'), 'input')
        self.assertEqual(r('via Events.SerialEventEnterCityScreen'), 'input')
        self.assertEqual(r('GameEvents.PlayerDoTurn'), 'game')
        self.assertEqual(r('LuaEvents.X'), 'game')
        self.assertEqual(r('LuaEvents.X', {'X': 'input'}), 'input')
        self.assertEqual(hazards.reach([]), 'game')
        self.assertEqual(hazards.reach(['callback Mouse.eLClick', 'via load']), 'load')
        self.assertEqual(hazards.reach(['callback Mouse.eLClick', 'Events.X']), 'game')
        self.assertEqual(hazards.reach(['callback Mouse.eLClick', 'ContextPtr:SetInputHandler']), 'input')

    def test_resolution(self):
        f = hazards._LuaFile(LUA_REACH)
        events = hazards.lua_event_reach([f])
        self.assertEqual(events, {'MOD_CLICK': 'input', 'MOD_TURN': 'game'})
        hits = hazards.scan_text(f, self.methods, [], events)
        got = {(h['line'], h['method']): (h['reach'], h['triggers']) for h in hits}
        self.assertEqual(got[(4, 'ChangeGold')], ('input', ['via callback Mouse.eLClick']))  # table entry, called by index
        self.assertEqual(got[(11, 'ChangeGold')], ('input', ['assigned to [Mouse.eLClick]']))  # table key
        self.assertEqual(got[(16, 'ChangeGold')], ('input', ['passed to AddButton']))  # nested call, local AddButton
        self.assertEqual(got[(25, 'ChangeGold')][0], 'input')  # field function, called as t.Plop; type() ignored
        self.assertNotIn('passed to type', got[(25, 'ChangeGold')][1])
        self.assertEqual(got[(34, 'CountNumBuildings')], ('game', ['via ContextPtr:SetUpdate']))  # 2 arguments
        self.assertEqual([k for k in got if k[1] == 'CountNumBuildings'], [(34, 'CountNumBuildings')])  # 1: reads
        self.assertEqual(got[(40, 'ChangeGold')], ('game', ['ContextPtr:SetUpdate']))  # pcall: the enclosing function
        self.assertEqual(got[(43, 'ChangeGold')][0], 'input')  # LuaEvents fired only from a button
        self.assertEqual(got[(44, 'ChangeGold')][0], 'game')
        self.assertEqual(got[(47, 'ChangeGold')], ('game', []))  # in a table, use unknown
        self.assertEqual(got[(48, 'ChangeGold')], ('load', ['load']))  # 'if (' is not a call

    def test_enclosing_call(self):
        code = hazards._strip_lua('Foo(a, Bar("x", 1), f)\nx = g\nif (h) then y = k end')
        self.assertEqual(hazards._enclosing_call(code, code.index('f)')), 'Foo')
        self.assertIsNone(hazards._enclosing_call(code, code.index('g\n')))
        self.assertIsNone(hazards._enclosing_call(code, code.index('k end')))
        self.assertEqual(hazards._call_args('f(a, g(b, c), {d, e})', 1), 3)
        self.assertEqual(hazards._call_args('f()', 1), 0)
        self.assertEqual(hazards._call_args('f "x"', 1), 1)


class ReportRulesTest(unittest.TestCase):
    """scan with a run report: curated reviews, the run's DLL and the add-ins the host ran."""

    def test_rules(self):
        methods = {
            'ChangeGold': [{'class': 'Player', 'kind': 'writes', 'why': 'w'}],
            'CalculateGoldRate': [{'class': 'Player', 'kind': 'curated', 'why': 'c', 'notWithDll': {'digestAdditions': True},
                                   'notWithDllWhy': 'fixed in this DLL'}],
        }
        curated = {'engine': [], 'reviews': [
            {'file': 'Screen.lua', 'function': 'OnShow', 'verdict': 'input', 'why': 'a screen the player opens'},
            {'file': 'Load.lua', 'methods': ['ChangeGold'], 'verdict': 'covered', 'why': 'the host does it'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'Screen.lua': 'function OnShow()\n\tPlayers[0]:ChangeGold(1)\nend\nContextPtr:SetShowHideHandler(OnShow)\n',
                'Load.lua': 'Players[0]:ChangeGold(1)\n',
                'Top.lua': 'ContextPtr:SetUpdate(function() Players[0]:CalculateGoldRate() end)\n',
                'Addin.lua': 'GameEvents.PlayerDoTurn.Add(function() Players[0]:ChangeGold(1) end)\n'
                             'Events.ActivePlayerTurnStart.Add(function() Players[0]:ChangeGold(2) end)\n',
            }
            for name, text in files.items():
                (root / name).write_text(text, encoding='utf-8')
            listed = [(n, str(root / n), 'addin' if n == 'Addin.lua' else 'override', '') for n in files]
            report = {'dll': {'digestAdditions': True},
                      'addins': {'contexts': [{'path': str(root / 'Addin.lua'), 'status': 'run'}]}}
            _, hits = hazards.scan(listed, methods, curated, {}, report=report)
            by = {(h['file'], h['line']): h for h in hits}
            self.assertEqual(by[('Screen.lua', 2)]['reach'], 'input')
            self.assertFalse(by[('Screen.lua', 2)]['covered'])
            self.assertEqual(by[('Load.lua', 1)]['coveredBy'], 'review')
            self.assertEqual((by[('Top.lua', 1)]['coveredBy'], by[('Top.lua', 1)]['reason']), ('dll', 'fixed in this DLL'))
            self.assertEqual(by[('Addin.lua', 1)]['coveredBy'], 'host')
            self.assertFalse(by[('Addin.lua', 2)]['covered'])  # a UI event the host does not fire
            _, plain = hazards.scan(listed, methods, curated, {})
            self.assertEqual(sorted(h['coveredBy'] for h in plain if h['covered']), ['review'])

            report_path = root / 'host-report.json'
            report.update(uiFiles={'knownFiles': [{'name': n, 'path': str(root / n)} for n in files if n != 'Addin.lua']},
                          profiles={'selected': []})
            report['addins']['contexts'][0].update(mod='m')
            report_path.write_text(json.dumps(report), encoding='utf-8')
            hits = hazards.scan_report(report_path, profiles_dir=root)
            self.assertEqual(len(hits), 5)
            self.assertTrue(all('reach' in h and 'reason' in h for h in hits))

    def test_shipped_reviews(self):
        methods, _, curated = hazards.load_methods()
        self.assertTrue(all(r['verdict'] in ('input', 'covered') and r['why'] for r in curated['reviews']))
        self.assertEqual(methods['CountNumBuildings'][0].get('minArgs'), 2)
        self.assertEqual(methods['CalculateGoldRate'][0].get('notWithDll'), {'digestAdditions': True})


if __name__ == '__main__':
    unittest.main()
