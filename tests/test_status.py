"""StatusWriter tests: write discipline for an SD card that must last a show."""
from __future__ import annotations

import json

import status as status_module


def test_set_state_only_touches_the_file_when_the_state_changes(
    monkeypatch, tmp_path
) -> None:
    """The main loop calls this ~1000x a second; unchanged state is not news."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    writer = status_module.StatusWriter()
    writes = []
    monkeypatch.setattr(writer._status, "write", lambda: writes.append(1))

    writer.set_state("IDLE")
    writer.set_state("IDLE")
    writer.set_state("IDLE")
    writer.set_state("ENGAGED")

    assert len(writes) == 2, "one write per actual change"


def test_the_status_file_is_replaced_atomically(monkeypatch, tmp_path) -> None:
    """A reader mid-write must never see a truncated file."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    writer = status_module.StatusWriter()
    writer.set_extra("cpu_percent", 12.5)

    writer.write()

    target = tmp_path / "motion-player" / "status.json"
    payload = json.loads(target.read_text())
    assert payload["cpu_percent"] == 12.5
    assert not (tmp_path / "motion-player" / "status.json.tmp").exists()


def test_extras_ride_along_without_their_own_write(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    writer = status_module.StatusWriter()

    writer.set_extra("temperature_c", 51.2)

    target = tmp_path / "motion-player" / "status.json"
    assert not target.exists(), "set_extra alone must not touch the disk"


def test_watch_as_the_only_flag_does_not_recurse_into_itself(monkeypatch, tmp_path, capsys) -> None:
    """--watch re-enters main with an empty argv; an empty argv must not fall
    back to sys.argv, where --watch is still waiting."""
    import sys
    import time

    monkeypatch.setattr(sys, "argv", ["motion-player-status", "--watch"])
    monkeypatch.setattr(status_module, "_status_file", lambda: tmp_path / "status.json")
    ticks = {"n": 0}

    def one_tick(_seconds: float) -> None:
        ticks["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", one_tick)

    assert status_module.main() == 0
    assert ticks["n"] == 1
    assert "State:" in capsys.readouterr().out
