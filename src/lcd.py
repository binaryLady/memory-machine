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

# Paired 5x8 glyphs. Alternating full and relaxed shapes is a beat rather
# than a blink: the icon swells and relaxes instead of appearing and
# vanishing. Each pair keeps that quality in its own vocabulary — the star
# sparkles, the ring contracts, the eye blinks.
HEART_FULL = (0x00, 0x0A, 0x1F, 0x1F, 0x1F, 0x0E, 0x04, 0x00)
HEART_SMALL = (0x00, 0x00, 0x0A, 0x1F, 0x0E, 0x04, 0x00, 0x00)

GLYPHS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "heart": (HEART_FULL, HEART_SMALL),
    "star": (
        (0x04, 0x15, 0x0E, 0x1F, 0x0E, 0x15, 0x04, 0x00),
        (0x00, 0x00, 0x04, 0x0E, 0x04, 0x00, 0x00, 0x00),
    ),
    "ring": (
        (0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E, 0x00, 0x00),
        (0x00, 0x00, 0x04, 0x0E, 0x04, 0x00, 0x00, 0x00),
    ),
    "note": (
        (0x02, 0x03, 0x02, 0x02, 0x0E, 0x1E, 0x0C, 0x00),
        (0x00, 0x02, 0x02, 0x02, 0x06, 0x06, 0x00, 0x00),
    ),
    "eye": (
        (0x00, 0x0E, 0x11, 0x15, 0x11, 0x0E, 0x00, 0x00),
        (0x00, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x00, 0x00),
    ),
}
_HEART_SLOT = 0

DEFAULT_TITLE = "memory-machine"
DEFAULT_LABELS = {
    "idle": "at rest",
    "engaged": "listening",
    "hello": "hello",
    "sleep": "goodnight",
    "goodbye": "goodbye",
}


def resolve_icon(config: Any) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """The beating pair for this config, or None for a bare column.

    A hand-drawn pair (icon_full/icon_small) wins over the named icon; an
    unknown name falls back to the heart rather than a dead panel.
    """
    full = getattr(config, "icon_full", None)
    small = getattr(config, "icon_small", None)
    if full and small:
        return tuple(full), tuple(small)
    name = str(getattr(config, "icon", "heart")).lower()
    if name == "none":
        return None
    if name not in GLYPHS:
        LOGGER.warning("Unknown lcd.icon %r; using the heart", name)
        name = "heart"
    return GLYPHS[name]


def panel_labels(config: Any) -> dict[str, str]:
    """The visitor-facing words, from config with the shipped defaults."""
    return {
        key: getattr(config, f"label_{key}", None) or default
        for key, default in DEFAULT_LABELS.items()
    }


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


# How long the panel says hello after waking before settling into "at rest".
HELLO_SECONDS = 5.0


def state_label(
    state: str,
    seconds_since_wake: float | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    """The line-two label: the state of the piece, in a visitor's words."""
    words = labels or DEFAULT_LABELS
    upper = state.upper()
    if upper == "SLEEP":
        return words["sleep"]
    if upper == "ENGAGED":
        return words["engaged"]
    if seconds_since_wake is not None and seconds_since_wake < HELLO_SECONDS:
        return words["hello"]
    return words["idle"]


def farewell_rows(title: str = DEFAULT_TITLE, goodbye: str = DEFAULT_LABELS["goodbye"]) -> list[str]:
    """What the panel shows when the piece shuts down."""
    rows = [
        f"  {title}",
        f"  {goodbye}",
        "",
        "",
    ]
    return [row[:COLUMNS].ljust(COLUMNS) for row in rows]


def format_rows(
    state: str,
    cpu_percent: float,
    temperature_c: float,
    lifts: int,
    uptime_s: float,
    label: str | None = None,
    title: str = DEFAULT_TITLE,
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

    listening = label if label is not None else state_label(state)

    rows = [
        f"  {title}",
        f"  {listening}",
        f"cpu {cpu_percent:3.0f}%   {temperature_c:4.1f}C",
        f"lifts {lifts:<5} up {uptime}",
    ]
    return [row[:COLUMNS].ljust(COLUMNS) for row in rows]


# Re-exported so existing imports and tests keep working; the readers moved to
# sysinfo so telemetry and the main loop can share them.
from sysinfo import read_cpu_percent, read_temperature_c  # noqa: E402,F401


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

    def set_backlight(self, on: bool) -> None:
        self._backlight = _BACKLIGHT if on else 0
        # A bare write latches the new backlight bit without disturbing the
        # controller.
        self._write(0)


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
        self._icon = resolve_icon(self._config)
        self._labels = panel_labels(self._config)
        self._title = getattr(self._config, "title", None) or DEFAULT_TITLE

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
            if self._icon is not None:
                lcd.define_glyph(_HEART_SLOT, self._icon[0])
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
        if self._lcd is None:
            return
        # Best effort only: the piece is already stopping, so a failed goodbye
        # must not turn a clean shutdown into an error.
        try:
            self._lcd.set_backlight(True)
            for index, row in enumerate(farewell_rows(self._title, self._labels["goodbye"])):
                self._lcd.write_at(index, 0, row)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not write the goodbye: %s", exc)

    def _run(self) -> None:
        assert self._lcd is not None
        lcd = self._lcd
        last_full: bool | None = None
        last_rows: list[str] = []
        next_stats = 0.0

        previous_state = ""
        woke_at: float | None = None

        while not self._stop.is_set():
            now = time.monotonic()
            current = self._state.upper()
            if current != previous_state:
                if current == "SLEEP":
                    # Dark panel overnight: the room is empty and the piece is
                    # resting; a lit display would say otherwise.
                    try:
                        lcd.set_backlight(False)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.debug("Backlight off failed: %s", exc)
                elif previous_state == "SLEEP":
                    woke_at = now
                    try:
                        lcd.set_backlight(True)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.debug("Backlight on failed: %s", exc)
                previous_state = current

            if current == "SLEEP":
                bpm = self._config.sleep_bpm
            elif current == "ENGAGED":
                bpm = self._config.engaged_bpm
            else:
                bpm = self._config.idle_bpm

            try:
                if now >= next_stats:
                    next_stats = now + 1.0
                    cpu, self._cpu_previous = read_cpu_percent(self._cpu_previous)
                    snapshot = self._status.snapshot()
                    since_wake = None if woke_at is None else now - woke_at
                    rows = format_rows(
                        self._state,
                        cpu,
                        read_temperature_c(),
                        int(snapshot.get("lift_count", 0)),
                        now - self._started_at,
                        label=state_label(self._state, since_wake, self._labels),
                        title=self._title,
                    )
                    for index, row in enumerate(rows):
                        # Only redraw lines that changed; the panel is slow and
                        # a full refresh every second visibly flickers.
                        if index >= len(last_rows) or last_rows[index] != row:
                            start = 1 if index == 0 else 0
                            lcd.write_at(index, start, row[start:])
                    last_rows = rows

                if self._icon is not None:
                    full = beat_is_full(now, bpm)
                    if full != last_full:
                        lcd.define_glyph(_HEART_SLOT, self._icon[0] if full else self._icon[1])
                        lcd.write_glyph_at(0, 0, _HEART_SLOT)
                        last_full = full
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("LCD panel write failed; stopping the panel: %s", exc)
                return

            self._stop.wait(0.05)
