from __future__ import annotations

import queue
import time

import pytest
from sensors.base import Sensor, SensorConfig


class FakeSensor(Sensor):
    """Sensor that exposes raw_change for testing the debounce contract."""

    def __init__(self, config: SensorConfig) -> None:
        super().__init__("fake", config)
        self._raw = False

    def _start(self) -> None:
        pass

    def _stop(self) -> None:
        pass

    def is_engaged(self) -> bool:
        return self._raw

    def raw_change(self, engaged: bool) -> None:
        self._raw = engaged
        self._on_raw_change(engaged)


def test_chattering_switch_is_rejected() -> None:
    events: queue.Queue = queue.Queue()
    cfg = SensorConfig(engaged_when="closed", bounce_time_ms=0, min_lift_ms=100, min_replace_ms=100)
    sensor = FakeSensor(cfg)
    sensor.start(events)

    sensor.raw_change(True)
    time.sleep(0.03)  # less than dwell
    sensor.raw_change(False)

    # The brief True pulse should not have produced an event yet.
    time.sleep(0.05)
    assert events.empty()

    # Once the state has settled to idle for the full replace dwell, a replace
    # event is emitted.
    event = events.get(timeout=0.5)
    assert event[0] == "replace"
    sensor.stop()


def test_stable_lift_is_accepted() -> None:
    events: queue.Queue = queue.Queue()
    cfg = SensorConfig(engaged_when="closed", bounce_time_ms=0, min_lift_ms=50, min_replace_ms=50)
    sensor = FakeSensor(cfg)
    sensor.start(events)

    sensor.raw_change(True)
    time.sleep(0.08)

    event = events.get(timeout=0.5)
    assert event[0] == "lift"
    sensor.stop()


def test_engaged_when_closed_inverts_event() -> None:
    events: queue.Queue = queue.Queue()
    cfg = SensorConfig(engaged_when="closed", bounce_time_ms=0, min_lift_ms=50, min_replace_ms=50)
    sensor = FakeSensor(cfg)
    sensor.start(events)

    # raw is pressed; with engaged_when=closed the pressed state means "lifted"
    sensor.raw_change(True)
    time.sleep(0.08)
    event = events.get(timeout=0.5)
    assert event[0] == "lift"
    sensor.stop()
