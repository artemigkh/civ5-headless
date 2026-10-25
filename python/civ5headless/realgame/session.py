"""The real-game session (plan 9.4): one Civilization V process driven through FireTuner.

    s = RealGameSession(cfg, run_dir)
    s.launch()                                  # start the game, wait for the main menu       -> dict
    s.set_mods(mod_ids)                         # enable exactly these mods, activate them      -> dict
    s.start_game(spec, map_seed, sync_seed, lua_probes=[...])   # setup, start, load, probes   -> dict
    s.autoplay(turns, max_seconds=None)         # observer autoplay; per-turn wall times        -> dict
    s.to_main_menu()                            # for the next setup in the same session        -> dict
    s.collect_logs(dest)                        # the game's logs written this session          -> [names]
    s.process_stats()                           # peak working set, peak private bytes, CPU     -> dict
    s.quit()                                    # ends the game, puts config.ini back           -> dict

autoplay returns {startTurn, endTurn, turns, endReason, turnSeconds: {turn: seconds since autoplay started},
wallSeconds, victory}; endReason is 'turns' (the count ran out), 'victory' (a winner, or the game state left ON),
'stopped' (on_poll asked), 'max_seconds' or 'stalled' (no new turn for stall_seconds; autoplay is halted then).
process_stats returns {peakWorkingSet, peakPrivateBytes, cpuSeconds, workingSet, privateBytes, peakVirtual, pid,
alive, launches, earlier: [the same for processes ended by a relaunch]}. Extras: game_database(dest) exports the
database the game holds in memory; call(context, lua) and states() run Lua and list the contexts.

Order, as in the host: start_game sets up the pregame state (spec.pregame_lua) in ModsSinglePlayer, starts the
game, waits until it has loaded, runs the Lua probes in InGame and leaves the game paused at turn 0 behind the load
screen. autoplay then arms (quick combat and movement, Game.SetAIAutoPlay(turns, 0): the human slot becomes the
observer) and only then closes the load screen and unpauses. A later autoplay in the same game just re-arms.

Seeds (seeds.py): the game reads config.ini's MapRandSeed/SyncRandSeed when its DLL loads, so the seeds must be in
the file before the launch. launch(map_seed, sync_seed) pins them up front (optional arguments); start_game with
other seeds pins them and relaunches the game (reseed='relaunch', the verified mechanism) or relies on the mod
activation reloading the DLL (reseed='reload', unverified). With the DLL's optional digest additions start_game
checks the seeds the engine used (HHSEEDS in HeadlessDigest.log) and fails on a mismatch. quit() restores the file.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import time

from .. import spec as specmod, winproc
from ..run import utc, write
from . import launch as launchmod, mods as modsmod, seeds, tuner

FRONT = {'MainMenu', 'LegalScreen', 'ModsBrowser'}
START = "PreGame.SetPersistSettings(false);Events.SerialEventStartGame();UIManager:SetUICursor(1);return 'start requested'"
LOADED = 'return not Controls.ActivateButton:IsHidden()'
SHOWN = 'return not ContextPtr:IsHidden()'
SETUP = r'''
local out={turn=Game.GetGameTurn(),activePlayer=Game.GetActivePlayer(),speed=GameInfo.GameSpeeds[Game.GetGameSpeedType()].Type,
 world=GameInfo.Worlds[Map.GetWorldSize()].Type,map=PreGame.GetMapScript(),plots=Map.GetNumPlots(),players={}}
for owner=0,63 do local p=Players[owner]
 if p and p:IsEverAlive() and not p:IsBarbarian() then local civ=GameInfo.Civilizations[p:GetCivilizationType()]
  out.players[#out.players+1]={owner=owner,civilization=civ and civ.Type or '',minor=p:IsMinorCiv(),human=p:IsHuman()} end end
return out
'''
ARM = ("assert(not PreGame.IsMultiplayerGame());local p=Players[0];assert(p and p:IsAlive() and not p:IsMinorCiv());"
       "Game.SetOption('GAMEOPTION_QUICK_COMBAT',true);Game.SetOption('GAMEOPTION_QUICK_MOVEMENT',true);"
       "Game.SetAIAutoPlay({turns},0);return Game.GetAIAutoPlay()")
CONTINUE = ("assert(not Controls.ActivateButton:IsHidden(),'loading is not complete');"
            "assert(not PreGame.IsMultiplayerGame(),'single player only');"
            "Events.LoadScreenClose();Game.SetPausePlayer(-1);UI.SetDontShowPopups(false);return 'continued'")
TURN = ("return {turn=Game.GetGameTurn(),autoplay=Game.GetAIAutoPlay(),pause=Game.GetPausePlayer(),"
        "winner=Game.GetWinner(),state=Game.GetGameState()}")
VICTORY = ("local ok,v=pcall(function() return Game.GetVictory() end);local info=ok and v and v>=0 and GameInfo.Victories[v];"
           "return {turn=Game.GetGameTurn(),winner=Game.GetWinner(),victory=info and info.Type or '',state=Game.GetGameState()}")
HALT = ("local rp=-1;for i=0,GameDefines.MAX_MAJOR_CIVS-1 do local p=Players[i];"
        "if p and p:IsAlive() and not p:IsMinorCiv() and not p:IsBarbarian() and not p:IsObserver() then rp=i;break end end;"
        "if Game.GetAIAutoPlay()>0 and rp>=0 then Game.SetAIAutoPlay(0,rp) end;return Game.GetAIAutoPlay()")
MENU = "Events.ExitToMainMenu();return 'menu requested'"
QUIT = "UI.ExitGame();return 'quit requested'"
# The database the game holds in memory, copied table by table into a new file (ATTACH ... CREATE TABLE AS).
EXPORT = r'''
local path=%s
local ok,err=pcall(function() for _ in DB.Query("ATTACH DATABASE '"..path.."' AS hhx") do end end)
if not ok then return {error='attach: '..tostring(err)} end
local names,failed={},{}
for row in DB.Query("SELECT name FROM main.sqlite_master WHERE type='table'") do
 if string.sub(row.name,1,7)~='sqlite_' then names[#names+1]=row.name end
end
for _,t in ipairs(names) do
 local ok2,e2=pcall(function() for _ in DB.Query('CREATE TABLE hhx."'..t..'" AS SELECT * FROM main."'..t..'"') do end end)
 if not ok2 then failed[#failed+1]=t..': '..tostring(e2) end
end
for _ in DB.Query("DETACH DATABASE hhx") do end
local mods={};local okm,act=pcall(Modding.GetActivatedMods);if okm and act then for _,m in ipairs(act) do mods[#mods+1]=m.ID end end
return {tables=#names,failed=failed,activated=mods}
'''
LOGS = ('Lua.log', 'Database.log', 'HeadlessDigest.log', 'HeadlessRuntime.log', 'HeadlessTrace-*.log')


class SessionError(RuntimeError):
    pass


def as_list(value):
    """A Lua array from the result wrapper ({} for an empty table) as a list."""
    return list(value) if isinstance(value, list) else []


def hhseeds(log_path, since):
    """The HHSEEDS lines (as dicts) of a HeadlessDigest.log written after since (epoch seconds), else []."""
    p = Path(log_path)
    if not p.is_file() or p.stat().st_mtime < since:
        return []
    lines = [l for l in p.read_text(encoding='utf-8', errors='replace').splitlines() if l.startswith('HHSEEDS|')]
    return [dict(f.partition('=')[::2] for f in l.split('|')[1:]) for l in lines]


class RealGameSession:
    def __init__(self, cfg, run_dir, *, reseed='relaunch', cpu_guard=True, cpu_limit=95, port=tuner.GAME_PORT,
                 launcher=None, launch_timeout=180, menu_timeout=300, load_timeout=900, poll=2.0, stall_seconds=900,
                 log=None):
        if reseed not in ('relaunch', 'reload'):
            raise ValueError("reseed must be 'relaunch' or 'reload'")
        self.cfg = cfg
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.reseed, self.cpu_guard, self.cpu_limit, self.port = reseed, cpu_guard, cpu_limit, port
        self.launcher = launcher or launchmod.launch_game
        self.launch_timeout, self.menu_timeout, self.load_timeout = launch_timeout, menu_timeout, load_timeout
        self.poll, self.stall_seconds = poll, stall_seconds
        self.log = log or (lambda message: None)
        self.marker = Path(cfg.workspace or self.dir) / 'cache' / seeds.MARKER  # one game at a time: one marker
        self.game = None
        self.tuner = None
        self.guard = None
        self.mods = None             # [(id, version, name)] once set_mods ran
        self.activated = False       # the mods are active and ModsSinglePlayer is up
        self.in_game = False
        self.continued = False
        self.launch_seeds = None     # (map, sync) in config.ini when the running game loaded its DLL
        self.launches = 0
        self.earlier = []            # process stats of games ended by a relaunch
        self.since = None            # wall clock of the first launch (logs written after it belong to the session)
        self.seq = 0

    # ---- plumbing ----

    def event(self, action, **values):
        row = dict(utc=utc(), action=action, **values)
        with (self.dir / 'session.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, default=str) + '\n')
        self.log(f'{action}: ' + ', '.join(f'{k}={v}' for k, v in values.items() if not isinstance(v, (dict, list))))

    def call(self, context, lua, label=None, timeout=120):
        """Run lua in a context; returns its first value. label records the call in calls/."""
        if self.tuner is None:
            raise SessionError('the game is not running')
        started = time.monotonic()
        result = self.tuner.execute(context, lua, timeout)
        if label:
            self.seq += 1
            (self.dir / 'calls').mkdir(exist_ok=True)
            write(self.dir / 'calls' / f'{self.seq:05d}-{label}.json', dict(utc=utc(), context=context,
                                                                          seconds=round(time.monotonic() - started, 3), result=result))
        if not result.get('ok'):
            raise SessionError(f"{label or context}: {result.get('error', 'Lua call failed')}")
        return (result.get('values') or [None])[0]

    def states(self):
        if self.tuner is None:
            raise SessionError('the game is not running')
        return {s['name'] for s in self.tuner.states(30)}

    def alive(self):
        return self.game is not None and self.game.alive()

    def wait_for(self, check, timeout, what):
        """Poll the contexts until check(names) is true; returns the names."""
        deadline = time.monotonic() + timeout
        while True:
            if not self.alive():
                raise SessionError(f'the game exited while waiting for {what}')
            names = self.states()
            if check(names):
                return names
            if time.monotonic() >= deadline:
                raise SessionError(f'timed out after {timeout} s waiting for {what} (contexts: {sorted(names)})')
            time.sleep(self.poll)

    def check(self, context, lua):
        """True when lua returns a true value in context; False when it fails (the context is still loading)."""
        try:
            return bool(self.call(context, lua))
        except SessionError:
            return False
        except tuner.TunerError:
            if self.tuner is None or self.tuner.error:
                raise  # the connection is gone, not just the context
            return False

    # ---- plan 9.4 ----

    def launch(self, map_seed=None, sync_seed=None):
        """Start the game and wait for the main menu. Seeds given here are pinned in config.ini first."""
        if self.alive():
            raise SessionError('the game is already running in this session')
        restored = seeds.restore(self.marker)  # a pin left by a session that died
        if restored is not None:
            self.event('config_ini_restored', original=restored)
        ini = self.cfg.require('config_ini')
        if seeds.ini_value(ini, 'EnableTuner') != '1':
            raise SessionError(f'{ini} does not have EnableTuner = 1: the game will not open its tuner port')
        if map_seed is not None or sync_seed is not None:
            seeds.pin(ini, map_seed, sync_seed, self.marker, self.dir / 'config.ini.backup')
        return self._launch()

    def _launch(self):
        ini = self.cfg.require('config_ini')
        loaded = seeds.read(ini)
        self.launch_seeds = (loaded['MapRandSeed'] or None, loaded['SyncRandSeed'] or None)
        self.since = self.since or time.time()
        t = time.monotonic()
        self.game = self.launcher(self.cfg.require('game_dir'), port=self.port, timeout=self.launch_timeout)
        self.launches += 1
        if self.cpu_guard:
            self.guard = launchmod.CpuGuard(self.game, self.dir / 'cpu-temperature.jsonl', limit=self.cpu_limit).start()
        self.tuner = tuner.connect(self.game.port, wait=30, alive=self.game.alive)
        names = self.wait_for(lambda n: bool(FRONT & n), self.menu_timeout, 'the main menu')
        menu_seconds = round(time.monotonic() - t, 2)
        if 'LegalScreen' in names:
            try:
                self.call('LegalScreen', modsmod.DISMISS_LEGAL, 'dismiss-legal')
            except (SessionError, tuner.TunerError) as error:
                self.event('legal_screen', error=str(error))
        self.activated = self.in_game = self.continued = False
        info = dict(pid=self.game.pid, exe=self.game.exe, tunerSeconds=self.game.seconds, menuSeconds=menu_seconds,
                    seconds=round(time.monotonic() - t, 2), seeds=dict(map=self.launch_seeds[0], sync=self.launch_seeds[1]),
                    launches=self.launches, loggingEnabled=seeds.ini_value(ini, 'LoggingEnabled') == '1')
        self.event('launched', **info)
        return info

    def set_mods(self, mod_ids):
        """Enable exactly these mods (ids, or id:version) and activate them; [] activates none."""
        t = time.monotonic()
        self.mods = modsmod.resolve(self.cfg, mod_ids)
        result = self._activate()
        return dict(result, mods=[dict(id=i, version=v, name=n) for i, v, n in self.mods], seconds=round(time.monotonic() - t, 2))

    def _activate(self):
        names = self.states()
        if 'InGame' in names:
            raise SessionError('mods are set at the main menu: call to_main_menu() first')
        if 'ModsBrowser' not in names:
            raise SessionError(f'no ModsBrowser context (contexts: {sorted(names)})')
        result = {}
        if self.mods is not None:
            result = self.call('ModsBrowser', modsmod.set_enabled_lua(self.mods), 'set-mods') or {}
            if not result.get('ok'):
                raise SessionError(f"the enabled mods could not be made the requested set: {result.get('error') or result}")
        self.call('ModsBrowser', modsmod.ACTIVATE, 'activate-mods')
        self.wait_for(lambda n: 'ModsSinglePlayer' in n and self.check('ModsSinglePlayer', SHOWN), self.menu_timeout,
                      'mod activation')
        self.activated = True
        out = dict(before=as_list(result.get('before')), after=as_list(result.get('after')),
                   disabled=result.get('disabled', 0), enabled=result.get('enabled', 0))
        self.event('mods_activated', **out)
        return out

    def _relaunch(self):
        self.earlier.append({k: v for k, v in self.process_stats().items() if k != 'earlier'})
        self._end_game()
        self._launch()

    def _resolve(self, spec, map_seed, sync_seed):
        if isinstance(spec, (str, Path)):
            spec = json.loads(Path(spec).read_text(encoding='utf-8'))
        spec = dict(spec)
        if 'specVersion' not in spec:
            given = dict(spec.get('seeds') or {})
            if map_seed is not None:
                given['map'] = map_seed
            if sync_seed is not None:
                given['sync'] = sync_seed
            spec['seeds'] = given
            from .. import dbcache
            spec = specmod.resolve(spec, dbcache.database(self.cfg, log=self.log)[0])
        return spec

    def start_game(self, spec, map_seed=None, sync_seed=None, lua_probes=()):
        """Set up and start a game from a spec (resolved, or resolved here against the configured database) and
        leave it loaded and paused at turn 0. The seeds default to the spec's; None for both means the clock."""
        if self.game is None:
            raise SessionError('launch() first')
        if not self.alive():
            raise SessionError(f'the game exited (code {self.game.popen.returncode})')
        if self.in_game:
            raise SessionError('a game is running: call to_main_menu() first')
        t = time.monotonic()
        resolved = self._resolve(spec, map_seed, sync_seed)
        given = resolved.get('seeds') or {}
        want = (map_seed if map_seed is not None else given.get('map'), sync_seed if sync_seed is not None else given.get('sync'))
        relaunched = False
        if want != self.launch_seeds:
            ini = self.cfg.require('config_ini')
            seeds.pin(ini, want[0], want[1], self.marker, self.dir / 'config.ini.backup')
            if self.reseed == 'relaunch':
                self.event('relaunch', reason='seeds', seeds=dict(map=want[0], sync=want[1]))
                self._relaunch()
                relaunched = True
            else:
                self.launch_seeds = want  # assumed: the activation reloads the DLL, which reads them
                self.activated = False
        if not self.activated:
            self._activate()
        write(self.dir / 'spec-resolved.json', resolved)
        pregame = self.call('ModsSinglePlayer', specmod.pregame_lua(resolved), 'pregame-setup')
        started_wall = time.time()
        self.call('ModsSinglePlayer', START, 'start-game')
        self.activated = False  # the next game activates the mods again
        self.wait_for(lambda n: {'InGame', 'LoadScreen'} <= n and self.check('LoadScreen', LOADED),
                      self.load_timeout, 'the game to load')
        self.in_game, self.continued = True, False
        setup = self.call('InGame', SETUP, 'setup-info')
        expected = (resolved['worldSize']['type'], resolved['speed']['type'])
        if setup.get('turn') != 0 or (setup.get('world'), setup.get('speed')) != expected:
            raise SessionError(f'the game started is not the spec: {setup} (expected turn 0, {expected})')
        observed = hhseeds(self.cfg.user_dir / 'Logs/HeadlessDigest.log', started_wall) if self.cfg.user_dir else []
        verified = None
        if observed and want[0] is not None:
            last = observed[-1]
            verified = (last.get('exeMap'), last.get('exeSync')) == (str(want[0]), str(want[1]))
            if not verified:
                raise SessionError(f'the engine did not use the pinned seeds: {last}'
                                   + (" (reseed='reload' assumes the activation rereads config.ini; use 'relaunch')"
                                      if self.reseed == 'reload' else ''))
        probes = []
        for path in lua_probes:
            path = Path(path)
            try:
                value = self.call('InGame', path.read_text(encoding='utf-8-sig'), f'probe-{path.stem}')
                probes.append(dict(file=str(path), ok=True, value=value))
            except (SessionError, tuner.TunerError) as error:
                probes.append(dict(file=str(path), ok=False, error=str(error)))
        info = dict(seeds=dict(map=want[0], sync=want[1]), relaunched=relaunched, pregame=pregame, setup=setup,
                    seedsObserved=observed[-1] if observed else None, seedsVerified=verified, probes=probes,
                    seconds=round(time.monotonic() - t, 2))
        self.event('game_started', **info)
        return info

    def autoplay(self, turns, max_seconds=None, on_poll=None, stall_seconds=None):
        """Autoplay turns turns with every player an AI (see the module docstring for the result)."""
        if not self.in_game:
            raise SessionError('start_game() first')
        stall_seconds = stall_seconds or self.stall_seconds
        start = self.call('InGame', TURN)
        armed = self.call('InGame', ARM.format(turns=int(turns)), 'arm-autoplay')
        if armed != turns:
            raise SessionError(f'autoplay did not arm ({armed} for {turns} turns)')
        if not self.continued:
            self.call('LoadScreen', CONTINUE, 'continue')
            self.continued = True
        started = time.monotonic()
        start_turn = last = start['turn']
        last_progress = started
        times, victory, reason, state = {}, None, None, start
        self.event('autoplay_started', turn=start_turn, turns=turns)
        while reason is None:
            time.sleep(self.poll)
            if not self.alive():
                raise SessionError(f'the game exited at turn {last} (crash, or the CPU guard)')
            state = self.call('InGame', TURN)
            now = time.monotonic()
            if state['turn'] != last:
                for t in range(last + 1, state['turn'] + 1):
                    times[t] = round(now - started, 2)
                last, last_progress = state['turn'], now
            if state.get('winner', -1) >= 0 or state.get('state', 0) != 0:
                reason = 'victory'
                victory = self.call('InGame', VICTORY, 'victory')
            elif state['turn'] >= start_turn + turns and state['autoplay'] == 0:
                reason = 'turns'
            elif on_poll is not None and on_poll(state):
                reason = 'stopped'
            elif max_seconds and now - started >= max_seconds:
                reason = 'max_seconds'
            elif now - last_progress >= stall_seconds:
                reason = 'stalled'
        if reason in ('stopped', 'max_seconds', 'stalled') and state.get('autoplay', 0) > 0:
            self.call('InGame', HALT, 'halt-autoplay')
        info = dict(startTurn=start_turn, endTurn=last, turns=last - start_turn, endReason=reason,
                    turnSeconds={str(k): v for k, v in sorted(times.items())}, wallSeconds=round(time.monotonic() - started, 2),
                    victory=victory)
        self.event('autoplay_done', **{k: v for k, v in info.items() if k != 'turnSeconds'})
        return info

    def to_main_menu(self):
        t = time.monotonic()
        names = self.states()
        if 'InGame' in names:
            self.call('InGame', HALT, 'halt-autoplay')
            self.call('InGame', MENU, 'main-menu')
            self.wait_for(lambda n: 'InGame' not in n and bool(FRONT & n), self.menu_timeout, 'the main menu')
        self.in_game = self.continued = self.activated = False
        info = dict(seconds=round(time.monotonic() - t, 2))
        self.event('main_menu', **info)
        return info

    def collect_logs(self, dest):
        """Copy the game's logs written during this session (Logs folder) into dest; returns the file names."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        logs = self.cfg.require('user_dir') / 'Logs'
        out = []
        for pattern in LOGS:
            for p in sorted(logs.glob(pattern)):
                if self.since is None or p.stat().st_mtime >= self.since - 1:
                    shutil.copy2(p, dest / p.name)
                    out.append(p.name)
        return out

    def process_stats(self):
        if self.game is None:
            return dict(launches=0, earlier=list(self.earlier))
        s = winproc.process_stats(self.game.popen)
        return dict(peakWorkingSet=s.get('PeakWorkingSet'), peakPrivateBytes=s.get('PeakPrivateBytes'),
                    cpuSeconds=s.get('CPUSeconds'), workingSet=s.get('WorkingSet'), privateBytes=s.get('PrivateBytes'),
                    peakVirtual=s.get('PeakVirtual'), pid=self.game.pid, alive=self.alive(), launches=self.launches,
                    earlier=list(self.earlier))

    def game_database(self, dest):
        """Export the database the game holds in memory into dest (a new SQLite file); returns dest."""
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        names = self.states()
        context = 'InGame' if 'InGame' in names else 'ModsSinglePlayer' if 'ModsSinglePlayer' in names else 'MainMenu'
        result = self.call(context, EXPORT % tuner.lua_string(dest.as_posix()), 'export-database')
        if isinstance(result, dict) and result.get('error'):
            raise SessionError(f"database export failed: {result['error']}")
        write(self.dir / 'export-database.json', result)
        return dest

    def _end_game(self, timeout=120):
        """Ask the game to exit, wait, end it if it does not; returns (exited, killed)."""
        exited, killed = self.game is None or not self.alive(), False
        if self.alive():
            try:
                names = self.states()
                self.call('InGame' if 'InGame' in names else 'MainMenu', QUIT, 'quit')
            except (SessionError, tuner.TunerError, OSError) as error:
                self.event('quit_request_failed', error=str(error))
            deadline = time.monotonic() + timeout
            while self.alive() and time.monotonic() < deadline:
                time.sleep(0.25)
            if self.alive():
                self.game.popen.kill()  # our own process handle: exactly the game this session started
                killed = True
                try:
                    self.game.popen.wait(30)
                except Exception:  # noqa: BLE001
                    pass
            exited = not self.alive()
        if self.tuner is not None:
            self.tuner.close()
            self.tuner = None
        if self.guard is not None:
            self.guard.stop('game ended')
            self.guard = None
        self.in_game = self.continued = self.activated = False
        return exited, killed

    def quit(self):
        exited, killed = self._end_game()
        restored = seeds.restore(self.marker)
        info = dict(exited=exited, killed=killed, configIniRestored=restored)
        self.event('quit', **info)
        return info

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.quit()
