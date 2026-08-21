"""Captain's log: one small local file per day recording every interaction.

Telemetry speaks to the network and may be silenced by it; this journal
speaks only to the SD card, so the record of who lifted, who stayed, and
when she slept survives any outage. One JSON line per event, one file per
gallery day, small enough to keep for the whole show — the raw material for
a visualization of a month of presence.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("motion-player.journal")


def journal_line(event: str, timestamp: str, **fields: Any) -> str:
    """One event as a JSON line — stable keys first, extras after."""
    record: dict[str, Any] = {"t": timestamp, "event": event}
    record.update(fields)
    return json.dumps(record, separators=(",", ":"))


def day_name(clock: Callable[[], time.struct_time]) -> str:
    """The journal file's stem: the local date, one file per gallery day."""
    return time.strftime("%Y-%m-%d", clock())


class Journal:
    """Appends interaction events to the day's log. Never raises.

    A failed write is a logged warning and a lost line, not a stopped show —
    the journal is a witness, not a dependency.
    """

    def __init__(self, directory: Path, clock: Callable[[], time.struct_time] | None = None) -> None:
        self._directory = directory
        self._clock = clock or time.localtime
        self._warned = False

    def record(self, event: str, **fields: Any) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", self._clock())
        line = journal_line(event, timestamp, **fields)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._directory / f"{day_name(self._clock)}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            if not self._warned:
                LOGGER.warning("Captain's log cannot write to %s: %s", self._directory, exc)
                self._warned = True
