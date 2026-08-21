"""Captain's log tests: one JSON line per event, one file per day, never raises."""
from __future__ import annotations

import json
import time

from journal import Journal, day_name, journal_line


def _clock_for(*, day: int, hour: int = 12):
    def clock() -> time.struct_time:
        return time.struct_time((2026, 8, day, hour, 30, 0, 0, 0, -1))

    return clock


def test_a_line_is_parseable_json_with_stable_keys() -> None:
    line = journal_line("lift", "2026-08-21T02:15:00", source="switch")

    record = json.loads(line)
    assert record == {"t": "2026-08-21T02:15:00", "event": "lift", "source": "switch"}
    assert list(record) == ["t", "event", "source"], "stable key order for easy reading"


def test_events_append_to_one_file_per_day(tmp_path) -> None:
    journal = Journal(tmp_path, clock=_clock_for(day=21))
    journal.record("lift", source="switch")
    journal.record("reward")

    day = tmp_path / "2026-08-21.jsonl"
    lines = day.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "lift"
    assert json.loads(lines[1])["event"] == "reward"


def test_a_new_day_opens_a_new_file(tmp_path) -> None:
    journal = Journal(tmp_path, clock=_clock_for(day=21))
    journal.record("lift")
    journal._clock = _clock_for(day=22)
    journal.record("lift")

    assert (tmp_path / "2026-08-21.jsonl").exists()
    assert (tmp_path / "2026-08-22.jsonl").exists()


def test_an_unwritable_journal_never_raises(tmp_path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the directory should be", encoding="utf-8")

    journal = Journal(blocked / "journal", clock=_clock_for(day=21))
    journal.record("lift")  # must not raise — the journal is a witness, not a dependency


def test_day_name_is_the_local_date() -> None:
    assert day_name(_clock_for(day=5)) == "2026-08-05"
