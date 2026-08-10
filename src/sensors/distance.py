"""Distance sensor backends (ultrasonic HC-SR04 and VL53L0X ToF)."""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from typing import Any

from .base import Sensor, SensorConfig

LOGGER = logging.getLogger("motion-player.sensor.distance")

_MEDIAN_WINDOW = 5
_POLL_INTERVAL = 0.05  # seconds


class DistanceSensor(Sensor):
    """Distance-based presence sensor with median filtering and hysteresis."""

    def __init__(self, config: Any) -> None:
        super().__init__("distance", SensorConfig(
            engaged_when="open",  # distance uses its own raw state below threshold
            bounce_time_ms=config.bounce_time_ms,
            min_lift_ms=config.min_lift_ms,
            min_replace_ms=config.min_replace_ms,
        ))
        self._threshold = config.threshold_cm
        self._hysteresis_low = self._threshold * 0.9
        self._hysteresis_high = self._threshold * 1.1
        self._readings: deque[float] = deque(maxlen=_MEDIAN_WINDOW)
        self._device: Any = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_raw = False
        self._lock = threading.Lock()

        if config.i2c_address is not None:
            self._init_vl53l0x(config.i2c_address)
        else:
            self._init_hcsr04(config.trigger_pin, config.echo_pin)

    def _init_hcsr04(self, trigger_pin: int, echo_pin: int) -> None:
        from gpiozero import DistanceSensor as GpioDistanceSensor  # type: ignore[import-untyped]

        self._device = GpioDistanceSensor(
            echo=echo_pin,
            trigger=trigger_pin,
            max_distance=4.0,
        )
        LOGGER.info("HC-SR04 initialised trigger=%s echo=%s", trigger_pin, echo_pin)

    def _init_vl53l0x(self, i2c_address: int) -> None:
        try:
            from VL53L0X import VL53L0X  # type: ignore[import-untyped]
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("VL53L0X library not available: %s", exc)
            raise
        self._device = VL53L0X(i2c_address=i2c_address)
        LOGGER.info("VL53L0X initialised at 0x%02x", i2c_address)

    def _read_distance_cm(self) -> float | None:
        if self._device is None:
            return None
        try:
            if hasattr(self._device, "distance"):
                # gpiozero.DistanceSensor reports distance in meters.
                return self._device.distance * 100.0
            # VL53L0X reports mm.
            return self._device.get_distance() / 10.0
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Distance read failed: %s", exc)
            return None

    def _start(self) -> None:
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
        if self._device is not None:
            try:
                self._device.close()
            except Exception:  # noqa: BLE001
                pass
            self._device = None

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            reading = self._read_distance_cm()
            if reading is not None:
                self._readings.append(reading)
                self._evaluate()
            time.sleep(_POLL_INTERVAL)

    def _evaluate(self) -> None:
        if len(self._readings) < _MEDIAN_WINDOW:
            return
        median = statistics.median(self._readings)

        with self._lock:
            currently_engaged = self._last_raw
            if currently_engaged:
                raw = median < self._hysteresis_high
            else:
                raw = median < self._hysteresis_low

            if raw != self._last_raw:
                self._last_raw = raw
                self._on_raw_change(raw)

    def is_engaged(self) -> bool:
        with self._lock:
            return self._last_raw
