"""MPR121-style capacitive touch/proximity sensor backend."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .base import Sensor, SensorConfig

LOGGER = logging.getLogger("motion-player.sensor.capacitive")

_POLL_INTERVAL = 0.05  # seconds


class CapacitiveSensor(Sensor):
    """Capacitive touch sensor via MPR121 over I²C."""

    def __init__(self, config: Any) -> None:
        super().__init__("capacitive", SensorConfig(
            engaged_when=config.engaged_when,
            bounce_time_ms=config.bounce_time_ms,
            min_lift_ms=config.min_lift_ms,
            min_replace_ms=config.min_replace_ms,
        ))
        self._channel = config.touch_channel
        self._i2c_address = config.i2c_address or 0x5A
        self._device: Any = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_raw = False
        self._lock = threading.Lock()

        self._init_device()

    def _init_device(self) -> None:
        # These imports are heavy and hardware-specific; keep them inside init.
        import busio  # type: ignore[import-untyped]
        import board  # type: ignore[import-untyped]
        import adafruit_mpr121  # type: ignore[import-untyped]

        i2c = busio.I2C(board.SCL, board.SDA)
        self._device = adafruit_mpr121.MPR121(i2c, address=self._i2c_address)
        LOGGER.info(
            "MPR121 initialised at 0x%02x channel=%s baseline=%s",
            self._i2c_address,
            self._channel,
            getattr(self._device, "baseline_data", [None] * 12)[self._channel],
        )

    def _start(self) -> None:
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
        self._device = None

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw = bool(self._device[self._channel].value)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Capacitive read failed: %s", exc)
                time.sleep(_POLL_INTERVAL)
                continue

            with self._lock:
                if raw != self._last_raw:
                    self._last_raw = raw
                    self._on_raw_change(raw)
            time.sleep(_POLL_INTERVAL)

    def is_engaged(self) -> bool:
        with self._lock:
            return self._last_raw
