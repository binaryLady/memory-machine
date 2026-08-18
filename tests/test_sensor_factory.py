from __future__ import annotations

import queue
import time
from dataclasses import dataclass

import pytest
from sensors import FusedSensor, KeyboardSensor, make_sensor
from sensors.base import Sensor, SensorConfig


@dataclass(frozen=True)
class FakeSensorConfig:
    sensor_type: str
    sensor_combine: str = "any"
    engaged_when: str = "open"
    gpio_pin: int = 4
    pull_up: bool = True
    trigger_pin: int = 23
    echo_pin: int = 24
    threshold_cm: float = 15.0
    i2c_address: int | None = None
    touch_channel: int = 0
    bounce_time_ms: int = 50
    min_lift_ms: int = 250
    min_replace_ms: int = 250
    max_engaged_minutes: int = 30


def test_keyboard_backend_is_returned_by_default() -> None:
    cfg = FakeSensorConfig(sensor_type="keyboard")
    sensor = make_sensor(cfg)
    assert isinstance(sensor, KeyboardSensor)


def test_unknown_hardware_falls_back_to_keyboard() -> None:
    # distance needs real hardware; on a laptop it should degrade gracefully.
    cfg = FakeSensorConfig(sensor_type="distance")
    sensor = make_sensor(cfg)
    assert isinstance(sensor, KeyboardSensor)


def test_fused_any_returns_combined_sensor() -> None:
    cfg = FakeSensorConfig(sensor_type="keyboard+keyboard", sensor_combine="any")
    sensor = make_sensor(cfg)
    assert isinstance(sensor, FusedSensor)
    assert "+" in sensor.name


def test_fused_all_returns_combined_sensor() -> None:
    cfg = FakeSensorConfig(sensor_type="keyboard+keyboard", sensor_combine="all")
    sensor = make_sensor(cfg)
    assert isinstance(sensor, FusedSensor)


class FakeMember(Sensor):
    """Member sensor whose raw state can be driven directly from a test."""

    def __init__(self, name: str, engaged_when: str = "closed") -> None:
        super().__init__(name, SensorConfig(
            engaged_when=engaged_when, bounce_time_ms=0, min_lift_ms=1, min_replace_ms=1
        ))
        self._raw = False

    def _start(self) -> None:
        pass

    def _stop(self) -> None:
        pass

    def is_engaged(self) -> bool:
        return self._raw

    def raw_change(self, raw: bool) -> None:
        self._raw = raw
        self._on_raw_change(raw)


def drain(events: queue.Queue, timeout: float = 0.4) -> list:
    deadline = time.monotonic() + timeout
    collected = []
    while time.monotonic() < deadline:
        try:
            collected.append(events.get(timeout=0.05))
        except queue.Empty:
            continue
    return collected


def test_combine_all_ignores_a_single_member_lift() -> None:
    a, b = FakeMember("a"), FakeMember("b")
    fused = FusedSensor([a, b], combine="all", engaged_when="closed")
    events: queue.Queue = queue.Queue()
    fused.start(events)

    a.raw_change(True)

    assert drain(events) == []
    fused.stop()


def test_combine_all_lifts_once_every_member_agrees() -> None:
    a, b = FakeMember("a"), FakeMember("b")
    fused = FusedSensor([a, b], combine="all", engaged_when="closed")
    events: queue.Queue = queue.Queue()
    fused.start(events)

    a.raw_change(True)
    b.raw_change(True)

    got = drain(events)
    assert [e[0] for e in got] == ["lift"]
    fused.stop()


def test_combine_any_lifts_on_the_first_member() -> None:
    a, b = FakeMember("a"), FakeMember("b")
    fused = FusedSensor([a, b], combine="any", engaged_when="closed")
    events: queue.Queue = queue.Queue()
    fused.start(events)

    a.raw_change(True)
    b.raw_change(True)  # already lifted; must not emit a second lift

    got = drain(events)
    assert [e[0] for e in got] == ["lift"]
    fused.stop()


def test_keyboard_sensor_no_longer_owns_quitting() -> None:
    """The main loop quits for every backend, so the sensor must not claim it."""
    sensor = KeyboardSensor()

    assert sensor.handle_key(ord("q")) is None
    assert sensor.handle_key(ord("d")) == "dump"


def test_spacebar_toggles_engagement() -> None:
    import queue

    sensor = KeyboardSensor()
    events: queue.Queue = queue.Queue()
    sensor.start(events)

    sensor.handle_key(ord(" "))
    assert sensor.is_engaged()
    assert events.get_nowait()[0] == "lift"

    sensor.handle_key(ord(" "))
    assert not sensor.is_engaged()
    assert events.get_nowait()[0] == "replace"


def test_a_second_instance_exits_with_a_distinct_status(tmp_path) -> None:
    """Exiting 0 made a lock collision look like a clean run to systemd."""
    import fcntl
    import os

    import motion_test

    held = os.open(str(tmp_path / "instance.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit) as exc:
            motion_test._acquire_lock(tmp_path)
        assert exc.value.code == 3
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)


class ExplodingSensor(Sensor):
    """A backend that constructs fine and only fails when started."""

    def __init__(self) -> None:
        super().__init__("exploding", SensorConfig(engaged_when="open"))

    def _start(self) -> None:
        raise RuntimeError("Unable to load any default pin factory!")

    def _stop(self) -> None:
        pass

    def is_engaged(self) -> bool:
        return False


def test_a_sensor_that_fails_to_start_degrades_to_keyboard() -> None:
    """gpiozero only fails in _start(), well past make_sensor's fallback."""
    from sensors import start_sensor

    events: queue.Queue = queue.Queue()

    started = start_sensor(ExplodingSensor(), events)

    assert isinstance(started, KeyboardSensor)
    started.handle_key(ord(" "))
    assert started.is_engaged(), "the fallback must be started, not merely returned"


def test_a_working_sensor_is_returned_unchanged() -> None:
    from sensors import start_sensor

    events: queue.Queue = queue.Queue()
    sensor = KeyboardSensor()

    assert start_sensor(sensor, events) is sensor


def test_fused_sensor_drops_members_that_cannot_start() -> None:
    events: queue.Queue = queue.Queue()
    working = KeyboardSensor()
    fused = FusedSensor([ExplodingSensor(), working], "any", "open")

    fused.start(events)

    assert fused._members == [working]


def test_fused_sensor_raises_when_no_member_starts() -> None:
    events: queue.Queue = queue.Queue()
    fused = FusedSensor([ExplodingSensor(), ExplodingSensor()], "any", "open")

    with pytest.raises(RuntimeError):
        fused.start(events)
