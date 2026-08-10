"""mmWave human-presence sensor backend (digital presence pin)."""
from __future__ import annotations

import logging
from typing import Any

from .base import Sensor, SensorConfig

LOGGER = logging.getLogger("motion-player.sensor.mmwave")


class MmwaveSensor(Sensor):
    """Reads a digital presence pin from an mmWave module.

    This is the contingency backend; for modules that expose a UART frame,
    extend this file with a serial parser.
    """

    def __init__(self, config: Any) -> None:
        super().__init__("mmwave", SensorConfig(
            engaged_when=config.engaged_when,
            bounce_time_ms=config.bounce_time_ms,
            min_lift_ms=max(config.min_lift_ms, 500),
            min_replace_ms=config.min_replace_ms,
        ))
        self._pin = config.gpio_pin
        self._pull_up = config.pull_up
        self._button: Any = None

    def _start(self) -> None:
        from gpiozero import Button  # type: ignore[import-untyped]

        self._button = Button(self._pin, pull_up=self._pull_up, bounce_time=self._config.bounce_time_ms / 1000.0)
        self._button.when_pressed = lambda: self._on_raw_change(True)
        self._button.when_released = lambda: self._on_raw_change(False)
        LOGGER.info("mmWave digital presence pin initialised gpio=%s pull_up=%s", self._pin, self._pull_up)

    def _stop(self) -> None:
        if self._button is not None:
            self._button.close()
            self._button = None

    def is_engaged(self) -> bool:
        if self._button is None:
            return False
        return bool(self._button.is_pressed)
