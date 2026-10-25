"""Game specs: one description of a new game for both the headless host and real-game reference runs.

  python work/headless/gamespec.py resolve SPEC.json [--db DB] [--out RESOLVED.json]
  python work/headless/gamespec.py lua SPEC.json [--db DB]

A spec is JSON that mirrors the single-player setup screens (plan section 4.4):

  {"map": {"script": "Assets\\\\Maps\\\\Continents.lua", "size": "WORLDSIZE_STANDARD",
           "options": {"TXT_KEY_MAP_OPTION_SEA_LEVEL": 2}},
   "speed": "GAMESPEED_STANDARD", "era": "ERA_ANCIENT", "difficulty": "HANDICAP_EMPEROR",
   "majors": 8, "cityStates": 16, "slots": [{"slot": 1, "civ": "CIVILIZATION_GREECE", "team": 1}],
   "gameOptions": {"GAMEOPTION_RAGING_BARBARIANS": true}, "victories": ["VICTORY_DOMINATION"],
   "maxTurns": 0, "seeds": {"map": 123, "sync": 456}}

- `map.script` is a map script file name as in the MapScripts table, or "random". A premade map is
  `map.civ5map` (a file in Map_Sizes) or `map.type` (a Maps type, resolved by size).
- Omitted fields behave like an untouched setup screen: map and game options stay unset, civs are
  random (-1, resolved later by the DLL with the seeded RNG), every victory is enabled, majors and
  city-states follow the world size's defaults.
- "random" choices made by the setup screen itself (map script, size) are resolved here from the
  spec seed, so the resolved spec is fully explicit; the reference run uses the resolved spec.
- Seeds default to fresh random values; the resolved spec records them.

`resolve` validates names against a game database and writes the resolved spec (IDs included) that
the host consumes. `lua` prints the front-end Lua that sets the same pregame state in the real game
(run in the ModsSinglePlayer context before Events.SerialEventStartGame).

The Lua sets GAMESPEED_STANDARD before the spec's speed: CvPreGame::setGameSpeed sets the turn timer for
every speed but Marathon, which keeps whatever the previous game of the session left (references recorded
before this pin: civ5headless.exe --pregame-turn-timer N reproduces them). The host mirrors the sequence.
"""
from pathlib import Path
import argparse, json, random, secrets, sqlite3, sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / 'work/headless/db/mods-reference-08D19878.db'
MAX_MAJOR_CIVS = 22
DEFAULTS = {'speed': 'GAMESPEED_STANDARD', 'era': 'ERA_ANCIENT', 'difficulty': 'HANDICAP_EMPEROR',
            'map': {'script': 'Assets\\Maps\\Continents.lua', 'size': 'WORLDSIZE_STANDARD'}}


class SpecError(ValueError):
    pass


def _one(db, sql, *args, what):
    row = db.execute(sql, args).fetchone()
    if row is None:
        raise SpecError(f'unknown {what}: {args[0] if args else sql}')
    return row


def _type_id(db, table, type_name):
    return _one(db, f'select ID from {table} where Type = ?', type_name, what=f'{table} type')[0]


def _find_file(db, sql, name, what):
    """Match a file name as stored in the database, or a unique path suffix of it (either slash)."""
    norm = lambda s: s.replace('\\', '/').lower()
    files = [r[0] for r in db.execute(sql)]
    exact = [f for f in files if norm(f) == norm(name)]
    found = exact or [f for f in files if norm(f).endswith('/' + norm(name).lstrip('/'))]
    if len(found) != 1:
        raise SpecError(f'{what} {name!r} matches {len(found)} entries' + (f': {found}' if found else ''))
    return found[0]


def resolve(spec, db_path=DEFAULT_DB):
    db = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True)
    seeds = dict(spec.get('seeds') or {})
    seeds.setdefault('map', secrets.randbelow(2**31 - 1) + 1)
    seeds.setdefault('sync', secrets.randbelow(2**31 - 1) + 1)
    rng = random.Random(seeds['map'] * 1000003 + seeds['sync'])
    m = dict(DEFAULTS['map'], **(spec.get('map') or {}))
    out = {'specVersion': 1, 'seeds': seeds}

    sizes = [r[0] for r in db.execute('select Type from Worlds order by ID')]
    size = m.get('size', DEFAULTS['map']['size'])
    if size == 'random':
        size = rng.choice(sizes)
    world = _one(db, 'select ID, Type, DefaultPlayers, DefaultMinorCivs from Worlds where Type = ?', size, what='world size')

    if 'civ5map' in m or 'type' in m:
        if 'civ5map' in m:
            path = _find_file(db, 'select FileName from Map_Sizes', m['civ5map'], 'premade map')
            row = _one(db, 'select FileName, MapType, WorldSizeType from Map_Sizes where FileName = ?', path, what='premade map')
        else:
            row = _one(db, 'select FileName, MapType, WorldSizeType from Map_Sizes where MapType = ? and WorldSizeType = ?',
                       m['type'], world[1], what='premade map type for this size')
        world = _one(db, 'select ID, Type, DefaultPlayers, DefaultMinorCivs from Worlds where Type = ?', row[2], what='world size')
        out['map'] = {'kind': 'civ5map', 'file': row[0], 'mapType': row[1], 'options': {}}
    else:
        script = m.get('script')
        if script == 'random':
            script = rng.choice([r[0] for r in db.execute('select FileName from MapScripts where SupportsSinglePlayer = 1 and Hidden = 0 order by FileName')])
        script = _find_file(db, 'select FileName from MapScripts', script, 'map script')
        options = {}
        for key, value in (m.get('options') or {}).items():
            opt = db.execute('select OptionID, Name from MapScriptOptions where FileName = ? and (OptionID = ? or Name = ?)',
                             (script, str(key), str(key))).fetchone()
            if opt is None:
                raise SpecError(f'map script {script} has no option {key}')
            values = db.execute('select Value, Name from MapScriptOptionPossibleValues where FileName = ? and OptionID = ?', (script, opt[0])).fetchall()
            if values:
                match = [v for v, n in values if value == v or value == n]
                if not match:
                    raise SpecError(f'option {opt[1]} has no value {value!r}; allowed {values}')
                value = match[0]
            else:
                value = 1 if value in (True, 1, '1') else 0
            options[int(opt[0])] = {'name': opt[1], 'value': int(value)}
        out['map'] = {'kind': 'script', 'file': script, 'options': options}
    out['worldSize'] = {'type': world[1], 'id': world[0]}

    for key, table in (('speed', 'GameSpeeds'), ('era', 'Eras'), ('difficulty', 'HandicapInfos')):
        t = spec.get(key, DEFAULTS[key])
        out[key] = {'type': t, 'id': _type_id(db, table, t)}

    majors = int(spec.get('majors', world[2]))
    if not 1 <= majors < MAX_MAJOR_CIVS:
        raise SpecError(f'majors must be 1..{MAX_MAJOR_CIVS - 1} (autoplay needs a free major slot for the observer)')
    out['majors'] = majors
    out['cityStates'] = int(spec.get('cityStates', world[3]))
    out['maxTurns'] = int(spec.get('maxTurns', 0))

    enabled = spec.get('victories')
    out['victories'] = {}
    for vid, vtype in db.execute('select ID, Type from Victories order by ID'):
        out['victories'][vtype] = {'id': vid, 'enabled': enabled is None or vtype in enabled}
    if enabled is not None:
        unknown = set(enabled) - set(out['victories'])
        if unknown:
            raise SpecError(f'unknown victories {sorted(unknown)}')

    out['gameOptions'] = {}
    for otype, value in (spec.get('gameOptions') or {}).items():
        row = _one(db, 'select ID, SupportsSinglePlayer from GameOptions where Type = ?', otype, what='game option')
        if not row[1]:
            raise SpecError(f'{otype} is not a single-player option')
        out['gameOptions'][otype] = {'id': row[0], 'value': 1 if value else 0}

    slots = []
    given = {s['slot']: s for s in spec.get('slots') or []}
    for i in range(MAX_MAJOR_CIVS):
        status = 'taken' if i == 0 else ('computer' if i < majors else 'closed')
        s = given.get(i, {})
        civ = s.get('civ', 'random')
        civ_id = -1 if civ == 'random' else _one(db, 'select ID from Civilizations where Type = ? and Playable = 1', civ, what='playable civilization')[0]
        slots.append({'slot': i, 'status': status, 'civ': civ, 'civId': civ_id, 'team': int(s.get('team', i))})
    bad = set(given) - set(range(majors))
    if bad:
        raise SpecError(f'slots {sorted(bad)} are outside the {majors} major slots')
    out['slots'] = slots
    return out


def pregame_lua(r):
    """Front-end Lua that sets the resolved spec's pregame state (ModsSinglePlayer context)."""
    L = ['PreGame.SetLeaderName(0,"");PreGame.SetCivilizationDescription(0,"");PreGame.SetCivilizationShortDescription(0,"");PreGame.SetCivilizationAdjective(0,"")',
         f'for i=0,{MAX_MAJOR_CIVS - 1} do PreGame.SetCivilization(i,-1);PreGame.SetTeam(i,i) end',
         f'PreGame.SetRandomWorldSize(false);PreGame.SetWorldSize({r["worldSize"]["id"]});PreGame.SetNumMinorCivs({r["cityStates"]})',
         'PreGame.SetLoadWBScenario(false)',
         f'PreGame.SetRandomMapScript(false);PreGame.SetMapScript({json.dumps(r["map"]["file"])})',
         # Standard first: CvPreGame::setGameSpeed sets the turn timer for every speed except Marathon,
         # which keeps the previous game's timer; standard pins it (TURNTIMER_MEDIUM) first.
         'PreGame.SetGameSpeed(GameInfo.GameSpeeds.GAMESPEED_STANDARD.ID)',
         f'PreGame.SetGameSpeed({r["speed"]["id"]});PreGame.SetEra({r["era"]["id"]});PreGame.SetHandicap(0,{r["difficulty"]["id"]})']
    L += [f'PreGame.SetVictory({v["id"]},{str(v["enabled"]).lower()})' for v in r['victories'].values()]
    L.append(f'PreGame.SetMaxTurns({r["maxTurns"]});PreGame.ResetGameOptions();PreGame.ResetMapOptions()')
    L += [f'PreGame.SetGameOption({json.dumps(t)},{str(bool(o["value"])).lower()})' for t, o in r['gameOptions'].items()]
    L += [f'PreGame.SetMapOption({oid},{o["value"]})' for oid, o in r['map']['options'].items()]
    L.append('PreGame.SetSlotStatus(0,SlotStatus.SS_TAKEN)')
    for s in r['slots'][1:]:
        L.append(f'PreGame.SetSlotStatus({s["slot"]},SlotStatus.SS_{"COMPUTER" if s["status"] == "computer" else "CLOSED"})')
    for s in r['slots']:
        if s['civId'] >= 0:
            L.append(f'PreGame.SetCivilization({s["slot"]},{s["civId"]})')
        if s['team'] != s['slot']:
            L.append(f'PreGame.SetTeam({s["slot"]},{s["team"]})')
    L.append(f'local out={{map=PreGame.GetMapScript(),world=PreGame.GetWorldSize(),minors=PreGame.GetNumMinorCivs(),speed=PreGame.GetGameSpeed(),slots={{}}}}\n'
             f'for i=0,{MAX_MAJOR_CIVS - 1} do out.slots[#out.slots+1]={{slot=i,status=PreGame.GetSlotStatus(i),civ=PreGame.GetCivilization(i),team=PreGame.GetTeam(i)}} end\n'
             'return out')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['resolve', 'lua'])
    ap.add_argument('spec', type=Path)
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    try:
        r = resolve(json.loads(a.spec.read_text(encoding='utf-8')), a.db)
    except SpecError as e:
        print(f'spec error: {e}', file=sys.stderr)
        return 2
    text = json.dumps(r, indent=1) if a.command == 'resolve' else pregame_lua(r)
    if a.out:
        a.out.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
