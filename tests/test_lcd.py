"""Heartbeat panel tests. Pure layout and timing only — no I2C anywhere."""
from __future__ import annotations

import lcd
import pytest


def test_every_row_is_exactly_the_panel_width() -> None:
    """A short line leaves stale characters from the previous write behind."""
    rows = lcd.format_rows("IDLE", 12.0, 54.3, 27, 15120)

    assert len(rows) == lcd.ROWS
    assert all(len(row) == lcd.COLUMNS for row in rows)


def test_long_values_cannot_overflow_the_panel() -> None:
    rows = lcd.format_rows("ENGAGED", 100.0, 100.0, 9999999, 9999999)

    assert all(len(row) == lcd.COLUMNS for row in rows)


def test_the_first_column_is_left_for_the_heart() -> None:
    rows = lcd.format_rows("IDLE", 0.0, 0.0, 0, 0)

    assert rows[0][0] == " ", "the heart glyph lives at row 0, column 0"


def test_state_reads_as_the_piece_rather_than_the_machine() -> None:
    at_rest = lcd.format_rows("IDLE", 0.0, 0.0, 0, 0)[1]
    listening = lcd.format_rows("ENGAGED", 0.0, 0.0, 0, 0)[1]

    assert "at rest" in at_rest
    assert "listening" in listening


def test_uptime_switches_to_days_when_it_is_long() -> None:
    hours = lcd.format_rows("IDLE", 0.0, 0.0, 0, 4 * 3600 + 12 * 60)[3]
    days = lcd.format_rows("IDLE", 0.0, 0.0, 0, 4 * 86400 + 15 * 3600)[3]

    assert "4h12m" in hours
    assert "4d15h" in days


def test_the_beat_is_a_pulse_not_a_square_wave() -> None:
    """Half on, half off would read as a blink rather than a heartbeat."""
    samples = [lcd.beat_is_full(t / 1000.0, 60) for t in range(1000)]
    proportion_full = sum(samples) / len(samples)

    assert 0.2 < proportion_full < 0.4


def test_a_quicker_rate_gives_more_beats_in_the_same_time() -> None:
    def beats(bpm: float) -> int:
        samples = [lcd.beat_is_full(t / 100.0, bpm) for t in range(600)]
        return sum(1 for a, b in zip(samples, samples[1:]) if not a and b)

    assert beats(100) > beats(60)


@pytest.mark.parametrize("bpm", [0, -30])
def test_a_nonsense_rate_stops_the_heart_rather_than_dividing_by_zero(bpm: float) -> None:
    assert lcd.beat_is_full(1.0, bpm) is False


def test_cpu_percent_needs_a_previous_sample() -> None:
    """The first reading has nothing to compare against, so it reports zero."""
    percent, state = lcd.read_cpu_percent(None)

    assert percent == 0.0
    assert isinstance(state, tuple)


def test_cpu_percent_is_a_percentage() -> None:
    percent, _ = lcd.read_cpu_percent((0, 0))

    assert 0.0 <= percent <= 100.0


def test_the_two_heart_glyphs_are_valid_5x8_bitmaps() -> None:
    for bitmap in (lcd.HEART_FULL, lcd.HEART_SMALL):
        assert len(bitmap) == 8, "eight rows"
        assert all(0 <= row <= 0x1F for row in bitmap), "five bits wide"

    assert sum(bin(r).count("1") for r in lcd.HEART_FULL) > sum(
        bin(r).count("1") for r in lcd.HEART_SMALL
    ), "the full heart must be the larger of the two"


def test_the_panel_says_goodnight_while_the_piece_sleeps() -> None:
    assert lcd.state_label("SLEEP") == "goodnight"
    rows = lcd.format_rows("SLEEP", 0.0, 0.0, 0, 0, label=lcd.state_label("SLEEP"))
    assert "goodnight" in rows[1]


def test_the_panel_says_hello_for_a_few_seconds_after_waking() -> None:
    assert lcd.state_label("IDLE", seconds_since_wake=2.0) == "hello"
    assert lcd.state_label("IDLE", seconds_since_wake=6.0) == "at rest"


def test_listening_beats_hello_when_someone_lifts_at_opening() -> None:
    """A visitor at 8:01 should see 'listening', not a leftover greeting."""
    assert lcd.state_label("ENGAGED", seconds_since_wake=2.0) == "listening"


def test_the_heart_is_still_when_sleep_bpm_is_zero() -> None:
    assert lcd.beat_is_full(1.0, 0.0) is False


def test_the_farewell_fits_the_panel() -> None:
    rows = lcd.farewell_rows()

    assert len(rows) == lcd.ROWS
    assert all(len(row) == lcd.COLUMNS for row in rows)
    assert "goodbye" in rows[1]


def test_the_backlight_bit_toggles() -> None:
    class FakeBus:
        def __init__(self) -> None:
            self.writes: list[int] = []

        def write_byte(self, address: int, value: int) -> None:
            self.writes.append(value)

    bus = FakeBus()
    panel = lcd.Hd44780I2c(bus, 0x27)

    panel.set_backlight(False)
    assert bus.writes[-1] & 0x08 == 0, "backlight bit must be clear"

    panel.set_backlight(True)
    assert bus.writes[-1] & 0x08 == 0x08, "backlight bit must be set"
