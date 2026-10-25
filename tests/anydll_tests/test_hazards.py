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


if __name__ == '__main__':
    unittest.main()
