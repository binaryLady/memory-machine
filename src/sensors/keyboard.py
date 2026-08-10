"""Keyboard sensor backend for development and laptop testing.

The main loop passes key codes from cv2.waitKey to handle_key(). This keeps
OpenCV on the main thread while still feeding the same event queue.
"""
from __future__ import annotations

import logging
import queue
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("motion-player.sensor.keyboard")


@dataclass
class KeyboardSensor:
    """No hardware required: spacebar toggles engaged/idle."""

    name: str = "keyboard"
    _engaged: bool = False
    _events: queue.Queue[Any] | None = None

    def start(self, events: queue.Queue[Any]) -> None:
        self._events = events
        LOGGER.info("Keyboard sensor active (space=toggle, q=quit, d=dump)")

    def stop(self) -> None:
        self._events = None

    def is_engaged(self) -> bool:
        return self._engaged

    def handle_key(self, key: int) -> str | None:
        """Process a cv2 key code. Returns 'quit' or 'dump' commands, if any."""
        if key == -1:
            return None
        if key == ord(" "):
            self._engaged = not self._engaged
            event = "lift" if self._engaged else "replace"
            LOGGER.info(
                "transition sensor=%s event=%s raw=%s engaged_when=open accepted=true",
                self.name,
                event,
                "engaged" if self._engaged else "idle",
            )
            if self._events is not None:
                self._events.put((event, time.monotonic(), self.name))
        elif key == ord("q"):
            return "quit"
        elif key == ord("d"):
            return "dump"
        return None
