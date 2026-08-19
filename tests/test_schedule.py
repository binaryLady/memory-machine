"""Sleep schedule tests: pure minute math plus the poll protocol."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from schedule import SleepScheduler, is_asleep_minute, parse_hhmm


@dataclass
class FakeScheduleConfig:
    enabled: bool = True
    sleep_start: str = "00:00"
    sleep_end: str = "08:00"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("00:00", 0),
        ("08:00", 480),
        ("23:59", 1439),
        (" 9:30 ", 570),
        ("24:00", None),
        ("12:60", None),
        ("noon", None),
        ("12", None),
        ("", None),
    ],
)
def test_parse_hhmm_accepts_midnight_and_rejects_garbage(value: str, expected) -> None:
    assert parse_hhmm(value) == expected


def test_sleep_spanning_midnight_covers_late_night_and_early_morning() -> None:
    """A 23:00-08:00 window is the realistic gallery setting."""
    start, end = 23 * 60, 8 * 60

    assert is_asleep_minute(23 * 60 + 30, start, end)
    assert is_asleep_minute(3 * 60, start, end)
    assert not is_asleep_minute(12 * 60, start, end)
    assert not is_asleep_minute(8 * 60, start, end), "opening time is awake"


def test_equal_start_and_end_means_the_piece_never_sleeps() -> None:
    assert not is_asleep_minute(0, 300, 300)
    assert not is_asleep_minute(300, 300, 300)


def test_a_disabled_schedule_never_reports_a_transition() -> None:
    scheduler = SleepScheduler(FakeScheduleConfig(enabled=False))

    for second in range(10):
        assert scheduler.poll(float(second), minute_of_day=120) is None
    assert not scheduler.asleep


def test_garbled_times_disable_the_schedule_rather_than_crashing() -> None:
    """A config typo must degrade to 'always awake', never take the piece down."""
    scheduler = SleepScheduler(FakeScheduleConfig(sleep_start="2am"))

    assert scheduler.poll(0.0, minute_of_day=120) is None
    assert not scheduler.asleep


def test_poll_reports_sleep_once_then_stays_quiet_until_wake() -> None:
    scheduler = SleepScheduler(FakeScheduleConfig())

    assert scheduler.poll(0.0, minute_of_day=120) == "sleep"
    assert scheduler.poll(1.5, minute_of_day=121) is None
    assert scheduler.asleep
    assert scheduler.poll(3.0, minute_of_day=480) == "wake"
    assert scheduler.poll(4.5, minute_of_day=481) is None
    assert not scheduler.asleep


def test_poll_reads_the_clock_at_most_once_per_second() -> None:
    """The main loop runs near 1 kHz; the schedule must not."""
    scheduler = SleepScheduler(FakeScheduleConfig())

    assert scheduler.poll(0.0, minute_of_day=120) == "sleep"
    # Within the same second, a wake-worthy minute is not even looked at.
    assert scheduler.poll(0.5, minute_of_day=480) is None
    assert scheduler.asleep
    assert scheduler.poll(1.1, minute_of_day=480) == "wake"


def test_a_clock_jump_past_the_wake_time_wakes_on_the_next_poll() -> None:
    """NTP catching up after boot must not leave the piece asleep at noon."""
    scheduler = SleepScheduler(FakeScheduleConfig())
    assert scheduler.poll(0.0, minute_of_day=60) == "sleep"

    assert scheduler.poll(2.0, minute_of_day=12 * 60) == "wake"
