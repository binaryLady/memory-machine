"""Digital GPIO sensor backends (switch, reed, beam, etc.)."""
from __future__ import annotations

import logging
from typing import Any

from .base import Sensor, SensorConfig

LOGGER = logging.getLogger("motion-player.sensor.digital")

# Backend-specific defaults. Global config values are used unless a backend
# entry overrides them here.
_DIGITAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "switch": {"pull_up": True, "min_lift_ms": 250, "min_replace_ms": 250},
    "reed": {"pull_up": True, "min_lift_ms": 250, "min_replace_ms": 250},
    "beam": {"pull_up": True, "min_lift_ms": 250, "min_replace_ms": 250},
    "reflective": {"pull_up": True, "min_lift_ms": 250, "min_replace_ms": 250},
    "hall": {"pull_up": True, "min_lift_ms": 250, "min_replace_ms": 250},
    "pir": {"pull_up": True, "min_lift_ms": 1000, "min_replace_ms": 250},
    "gpio_raw": {"pull_up": None},  # use config value
}


def _base_config(sensor_type: str, config: Any) -> tuple[SensorConfig, bool]:
    table = _DIGITAL_DEFAULTS.get(sensor_type, {})
    pull_up = config.pull_up if table.get("pull_up") is None else table["pull_up"]
    return SensorConfig(
        engaged_when=config.engaged_when,
        bounce_time_ms=config.bounce_time_ms,
        min_lift_ms=table.get("min_lift_ms", config.min_lift_ms),
        min_replace_ms=table.get("min_replace_ms", config.min_replace_ms),
    ), pull_up


class DigitalSensor(Sensor):
    """gpiozero.Button-based digital input."""

    def __init__(self, sensor_type: str, config: Any) -> None:
        base_config, self._pull_up = _base_config(sensor_type, config)
        super().__init__(sensor_type, base_config)
        self._pin = config.gpio_pin
        self._button: Any = None
        self._last_raw = False

    def _start(self) -> None:
        from gpiozero import Button  # type: ignore[import-untyped]

        # gpiozero handles the first-level bounce filter.
        self._button = Button(
            self._pin,
            pull_up=self._pull_up,
            bounce_time=self._config.bounce_time_ms / 1000.0,
        )
        self._last_raw = self._button.is_pressed
        self._button.when_pressed = lambda: self._on_raw_change(True)
        self._button.when_released = lambda: self._on_raw_change(False)

    def _stop(self) -> None:
        if self._button is not None:
            self._button.close()
            self._button = None

    def is_engaged(self) -> bool:
        if self._button is None:
            return False
        return bool(self._button.is_pressed)
