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
| `python/civ5headless/` | Game specs, database cache, runners, comparison tools |
| `tools/` | Host build (`build_host.py`, `toolchain.py`), interface stub generator, PE import lister |
| `probes/` | Lua probes for the real game and the host |
| `examples/` | Game specs and queues |
| `docs/` | User guide, engine contract, database builder, DLL additions, plan, history |

## Building

The host must be built with MSVC 2008 SP1 (VC9), the game DLL's compiler, because C++ objects cross the engine
interfaces:

```
python tools/build_host.py [--toolchain DIR]
```

`tools/toolchain.py` describes where the toolchain is looked for (a `--toolchain` folder, `C5H_TOOLCHAIN`, a portable
copy in `toolchain/`, or an installed Visual Studio 2008).

## Licence

GNU General Public License v3 ([LICENSE](LICENSE)), as for the Civ V SDK sources this builds on (Community Patch
Project licence).
