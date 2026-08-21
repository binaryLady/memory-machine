"""Sensor factory, fusion, and graceful fallback to keyboard."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from .base import Sensor, SensorConfig
from .digital import DigitalSensor
from .keyboard import KeyboardSensor
from .null import NullSensor

LOGGER = logging.getLogger("motion-player.sensor")


def _make_single(sensor_type: str, config: Any, gamepad: Any = None) -> Sensor:
    if sensor_type in {"switch", "reed", "beam", "reflective", "hall", "pir", "gpio_raw"}:
        return DigitalSensor(sensor_type, config)
    if sensor_type == "distance":
        from .distance import DistanceSensor  # type: ignore[misc]

        return DistanceSensor(config)
    if sensor_type == "capacitive":
        from .capacitive import CapacitiveSensor  # type: ignore[misc]

        return CapacitiveSensor(config)
    if sensor_type == "gamepad":
        from .gamepad import GamepadSensor  # type: ignore[misc]

        return GamepadSensor(config, gamepad)
    if sensor_type == "mmwave":
        from .mmwave import MmwaveSensor  # type: ignore[misc]

        return MmwaveSensor(config)
    if sensor_type == "keyboard":
        return KeyboardSensor()
    if sensor_type == "none":
        return NullSensor()
    raise ValueError(f"unknown sensor_type: {sensor_type}")


class FusedSensor(Sensor):
    """Combines multiple sensor backends according to sensor_combine.

    Members debounce independently and publish onto a private queue. This class
    re-evaluates the combined state on every member event and forwards a single
    lift/replace only when that combined state actually flips, so "all" really
    does require every member.
    """

    def __init__(self, members: list[Sensor], combine: str, engaged_when: str) -> None:
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
        self._member_events: queue.Queue[Any] = queue.Queue()
        self._pump_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lifted = False

    def start(self, events: queue.Queue[Any]) -> None:
        self._events = events
        started: list[Sensor] = []
        for member in self._members:
            try:
                member.start(self._member_events)
                started.append(member)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error(
                    "Sensor backend %s failed to start: %s; continuing without it",
                    member.name,
                    exc,
                )
        if not started:
            raise RuntimeError(f"no backend of {self._name} could start")
        self._members = started
        self._lifted = self.is_lifted()
        self._stop_event.clear()
        self._pump_thread = threading.Thread(target=self._pump_loop, daemon=True)
        self._pump_thread.start()

    def _start(self) -> None:
        pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=1.0)
            self._pump_thread = None
        for member in self._members:
            member.stop()

    def _stop(self) -> None:
        pass

    def _pump_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                _event, timestamp, source = self._member_events.get(timeout=0.1)
            except queue.Empty:
                continue

            lifted = self.is_lifted()
            if lifted == self._lifted:
                LOGGER.info(
                    "transition sensor=%s source=%s combine=%s accepted=false reason=combined_state_unchanged",
                    self._name,
                    source,
                    self._combine,
                )
                continue

            self._lifted = lifted
            event = "lift" if lifted else "replace"
            LOGGER.info(
                "transition sensor=%s event=%s source=%s combine=%s accepted=true ts=%.3f",
                self._name,
                event,
                source,
                self._combine,
                timestamp,
            )
            if self._events is not None:
                self._events.put((event, timestamp, self._name))

    def is_engaged(self) -> bool:
        states = [m.is_engaged() for m in self._members]
        if self._combine == "all":
            return all(states)
        return any(states)

    def is_lifted(self) -> bool:
        states = [m.is_lifted() for m in self._members]
        if self._combine == "all":
            return all(states)
        return any(states)


def make_sensor(config: Any, gamepad: Any = None) -> Sensor:
    """Create the configured sensor backend, falling back to keyboard on failure.

    gamepad carries what each control on a pad does; without it a pad still
    holds on any button, which is all a fused member needs to be useful.
    """
    raw_types = [t.strip() for t in config.sensor_type.split("+")]

    # Special-case the backends that need no hardware, so they always work.
    if raw_types == ["keyboard"]:
        return KeyboardSensor()
    if raw_types == ["none"]:
        return NullSensor()

    members: list[Sensor] = []
    for sensor_type in raw_types:
        try:
            sensor = _make_single(sensor_type, config, gamepad)
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


def start_sensor(sensor: Sensor, events: queue.Queue[Any]) -> Sensor:
    """Start a sensor, degrading to the keyboard backend if the hardware fails.

    Digital backends only touch gpiozero in _start(), so a missing pin factory
    or a permissions problem surfaces here rather than at construction, well
    past make_sensor's fallback. Losing the sensor should leave the piece idling
    and triggerable by hand, not take the installation down.
    """
    try:
        sensor.start(events)
        return sensor
    except Exception as exc:  # noqa: BLE001
        LOGGER.error(
            "Sensor %s could not start: %s. Falling back to the keyboard backend; "
            "the piece will idle until a key is pressed.",
            sensor.name,
            exc,
        )

    fallback = KeyboardSensor()
    fallback.start(events)
    return fallback
