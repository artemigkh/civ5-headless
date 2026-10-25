"""What this installation can do, detected at run time: missing pieces become "not available" checks, not crashes.

- host options: parsed from civ5headless.exe's usage text (--lua-probe, --frame-skew, --heap-perturb, ...);
- civ5headless.fingerprint: read() for the C5HFP sections and C5HM metrics; its probe (civ5headless.probes);
- civ5headless.realgame.session.RealGameSession: the real-game session;
- civ5headless.hazards: the UI hazard scan.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import importlib
import re
import subprocess

from .. import config, winproc


@dataclass
class Capabilities:
    host_options: set = field(default_factory=set)
    host_usage_error: str | None = None
    fingerprint: object = None
    fingerprint_probe: object = None
    session_class: object = None
    hazards: object = None
    notes: dict = field(default_factory=dict)   # capability -> why it is not available

    @property
    def lua_probe(self):
        return '--lua-probe' in self.host_options

    def has(self, option):
        return option in self.host_options

    def to_dict(self):
        return dict(hostOptions=sorted(self.host_options), luaProbe=self.lua_probe,
                    fingerprint=self.fingerprint is not None,
                    fingerprintProbe=str(self.fingerprint_probe) if self.fingerprint_probe else None,
                    realGameSession=self.session_class is not None, hazards=self.hazards is not None,
                    notes=dict(self.notes))


def host_options(exe, timeout=30):
    """(the --options in the host's usage text, error or None)."""
    try:
        r = subprocess.run([str(exe), '--help'], capture_output=True, text=True, errors='replace', timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=getattr(winproc, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        return set(), f'cannot run {exe}: {error}'
    return set(re.findall(r'(?<![\w-])(--[a-z][a-z0-9-]+)', r.stdout + r.stderr)), None


def _module(name, attribute=None):
    try:
        mod = importlib.import_module(name)
    except ImportError as error:
        return None, f'{name} is not installed ({error})'
    if attribute and not hasattr(mod, attribute):
        return None, f'{name} has no {attribute}'
    return mod, None


def fingerprint_probe(cfg, fingerprint):
    """(the fingerprint probe both sides run, why not): the configured probes folder's fingerprint.lua
    (civ5headless.probes, which run.play and RealGameSession.start_game use), else fingerprint.probe_path()."""
    try:
        from .. import probes
        return probes.fingerprint_lua(cfg or config.load()), None
    except (ImportError, config.ConfigError) as error:
        first = str(error)
    try:
        return fingerprint.probe_path(), None
    except (AttributeError, FileNotFoundError) as error:
        return None, f'no fingerprint probe: {first}; {error}'


def detect(exe, cfg=None, overrides=None):
    """Capabilities of this installation. overrides: {name: value} that replaces a detection (tests, fakes):
    host_options, fingerprint, session_class, hazards."""
    overrides = overrides or {}
    cap = Capabilities()
    if 'host_options' in overrides:
        cap.host_options = set(overrides['host_options'])
    elif exe:
        cap.host_options, cap.host_usage_error = host_options(exe)
        if cap.host_usage_error:
            cap.notes['host'] = cap.host_usage_error
    if not cap.lua_probe:
        cap.notes['luaProbe'] = 'the host has no --lua-probe option (an older civ5headless.exe)'
    if 'fingerprint' in overrides:
        cap.fingerprint = overrides['fingerprint']
    else:
        cap.fingerprint, why = _module('civ5headless.fingerprint', 'read')
        if why:
            cap.notes['fingerprint'] = why
    if 'fingerprint_probe' in overrides:
        cap.fingerprint_probe = overrides['fingerprint_probe']
    elif cap.fingerprint is not None:
        cap.fingerprint_probe, why = fingerprint_probe(cfg, cap.fingerprint)
        if why:
            cap.notes['fingerprintProbe'] = why
    if 'session_class' in overrides:
        cap.session_class = overrides['session_class']
    else:
        mod, why = _module('civ5headless.realgame.session', 'RealGameSession')
        cap.session_class = getattr(mod, 'RealGameSession', None) if mod else None
        if why:
            cap.notes['realGameSession'] = why
    if 'hazards' in overrides:
        cap.hazards = overrides['hazards']
    else:
        cap.hazards, why = _module('civ5headless.hazards')
        if why:
            cap.notes['hazards'] = why
    return cap
