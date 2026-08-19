"""Character-LCD heartbeat panel: an HD44780 20x4 behind a PCF8574 I2C backpack.

The panel shows the installation's pulse — a heart that beats slowly at rest and
quickens while someone is listening — above a few health figures. It is an
output only: nothing here can affect playback, and every failure degrades to the
piece running without it.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

LOGGER = logging.getLogger("motion-player.lcd")

# PCF8574 backpack bit assignments, near-universal on these modules.
_RS = 0x01
_ENABLE = 0x04
_BACKLIGHT = 0x08

# DDRAM address of each row on a 20x4 panel.
_ROW_OFFSETS = (0x00, 0x40, 0x14, 0x54)

COLUMNS = 20
ROWS = 4

# Two 5x8 glyphs. Alternating them is a beat rather than a blink: the heart
# swells and relaxes instead of appearing and vanishing.
HEART_FULL = (0x00, 0x0A, 0x1F, 0x1F, 0x1F, 0x0E, 0x04, 0x00)
HEART_SMALL = (0x00, 0x00, 0x0A, 0x1F, 0x0E, 0x04, 0x00, 0x00)
_HEART_SLOT = 0


def beat_is_full(elapsed_s: float, bpm: float) -> bool:
    """True while the heart is at full size.

    A real beat is not a square wave: the swell is brief and the rest between
    beats is long, which is what makes it read as a pulse rather than a flash.
    """
    if bpm <= 0:
        return False
    period = 60.0 / bpm
    phase = (elapsed_s % period) / period
    return phase < 0.28


def format_rows(
    state: str, cpu_percent: float, temperature_c: float, lifts: int, uptime_s: float
) -> list[str]:
    """The four lines, each padded to exactly the panel width.

    Column zero of the first row is left blank for the heart glyph, which is
    written separately so a beat does not rewrite the whole line.
    """
    hours, remainder = divmod(int(max(0.0, uptime_s)), 3600)
    minutes = remainder // 60
    if hours >= 24:
        uptime = f"{hours // 24}d{hours % 24:02d}h"
    else:
        uptime = f"{hours}h{minutes:02d}m"

    listening = "listening" if state.upper() == "ENGAGED" else "at rest"

    rows = [
        "  memory-machine",
        f"  {listening}",
        f"cpu {cpu_percent:3.0f}%   {temperature_c:4.1f}C",
        f"lifts {lifts:<5} up {uptime}",
    ]
    return [row[:COLUMNS].ljust(COLUMNS) for row in rows]


def read_cpu_percent(previous: tuple[int, int] | None) -> tuple[float, tuple[int, int]]:
    """CPU use since the last call, from /proc/stat totals."""
    try:
        with open("/proc/stat", encoding="utf-8") as handle:
            fields = handle.readline().split()[1:]
    except OSError:
        return 0.0, previous or (0, 0)

    values = [int(v) for v in fields[:8]]
    idle = values[3] + values[4]
    total = sum(values)
    if previous is None:
        return 0.0, (idle, total)

    idle_delta = idle - previous[0]
    total_delta = total - previous[1]
    if total_delta <= 0:
        return 0.0, (idle, total)
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), (idle, total)


def read_temperature_c() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as handle:
            return int(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        return 0.0


class Hd44780I2c:
    """Minimal 4-bit HD44780 driver over a PCF8574 expander."""

    def __init__(self, bus: Any, address: int) -> None:
        self._bus = bus
        self._address = address
        self._backlight = _BACKLIGHT

    def _write(self, value: int) -> None:
        self._bus.write_byte(self._address, value | self._backlight)

    def _pulse(self, value: int) -> None:
        self._write(value | _ENABLE)
        time.sleep(0.0005)
        self._write(value & ~_ENABLE)
        time.sleep(0.0001)

    def _send(self, value: int, mode: int) -> None:
        self._pulse((value & 0xF0) | mode)
        self._pulse(((value << 4) & 0xF0) | mode)

    def command(self, value: int) -> None:
        self._send(value, 0)

    def write_char(self, value: int) -> None:
        self._send(value, _RS)

    def initialise(self) -> None:
        time.sleep(0.05)
        # Three attempts at 8-bit mode, then drop to 4-bit: the documented wake
        # sequence, and the part most likely to need the delays it specifies.
        for _ in range(3):
            self._pulse(0x30)
            time.sleep(0.005)
        self._pulse(0x20)
        self.command(0x28)  # 4-bit, 2 lines, 5x8 font
        self.command(0x08)  # display off
        self.command(0x01)  # clear
        time.sleep(0.002)
        self.command(0x06)  # entry mode: advance right, no shift
        self.command(0x0C)  # display on, cursor off

    def define_glyph(self, slot: int, bitmap: tuple[int, ...]) -> None:
        self.command(0x40 | ((slot & 0x07) << 3))
        for row in bitmap:
            self.write_char(row)

    def write_at(self, row: int, column: int, text: str) -> None:
        self.command(0x80 | (_ROW_OFFSETS[row] + column))
        for character in text:
            self.write_char(ord(character))

    def write_glyph_at(self, row: int, column: int, slot: int) -> None:
        self.command(0x80 | (_ROW_OFFSETS[row] + column))
        self.write_char(slot)


class Heartbeat:
    """Drives the panel from a background thread.

    Kept off the render loop deliberately: an I2C write takes milliseconds, and
    the frame budget is 33. Nothing here blocks playback, and a panel that fails
    to open simply is not used.
    """

    def __init__(self, config: Any, status: Any) -> None:
        self._config = config.lcd
        self._status = status
        self._state = "IDLE"
        self._lcd: Hd44780I2c | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at = time.monotonic()
        self._cpu_previous: tuple[int, int] | None = None

    def _open(self) -> Hd44780I2c | None:
        try:
            try:
                from smbus2 import SMBus  # type: ignore[import-untyped]
            except ImportError:
                from smbus import SMBus  # type: ignore[import-untyped]
        except ImportError:
            LOGGER.error("No smbus module; install python3-smbus to use the LCD panel")
            return None

        try:
            bus = SMBus(self._config.i2c_bus)
            lcd = Hd44780I2c(bus, self._config.i2c_address)
            lcd.initialise()
            lcd.define_glyph(_HEART_SLOT, HEART_FULL)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Could not open the LCD at bus %s address 0x%02X: %s",
                self._config.i2c_bus,
                self._config.i2c_address,
                exc,
            )
            return None

        LOGGER.info("LCD panel active at 0x%02X", self._config.i2c_address)
        return lcd

    def start(self) -> None:
        if not self._config.enabled:
            return
        self._lcd = self._open()
        if self._lcd is None:
            return
        self._thread = threading.Thread(target=self._run, name="lcd-heartbeat", daemon=True)
        self._thread.start()

    def set_state(self, state: str) -> None:
        self._state = state

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        assert self._lcd is not None
        lcd = self._lcd
        last_full: bool | None = None
        last_rows: list[str] = []
        next_stats = 0.0

        while not self._stop.is_set():
            now = time.monotonic()
            engaged = self._state.upper() == "ENGAGED"
            bpm = self._config.engaged_bpm if engaged else self._config.idle_bpm

            try:
                if now >= next_stats:
                    next_stats = now + 1.0
                    cpu, self._cpu_previous = read_cpu_percent(self._cpu_previous)
                    snapshot = self._status.snapshot()
                    rows = format_rows(
                        self._state,
                        cpu,
                        read_temperature_c(),
                        int(snapshot.get("lift_count", 0)),
                        now - self._started_at,
                    )
                    for index, row in enumerate(rows):
                        # Only redraw lines that changed; the panel is slow and
                        # a full refresh every second visibly flickers.
                        if index >= len(last_rows) or last_rows[index] != row:
                            start = 1 if index == 0 else 0
                            lcd.write_at(index, start, row[start:])
                    last_rows = rows

                full = beat_is_full(now, bpm)
                if full != last_full:
                    lcd.define_glyph(_HEART_SLOT, HEART_FULL if full else HEART_SMALL)
                    lcd.write_glyph_at(0, 0, _HEART_SLOT)
                    last_full = full
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("LCD panel write failed; stopping the panel: %s", exc)
                return

            self._stop.wait(0.05)
