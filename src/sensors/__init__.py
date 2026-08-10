"""Sensor factory, fusion, and graceful fallback to keyboard."""
from __future__ import annotations

import logging
import queue
from typing import Any

from .base import Sensor, SensorConfig
from .digital import DigitalSensor
from .keyboard import KeyboardSensor

LOGGER = logging.getLogger("motion-player.sensor")


def _make_single(sensor_type: str, config: Any) -> Sensor:
    if sensor_type in {"switch", "reed", "beam", "reflective", "hall", "pir", "gpio_raw"}:
        return DigitalSensor(sensor_type, config)
    if sensor_type == "distance":
        from .distance import DistanceSensor  # type: ignore[misc]

        return DistanceSensor(config)
    if sensor_type == "capacitive":
        from .capacitive import CapacitiveSensor  # type: ignore[misc]

        return CapacitiveSensor(config)
    if sensor_type == "mmwave":
        from .mmwave import MmwaveSensor  # type: ignore[misc]

        return MmwaveSensor(config)
    if sensor_type == "keyboard":
        return KeyboardSensor()
    raise ValueError(f"unknown sensor_type: {sensor_type}")


class FusedSensor(Sensor):
    """Combines multiple sensor backends according to sensor_combine."""

    def __init__(self, members: list[Sensor], combine: str, engaged_when: str) -> None:
        # The base class is used only for name/contract; individual members
        # own their own queues. This class aggregates instantaneous reads.
        super().__init__(
            "+".join(m.name for m in members),
            SensorConfig(
                engaged_when=engaged_when,
                bounce_time_ms=0,
                min_lift_ms=0,
                min_replace_ms=0,
            ),
        )
        self._members = members
        self._combine = combine
        self._events: queue.Queue[Any] | None = None
        self._engaged = False

    def start(self, events: queue.Queue[Any]) -> None:
        self._events = events
        for member in self._members:
            member.start(events)

    def _start(self) -> None:
        pass

    def stop(self) -> None:
        for member in self._members:
            member.stop()

    def _stop(self) -> None:
        pass

    def is_engaged(self) -> bool:
        states = [m.is_engaged() for m in self._members]
        if self._combine == "all":
            return all(states)
        return any(states)


def make_sensor(config: Any) -> Sensor:
    """Create the configured sensor backend, falling back to keyboard on failure."""
    raw_types = [t.strip() for t in config.sensor_type.split("+")]

    # Special-case the keyboard-only path so it is always available.
    if raw_types == ["keyboard"]:
        return KeyboardSensor()

    members: list[Sensor] = []
    for sensor_type in raw_types:
        try:
            sensor = _make_single(sensor_type, config)
            members.append(sensor)
            LOGGER.info("Sensor backend initialised: %s", sensor.name)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Failed to initialise sensor backend %r: %s. Continuing to load remaining members.",
                sensor_type,
                exc,
            )

    if not members:
        LOGGER.error("All configured sensor backends failed; falling back to keyboard")
        return KeyboardSensor()

    if len(members) == 1:
        return members[0]

    return FusedSensor(members, config.sensor_combine, config.engaged_when)
