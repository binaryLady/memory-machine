"""Sensor base class and debounce contract."""
from __future__ import annotations

import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("motion-player.transitions")


@dataclass(frozen=True)
class SensorConfig:
    """Subset of config.SensorConfig needed by sensor backends."""

    engaged_when: str = "open"
    bounce_time_ms: int = 50
    min_lift_ms: int = 250
    min_replace_ms: int = 250


class Sensor(ABC):
    """Interface for all sensor backends.

    Backends must push ("lift" | "replace", monotonic_ts, sensor_name) tuples
    onto the supplied queue for accepted state changes. Raw edges are logged
    whether accepted or not.
    """

    def __init__(self, name: str, config: SensorConfig) -> None:
        self._name = name
        self._config = config
        self._events: queue.Queue[Any] | None = None
        self._timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()
        self._last_intended_raw: bool | None = None

    @property
    def name(self) -> str:
        return self._name

    def start(self, events: queue.Queue[Any]) -> None:
        self._events = events
        self._start()

    @abstractmethod
    def _start(self) -> None:
        ...

    def stop(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._stop()

    @abstractmethod
    def _stop(self) -> None:
        ...

    @abstractmethod
    def is_engaged(self) -> bool:
        """Return the instantaneous raw hardware state (not debounced)."""
        ...

    def _on_raw_change(self, engaged: bool, timestamp: float | None = None) -> None:
        """To be called by backends whenever the raw state changes.

        The debounce contract runs here, shared by every backend.
        """
        if timestamp is None:
            timestamp = time.monotonic()

        raw_label = "engaged" if engaged else "idle"
        LOGGER.debug("raw_change sensor=%s raw=%s", self._name, raw_label)

        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            # Wait for the configured dwell before accepting the change.
            self._last_intended_raw = engaged
            dwell_ms = self._config.min_lift_ms if engaged else self._config.min_replace_ms
            self._timer = threading.Timer(dwell_ms / 1000.0, self._on_dwell_expired, [timestamp])
            self._timer.daemon = True
            self._timer.start()

    def _on_dwell_expired(self, timestamp: float) -> None:
        """Check whether the raw state persisted; emit or reject accordingly."""
        with self._timer_lock:
            self._timer = None

        current = self.is_engaged()
        if current != self._last_intended_raw:
            LOGGER.info(
                "transition sensor=%s intended_raw=%s now_raw=%s accepted=false reason=dwell_expired_state_changed ts=%.3f",
                self._name,
                "engaged" if self._last_intended_raw else "idle",
                "engaged" if current else "idle",
                timestamp,
            )
            return

        self._emit(current, timestamp)

    def _emit(self, raw_engaged: bool, timestamp: float) -> None:
        """Emit the debounced event."""
        # Map raw state to the semantic "engaged" state using engaged_when.
        engaged = raw_engaged if self._config.engaged_when == "closed" else not raw_engaged
        event = "lift" if engaged else "replace"

        LOGGER.info(
            "transition sensor=%s event=%s raw=%s engaged_when=%s accepted=true ts=%.3f",
            self._name,
            event,
            "engaged" if raw_engaged else "idle",
            self._config.engaged_when,
            timestamp,
        )

        if self._events is not None:
            self._events.put((event, timestamp, self._name))
