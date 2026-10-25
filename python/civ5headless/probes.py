"""Lua probe files for host games (--lua-probe) and real-game sessions (RealGameSession.start_game(lua_probes=...)).

Both run the probes, in order, in the InGame context once the game has started, before turn 0 is processed, so the
same files give the same lines in Lua.log on both sides.

  fingerprint_probes(cfg, folder, every=None, turns=None, split=None) -> [Path]

is the fingerprint probe (<probes>/fingerprint.lua, plan 9.3; read with civ5headless.fingerprint) preceded, when any
setting is given, by a generated fingerprint-settings.lua in folder that sets its configuration globals:
C5HFP_EVERY (fingerprint every k-th turn; default every turn), C5HFP_TURNS (these turns too) and C5HFP_SPLIT
(sections per printed line).
"""
from __future__ import annotations
from pathlib import Path

from . import config

FINGERPRINT = 'fingerprint.lua'
SETTINGS = 'fingerprint-settings.lua'


def probes_dir(cfg, probes=None):
    """The probes folder: probes if given, else the configured one. Raises config.ConfigError."""
    return Path(probes) if probes else cfg.require('probes', 'pass the probes folder')


def fingerprint_lua(cfg, probes=None):
    """<probes>/fingerprint.lua. Raises config.ConfigError when it is missing."""
    path = probes_dir(cfg, probes) / FINGERPRINT
    if not path.is_file():
        raise config.ConfigError(f'{path} not found (probes in {config.FILE_NAME} names the folder holding {FINGERPRINT})')
    return path


def fingerprint_options(value, every=None, turns=None, split=None):
    """dict(every, turns, split) when fingerprints are wanted, else None. value: a flag, or a dict with those keys;
    every, turns (a list, or a string such as '1,50,100') and split fill what it leaves out and each implies it."""
    if isinstance(value, dict):
        unknown = set(value) - {'every', 'turns', 'split'}
        if unknown:
            raise ValueError(f'unknown fingerprint settings: {", ".join(sorted(unknown))} (every, turns, split)')
        every, turns, split = value.get('every', every), value.get('turns', turns), value.get('split', split)
    if not (value or every or turns or split):
        return None
    if isinstance(turns, str):
        turns = turns.replace(',', ' ').split()
    return dict(every=every, turns=[int(t) for t in turns or []], split=split)


def fingerprint_settings(every=None, turns=None, split=None):
    """Lua that sets the fingerprint probe's configuration globals, or '' when nothing is set."""
    lines = []
    if every is not None:
        if int(every) < 1:
            raise ValueError('fingerprint every must be at least 1')
        lines.append(f'C5HFP_EVERY = {int(every)}')
    if turns:
        lines.append('C5HFP_TURNS = {' + ', '.join(str(int(t)) for t in turns) + '}')
    if split is not None:
        if int(split) < 1:
            raise ValueError('fingerprint split must be at least 1')
        lines.append(f'C5HFP_SPLIT = {int(split)}')
    if not lines:
        return ''
    return '-- civ5headless: fingerprint probe settings (read by fingerprint.lua, which runs next)\n' + '\n'.join(lines) + '\n'


def fingerprint_probes(cfg, folder, every=None, turns=None, split=None, probes=None):
    """The files that run the fingerprint probe with these settings, in order (settings file written to folder)."""
    probe = fingerprint_lua(cfg, probes)
    text = fingerprint_settings(every, turns, split)
    if not text:
        return [probe]
    settings = Path(folder) / SETTINGS
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(text, encoding='utf-8')
    return [settings, probe]
