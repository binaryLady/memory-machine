"""Overnight sleep schedule: decide when the piece rests and when it wakes.

The gallery runs east-coast hours, so the piece can sleep between closing and
opening rather than looping to an empty room all night. The scheduler only
answers "is it night?"; the main loop applies the consequences.
"""
from __future__ import annotations

import logging
import time
from typing import Any

LOGGER = logging.getLogger("motion-player.schedule")

# How often the wall clock is consulted. The main loop runs near 1 kHz; once a
# second is ample for a minute-granular schedule.
_POLL_INTERVAL_S = 1.0


def parse_hhmm(value: str) -> int | None:
    """Minutes since midnight for "HH:MM", or None for anything else."""
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def is_asleep_minute(minute: int, start_min: int, end_min: int) -> bool:
    """Whether `minute` falls in the sleep window.

    start == end means no window at all; start > end is a window spanning
    midnight, e.g. 23:00-08:00.
    """
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= minute < end_min
    return minute >= start_min or minute < end_min


class SleepScheduler:
    """Reports sleep/wake flips, statelessly recomputed from the wall clock.

    A clock jump (NTP catching up after boot) is handled by construction: every
    poll derives asleep-ness afresh and only the change is reported, so the
    piece lands in the right state on the next poll no matter how the clock
    moved.
    """

    def __init__(self, config: Any) -> None:
        self._enabled = bool(config.enabled)
        self._start = parse_hhmm(config.sleep_start)
        self._end = parse_hhmm(config.sleep_end)
        if self._enabled and (self._start is None or self._end is None):
            LOGGER.error(
                "Sleep schedule disabled: could not parse %r-%r as HH:MM",
                config.sleep_start,
                config.sleep_end,
            )
            self._enabled = False
        self._asleep = False
        self._next_poll = 0.0
        if self._enabled:
            LOGGER.info(
                "Sleep schedule active: %s to %s", config.sleep_start, config.sleep_end
            )

    @property
    def asleep(self) -> bool:
        return self._asleep

    def poll(self, now_monotonic: float, minute_of_day: int | None = None) -> str | None:
        """Return "sleep" or "wake" when the state flips, else None.

        minute_of_day is injectable for tests; live callers leave it None and
        the local wall clock is read, at most once per second.
        """
        if not self._enabled:
            return None
        if now_monotonic < self._next_poll:
            return None
        self._next_poll = now_monotonic + _POLL_INTERVAL_S

        if minute_of_day is None:
            local = time.localtime()
            minute_of_day = local.tm_hour * 60 + local.tm_min

        assert self._start is not None and self._end is not None
        asleep = is_asleep_minute(minute_of_day, self._start, self._end)
        if asleep == self._asleep:
            return None
        self._asleep = asleep
        return "sleep" if asleep else "wake"
