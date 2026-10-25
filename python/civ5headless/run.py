"""One host game: play a new game from a spec in civ5headless.exe and write a vpbench-style run folder.

  c5h run SPEC.json --turns N [--run NAME | --run-dir DIR] [--seeds MAP SYNC]
          [--dll DLL] [--db DB] [--mods-dir MODS] [--mods-db Civ5ModsDatabase.db | --mod ID[:VER]... | --no-mods]
          [--loc-db DB] [--game-dir DIR] [--exe EXE]
          [--profiles DIR | --no-profiles] [--skip-addin NAME]... [--no-addins]
          [--fingerprint] [--fingerprint-every K] [--fingerprint-turns T,T,...] [--fingerprint-split N]
          [--lua-probe FILE]... [--heap-perturb N] [--frame-skew K]
          [--diagnostics 1] [--improved-mask N | --ab-role baseline|test] [--checkpoint-every 1]
          [--maximum-seconds S] [--stall-seconds S] [--max-memory-mb MB] [--affinity MASK] [--low-priority]
          [--prune] [--host-arg ARG]...

From Python: run.play(spec, turns, ...) -> Result (see play).

Inputs left out come from the configuration (civ5headless.toml or discovery; c5h doctor): the game folder, the DLL,
the MODS folder, the mods and localization databases, the profiles folder, the host exe and the runs folder (run
folder <runs>/NAME; without --run or --run-dir, NAME is <spec stem>-<date>-<time>). The game database is --db, else
the configured db, else the cached build for the mods and DLL (dbcache.py).

Mods: the activated mods are those of the mods database (--mods-db, default the game's registry). --mod gives the
mod set instead: a registry is generated from the .modinfo files (modsdb.py), so the game need not have activated
them. --no-mods plays without mods (the database is the DLC snapshot post-processed by the DLL).

UI: the host runs the activated mods' InGameUIAddins (--skip-addin NAME leaves one out, --no-addins all) and the UI
emulation profiles from --profiles (default: config profiles; --no-profiles: none). --fingerprint runs the Lua
fingerprint probe (probes/fingerprint.lua; c5h fingerprint compares two runs), every turn or every K-th
(--fingerprint-every) plus --fingerprint-turns, before the --lua-probe files.

The run folder has the files vpbench writes and its readers use (compare.py, abcompare.py, samerun.py):
events.jsonl, setup.json, spec-resolved.json, status.json, turn-times.jsonl, turn-seen.json,
checkpoints/turn-NNNN.json (+ turn-NNNN-final.json), replay-messages.json, replay-data.json; plus the host's
own outputs (host-report.json, newgame-report.json, Logs/ with HeadlessDigest.log and Lua.log, t000-*.json,
dump-t000/, dump-tN/).

Differences from a real-game run (docs/user-guide.md, "Run folders"):
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
from dataclasses import dataclass
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone
from types import SimpleNamespace

from . import config, dbcache, modsdb, probes, winproc
from . import spec as gamespec

# vpbench.SETUP (the real-game benchmark of the Vox Populi fork this came from), as a function. Keep in sync.
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
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
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


def run_folder(a, cfg):
    if getattr(a, 'run_dir', None):
        return Path(a.run_dir).resolve()
    name = getattr(a, 'run', None) or f'{Path(a.spec).stem}-{datetime.now():%Y%m%d-%H%M%S}'
    return (cfg.require('runs') / name).resolve()


def fingerprint_options(a):
    """dict(every, turns, split) when the run takes Lua fingerprints, else None. a.fingerprint is a flag or a dict
    with those keys; a.fingerprint_every, _turns and _split (each implies the flag) fill what it leaves out."""
    return probes.fingerprint_options(getattr(a, 'fingerprint', None),
                                      *(getattr(a, f'fingerprint_{k}', None) for k in ('every', 'turns', 'split')))


def newgame(a, quiet=False, cfg=None):
    """Play one game; returns 0 when completed. a: argparse namespace (see add_arguments) or an equivalent object;
    cfg: the configuration that supplies whatever a leaves out (default config.load())."""
    cfg = cfg or config.load()
    folder = run_folder(a, cfg)
    if (folder / 'status.json').is_file():
        raise FileExistsError(f'{folder} already has a status.json; use a new run name')
    run = Run(folder)
    status = dict(state='failed', backend='headless')
    job = None
    try:
        no_mods = bool(getattr(a, 'no_mods', False))
        mods_dir, mods_db = modsdb.resolve(cfg, [] if no_mods else getattr(a, 'mod', None), getattr(a, 'mods_dir', None),
                                           getattr(a, 'mods_db', None),
                                           log=lambda m: run.log('mods_registry', quiet=quiet, message=m))
        loc_db = getattr(a, 'loc_db', None) or cfg.loc_db
        game_dir = getattr(a, 'game_dir', None) or cfg.require('game_dir', 'pass --game-dir')
        dll = Path(a.dll or cfg.require('dll', 'pass --dll')).resolve()
        exe = dbcache.find_exe(a.exe, cfg)
        no_profiles = bool(getattr(a, 'no_profiles', False))
        profiles = None if no_profiles else getattr(a, 'profiles', None) or cfg.profiles
        profiles = Path(profiles).resolve() if profiles else None
        if not profiles and not no_profiles:
            run.log('warning', quiet=quiet, message="no profiles folder configured: the host looks for profiles\\ next to "
                    "its exe and in the folders above (set profiles in civ5headless.toml, or pass --profiles or --no-profiles)")
        fingerprint = fingerprint_options(a)
        lua_probes = probes.fingerprint_probes(cfg, run.dir, **fingerprint) if fingerprint else []
        lua_probes += [Path(p).resolve() for p in getattr(a, 'lua_probe', None) or []]
        db, dbinfo = dbcache.database(cfg, db=a.db, mods_dir=mods_dir, mods_db=mods_db, dll=dll, exe=exe,
                                      log=lambda m: run.log('database_built', quiet=quiet, message=m))
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
        if no_mods:
            cmd += ['--no-mods']
        else:
            if mods_dir: cmd += ['--mods-dir', str(Path(mods_dir).resolve())]
            if mods_db: cmd += ['--mods-db', str(Path(mods_db).resolve())]
        if loc_db: cmd += ['--loc-db', str(Path(loc_db).resolve())]
        cmd += ['--game-dir', str(game_dir)]
        if no_profiles:
            cmd += ['--no-profiles']
        elif profiles:
            cmd += ['--profiles', str(profiles)]
        if getattr(a, 'no_addins', False): cmd += ['--no-addins']
        for name in getattr(a, 'skip_addin', None) or []:
            cmd += ['--skip-addin', name]
        for probe in lua_probes:
            cmd += ['--lua-probe', str(probe)]
        if getattr(a, 'heap_perturb', None): cmd += ['--heap-perturb', str(a.heap_perturb)]
        if getattr(a, 'frame_skew', None): cmd += ['--frame-skew', str(a.frame_skew)]
        cmd += list(a.host_arg or [])
        write(run.dir / 'hh-command.json', dict(command=cmd, exe=str(exe), exeSHA256=dbcache.sha256_file(exe), dll=str(dll),
                                                dllSHA256=dll_sha, database=dbinfo, modsDb=str(mods_db) if mods_db else None,
                                                noMods=no_mods, profiles=str(profiles) if profiles else None,
                                                fingerprint=fingerprint))
        affinity = int(a.affinity, 0) if isinstance(a.affinity, str) else a.affinity
        job = winproc.Job(memory_mb=a.max_memory_mb, affinity=affinity)
        meter = winproc.LoadMeter().start()  # what else ran (the real game) during this run
        started = time.monotonic(); started_utc = utc()
        with open(run.dir / 'host-stdout.txt', 'wb') as out:
            proc = subprocess.Popen(cmd, cwd=str(run.dir), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=winproc.CREATE_NO_WINDOW)
            job.assign(proc)
            if getattr(a, 'low_priority', False):
                winproc.set_priority(proc)  # leave the foreground (and a real game) responsive
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
            load = meter.stop()
            load['otherBusyCores'] = round(load['systemBusyCores'] - (pstats.get('CPUSeconds') or 0) / max(host_seconds, 1e-6), 2)
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
                      background=load, diagnosticsLogPrefix=prefixes[-1] if prefixes else None, logsFolder=str((run.dir / 'Logs').resolve()))
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


@dataclass
class Result:
    """One played game: the run folder, whether it completed, its status.json and the host's report."""
    dir: Path
    ok: bool
    status: dict

    @property
    def report(self):
        """host-report.json when the host writes one (plan 9.2), else newgame-report.json."""
        return read(self.dir / 'host-report.json') or read(self.dir / 'newgame-report.json', {}) or {}

    @property
    def digest_log(self):
        return self.dir / 'Logs/HeadlessDigest.log'

    @property
    def lua_log(self):
        return self.dir / 'Logs/Lua.log'


def play(spec, turns, *, run=None, run_dir=None, cfg=None, seeds=None, dll=None, db=None, mods_dir=None,
         mods_db=None, mods=None, no_mods=False, loc_db=None, game_dir=None, exe=None, profiles=None, no_profiles=False,
         skip_addins=(), no_addins=False, fingerprint=False, lua_probes=(), heap_perturb=None, frame_skew=None,
         diagnostics=0, improved_mask=None, ab_role=None, checkpoint_every=1, max_seconds=21600, stall_seconds=900,
         max_memory_mb=3500, affinity=None, low_priority=False, prune=False, host_args=(), poll=1.0, quiet=True):
    """Play one game in civ5headless.exe and return its Result.

    spec: a spec file (resolved or not) or a spec dict (written to the run folder as spec.json); turns: autoplay to
    this turn; run / run_dir: the run folder (<runs>/run, or run_dir; default <runs>/<spec stem>-<date>-<time>);
    cfg: a config.Config (default config.load()); seeds: {'map': M, 'sync': S} over the spec's;
    mods: the mod set as 'ID[:VER]' strings (a registry is generated; instead of mods_db); no_mods: play without mods;
    profiles / no_profiles, skip_addins / no_addins: the host's UI emulation profiles and InGameUIAddins;
    fingerprint: True, or dict(every=K, turns=[...], split=N), runs the Lua fingerprint probe before lua_probes;
    lua_probes: files for the host's --lua-probe; heap_perturb, frame_skew: the host options of the same name;
    host_args: further host arguments. The other keywords are the c5h run options of the same name; anything left
    None comes from the configuration. Raises FileExistsError when the run folder already holds a game."""
    cfg = cfg or config.load()
    if isinstance(spec, dict):
        folder = Path(run_dir).resolve() if run_dir else cfg.require('runs') / (run or f'spec-{datetime.now():%Y%m%d-%H%M%S}')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'spec.json').write_text(json.dumps(spec, indent=1) + '\n', encoding='utf-8')
        spec, run_dir = folder / 'spec.json', folder
    a = SimpleNamespace(run=run, run_dir=str(run_dir) if run_dir else None, spec=str(spec), target_turn=int(turns),
                        seeds=dict(seeds) if seeds else None, dll=dll, db=db, mods_dir=mods_dir, mods_db=mods_db,
                        mod=list(mods) if mods is not None else None, no_mods=no_mods, loc_db=loc_db,
                        game_dir=game_dir, exe=exe, profiles=profiles, no_profiles=no_profiles,
                        skip_addin=list(skip_addins or []), no_addins=no_addins, fingerprint=fingerprint,
                        lua_probe=list(lua_probes or []),
                        heap_perturb=heap_perturb, frame_skew=frame_skew, diagnostics=int(diagnostics or 0),
                        improved_mask=improved_mask, ab_role=ab_role, checkpoint_every=int(checkpoint_every or 1),
                        maximum_seconds=max_seconds, stall_seconds=stall_seconds, max_memory_mb=max_memory_mb or None,
                        affinity=affinity, low_priority=low_priority, prune=prune, host_arg=list(host_args or []),
                        poll=poll)
    folder = run_folder(a, cfg)
    a.run_dir = str(folder)
    code = newgame(a, quiet=quiet, cfg=cfg)
    status = read(folder / 'status.json', {}) or {}
    return Result(folder, code == 0 and status.get('state') == 'completed', status)


def add_arguments(n):
    """The c5h run options (queue.py builds the same namespace from a queue's jobs)."""
    n.add_argument('spec', help='game spec (spec.py format, resolved or not)')
    n.add_argument('--turns', '--target-turn', dest='target_turn', type=int, required=True, help='autoplay to this turn')
    n.add_argument('--run', help='run name: <runs>/NAME (default <spec stem>-<date>-<time>)')
    n.add_argument('--run-dir', help='run folder (instead of --run)')
    n.add_argument('--seeds', nargs=2, type=int, metavar=('MAP', 'SYNC'), help="map and sync seeds over the spec's")
    n.add_argument('--dll', help='game DLL (default: config dll)')
    n.add_argument('--db', help='built game database (default: config db, else the cached build from the mods and DLL)')
    n.add_argument('--mods-dir', help='MODS folder or pinned copy, read only (default: config mods_dir)')
    n.add_argument('--mods-db', help='Civ5ModsDatabase.db with the activated mods (default: config mods_db)')
    n.add_argument('--mod', action='append', help='activated mod GUID[:version] (repeatable): the mod set, from a '
                   'generated registry instead of --mods-db')
    n.add_argument('--no-mods', action='store_true', help='play without mods')
    n.add_argument('--loc-db', help='Localization-Merged.db (default: config loc_db)')
    n.add_argument('--game-dir', help='game folder (default: config game_dir)')
    n.add_argument('--exe', help='civ5headless.exe (default: config exe)')
    n.add_argument('--profiles', help='UI emulation profiles folder (default: config profiles)')
    n.add_argument('--no-profiles', action='store_true', help='run no UI emulation profile')
    n.add_argument('--skip-addin', action='append', help="leave out this InGameUIAddin: its file name without extension, "
                   "e.g. SmallResourceIcons (repeatable)")
    n.add_argument('--no-addins', action='store_true', help="run none of the mods' InGameUIAddins")
    n.add_argument('--fingerprint', action='store_true', help='run the Lua fingerprint probe (probes/fingerprint.lua)')
    n.add_argument('--fingerprint-every', type=int, help='fingerprint every K-th turn (default every turn; implies --fingerprint)')
    n.add_argument('--fingerprint-turns', help='fingerprint these turns too, e.g. 1,50,100 (implies --fingerprint)')
    n.add_argument('--fingerprint-split', type=int, help='fingerprint sections per Lua.log line (default 12)')
    n.add_argument('--lua-probe', action='append', help='Lua file the host runs once the game has started (repeatable)')
    n.add_argument('--heap-perturb', type=int, help='host heap layout perturbation seed (0: off)')
    n.add_argument('--frame-skew', type=int, help='an extra engine update before every K-th one')
    n.add_argument('--diagnostics', type=int, default=0, help='Stacking diagnostics level during autoplay (behaviour runs)')
    n.add_argument('--improved-mask', type=int, default=None, help='A/B: Game.SetStackingAIImprovedMask(N) before arming (DLLs with the switch)')
    n.add_argument('--ab-role', choices=['baseline', 'test'], help='A/B of two DLL builds: record improvedMask 0 or -1 in setup.json')
    n.add_argument('--checkpoint-every', type=int, default=1, help='checkpoint every n turns (default 1)')
    n.add_argument('--maximum-seconds', type=int, default=21600)
    n.add_argument('--stall-seconds', type=int, default=900, help='kill the host after this long without a new turn')
    n.add_argument('--max-memory-mb', type=int, default=3500, help='per-process commit limit (job object); 0 = none')
    n.add_argument('--affinity', default=None, help='CPU affinity mask for the host (e.g. 0x3)')
    n.add_argument('--low-priority', action='store_true', help='run the host below normal priority')
    n.add_argument('--prune', action='store_true', help='delete the database copy, state dumps and AI logs afterwards')
    n.add_argument('--poll', type=float, default=1.0, help='progress poll interval in seconds')
    n.add_argument('--host-arg', action='append', help='extra civ5headless.exe argument (repeatable), e.g. --host-arg=--no-game-logging')


def check_args(a, error):
    if a.target_turn <= 0: error('--turns N (> 0) is required')
    if a.improved_mask is not None and a.ab_role: error('--improved-mask and --ab-role exclude each other')
    if a.mod and a.no_mods: error('--mod and --no-mods exclude each other')
    if (a.mod or a.no_mods) and a.mods_db: error('--mod and --no-mods exclude --mods-db (the registry is generated)')
    if a.profiles and a.no_profiles: error('--profiles and --no-profiles exclude each other')
    try:
        fingerprint_options(a)
    except ValueError:
        error('--fingerprint-turns takes turn numbers, e.g. 1,50,100')
    if a.max_memory_mb == 0: a.max_memory_mb = None
    a.seeds = dict(map=a.seeds[0], sync=a.seeds[1]) if a.seeds else None


def main(argv=None, cfg=None):
    p = argparse.ArgumentParser(prog='c5h run', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    a = p.parse_args(argv)
    check_args(a, p.error)
    try:
        return newgame(a, cfg=cfg or config.load())
    except FileExistsError as error:
        print(f'c5h run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
