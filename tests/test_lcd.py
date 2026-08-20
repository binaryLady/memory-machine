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


def test_custom_title_and_labels_reach_the_panel() -> None:
    rows = lcd.format_rows("IDLE", 5.0, 40.0, 3, 60, label="dreaming", title="her memory")

    assert rows[0].startswith("  her memory")
    assert rows[1].startswith("  dreaming")
    assert all(len(row) == lcd.COLUMNS for row in rows)


def test_state_label_speaks_the_configured_words() -> None:
    words = {"idle": "waiting", "engaged": "with you", "hello": "good morning",
             "sleep": "dreaming", "goodbye": "farewell"}

    assert lcd.state_label("ENGAGED", labels=words) == "with you"
    assert lcd.state_label("SLEEP", labels=words) == "dreaming"
    assert lcd.state_label("IDLE", 1.0, labels=words) == "good morning"
    assert lcd.state_label("IDLE", 99.0, labels=words) == "waiting"


def test_farewell_uses_the_configured_voice() -> None:
    rows = lcd.farewell_rows("her memory", "farewell")

    assert rows[0].startswith("  her memory")
    assert rows[1].startswith("  farewell")
    assert all(len(row) == lcd.COLUMNS for row in rows)


def test_every_builtin_glyph_pair_fits_the_hardware() -> None:
    """8 rows of 5 bits each — anything else garbles the CGRAM write."""
    for name, (full, small) in lcd.GLYPHS.items():
        for shape in (full, small):
            assert len(shape) == 8, name
            assert all(0 <= row <= 31 for row in shape), name


class _LcdStub:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_resolve_icon_prefers_the_hand_drawn_pair() -> None:
    drawn = ((1,) * 8, (2,) * 8)
    config = _LcdStub(icon="star", icon_full=drawn[0], icon_small=drawn[1])

    icon = lcd.resolve_icon(config)
    assert (icon.full, icon.small) == (((1,) * 8,), ((2,) * 8,))
    assert (icon.cols, icon.rows) == (1, 1)


def test_resolve_icon_falls_back_to_the_heart_on_nonsense() -> None:
    icon = lcd.resolve_icon(_LcdStub(icon="dragon"))

    assert icon.full == (lcd.GLYPHS["heart"][0],)
    assert icon.small == (lcd.GLYPHS["heart"][1],)


def test_resolve_icon_none_means_a_bare_column() -> None:
    assert lcd.resolve_icon(_LcdStub(icon="none")) is None


def test_panel_labels_fill_gaps_with_the_shipped_words() -> None:
    labels = lcd.panel_labels(_LcdStub(label_engaged="with you"))

    assert labels["engaged"] == "with you"
    assert labels["idle"] == "at rest"
    assert labels["goodbye"] == "goodbye"


ART_1X1 = """\
.....
.#.#.
#####
#####
#####
.###.
..#..
.....
---
.....
.....
.#.#.
#####
.###.
..#..
.....
.....
"""


def test_icon_art_single_cell_matches_the_builtin_heart() -> None:
    icon = lcd.parse_icon_art(ART_1X1)

    assert (icon.cols, icon.rows) == (1, 1)
    assert icon.full == (lcd.HEART_FULL,)
    assert icon.small == (lcd.HEART_SMALL,)


def test_icon_art_two_by_two_tiles_in_reading_order() -> None:
    full = "\n".join(["#" * 10] * 16)
    small = "\n".join(["." * 10] * 16)
    icon = lcd.parse_icon_art(full + "\n---\n" + small)

    assert (icon.cols, icon.rows) == (2, 2)
    assert len(icon.full) == 4 and len(icon.small) == 4
    assert all(tile == (31,) * 8 for tile in icon.full)
    assert all(tile == (0,) * 8 for tile in icon.small)


def test_icon_art_leftmost_pixel_is_the_high_bit() -> None:
    frame = ["#...."] + ["....#"] * 7
    icon = lcd.parse_icon_art("\n".join(frame) + "\n---\n" + "\n".join(frame))

    assert icon.full[0][0] == 0b10000
    assert icon.full[0][1] == 0b00001


@pytest.mark.parametrize("bad, why", [
    ("#####\n" * 8, "missing the --- separator"),
    ("#" * 7 + "\n" + ("#####\n" * 7) + "---\n" + "#####\n" * 8, "width 7"),
    ("#####\n" * 5 + "---\n" + "#####\n" * 5, "height 5"),
    ("##?##\n" + "#####\n" * 7 + "---\n" + "#####\n" * 8, "unknown pixel"),
    ("#####\n" * 8 + "---\n" + "#####\n" * 16, "mismatched frame heights"),
])
def test_icon_art_rejects_undrawable_files(bad: str, why: str) -> None:
    with pytest.raises(ValueError):
        lcd.parse_icon_art(bad)


def test_text_gives_way_to_the_icon_cells() -> None:
    big = lcd.parse_icon_art(
        "\n".join(["#" * 10] * 16) + "\n---\n" + "\n".join(["." * 10] * 16)
    )
    single = lcd.resolve_icon(_LcdStub(icon="heart"))

    assert [lcd.text_start(row, big) for row in range(4)] == [2, 2, 0, 0]
    assert [lcd.text_start(row, single) for row in range(4)] == [1, 0, 0, 0]
    assert [lcd.text_start(row, None) for row in range(4)] == [0, 0, 0, 0]


def test_resolve_icon_reads_pixel_art_from_the_media_folder(tmp_path, monkeypatch) -> None:
    import config as config_module

    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "bigheart.txt").write_text(ART_1X1, encoding="utf-8")
    monkeypatch.setattr(config_module, "MEDIA_DIR", tmp_path)

    icon = lcd.resolve_icon(_LcdStub(icon="bigheart"))

    assert icon.full == (lcd.HEART_FULL,)


def test_broken_pixel_art_falls_back_to_the_heart(tmp_path, monkeypatch) -> None:
    import config as config_module

    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "broken.txt").write_text("not art", encoding="utf-8")
    monkeypatch.setattr(config_module, "MEDIA_DIR", tmp_path)

    icon = lcd.resolve_icon(_LcdStub(icon="broken"))

    assert icon.full == (lcd.GLYPHS["heart"][0],)


def test_a_deliberately_blank_label_stays_blank() -> None:
    labels = lcd.panel_labels(_LcdStub(label_idle="", label_engaged="with you"))

    assert labels["idle"] == ""
    assert labels["engaged"] == "with you"
    assert labels["sleep"] == "goodnight", "absent still means the shipped word"


def test_art_layout_centers_the_big_icon() -> None:
    big = lcd.parse_icon_art(
        "\n".join(["#" * 10] * 16) + "\n---\n" + "\n".join(["." * 10] * 16)
    )

    assert lcd.icon_origin(big) == (1, 9)


def test_stars_never_land_on_the_centered_icon() -> None:
    big = lcd.parse_icon_art(
        "\n".join(["#" * 10] * 16) + "\n---\n" + "\n".join(["." * 10] * 16)
    )
    row0, col0 = lcd.icon_origin(big)
    cells = {(row0 + r, col0 + c) for r in range(big.rows) for c in range(big.cols)}

    for star in lcd.STARS_A + lcd.STARS_B:
        assert star not in cells, f"star at {star} would overwrite the icon"
        assert 0 <= star[0] < lcd.ROWS and 0 <= star[1] < lcd.COLUMNS
