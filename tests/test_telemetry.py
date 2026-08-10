from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Callable

import config as config_module
import status as status_module
from pathlib import Path
from telemetry import Telemetry


class _TelemetryHandler(BaseHTTPRequestHandler):
    def __init__(self, collector: list[dict[str, Any]], *args: Any, **kwargs: Any) -> None:
        self._collector = collector
        super().__init__(*args, **kwargs)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            data = []
        self._collector.extend(data if isinstance(data, list) else [data])
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _make_server(collector: list[dict[str, Any]]) -> HTTPServer:
    def handler(*args: Any, **kwargs: Any) -> _TelemetryHandler:
        return _TelemetryHandler(collector, *args, **kwargs)

    server = HTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


@dataclass(frozen=True)
class _TelemetryConfig:
    enabled: bool
    endpoint_url: str
    interval_s: int
    batch_size: int
    timeout_s: int
    log_tail_lines: int


@dataclass
class _Config:
    telemetry: _TelemetryConfig


def _fake_status() -> status_module.StatusWriter:
    writer = status_module.StatusWriter()
    writer._status.state = "IDLE"
    writer._status.lift_count = 3
    writer._status.accepted_count = 4
    writer._status.rejected_count = 1
    return writer


def test_disabled_telemetry_does_not_send() -> None:
    collector: list[dict[str, Any]] = []
    server = _make_server(collector)
    url = f"http://127.0.0.1:{server.server_port}/telemetry"
    cfg = _Config(_TelemetryConfig(enabled=False, endpoint_url=url, interval_s=1, batch_size=10, timeout_s=2, log_tail_lines=0))
    tel = Telemetry(cfg, _fake_status())
    tel.start()
    tel.event("lift")
    time.sleep(0.1)
    tel.stop()
    server.shutdown()
    assert collector == []


def test_event_is_posted_to_endpoint() -> None:
    collector: list[dict[str, Any]] = []
    server = _make_server(collector)
    url = f"http://127.0.0.1:{server.server_port}/telemetry"
    cfg = _Config(_TelemetryConfig(enabled=True, endpoint_url=url, interval_s=60, batch_size=10, timeout_s=2, log_tail_lines=0))
    tel = Telemetry(cfg, _fake_status())
    tel.start()
    tel.event("lift", state="ENGAGED")
    time.sleep(0.2)
    tel.stop()
    server.shutdown()
    assert len(collector) >= 1
    first = collector[0]
    assert first["type"] == "event"
    assert first["event"] == "lift"
    assert first["state"] == "ENGAGED"


def test_heartbeat_is_sent_on_interval() -> None:
    collector: list[dict[str, Any]] = []
    server = _make_server(collector)
    url = f"http://127.0.0.1:{server.server_port}/telemetry"
    cfg = _Config(_TelemetryConfig(enabled=True, endpoint_url=url, interval_s=1, batch_size=10, timeout_s=2, log_tail_lines=0))
    tel = Telemetry(cfg, _fake_status())
    tel.start()
    # No sensor is needed for heartbeat state fields.
    end = time.monotonic() + 2.5
    while time.monotonic() < end:
        tel.heartbeat()
        time.sleep(0.1)
    tel.stop()
    server.shutdown()
    heartbeats = [item for item in collector if item.get("event") == "heartbeat"]
    assert len(heartbeats) >= 1
    assert heartbeats[0]["lift_count"] == 3
    assert heartbeats[0]["accepted_count"] == 4
    assert heartbeats[0]["rejected_count"] == 1


def test_heartbeat_includes_log_tail() -> None:
    import tempfile

    collector: list[dict[str, Any]] = []
    server = _make_server(collector)
    url = f"http://127.0.0.1:{server.server_port}/telemetry"
    cfg = _Config(_TelemetryConfig(enabled=True, endpoint_url=url, interval_s=60, batch_size=10, timeout_s=2, log_tail_lines=5))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("line one\n")
        f.write("line two\n")
        log_path = f.name

    tel = Telemetry(cfg, _fake_status(), Path(log_path))
    tel.start()
    tel.heartbeat()
    time.sleep(0.2)
    tel.stop()
    server.shutdown()
    heartbeats = [item for item in collector if item.get("event") == "heartbeat"]
    assert len(heartbeats) == 1
    assert heartbeats[0]["log_tail"] == ["line one\n", "line two\n"]


def test_telemetry_url_must_be_http_or_https() -> None:
    import textwrap
    from pathlib import Path

    path = Path("/tmp/test_telemetry_config.ini")
    path.write_text(textwrap.dedent("""
        [telemetry]
        enabled = true
        endpoint_url = javascript:alert(1)
        interval_s = 60
        batch_size = 10
        timeout_s = 5
    """))
    cfg = config_module.load(str(path))
    problems = config_module.validate(cfg)
    assert any("http:// or https://" in p for p in problems)
