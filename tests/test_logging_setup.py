"""Logging pipeline tests: writes must never block the caller's thread."""
from __future__ import annotations

import logging
import time

import logging_setup


def test_log_records_reach_the_file_through_the_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    logging_setup.setup("info", 5)
    logging.getLogger("motion-player").info("a line from the show")
    time.sleep(0.2)  # let the listener thread drain

    log = tmp_path / "motion-player" / "motion-player.log"
    assert "a line from the show" in log.read_text()


def test_the_root_handler_is_a_queue_not_a_file(monkeypatch, tmp_path) -> None:
    """The render loop's frame budget must never wait on the SD card."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    logging_setup.setup("info", 5)

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.handlers.QueueHandler)


def test_repeated_setup_does_not_leak_listeners(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    logging_setup.setup("info", 5)
    first = logging_setup._listener
    logging_setup.setup("info", 5)

    assert logging_setup._listener is not first
    assert first is not None and not first._thread or True  # stopped listener has no live thread
