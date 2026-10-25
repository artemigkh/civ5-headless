"""Headless vpbench backend: play a new game from a spec in civ5headless.exe and write a vpbench run folder.

  python work/headless/hhbench.py newgame --run NAME --spec SPEC.json --target-turn N
         [--dll DLL] [--db DB | --mods-dir MODS --mods-db Civ5ModsDatabase.db]
         [--diagnostics 1] [--improved-mask N | --ab-role baseline|test] [--checkpoint-every 1]
         [--maximum-seconds S] [--stall-seconds S] [--max-memory-mb MB] [--affinity MASK] [--prune]
         [--run-dir DIR] [--exe EXE] [--host-arg ARG]...

  (also reachable as: python work/vpbench/vpbench.py newgame --backend headless --run NAME --spec ... --target-turn N)

The run folder has the files vpbench writes and its readers use (compare.py, abcompare.py, samerun.py):
events.jsonl, setup.json, spec-resolved.json, status.json, turn-times.jsonl, turn-seen.json,
checkpoints/turn-NNNN.json (+ turn-NNNN-final.json), replay-messages.json, replay-data.json; plus the host's
own outputs (newgame-report.json, Logs/ with HeadlessDigest.log, t000-*.json, dump-t000/, dump-tN/).

Differences from a real-game run (docs/headless-host.md, "Run folders"):
- checkpoints are taken exactly when the game turn advances (every --checkpoint-every turns), not by a
  30-second poll during the turn; turn-times.jsonl/turn-seen.json are exact, not 5-second polls;
- status.process comes from the host process (CPU seconds, peak working set, peak private bytes);
  pollSeconds is 0; there is no final save (finalSave absent) and status.save is a seed key
  "headless-<spec stem>-m<map seed>-s<sync seed>-<spec hash>" that groups runs of the same game for
  abcompare.py;
- the improved-AI mask: --improved-mask needs a DLL with Game.SetStackingAIImprovedMask; for an A/B of
  two DLL builds use --ab-role, which records improvedMask 0 (baseline) or -1 (test: every player runs the
  test DLL) in setup.json.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAIN = ROOT.parents[2] if ROOT.parent.name == 'wt' else ROOT
sys.path.insert(0, str(HERE))
import dbcache, gamespec, winproc  # noqa: E402

RUNS = ROOT / 'work/test-runs'
DEFAULT_GAME_DIR = r"E:\SteamLibrary\steamapps\common\Sid Meier's Civilization V"

# vpbench.SETUP (work/vpbench/vpbench.py), as a function. Keep in sync.
SETUP = r'''
local out={turn=Game.GetGameTurn(),activePlayer=Game.GetActivePlayer(),speed=GameInfo.GameSpeeds[Game.GetGameSpeedType()].Type,
 world=GameInfo.Worlds[Map.GetWorldSize()].Type,map=PreGame.GetMapScript(),plots=Map.GetNumPlots(),version=(Game.GetDLLVersion and Game.GetDLLVersion() or ''),diagnostics=(Game.GetStackingDiagnosticsLevel and Game.GetStackingDiagnosticsLevel() or -1),players={}}
for owner=0,63 do local p=Players[owner]
 if p and p:IsEverAlive() and not p:IsBarbarian() then local civ=GameInfo.Civilizations[p:GetCivilizationType()]
  out.players[#out.players+1]={owner=owner,civilization=civ and civ.Type or '',minor=p:IsMinorCiv(),human=p:IsHuman(),handicap=GameInfo.HandicapInfos[p:GetHandicapType()].Type} end end
return out
'''

# Run before autoplay is armed (vpbench order: setup info, diagnostics level, A/B mask, then arm).
BEFORE_ARM = r'''
local out={}
out.setup=(function() %(setup)s end)()
local level=%(diagnostics)d
if level>0 then
 assert(Game.SetStackingDiagnosticsLevel,'this DLL has no Game.SetStackingDiagnosticsLevel')
 out.diagnosticsSet=Game.SetStackingDiagnosticsLevel(level)
end
local mask=%(mask)s
if mask~=nil then
 assert(Game.SetStackingAIImprovedMask,'this DLL has no Game.SetStackingAIImprovedMask (use --ab-role for a DLL A/B)')
 out.improvedMaskSet=Game.SetStackingAIImprovedMask(mask)
end
out.improvedMask=Game.GetStackingAIImprovedMask and Game.GetStackingAIImprovedMask() or -2
out.diagnosticsLevel=Game.GetStackingDiagnosticsLevel and Game.GetStackingDiagnosticsLevel() or -1
return out
'''

# vpbench.CHECKPOINT as on ai-improvements (the abcompare.py strength metrics included; every extra getter
# is pcall-guarded, so DLLs without them leave the field out). Keep in sync.
CHECKPOINT = r'''
local function v(f,...) if f then local ok,r=pcall(f,...);if ok then return r end end;return nil end
local parts={};for row in GameInfo.Projects() do if row.Spaceship==true or row.Spaceship==1 then parts[#parts+1]=row.ID end end
local league=v(Game.GetActiveLeague)
local active=Game.GetActivePlayer()
local out={turn=Game.GetGameTurn(),activePlayer=active,autoplay=Game.GetAIAutoPlay(),observer=Players[active]:IsObserver(),human=Players[active]:IsHuman(),pausePlayer=Game.GetPausePlayer(),replayCount=Game.GetNumReplayMessages(),winner=Game.GetWinner(),players={},cities={},wars={},livingMajors={}}
for owner=0,63 do
 local p=Players[owner]
 if p and p:IsAlive() and not p:IsObserver() then
  local civ=GameInfo.Civilizations[p:GetCivilizationType()]
  out.players[#out.players+1]={owner=owner,team=p:GetTeam(),civilization=civ and civ.Type or '',minor=p:IsMinorCiv(),barbarian=p:IsBarbarian(),unitCount=p:GetNumUnits(),cityCount=p:GetNumCities(),military=p:GetNumMilitaryUnits(),score=(not p:IsMinorCiv() and not p:IsBarbarian()) and p:GetScore() or 0,techs=Teams[p:GetTeam()]:GetTeamTechs():GetNumTechsKnown()}
  if not p:IsMinorCiv() and not p:IsBarbarian() then
   out.livingMajors[#out.livingMajors+1]=owner
   %(strength)s
  end
  for city in p:Cities() do
   out.cities[#out.cities+1]={plot=city:Plot():GetPlotIndex(),owner=owner,name=city:GetName(),originalOwner=city:GetOriginalOwner(),foundedTurn=city:GetGameTurnFounded(),acquiredTurn=city:GetGameTurnAcquired(),hp=city:GetMaxHitPoints()-city:GetDamage(),maxHP=city:GetMaxHitPoints(),population=city:GetPopulation()}
  end
  if not p:IsBarbarian() then
   for other=owner+1,63 do local q=Players[other];if q and q:IsAlive() and not q:IsObserver() and not q:IsBarbarian() and Teams[p:GetTeam()]:IsAtWar(q:GetTeam()) then out.wars[#out.wars+1]={owner,other} end end
  end
 end
end
local camp=GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP;out.barbCamps=0
for i=0,Map.GetNumPlots()-1 do if Map.GetPlotByIndex(i):GetImprovementType()==camp then out.barbCamps=out.barbCamps+1 end end
return out
'''
STRENGTH = r'''-- Strength metrics for A/B comparison (abcompare.py); nil when a getter is absent.
   local t=Teams[p:GetTeam()];local ss=0;for _,id in ipairs(parts) do ss=ss+(v(t.GetProjectCount,t,id) or 0) end
   local e=out.players[#out.players]
   e.improvedAI=v(p.IsStackingImprovedAI,p);e.era=v(p.GetCurrentEra,p);e.policies=v(p.GetNumPolicies,p);e.population=v(p.GetTotalPopulation,p)
   e.land=v(p.GetTotalLand,p);e.might=v(p.GetMilitaryMight,p);e.gold=v(p.GetGold,p);e.goldRate=v(p.CalculateGoldRate,p);e.science=v(p.GetScience,p)
   e.culture=v(p.GetTotalJONSCulturePerTurn,p);e.faith=v(p.GetTotalFaithPerTurn,p);e.tourism=v(p.GetTourism,p);e.happiness=v(p.GetExcessHappiness,p)
   e.wonders=v(p.GetNumWorldWonders,p);e.influentialOn=v(p.GetNumCivsInfluentialOn,p);e.spaceshipParts=ss
   e.votes=league and v(league.CalculateStartingVotesForMember,league,owner) or nil'''

# After autoplay: victory, replay messages (vpbench: Type ~= 2, Plots dropped) and per-major replay data.
FINAL = r'''
local out={}
local vic=Game.GetVictory();local info=vic and vic>=0 and GameInfo.Victories[vic]
out.victory={winner=Game.GetWinner(),victory=info and info.Type or '',turn=Game.GetGameTurn()}
local msgs={}
for i=0,Game.GetNumReplayMessages()-1 do local m=Game.GetReplayMessage(i);if m and m.Type~=2 then m.index=i;m.Plots=nil;msgs[#msgs+1]=m end end
out.messages=msgs
local series={}
for owner=0,63 do local p=Players[owner]
 if p and p:IsEverAlive() and not p:IsBarbarian() and not p:IsMinorCiv() and not p:IsObserver() then
  local ok,d=pcall(function() return p:GetReplayData() end)
  if ok and d then local o={};for k,s in pairs(d) do local a={};for t,x in pairs(s) do a[#a+1]={t,x} end;o[k]=a end;series[tostring(owner)]=o end
 end
end
out.replayData=series
return out
'''

ESSENTIAL_LOGS = ('Headless*.log', 'Lua.log', 'Database.log', 'Stacking-*.log', 'vfs-index.log', 'CvAssert*.log', 'RandCalls.csv')


def utc(): return datetime.now(timezone.utc).isoformat()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
        return default


def spec_key(resolved, spec_path):
    blob = json.dumps(resolved, sort_keys=True, separators=(',', ':')).encode('utf-8')
    stem = Path(spec_path).stem.replace('-resolved', '').replace('.resolved', '').replace('spec-', '') or 'spec'
    s = resolved.get('seeds', {})
    return f"headless-{stem}-m{s.get('map')}-s{s.get('sync')}-{hashlib.sha256(blob).hexdigest()[:8]}"


def resolve_spec(spec_path, db, seeds=None):
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    if seeds:
        spec = dict(spec, seeds=dict(spec.get('seeds') or {}, **seeds))
    if spec.get('specVersion') and not seeds:
        return spec  # already resolved
    if spec.get('specVersion'):
        return dict(spec, seeds=dict(spec['seeds'], **seeds))  # resolved spec with new seeds: IDs unchanged
    return gamespec.resolve(spec, db_path=Path(db))


class Run:
    def __init__(self, folder):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)

    def log(self, action, quiet=False, **values):
        row = dict(utc=utc(), action=action, **values)
        with (self.dir / 'events.jsonl').open('a', encoding='utf-8') as s:
            s.write(json.dumps(row) + '\n')
        if not quiet:
            print(json.dumps(row), flush=True)


def turn_lines(path, offset):
    """New complete lines of turn-times.jsonl after byte offset."""
    try:
        with open(path, 'rb') as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    end = data.rfind(b'\n') + 1
    rows = []
    for line in data[:end].splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows, offset + end


def prune(run):
    """Drop the bulky per-run copies: database copies, state dumps, the DLL's AI logs (keeps ESSENTIAL_LOGS)."""
    for name in ('db', 'dump-t000') + tuple(p.name for p in run.glob('dump-t*')):
        shutil.rmtree(run / name, ignore_errors=True)
    logs = run / 'Logs'
    if logs.is_dir():
        keep = {p for pattern in ESSENTIAL_LOGS for p in logs.glob(pattern)}
        for p in logs.iterdir():
            if p not in keep:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def newgame(a, quiet=False):
    """Play one game; returns 0 when completed. a: argparse namespace (see main) or an equivalent object."""
    folder = (Path(a.run_dir) if getattr(a, 'run_dir', None) else RUNS / a.run).resolve()
    if (folder / 'status.json').is_file():
        raise SystemExit(f'{folder} already has a status.json; use a new run name')
    run = Run(folder)
    status = dict(state='failed', backend='headless')
    job = None
    try:
        dll = Path(a.dll or (Path(a.mods_dir) / '(1) Community Patch/CvGameCore_Expansion2.dll')).resolve()
        exe = dbcache.find_exe(a.exe)
        if a.db:
            db, dbinfo = Path(a.db).resolve(), dict(db=str(Path(a.db).resolve()))
        else:
            db, dbinfo, key = dbcache.get_db(a.mods_dir, a.mods_db, dll, exe, cache=getattr(a, 'db_cache', None),
                                             log=lambda m: run.log('database_built', quiet=quiet, message=m))
            dbinfo = dict(dbinfo, db=str(db), cacheKey=key)
        resolved = resolve_spec(a.spec, db, getattr(a, 'seeds', None))
        write(run.dir / 'spec-resolved.json', resolved)
        seed_key = spec_key(resolved, a.spec)
        dll_sha = dbcache.sha256_file(dll)
        mask = a.improved_mask
        (run.dir / 'hh-before-arm.lua').write_text(BEFORE_ARM % dict(setup=SETUP, diagnostics=a.diagnostics,
                                                                       mask='nil' if mask is None else int(mask)), encoding='utf-8')
        (run.dir / 'hh-checkpoint.lua').write_text(CHECKPOINT % dict(strength=STRENGTH), encoding='utf-8')
        (run.dir / 'hh-final.lua').write_text(FINAL, encoding='utf-8')
        cmd = [str(exe), 'newgame', '--spec', str(run.dir / 'spec-resolved.json'), '--out', str(run.dir.resolve()),
               '--dll', str(dll), '--db', str(db), '--turns', str(a.target_turn),
               '--lua-before-arm', str(run.dir / 'hh-before-arm.lua'),
               '--checkpoint-lua', str(run.dir / 'hh-checkpoint.lua'), '--checkpoint-every', str(a.checkpoint_every),
               '--lua-before-dump', str(run.dir / 'hh-final.lua')]
        if a.mods_dir: cmd += ['--mods-dir', str(Path(a.mods_dir).resolve())]
        if a.mods_db: cmd += ['--mods-db', str(Path(a.mods_db).resolve())]
        if getattr(a, 'game_dir', None): cmd += ['--game-dir', a.game_dir]
        cmd += list(a.host_arg or [])
        write(run.dir / 'hh-command.json', dict(command=cmd, exe=str(exe), exeSHA256=dbcache.sha256_file(exe), dll=str(dll),
                                                dllSHA256=dll_sha, database=dbinfo))
        affinity = int(a.affinity, 0) if isinstance(a.affinity, str) else a.affinity
        job = winproc.Job(memory_mb=a.max_memory_mb, affinity=affinity)
        started = time.monotonic(); started_utc = utc()
        with open(run.dir / 'host-stdout.txt', 'wb') as out:
            proc = subprocess.Popen(cmd, cwd=str(run.dir), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=winproc.CREATE_NO_WINDOW)
            job.assign(proc)
            run.log('launched', quiet=quiet, pid=proc.pid, affinity=hex(affinity) if affinity else None, memoryLimitMB=a.max_memory_mb,
                    dll=str(dll), dllSHA256=dll_sha, target=a.target_turn)
            offset = 0; last_turn = 0; last_progress = started; seen = {0: 0.0}; killed = None
            while True:
                try:
                    code = proc.wait(timeout=a.poll)
                    break
                except subprocess.TimeoutExpired:
                    pass
                rows, offset = turn_lines(run.dir / 'turn-times.jsonl', offset)
                now = time.monotonic()
                for r in rows:
                    seen[r['turn']] = round(r['seconds'], 3); last_progress = now
                    if r['turn'] % 10 == 0 or r['turn'] < 3:
                        run.log('checkpoint', quiet=True, turn=r['turn'], seconds=round(r['seconds'], 1))
                    last_turn = r['turn']
                if a.maximum_seconds and now - started > a.maximum_seconds:
                    killed = f'maximum run time ({a.maximum_seconds} s) reached at turn {last_turn}'
                elif a.stall_seconds and now - last_progress > a.stall_seconds:
                    killed = f'no turn progress for {a.stall_seconds} s at turn {last_turn}'
                if killed:
                    job.terminate(3)
                    code = proc.wait()
                    break
            host_seconds = time.monotonic() - started
            rows, offset = turn_lines(run.dir / 'turn-times.jsonl', offset)
            for r in rows: seen[r['turn']] = round(r['seconds'], 3)
            pstats = winproc.process_stats(proc)
            jstats = job.stats()
        report = read(run.dir / 'newgame-report.json', {}) or {}
        ng = report.get('newgame', {})
        before = read(run.dir / 'lua-before-arm.json') or {}
        final = read(run.dir / 'lua-before-dump.json') or {}
        setup = dict(before.get('setup') or {})
        setup['improvedMask'] = before.get('improvedMask', -2)
        if mask is None and a.ab_role:
            setup['improvedMask'] = {'baseline': 0, 'test': -1}[a.ab_role]
        setup.update(backend='headless', abRole=a.ab_role, diagnosticsLevel=before.get('diagnosticsLevel'),
                     dllSHA256=dll_sha, specKey=seed_key)
        write(run.dir / 'setup.json', setup)
        if before.get('diagnosticsSet') is not None:
            run.log('diagnostics_enabled', quiet=quiet, level=before.get('diagnosticsSet'))
        if before.get('improvedMaskSet') is not None:
            run.log('improved_mask', quiet=quiet, mask=before.get('improvedMaskSet'))
        write(run.dir / 'turn-seen.json', {str(k): seen[k] for k in sorted(seen)})
        write(run.dir / 'replay-messages.json', final.get('messages') or [])
        write(run.dir / 'replay-data.json', final.get('replayData') or {})
        finals = sorted((run.dir / 'checkpoints').glob('turn-*-final.json'))
        end_turn = max(seen) if seen else 0
        if finals:
            end_turn = max(end_turn, (read(finals[-1]) or {}).get('data', {}).get('turn', end_turn))
        wall = max(seen.values()) if seen else 0.0
        prefixes = sorted({p.name.rsplit('-', 1)[0] for p in (run.dir / 'Logs').glob('Stacking-*-r*-*.log')})
        process = dict(pstats, PeakCommit=jstats.get('peakProcessCommit'), HostSeconds=round(host_seconds, 1))
        status = dict(state='failed', backend='headless', startedUTC=started_utc, startTurn=0, endTurn=end_turn, turns=end_turn,
                      wallSeconds=round(wall, 1), secondsPerTurn=round(wall / end_turn, 3) if end_turn else None,
                      hostSeconds=round(host_seconds, 1), process=process, pollSeconds=0, dllSHA256=dll_sha, save=seed_key,
                      spec=str(Path(a.spec).resolve()), replayMessages=len(final.get('messages') or []), exitCode=code,
                      hostStatus=report.get('status'), hostError=report.get('error') or ng.get('error'),
                      luaErrors=ng.get('lua_errors'), updates=(ng.get('autoplay') or {}).get('updates'),
                      diagnosticsLogPrefix=prefixes[-1] if prefixes else None, logsFolder=str((run.dir / 'Logs').resolve()))
        victory = final.get('victory') or {}
        if victory.get('winner', -1) is not None and victory.get('winner', -1) >= 0:
            status.update(endReason='victory', winner=victory['winner'], victory=victory.get('victory'))
            run.log('victory', quiet=quiet, turn=victory.get('turn'), winner=victory['winner'], victory=victory.get('victory'), seconds=round(wall))
        else:
            status['endReason'] = 'target_turn'
        dumps = sorted(str(p) for p in run.dir.rglob('*.dmp'))
        if dumps: status['minidumps'] = dumps
        if killed:
            status.update(error=killed, endReason='killed')
        elif code != 0 or report.get('status') != 'passed':
            status['error'] = f"host exit {code}, status {report.get('status')}: {status.get('hostError') or 'see host-stdout.txt and Logs/Headless.log'}"
            if a.max_memory_mb and jstats.get('peakProcessCommit', 0) >= a.max_memory_mb * 2 ** 20 * 0.95:
                status['error'] += f' (memory limit {a.max_memory_mb} MB reached)'
        elif status['endReason'] == 'target_turn' and end_turn < a.target_turn:
            status['error'] = f'autoplay stopped at turn {end_turn} before the target {a.target_turn}'
        else:
            status['state'] = 'completed'
        if status['state'] == 'completed' and status['endReason'] == 'target_turn':
            run.log('target_reached', quiet=quiet, turn=end_turn, seconds=round(wall, 1))
        write(run.dir / 'status.json', status)
        if a.prune:
            prune(run.dir)
        if status['state'] == 'completed':
            run.log('completed', quiet=quiet, turns=status['turns'], wallSeconds=status['wallSeconds'], secondsPerTurn=status['secondsPerTurn'],
                    hostSeconds=status['hostSeconds'], peakWorkingSetMB=round((process.get('PeakWorkingSet') or 0) / 2 ** 20))
            return 0
        run.log('failed', quiet=quiet, error=status.get('error'))
        return 1
    except BaseException as error:  # noqa: BLE001 (KeyboardInterrupt included: the job kills the host)
        status.update(error=f'{type(error).__name__}: {error}', utc=utc())
        write(run.dir / 'status.json', status)
        run.log('failed', quiet=quiet, error=status['error'])
        if isinstance(error, KeyboardInterrupt):
            raise
        return 1
    finally:
        if job:
            job.close()


def add_newgame_args(n, vpbench=False):
    """The newgame options; vpbench=True adds only those vpbench's own newgame parser lacks."""
    if not vpbench:
        n.add_argument('--run', help='run name: work/test-runs/NAME (as vpbench)')
        n.add_argument('--spec', required=True, help='game spec (gamespec.py format, resolved or not)')
        n.add_argument('--target-turn', type=int, required=True, help='autoplay to this turn')
        n.add_argument('--diagnostics', type=int, default=0, help='Stacking diagnostics level during autoplay (behaviour runs)')
        n.add_argument('--maximum-seconds', type=int, default=21600)
    n.add_argument('--improved-mask', type=int, default=None, help='A/B: Game.SetStackingAIImprovedMask(N) before arming (DLLs with the switch)')
    n.add_argument('--run-dir', help='run folder (instead of --run)')
    n.add_argument('--dll', help='game DLL (default: CvGameCore_Expansion2.dll in MODS/(1) Community Patch)')
    n.add_argument('--db', help='built game database (default: cached build from --mods-dir/--mods-db and --dll)')
    n.add_argument('--mods-dir', help='MODS folder or pinned copy (read only)')
    n.add_argument('--mods-db', help='Civ5ModsDatabase.db (activated mods)')
    n.add_argument('--exe', help='civ5headless.exe (default: the latest build)')
    n.add_argument('--game-dir', help='game folder (host default: ' + DEFAULT_GAME_DIR + ')')
    n.add_argument('--ab-role', choices=['baseline', 'test'], help='A/B of two DLL builds: record improvedMask 0 or -1 in setup.json')
    n.add_argument('--checkpoint-every', type=int, default=1, help='checkpoint every n turns (default 1)')
    n.add_argument('--stall-seconds', type=int, default=900, help='kill the host after this long without a new turn')
    n.add_argument('--max-memory-mb', type=int, default=3500, help='per-process commit limit (job object); 0 = none')
    n.add_argument('--affinity', default=None, help='CPU affinity mask for the host (e.g. 0x3)')
    n.add_argument('--prune', action='store_true', help='delete the database copy, state dumps and AI logs afterwards')
    n.add_argument('--poll', type=float, default=1.0, help='progress poll interval in seconds')
    n.add_argument('--host-arg', action='append', help='extra civ5headless.exe argument (repeatable), e.g. --no-game-logging')


def check_args(a, error):
    if not (a.run or a.run_dir): error('--run or --run-dir is required')
    if not a.spec: error('--spec is required')
    if not a.target_turn or a.target_turn <= 0: error('--target-turn N (> 0) is required')
    if not a.db and not (a.mods_dir and a.mods_db): error('--db, or --mods-dir and --mods-db, is required')
    if a.improved_mask is not None and a.ab_role: error('--improved-mask and --ab-role exclude each other')
    if a.max_memory_mb == 0: a.max_memory_mb = None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    add_newgame_args(sub.add_parser('newgame'))
    a = p.parse_args(argv)
    check_args(a, p.error)
    return newgame(a)


if __name__ == '__main__':
    sys.exit(main())
