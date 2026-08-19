"""Centralised logging setup for motion-player."""
from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import queue
from pathlib import Path

# Kept module-level so repeated setup() calls (tests) can stop the previous
# listener instead of leaking threads.
_listener: logging.handlers.QueueListener | None = None


def setup(log_level: str, log_max_mb: int, console: bool = False) -> logging.Logger:
    """Configure root logging to a size-capped rotating file.

    log_max_mb is interpreted as a hard cap across the active file plus all
    rotated backups. We split that budget across five files so the total on disk
    stays bounded near the requested cap.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    app_state = state_dir / "motion-player"
    app_state.mkdir(parents=True, exist_ok=True)
    log_path = app_state / "motion-player.log"

    # Five rotated files means each file is roughly log_max_mb / 5 MB.
    backup_count = 4
    per_file_bytes = int((log_max_mb * 1024 * 1024) / (backup_count + 1))
    per_file_bytes = max(per_file_bytes, 1_048_576)  # at least 1 MB

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=per_file_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Remove existing handlers so repeated calls in tests don't duplicate.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Log records cross a queue to a background thread that owns the actual
    # file (and console) writes. The render loop has a 33ms frame budget; a
    # log write that hits a slow SD card must not spend it.
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None

    sinks: list[logging.Handler] = [file_handler]
    if console:
        # Without this, --verbose only raises the level and everything still
        # goes to the log file, so a foreground run looks like it has hung.
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        console_handler.setLevel(logging.DEBUG)
        sinks.append(console_handler)

    log_queue: queue.Queue = queue.Queue(maxsize=10000)
    root.addHandler(logging.handlers.QueueHandler(log_queue))
    _listener = logging.handlers.QueueListener(log_queue, *sinks, respect_handler_level=True)
    _listener.start()
    atexit.register(_listener.stop)

    # Dedicated transition logger; all sensor raw and accepted edges go here.
    transitions = logging.getLogger("motion-player.transitions")
    transitions.setLevel(logging.DEBUG)

    app_logger = logging.getLogger("motion-player")
    app_logger.setLevel(level)
    app_logger.info("Logging initialised: %s (level=%s, max_mb=%s)", log_path, log_level, log_max_mb)

    return app_logger
