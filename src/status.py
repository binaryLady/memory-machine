#!/usr/bin/env python3
"""Runtime status file writer and motion-player-status CLI."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("motion-player.status")


def _state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "motion-player"


def _status_file() -> Path:
    return _state_dir() / "status.json"


@dataclass
class Status:
    pid: int = 0
    start_time: float = 0.0
    state: str = "unknown"
    sensor_name: str = "unknown"
    sensor_engaged: bool = False
    lift_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    audio_sink: str = "unknown"
    display_mode: str = "unknown"
    last_error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def write(self) -> None:
        _state_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": self.pid,
            "start_time": self.start_time,
            "state": self.state,
            "sensor_name": self.sensor_name,
            "sensor_engaged": self.sensor_engaged,
            "lift_count": self.lift_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "audio_sink": self.audio_sink,
            "display_mode": self.display_mode,
            "last_error": self.last_error,
            **self.extra,
        }
        try:
            _status_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Could not write status file: %s", exc)


class StatusWriter:
    """Used by the running engine to keep status.json current."""

    def __init__(self) -> None:
        self._status = Status()
        self._status.start_time = time.monotonic()
        self._status.pid = os.getpid()

    def set_sensor(self, sensor: Any) -> None:
        self._status.sensor_name = getattr(sensor, "name", "unknown")
        try:
            self._status.sensor_engaged = bool(sensor.is_engaged())
        except Exception:  # noqa: BLE001
            self._status.sensor_engaged = False

    def set_state(self, state: str) -> None:
        self._status.state = state
        self.write()

    def lift_accepted(self) -> None:
        self._status.lift_count += 1
        self._status.accepted_count += 1
        self.write()

    def transition_rejected(self) -> None:
        self._status.rejected_count += 1
        self.write()

    def set_audio_sink(self, sink: str) -> None:
        self._status.audio_sink = sink

    def set_display_mode(self, mode: str) -> None:
        self._status.display_mode = mode

    def set_last_error(self, message: str) -> None:
        self._status.last_error = message
        self.write()

    def snapshot(self) -> dict[str, Any]:
        return dataclasses.asdict(self._status)

    def write(self) -> None:
        self._status.write()


def _systemd_restarts() -> int:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", "motion-player", "--property=NRestarts"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("NRestarts="):
                return int(line.split("=", 1)[1])
    except Exception:  # noqa: BLE001
        pass
    return 0


def _print_status(status: Status, json_mode: bool) -> None:
    uptime = max(0, time.monotonic() - status.start_time)
    restarts = _systemd_restarts()
    if json_mode:
        payload = {
            "uptime_s": uptime,
            "systemd_restarts": restarts,
            **status.__dict__,
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Process:           pid={status.pid}")
    print(f"Uptime:            {uptime:.1f}s")
    print(f"systemd restarts:  {restarts}")
    print(f"State:             {status.state}")
    print(f"Sensor:            {status.sensor_name} (engaged={status.sensor_engaged})")
    print(f"Lift count:        {status.lift_count}")
    print(f"Accepted/Rejected: {status.accepted_count}/{status.rejected_count}")
    print(f"Audio sink:        {status.audio_sink}")
    print(f"Display mode:      {status.display_mode}")
    print(f"Last error:        {status.last_error or '(none)'}")


def main(argv: list[str] | None = None) -> int:
    import config as config_module

    argv = argv or sys.argv[1:]
    json_mode = "--json" in argv
    status_file = _status_file()
    status = Status()
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            status = Status(**{k: v for k, v in data.items() if k in status.__dict__})
            status.extra = {k: v for k, v in data.items() if k not in status.__dict__}
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not read status file: {exc}", file=sys.stderr)

    _print_status(status, json_mode)
    print()

    try:
        cfg = config_module.load()
        problems = config_module.validate(cfg)
        print(cfg.dump())
        if problems:
            print("Config problems:")
            for problem in problems:
                print(f"  - {problem}")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not load config for status: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
