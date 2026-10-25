# civ5-headless

Runs Civilization V (Brave New World) AI autoplay games without the game: `civ5headless.exe` loads a game DLL built
from the Civ V SDK (the stock DLL, Community Patch, Vox Populi or your own) and plays it with your mods, maps and
setup options, several games at a time, much faster than the real game. A verification suite measures how closely the
headless games represent real Civ V autoplay for your DLL and mods.

Status: being split out of a Vox Populi fork where it was developed; see [docs/plan.md](docs/plan.md) for the plan and
[docs/history](docs/history) for how the host was built and checked against the real game.

## Layout

| Folder | Contents |
|---|---|
| `host/` | The C++ host (driver, engine services, Lua runtime, new-game setup, database builder) |
| `sdk/` | The Civ V SDK headers and import libraries the host builds against ([sdk/README.md](sdk/README.md)) |
| `python/civ5headless/` | The `c5h` tools: configuration, game specs, database builder and cache, runners, comparison |
| `tests/` | Unit tests (`python -m unittest discover -s tests`) |
| `tools/` | Host build (`build_host.py`, `toolchain.py`), interface stub generator, PE import lister, development tools |
| `profiles/` | UI emulation profiles the host runs in place of the game's UI ([docs/profiles.md](docs/profiles.md)) |
| `probes/` | Lua probes for the real game and the host |
| `examples/` | Game specs and queues |
| `docs/` | User guide, engine contract, database builder, DLL additions, plan, history |

## Building

The host must be built with MSVC 2008 SP1 (VC9), the game DLL's compiler, because C++ objects cross the engine
interfaces. `tools/get_toolchain.py` makes a portable copy in `toolchain/` from Microsoft's Windows SDK 7.0 ISO
(downloaded, or `--iso`), without installing anything:

```
python tools/get_toolchain.py [--iso GRMSDK_EN_DVD.iso]
python tools/build_host.py [--toolchain DIR]
```

`tools/toolchain.py` describes where the toolchain is looked for (a `--toolchain` folder, `C5H_TOOLCHAIN`, the
portable copy in `toolchain/`, or an installed Visual Studio 2008).

## Python tools

Python 3.11 or newer, standard library only. `c5h.cmd` runs them from the checkout (`python -m civ5headless` with
`python` on `PYTHONPATH`); `pip install -e .` installs a `c5h` command (pip fetches setuptools for it):

```
c5h doctor                                               # what was found and what is missing
c5h run examples/specs/continents-tiny.json --turns 30   # one game; the run folder goes to runs/
c5h compare runs/A runs/B                                # per-turn state digests of two runs
```

The game folder, the `My Games` folder, the mods and the host are discovered (Steam registry and libraries, the
Documents known folder, `out/latest.txt`), and the game database is built from the game's files and the mods.
`--mod ID[:VER]` plays any mod set in a MODS folder (the mods registry is generated from the `.modinfo` files),
`--no-mods` none.
Anything else, or anything to override, goes in `civ5headless.toml`; see
[civ5headless.example.toml](civ5headless.example.toml). `c5h -h` lists the commands; the
[user guide](docs/user-guide.md) covers them, and `civ5headless.realgame` drives the real game for references.

Tests: `python -m unittest discover -s tests`; with `C5H_INTEGRATION=1` they also run the host
on a short game and build the DLC snapshot.

## Licence

GNU General Public License v3 ([LICENSE](LICENSE)), as for the Civ V SDK sources this builds on (Community Patch
Project licence).
