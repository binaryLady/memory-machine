"""Null sensor: an installation with no sensor fitted."""
from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("motion-player.sensor.none")


@dataclass
class NullSensor:
    """Never engages. The piece loops forward instead of waiting for a lift."""

    name: str = "none"

    def start(self, events: queue.Queue[Any]) -> None:
        LOGGER.info("No sensor configured; the piece will loop forward")

    def stop(self) -> None:
        pass

    def is_engaged(self) -> bool:
        return False

    def is_lifted(self) -> bool:
        return False
