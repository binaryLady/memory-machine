from __future__ import annotations

from dataclasses import dataclass

import pytest
from sensors import FusedSensor, KeyboardSensor, make_sensor


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
