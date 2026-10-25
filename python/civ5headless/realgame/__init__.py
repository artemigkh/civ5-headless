"""Real-game automation through FireTuner (plan 9.4).

tuner.py      FireTuner client (and a persistent service for manual use); tuner_result.lua returns Lua values as JSON
launch.py     starts the game with its tuner port open; optional CPU-temperature guard (Core Temp)
mods.py       makes the enabled mods exactly a given set and activates them
seeds.py      pins the seeds through config.ini, and puts the file back
session.py    RealGameSession: launch, set_mods, start_game, autoplay, to_main_menu, collect_logs, process_stats, quit
probe.py      Lua probes in the real game, optionally in a game from a spec (references for the host)
record.py     records a matrix of references, one probe run per case
dbcapture.py  copies the game's databases (DLC snapshot, modded) and checks them against the game's memory

All of it is tested against a fake game behind a fake tuner (tests/platform_tests/test_realgame.py); docs/user-guide.md
says what has not yet run against the real game.
"""
