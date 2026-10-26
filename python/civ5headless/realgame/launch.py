"""Start the real game with its tuner port open, and an optional CPU-temperature guard.

launch_game(game_dir) starts CivilizationV_DX11.exe -DX11 directly (Steam must be running and signed in). Like a
Steam SDK development launch it puts steam_appid.txt (8930) into the game folder first, when there is none, and takes
it out again once the tuner port is open: without it the Steam API restarts the game through Steam (the DX9
default). It waits until the game's own process listens on the tuner port (127.0.0.1:4318) and returns a Game.

CpuGuard watches the CPU temperature from Core Temp's shared memory (CoreTempMappingObjectEx, read only; nothing to
install or configure) and ends the game it was given (by its process handle) when the hottest core stays at or above
the limit for `sustained` samples in a row. Without Core Temp running it only records that no reading is available.
Its events go to <run>/cpu-temperature.jsonl.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
import time

from .. import winproc

APP_ID = '8930'
EXE_NAMES = ('CivilizationV_DX11.exe', 'CivilizationV.exe', 'CivilizationV_Tablet.exe')
TUNER_PORT = 4318


class LaunchError(RuntimeError):
    pass


@dataclass
class Game:
    popen: subprocess.Popen
    pid: int
    exe: str
    port: int
    seconds: float                        # launch to tuner port open
    started: float = field(default_factory=time.monotonic)

    def alive(self):
        return self.popen.poll() is None


def running_games():
    """Process ids of running game executables (any of EXE_NAMES)."""
    return sorted(winproc.pids('CivilizationV'))


class steam_appid:
    """Context manager: steam_appid.txt with the game's app id in the game folder while launching (only when absent;
    an existing file with another id is an error and left alone)."""

    def __init__(self, game_dir):
        self.path = Path(game_dir) / 'steam_appid.txt'
        self.created = False

    def __enter__(self):
        if self.path.exists():
            if self.path.read_text(encoding='ascii', errors='replace').strip() != APP_ID:
                raise LaunchError(f'{self.path} holds another app id; it was left untouched')
        else:
            self.path.write_text(APP_ID, encoding='ascii')
            self.created = True
        return self

    def __exit__(self, *exc):
        if self.created:
            self.path.unlink(missing_ok=True)


def wait_for_port(popen, port, timeout):
    """Wait until popen's process listens on port; LaunchError when it exits first or the time runs out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if popen.poll() is not None:
            raise LaunchError(f'the game exited (code {popen.returncode}) before its tuner port opened')
        if popen.pid in winproc.listening_pids(port):
            return
        time.sleep(0.5)
    raise LaunchError(f'the tuner port {port} did not open within {timeout} s (game pid {popen.pid} left running; '
                      'is EnableTuner = 1 in config.ini?)')


def launch_game(game_dir, exe_name=EXE_NAMES[0], args=('-DX11',), port=TUNER_PORT, timeout=180, check_steam=True):
    game_dir = Path(game_dir)
    exe = game_dir / exe_name
    if not exe.is_file():
        raise LaunchError(f'{exe} not found')
    if running_games():
        raise LaunchError('the game is already running')
    if check_steam and not winproc.pids('steam.exe'):
        raise LaunchError('start Steam and sign in first')
    t = time.monotonic()
    with steam_appid(game_dir):
        # The game writes noise to its console ("number - table" per tuner call): never into the caller's streams.
        popen = subprocess.Popen([str(exe), *args], cwd=str(game_dir), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            wait_for_port(popen, port, timeout)
        except LaunchError:
            if popen.poll() is None and time.monotonic() - t < 5:
                popen.kill()
            raise
    return Game(popen=popen, pid=popen.pid, exe=str(exe), port=port, seconds=round(time.monotonic() - t, 2), started=t)


# ---- CPU temperature guard ----

CORE_TEMP_MAPPING = 'CoreTempMappingObjectEx'
CORE_TEMP_BYTES = 2686  # the documented version-2 layout ends with the Fahrenheit and delta flags at 2684/2685


def parse_core_temp(buf):
    """Core Temp's shared memory (https://www.alcpu.com/CoreTemp/developers.html) to a sample dict."""
    cores, cpus = struct.unpack_from('<II', buf, 1536)
    if cores < 1 or cpus < 1 or cores * cpus > 256:
        raise ValueError('invalid sensor counts')
    fahrenheit, delta = buf[2684] != 0, buf[2685] != 0
    temps = []
    for i in range(cores * cpus):
        tj = struct.unpack_from('<I', buf, 1024 + 4 * (i // cores))[0]
        if not 40 <= tj <= 125:
            raise ValueError('unsupported or invalid TjMax')
        value = struct.unpack_from('<f', buf, 1544 + 4 * i)[0]
        if fahrenheit:
            value = value * 5 / 9 if delta else (value - 32) * 5 / 9
        if delta:
            value = tj - value
        if math.isnan(value) or math.isinf(value) or not -20 <= value <= 125:
            raise ValueError('invalid sensor temperature')
        temps.append(round(value, 1))
    return dict(maximumC=max(temps), minimumC=min(temps), coreTemperaturesC=temps, coreCount=cores, cpuCount=cpus)


def read_core_temp():
    """A sample from the running Core Temp, or ValueError when there is none."""
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenFileMappingW.restype = wintypes.HANDLE
    kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenFileMappingW(0x0004, False, CORE_TEMP_MAPPING)  # FILE_MAP_READ
    if not handle:
        raise ValueError('Core Temp is not running (no shared memory)')
    try:
        view = kernel32.MapViewOfFile(handle, 0x0004, 0, 0, CORE_TEMP_BYTES)
        if not view:
            raise ValueError('cannot map Core Temp shared memory')
        try:
            return parse_core_temp(ctypes.string_at(view, CORE_TEMP_BYTES))
        finally:
            kernel32.UnmapViewOfFile(view)
    finally:
        kernel32.CloseHandle(handle)


class CpuGuard:
    """A thread that ends the game when the CPU stays too hot. stop() disarms it."""

    def __init__(self, game, log_path, limit=95, sustained=3, sample_seconds=15, reader=read_core_temp):
        self.game, self.log_path = game, Path(log_path)
        self.limit, self.sustained, self.sample_seconds, self.reader = limit, sustained, sample_seconds, reader
        self.stopped = threading.Event()
        self.tripped = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def event(self, kind, **values):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(event=kind, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **values)) + '\n')

    def start(self):
        self.event('armed', pid=self.game.pid, limitC=self.limit, sustainedSamples=self.sustained, sampleSeconds=self.sample_seconds)
        self.thread.start()
        return self

    def stop(self, reason='stopped'):
        if not self.stopped.is_set():
            self.stopped.set()
            if self.thread.is_alive() and self.thread is not threading.current_thread():
                self.thread.join(5)
            self.event('disarmed', reason=reason)

    def _run(self):
        hot, unavailable = 0, False
        while not self.stopped.is_set():
            if not self.game.alive():
                return
            try:
                sample = self.reader()
                unavailable = False
            except (ValueError, OSError) as error:
                hot = 0
                if not unavailable:  # once per outage
                    self.event('temperature_unavailable', detail=str(error))
                unavailable = True
                sample = None
            if sample is not None:
                hot = hot + 1 if sample['maximumC'] >= self.limit else 0
                self.event('sample', hotSamples=hot, **sample)
                if hot >= self.sustained:
                    self.tripped = True
                    try:
                        self.game.popen.kill()
                        self.event('stopped', reason='sustained CPU temperature', maximumC=sample['maximumC'])
                    except OSError as error:
                        self.event('stop_failed', detail=str(error))
                    return
            self.stopped.wait(self.sample_seconds)
