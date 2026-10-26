"""Civilization V saved games (.Civ5Save): the header that names the game, its DLC, mods and DLL.

  c5h save SAVE.Civ5Save... [--json]        what each save is: turn, civilization, map, DLC, mods, DLL

The real game and the host (the last turn of every run, --autosave, --save-at) write the same files, and each loads
the other's (docs/saves.md). The header comes first, uncompressed (u32 little-endian; a string is a u32 length and its
bytes; a GUID its 16 bytes as in memory):

  "CIV5", u32 8 (save version), game version "1.0.3.279 (403694)", build "403694",
  u32 turn, u8 game type (0: single player),
  the active player's civilization and handicap, the start era, the active player's current era, the game speed, the
  world size and the map script (type names; the map script a path),
  u32 n DLC, each GUID, u32 1, name; u32 n mods, each ID, u32 version, name (activation order),
  the leader name and civilization name (empty unless the player set them), the player colour,
  the DLL's GUID (GetDLLGUID) and version, a constant GUID {0d41152c-948e-498f-8cdf-699d04c98a95}, u32 0.

Then the pregame's own record, u32 2 and the game state, zlib-compressed in 64 KiB pieces; read_header stops before.
The host checks a save before it loads one: a single-player game, the DLL (GUID) and the mod set the save names.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import argparse, json, struct, sys, uuid

SAVE_VERSION = 8
SINGLE_PLAYER = 0
GAME_TYPES = {0: 'single player', 1: 'network multiplayer', 2: 'hotseat', 3: 'email multiplayer'}
TAIL_GUID = '0d41152c-948e-498f-8cdf-699d04c98a95'


class SaveError(ValueError):
    """Not a .Civ5Save this code reads (no CIV5 at the start, another save version, a header cut short)."""


@dataclass
class SaveHeader:
    path: str
    saveVersion: int
    gameVersion: str
    gameBuild: str
    turn: int
    gameType: int
    civilization: str
    handicap: str
    startEra: str
    currentEra: str
    speed: str
    worldSize: str
    mapScript: str
    dlc: list = field(default_factory=list)   # [{'id': GUID text, 'name': ...}]
    mods: list = field(default_factory=list)  # [{'id': ..., 'version': int, 'name': ...}] in activation order
    leaderName: str = ''
    civilizationName: str = ''
    playerColor: str = ''
    dllGuid: str = ''
    dllVersion: str = ''
    headerBytes: int = 0
    fileBytes: int = 0

    @property
    def mod_set(self):
        """The mods as c5h's --mod values, 'ID:VERSION' in activation order ([] for an unmodded game)."""
        return [f"{m['id']}:{m['version']}" for m in self.mods]

    def as_dict(self):
        return asdict(self)


class _Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise SaveError("the save's header is cut short or malformed")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def u8(self):
        return self.take(1)[0]

    def str(self):
        n = self.u32()
        if n > 1 << 20:
            raise SaveError("the save's header is cut short or malformed")
        return self.take(n).decode('utf-8', errors='replace')

    def guid(self):
        return '{' + str(uuid.UUID(bytes_le=bytes(self.take(16)))) + '}'


def is_save(path):
    """Whether path names a saved game: a .Civ5Save, or a file that starts as one (CIV5)."""
    path = Path(path)
    if path.suffix.lower() == '.civ5save':
        return True
    try:
        with path.open('rb') as f:
            return f.read(4) == b'CIV5'
    except OSError:
        return False


def read_header(path):
    """The header of a .Civ5Save (SaveHeader). Raises OSError, SaveError."""
    path = Path(path)
    with path.open('rb') as f:
        data = f.read(1 << 20)  # the header is a few KB; a million mods would not fit
        size = path.stat().st_size
    if data[:4] != b'CIV5':
        raise SaveError(f'{path.name} is not a .Civ5Save (no CIV5 at the start)')
    r = _Reader(data)
    r.pos = 4
    version = r.u32()
    if version != SAVE_VERSION:
        raise SaveError(f'{path.name}: save version {version} (this reads {SAVE_VERSION})')
    h = dict(saveVersion=version, gameVersion=r.str(), gameBuild=r.str(), turn=r.u32(), gameType=r.u8())
    for k in ('civilization', 'handicap', 'startEra', 'currentEra', 'speed', 'worldSize', 'mapScript'):
        h[k] = r.str()
    dlc = []
    for _ in range(r.u32()):
        gid = r.guid()
        r.u32()
        dlc.append(dict(id=gid, name=r.str()))
    mods = []
    for _ in range(r.u32()):
        mid = r.str()
        ver = r.u32()
        mods.append(dict(id=mid, version=ver, name=r.str()))
    h.update(dlc=dlc, mods=mods, leaderName=r.str(), civilizationName=r.str(), playerColor=r.str(), dllGuid=r.guid(),
             dllVersion=r.str())
    if r.guid().strip('{}') != TAIL_GUID or r.u32() != 0:
        raise SaveError(f"{path.name}: the header does not end as a Civilization V save's does")
    return SaveHeader(path=str(path), headerBytes=r.pos, fileBytes=size, **h)


def describe(h):
    """A few lines on a save for people."""
    mods = ', '.join(f"{m['name'] or m['id']} v{m['version']}" for m in h.mods) or 'none'
    return '\n'.join([
        f'{Path(h.path).name}: turn {h.turn}, {GAME_TYPES.get(h.gameType, f"game type {h.gameType}")}',
        f'  player   {h.civilization} ({h.handicap}), era {h.currentEra}' + (f', {h.leaderName}' if h.leaderName else ''),
        f'  game     {h.mapScript}, {h.worldSize}, {h.speed}, start {h.startEra}',
        f'  DLL      {h.dllGuid} version {h.dllVersion}',
        f'  mods     {mods}',
        f'  DLC      {len(h.dlc)}: ' + ', '.join(d['name'] for d in h.dlc),
        f'  written  game {h.gameVersion}, {h.fileBytes:,} bytes'])


def main(argv=None):
    p = argparse.ArgumentParser(prog='c5h save', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('saves', nargs='+', help='.Civ5Save files')
    p.add_argument('--json', action='store_true', help='print the headers as JSON')
    a = p.parse_args(argv)
    out, failed = [], 0
    for s in a.saves:
        try:
            h = read_header(s)
        except (OSError, SaveError) as error:
            print(f'c5h save: {s}: {error}', file=sys.stderr)
            failed += 1
            continue
        out.append(h.as_dict() if a.json else describe(h))
    if a.json:
        print(json.dumps(out if len(a.saves) > 1 else (out[0] if out else None), indent=1, ensure_ascii=False))
    elif out:
        print('\n\n'.join(out))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
