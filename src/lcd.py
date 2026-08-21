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
from dataclasses import dataclass
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

DEFAULT_TITLE = "Memory<>Machine"
DEFAULT_LABELS = {
    "idle": "at rest",
    "engaged": "holding on",
    "reward": "I see you",
    "hello": "hello",
    "sleep": "goodnight",
    "goodbye": "goodbye",
}

# The instructions panel: her name on every page, the controls in the
# operator's words, and the portrait speaking for itself underneath — first
# person, to the one standing in front of it, from inside the piece's own
# premise: a face a machine remembered from her paintings; to look is to
# measure, and measuring makes it forget; let go and it re-learns itself; you
# can only see it by unmaking it. Each page is up to four rows of at most 20
# printable-ASCII columns; the first row leaves the icon's columns clear.
DEFAULT_INSTRUCTION_PAGES: tuple[tuple[str, ...], ...] = (
    ("Memory<>Machine", "OBSERVER DETECTED", "a face, remembered", "by a machine"),
    ("Memory<>Machine", "HOLD START or SELECT", "looking is measuring", "I begin to forget"),
    ("Memory<>Machine", "let go: I recover", "re-learning my face", "from what I painted"),
    ("Memory<>Machine", "stay to my beginning", "I am noise, then", "I turn to face you"),
    ("Memory<>Machine", "A or B: I refract", "ARROWS: my voices", "analog, unresolved"),
    ("Memory<>Machine", "you can only see me", "by unmaking me", "observed: altered"),
)

# The instructions panel's twinkle: the title row's far corner, past where a
# centered title reaches, alternating with the beat like the show corners.
INSTRUCTION_STARS = (((0, 18),), ((0, 19),))


@dataclass(frozen=True)
class PanelIcon:
    """A beating icon of one or more 5x8 tiles, row-major.

    Both frames live in CGRAM at once (full in the low slots, relaxed in the
    high), so a beat is a handful of cheap character writes, never a glyph
    redefinition. That is also where the size cap comes from: the chip has 8
    slots, both frames must fit, so an icon is at most 4 tiles — 2x2 cells,
    10x16 pixels — which is exactly the text margin the panel layout keeps.
    """

    full: tuple[tuple[int, ...], ...]
    small: tuple[tuple[int, ...], ...]
    cols: int
    rows: int


_ON_PIXELS = set("#*X8@")
_OFF_PIXELS = set("._ -")


def parse_icon_art(text: str) -> PanelIcon:
    """A pixel-art icon file: two frames of #/. rows separated by ---.

    Width must be 5 or 10 columns, height 8 or 16 rows, both frames the same
    size. Raises ValueError with a drawable explanation on anything else.
    """
    frames: list[list[str]] = [[]]
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.strip() == "---":
            frames.append([])
            continue
        if not stripped.strip():
            continue
        frames[-1].append(stripped)
    if len(frames) != 2 or not frames[0] or not frames[1]:
        raise ValueError("an icon file is two frames — full, a line of ---, then relaxed")

    grids = []
    width = max(len(row) for frame in frames for row in frame)
    if width not in (5, 10):
        raise ValueError(f"icon rows must be 5 or 10 pixels wide; widest is {width}")
    for frame in frames:
        if len(frame) not in (8, 16):
            raise ValueError(f"a frame must be 8 or 16 rows tall; got {len(frame)}")
        grid = []
        for row in frame:
            padded = row.ljust(width)
            bits = []
            for char in padded:
                if char in _ON_PIXELS:
                    bits.append(1)
                elif char in _OFF_PIXELS:
                    bits.append(0)
                else:
                    raise ValueError(f"unknown pixel {char!r}; use # for lit and . for dark")
            grid.append(bits)
        grids.append(grid)
    if len(grids[0]) != len(grids[1]):
        raise ValueError("both frames must be the same height")

    cols = width // 5
    rows = len(grids[0]) // 8

    def tiles(grid: list[list[int]]) -> tuple[tuple[int, ...], ...]:
        out = []
        for tile_row in range(rows):
            for tile_col in range(cols):
                tile = []
                for y in range(8):
                    bits = grid[tile_row * 8 + y][tile_col * 5:tile_col * 5 + 5]
                    value = 0
                    for bit in bits:
                        value = (value << 1) | bit
                    tile.append(value)
                out.append(tuple(tile))
        return tuple(out)

    return PanelIcon(full=tiles(grids[0]), small=tiles(grids[1]), cols=cols, rows=rows)


# Art layout: the icon centered on the panel, ROM asterisks twinkling around
# it. Two scatter sets alternate with the beat — stars cost no glyph slots.
STARS_A = ((0, 3), (0, 16), (1, 6), (2, 13), (3, 4), (3, 15))
STARS_B = ((0, 8), (0, 12), (1, 14), (2, 5), (3, 9), (3, 18))

# Show layout: the panel narrates the piece — title always up, the state's
# word beside a beating heart, health beneath, stars twinkling in the corners
# the text never reaches. A centered 18-column title uses row 0 columns 1-18,
# the word row keeps its ends clear, the cpu row ends by column 15, and the
# lifts row can run the full width — so the stars live at the free corners.
SHOW_STARS = {
    "calm": (
        ((0, 0), (2, 19)),
        ((0, 19), (2, 17)),
    ),
    "lively": (
        ((0, 0), (2, 17)),
        ((0, 19), (2, 19)),
    ),
}
ALL_SHOW_STARS = ((0, 0), (0, 19), (2, 17), (2, 19))


def show_mood(state: str, seconds_since_wake: float | None = None) -> str:
    """The show layout's personality for a state.

    Listening is lively, the turn into forward is radiant, rest is calm, the
    wake window greets with every star lit, and sleep goes dark (the
    backlight is already off).
    """
    upper = state.upper()
    if upper == "SLEEP":
        return "dark"
    if upper == "REWARD":
        return "radiant"
    if upper == "ENGAGED":
        return "lively"
    if seconds_since_wake is not None and seconds_since_wake < HELLO_SECONDS:
        return "hello"
    return "calm"


MOOD_WORDS = {
    "calm": "idle",
    "lively": "engaged",
    "radiant": "reward",
    "hello": "hello",
    "dark": "sleep",
}


def mood_word(mood: str, labels: dict[str, str]) -> str:
    """The configured word a mood speaks."""
    return labels[MOOD_WORDS[mood]]


# While she is interacting the panel gives itself over: title up, one big
# heart beating at the center, the word beneath, health yielding for the
# moment. Star cells here clear the title row (columns 1-18), the icon
# (rows 1-2, columns 9-10), and a centered word on row 3 (columns 1-18).
INTER_STARS = (
    ((0, 0), (1, 16), (2, 4), (3, 19)),
    ((0, 19), (1, 3), (2, 15), (3, 0)),
)
ALL_INTER_STARS = tuple(sorted(INTER_STARS[0] + INTER_STARS[1]))


def show_view(mood: str) -> str:
    """Which face the show layout wears: the background texture or her focus."""
    return "interacting" if mood in ("lively", "radiant") else "background"


def interacting_rows(title: str, word: str) -> list[str]:
    """The interacting view's text: title up, word beneath the big heart."""
    blank = " " * COLUMNS
    return [center_line(title), blank, blank, center_line(word)]


def show_stars(mood: str, full: bool) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """(shown, hidden) star cells for a mood at a beat phase.

    Background moods twinkle the corners; lively alternates the interacting
    scatter; radiant flashes the whole interacting sky with the beat; hello
    holds every corner star lit; dark shows none.
    """
    if mood == "dark":
        return (), ()
    if mood == "hello":
        return ALL_SHOW_STARS, ()
    if mood == "radiant":
        return (ALL_INTER_STARS, ()) if full else ((), ALL_INTER_STARS)
    if mood == "lively":
        first, second = INTER_STARS
        return (first, second) if full else (second, first)
    first, second = SHOW_STARS[mood]
    return (first, second) if full else (second, first)


def icon_origin(icon: PanelIcon) -> tuple[int, int]:
    """Top-left cell that centers the icon on the 20x4 panel."""
    return (ROWS - icon.rows) // 2, (COLUMNS - icon.cols) // 2


def text_start(row_index: int, icon: PanelIcon | None) -> int:
    """First text column of a panel row: the icon owns its cells, text the rest."""
    if icon is not None and row_index < icon.rows:
        return icon.cols
    return 0


def resolve_icon(config: Any) -> PanelIcon | None:
    """The beating icon for this config, or None for a bare column.

    A hand-drawn bitmap pair (icon_full/icon_small) wins over the named icon;
    a name that is neither built-in nor `none` is looked up as pixel art at
    <media>/icons/<name>.txt; anything broken falls back to the heart rather
    than a dead panel.
    """
    full = getattr(config, "icon_full", None)
    small = getattr(config, "icon_small", None)
    if full and small:
        return PanelIcon(full=(tuple(full),), small=(tuple(small),), cols=1, rows=1)
    name = str(getattr(config, "icon", "heart")).lower()
    if name == "none":
        return None
    if name in GLYPHS:
        pair = GLYPHS[name]
        return PanelIcon(full=(pair[0],), small=(pair[1],), cols=1, rows=1)

    import config as config_module

    art = config_module.MEDIA_DIR / "icons" / f"{name}.txt"
    if art.exists():
        try:
            return parse_icon_art(art.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not use icon art %s (%s); using the heart", art, exc)
    else:
        LOGGER.warning("Unknown lcd.icon %r and no %s; using the heart", name, art)
    pair = GLYPHS["heart"]
    return PanelIcon(full=(pair[0],), small=(pair[1],), cols=1, rows=1)


def panel_labels(config: Any) -> dict[str, str]:
    """The visitor-facing words, from config with the shipped defaults.

    An explicitly empty label stays empty — a deliberately silent panel —
    while an absent one gets the shipped word.
    """
    labels = {}
    for key, default in DEFAULT_LABELS.items():
        value = getattr(config, f"label_{key}", None)
        labels[key] = default if value is None else value
    return labels


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
    if upper == "REWARD":
        return words["reward"]
    if upper == "ENGAGED":
        return words["engaged"]
    if seconds_since_wake is not None and seconds_since_wake < HELLO_SECONDS:
        return words["hello"]
    return words["idle"]


def center_line(text: str, start: int = 2) -> str:
    """Text centered on the panel row, never intruding on the icon's columns.

    The left margin (`start`) is where the icon lives; short text centers past
    it naturally, long text is pinned to it rather than colliding.
    """
    pad = max(start, (COLUMNS - len(text)) // 2)
    return (" " * pad + text)[:COLUMNS].ljust(COLUMNS)


def farewell_rows(title: str = DEFAULT_TITLE, goodbye: str = DEFAULT_LABELS["goodbye"]) -> list[str]:
    """What the panel shows when the piece shuts down."""
    rows = [
        center_line(title),
        center_line(goodbye),
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
        center_line(title),
        center_line(listening),
        f"cpu {cpu_percent:3.0f}%   {temperature_c:4.1f}C",
        f"holds {lifts:<5} up {uptime}",
    ]
    return [row[:COLUMNS].ljust(COLUMNS) for row in rows]


def instruction_pages(config: Any) -> tuple[tuple[str, ...], ...]:
    """The instruction card's pages: the operator's own, or the shipped deck."""
    pages = getattr(config, "pages", ()) or ()
    return tuple(pages) if pages else DEFAULT_INSTRUCTION_PAGES


def page_index(elapsed_s: float, page_seconds: float, count: int) -> int:
    """Which page the deck shows after `elapsed_s` of rotation."""
    if count <= 0:
        return 0
    if page_seconds <= 0:
        return 0
    return int(max(0.0, elapsed_s) // page_seconds) % count


def instruction_rows(pages: tuple[tuple[str, ...], ...], index: int) -> list[str]:
    """One page as four full-width rows: title row past the icon, the rest
    centered on the whole panel."""
    page = pages[index % len(pages)] if pages else ()
    lines = list(page[:ROWS]) + [""] * (ROWS - len(page[:ROWS]))
    rows = [center_line(lines[0])]
    for line in lines[1:]:
        pad = max(0, (COLUMNS - len(line)) // 2)
        rows.append(" " * pad + line)
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
        self._config = config
        self._status = status
        self._state = "IDLE"
        self._lcd: Hd44780I2c | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at = time.monotonic()
        self._cpu_previous: tuple[int, int] | None = None
        self._icon = resolve_icon(self._config)
        self._labels = panel_labels(self._config)
        title = getattr(self._config, "title", None)
        self._title = DEFAULT_TITLE if title is None else title
        self._layout = str(getattr(self._config, "layout", "status")).lower()
        self._pages = instruction_pages(self._config)
        self._page_seconds = float(getattr(self._config, "page_seconds", 6.0))
        self._backlight = bool(getattr(self._config, "backlight", True))

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
            lcd.set_backlight(self._backlight)
            if self._icon is not None:
                # Both frames resident at once: full tiles in the low slots,
                # relaxed in the high, so beating is character writes only.
                for slot, tile in enumerate(self._icon.full):
                    lcd.define_glyph(slot, tile)
                for slot, tile in enumerate(self._icon.small):
                    lcd.define_glyph(len(self._icon.full) + slot, tile)
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
        self._thread = threading.Thread(
            target=self._run,
            name=f"lcd-heartbeat-0x{self._config.i2c_address:02X}",
            daemon=True,
        )
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
            self._lcd.set_backlight(self._backlight)
            for index, row in enumerate(farewell_rows(self._title, self._labels["goodbye"])):
                self._lcd.write_at(index, 0, row)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not write the goodbye: %s", exc)

    def _run(self) -> None:
        assert self._lcd is not None
        lcd = self._lcd
        last_full: bool | None = None
        last_mood: str | None = None
        last_view: str | None = None
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
                        lcd.set_backlight(self._backlight)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.debug("Backlight on failed: %s", exc)
                previous_state = current

            if current == "SLEEP":
                bpm = self._config.sleep_bpm
            elif current in ("ENGAGED", "REWARD"):
                # The reward is still a visitor present: the heart stays quick.
                bpm = self._config.engaged_bpm
            else:
                bpm = self._config.idle_bpm

            try:
                if self._layout == "show":
                    # The panel narrates in two faces. Background: title,
                    # word beside a tiny beating heart, health beneath, stars
                    # in the corners. Interacting: she takes the panel — one
                    # big heart beating at the center, the word beneath it.
                    since = None if woke_at is None else now - woke_at
                    mood = show_mood(current, since)
                    word = mood_word(mood, self._labels)
                    view = show_view(mood)
                    full = beat_is_full(now, bpm)

                    if view != last_view:
                        # Reprogram CGRAM per face — on the rare state flip,
                        # never per beat. The background's tiny heart is the
                        # classic pair; the interacting face loads the big
                        # icon, both frames resident.
                        if view == "background":
                            lcd.define_glyph(0, HEART_FULL)
                            lcd.define_glyph(1, HEART_SMALL)
                        elif self._icon is not None:
                            for slot, tile in enumerate(self._icon.full):
                                lcd.define_glyph(slot, tile)
                            for slot, tile in enumerate(self._icon.small):
                                lcd.define_glyph(len(self._icon.full) + slot, tile)
                        last_rows = []
                        last_view = view
                        last_mood = None

                    rows_due = now >= next_stats
                    if view == "background" and rows_due:
                        next_stats = now + 1.0
                        cpu, self._cpu_previous = read_cpu_percent(self._cpu_previous)
                        snapshot = self._status.snapshot()
                        rows = format_rows(
                            self._state,
                            cpu,
                            read_temperature_c(),
                            int(snapshot.get("lift_count", 0)),
                            now - self._started_at,
                            label=word,
                            title=self._title,
                        )
                        for index, row in enumerate(rows):
                            if index >= len(last_rows) or last_rows[index] != row:
                                lcd.write_at(index, 0, row)
                        last_rows = rows
                    elif view == "interacting" and (mood != last_mood or not last_rows):
                        rows = interacting_rows(self._title, word)
                        for index, row in enumerate(rows):
                            if index >= len(last_rows) or last_rows[index] != row:
                                lcd.write_at(index, 0, row)
                        last_rows = rows

                    if rows_due or full != last_full or mood != last_mood:
                        if mood != last_mood:
                            # A new personality clears the whole sky first,
                            # so no star of the old mood lingers.
                            for row, col in ALL_SHOW_STARS + ALL_INTER_STARS:
                                lcd.write_at(row, col, " ")
                        if self._icon is not None:
                            if view == "background" and len(last_rows) > 1:
                                # Tiny heart inline, two cells before the word.
                                pad = len(last_rows[1]) - len(last_rows[1].lstrip())
                                lcd.write_glyph_at(1, max(0, pad - 2), 0 if full else 1)
                            elif view == "interacting":
                                origin_row, origin_col = icon_origin(self._icon)
                                base = 0 if full else len(self._icon.full)
                                for cell in range(len(self._icon.full)):
                                    lcd.write_glyph_at(
                                        origin_row + cell // self._icon.cols,
                                        origin_col + cell % self._icon.cols,
                                        base + cell,
                                    )
                        shown, hidden = show_stars(mood, full)
                        for row, col in hidden:
                            lcd.write_at(row, col, " ")
                        for row, col in shown:
                            lcd.write_at(row, col, "*")
                        last_full = full
                        last_mood = mood
                    self._stop.wait(0.05)
                    continue

                if self._layout == "instructions":
                    # The card deck turns on its own clock; a page only redraws
                    # the rows that changed, and the icon's beat below stays
                    # the shared heartbeat machinery.
                    index = page_index(now - self._started_at, self._page_seconds, len(self._pages))
                    rows = instruction_rows(self._pages, index)
                    if rows != last_rows:
                        for row_index, row in enumerate(rows):
                            if row_index >= len(last_rows) or last_rows[row_index] != row:
                                start = text_start(row_index, self._icon)
                                lcd.write_at(row_index, start, row[start:])
                        last_rows = rows

                if self._layout not in ("art", "instructions") and now >= next_stats:
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
                            start = text_start(index, self._icon)
                            lcd.write_at(index, start, row[start:])
                    last_rows = rows

                if self._icon is not None:
                    full = beat_is_full(now, bpm)
                    if full != last_full:
                        origin_row, origin_col = (
                            icon_origin(self._icon) if self._layout == "art" else (0, 0)
                        )
                        base = 0 if full else len(self._icon.full)
                        for cell in range(len(self._icon.full)):
                            lcd.write_glyph_at(
                                origin_row + cell // self._icon.cols,
                                origin_col + cell % self._icon.cols,
                                base + cell,
                            )
                        if self._layout == "art":
                            # Stars twinkle in counter-phase with the beat —
                            # ROM asterisks, so they cost no glyph slots.
                            shown, hidden = (STARS_A, STARS_B) if full else (STARS_B, STARS_A)
                            for row, col in hidden:
                                lcd.write_at(row, col, " ")
                            for row, col in shown:
                                lcd.write_at(row, col, "*")
                        elif self._layout == "instructions":
                            first, second = INSTRUCTION_STARS
                            shown, hidden = (first, second) if full else (second, first)
                            for row, col in hidden:
                                lcd.write_at(row, col, " ")
                            for row, col in shown:
                                lcd.write_at(row, col, "*")
                        last_full = full
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("LCD panel write failed; stopping the panel: %s", exc)
                return

            self._stop.wait(0.05)


class Panels:
    """Both panels — the heartbeat and the instruction card — as one object.

    Each panel opens its own bus handle and runs its own thread; one failing,
    or being absent, never touches the other.
    """

    def __init__(self, config: Any, status: Any) -> None:
        self._panels = [
            Heartbeat(config.lcd, status),
            Heartbeat(config.lcd2, status),
        ]

    def start(self) -> None:
        for panel in self._panels:
            panel.start()

    def set_state(self, state: str) -> None:
        for panel in self._panels:
            panel.set_state(state)

    def stop(self) -> None:
        for panel in self._panels:
            panel.stop()
