"""City-state pins: the real game's city-states, handed to the host games compared with it.

A DLL that leaves the choice of random civilizations and city-states to the game's exe (the stock DLL) gets them
from the host instead, which cannot draw what the exe drew. The suite names every major civilization in the specs;
the real game's front end cannot be told which city-states to use, so the suite reads them from the real game's
turn-0 fingerprint (the probe's `player` lines, `minor=MINOR_CIV_X` per slot) and gives them to the host games that
are compared with that real game as the spec's `minorCivs` (types in slot order, slot MAX_MAJOR_CIVS + index). A DLL
that chooses by itself (Vox Populi) keeps its choice; the host's report then says whether it matches the pins.

The real side publishes each game's pins as soon as that game has started (or that there are none); the host side
waits for them before it starts a pinned game.
"""
from __future__ import annotations
import threading
import time


class Pins:
    """{real game name: pins} shared by the real side (publish, close) and the host side (wait)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.values = {}
        self.closed = None

    def publish(self, game, minor_civs=None, reason=None, **info):
        """The pins of one real game: minor_civs (types in slot order) or None with the reason."""
        with self.cond:
            if game not in self.values:
                self.values[game] = dict(info, minorCivs=list(minor_civs) if minor_civs else None, reason=reason,
                                         published=time.monotonic())
            self.cond.notify_all()

    def close(self, reason):
        """No more pins: every game still waited for gets none, with this reason."""
        with self.cond:
            self.closed = reason
            self.cond.notify_all()

    def get(self, game):
        with self.cond:
            return self.values.get(game)

    def wait(self, game, timeout):
        """The pins of game (a dict with minorCivs, None when there are none, and the reason), waiting at most
        timeout seconds."""
        end = time.monotonic() + max(0.0, timeout)
        with self.cond:
            while game not in self.values and self.closed is None:
                left = end - time.monotonic()
                if left <= 0:
                    return dict(minorCivs=None, reason='the real game did not start it in time')
                self.cond.wait(min(left, 1.0))
            if game in self.values:
                return dict(self.values[game])
            return dict(minorCivs=None, reason=self.closed)


def from_fingerprint(fp):
    """(minor civ types in slot order from MAX_MAJOR_CIVS, info) from a fingerprint's turn-0 player lines."""
    meta = getattr(fp, 'meta', None) or {}
    try:
        first = int(meta.get('maxMajors'))
    except (TypeError, ValueError):
        first = 22
    minors = {}
    for player, fields in (getattr(fp, 'players', None) or {}).items():
        if (fields or {}).get('minor'):
            minors[int(player)] = fields['minor']
    types, slot = [], first
    while slot in minors:
        types.append(minors[slot])
        slot += 1
    info = dict(maxMajors=first, slots={str(k): v for k, v in sorted(minors.items())})
    rest = sorted(s for s in minors if s >= slot or s < first)
    if rest:
        info['note'] = (f'city-state slots not contiguous from {first}: pinned the first {len(types)}, not slots '
                        + ', '.join(map(str, rest)))
    return types, info
