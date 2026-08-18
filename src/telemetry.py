"""Remote telemetry over HTTP for unattended monitoring."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("motion-player.telemetry")


@dataclass
class _HeartbeatData:
    uptime_s: float
    state: str
    sensor_name: str
    sensor_engaged: bool
    lift_count: int
    accepted_count: int
    rejected_count: int
    audio_sink: str
    last_error: str


class Telemetry:
    """Non-blocking telemetry sender.

    Events are queued and sent by a daemon thread so the main loop is never
    blocked by the network. Heartbeats are emitted on a fixed interval.
    """

    def __init__(self, config: Any, status: Any, log_path: Path | None = None) -> None:
        self._enabled = config.telemetry.enabled
        self._endpoint = config.telemetry.endpoint_url.strip()
        self._interval_s = max(1, config.telemetry.interval_s)
        self._batch_size = max(1, config.telemetry.batch_size)
        self._timeout_s = max(1, config.telemetry.timeout_s)
        self._log_tail_lines = max(0, config.telemetry.log_tail_lines)
        self._log_path = log_path
        self._status = status
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1000)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_time = time.monotonic()
        # None means "never sent"; 0.0 would gate the first heartbeat on host
        # uptime, since time.monotonic() counts from boot on Linux.
        self._last_heartbeat: float | None = None

        if self._enabled and not self._endpoint:
            LOGGER.warning("Telemetry enabled but endpoint_url is empty; disabling")
            self._enabled = False

    def start(self) -> None:
        if not self._enabled:
            LOGGER.debug("Telemetry disabled")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        LOGGER.info("Telemetry started: %s", self._endpoint)

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def event(self, event_type: str, **kwargs: Any) -> None:
        """Record an event. Never blocks the caller."""
        if not self._enabled:
            return
        payload = {
            "type": "event",
            "event": event_type,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "monotonic_s": time.monotonic() - self._start_time,
            **kwargs,
        }
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            LOGGER.warning("Telemetry queue full; dropping event %s", event_type)

    def heartbeat(self, sensor: Any | None = None) -> None:
        """Queue a heartbeat payload if the interval has elapsed."""
        if not self._enabled:
            return
        now = time.monotonic()
        if self._last_heartbeat is not None and now - self._last_heartbeat < self._interval_s:
            return
        self._last_heartbeat = now
        snapshot = self._status.snapshot()
        if not snapshot:
            return
        data = _HeartbeatData(
            uptime_s=now - snapshot.get("start_time", self._start_time),
            state=snapshot.get("state", "unknown"),
            sensor_name=snapshot.get("sensor_name", "unknown"),
            sensor_engaged=bool(snapshot.get("sensor_engaged", False)),
            lift_count=int(snapshot.get("lift_count", 0)),
            accepted_count=int(snapshot.get("accepted_count", 0)),
            rejected_count=int(snapshot.get("rejected_count", 0)),
            audio_sink=snapshot.get("audio_sink", "unknown"),
            last_error=snapshot.get("last_error", ""),
        )
        raw = False
        raw_label: str | None = None
        if sensor is not None:
            try:
                raw = bool(sensor.is_engaged())
                raw_label = "engaged" if raw else "idle"
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Could not read sensor for telemetry heartbeat: %s", exc)
        self.event(
            "heartbeat",
            state=data.state,
            sensor=data.sensor_name,
            sensor_engaged=data.sensor_engaged,
            sensor_raw=raw_label,
            uptime_s=data.uptime_s,
            lift_count=data.lift_count,
            accepted_count=data.accepted_count,
            rejected_count=data.rejected_count,
            audio_sink=data.audio_sink,
            last_error=data.last_error,
            log_tail=self._read_log_tail(),
        )

    def _read_log_tail(self) -> list[str]:
        if self._log_path is None or self._log_tail_lines <= 0:
            return []
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()[-self._log_tail_lines :]
        except OSError as exc:
            LOGGER.debug("Could not read log tail for telemetry: %s", exc)
            return []

    def _run(self) -> None:
        batch: list[dict[str, Any]] = []
        next_heartbeat = time.monotonic() + self._interval_s
        while not self._stop_event.is_set():
            now = time.monotonic()

            # Drain the queue up to batch_size or until a heartbeat is due.
            deadline = min(next_heartbeat, now + self._timeout_s)
            wait = max(0.0, deadline - now)
            try:
                item = self._queue.get(timeout=wait)
            except queue.Empty:
                item = None

            if item is None:
                # Either timeout or stop signal.
                if self._stop_event.is_set():
                    break
            else:
                batch.append(item)

            if len(batch) >= self._batch_size or (now >= next_heartbeat and batch):
                self._send(batch)
                batch = []

            if now >= next_heartbeat:
                next_heartbeat = now + self._interval_s

        # Flush remaining events on stop.
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                batch.append(item)
        if batch:
            self._send(batch)

    def _send(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        payload = json.dumps(batch, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "motion-player-telemetry/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                if resp.status >= 400:
                    LOGGER.warning("Telemetry endpoint returned %s", resp.status)
        except urllib.error.URLError as exc:
            LOGGER.warning("Telemetry send failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Telemetry send unexpected error: %s", exc)
