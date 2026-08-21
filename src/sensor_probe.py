#!/usr/bin/env python3
"""motion-player-sensor: check the sensor the piece is configured to use.

Two questions have been answered by hand in a markdown file for weeks: has a
lift ever actually been accepted from real hardware, and has the rewind ever
run end to end. Both are already in the log; this reads them out and says so
plainly, so the answer is a command rather than a memory.

The parsing and formatting below are pure functions over log lines, so they are
tested without a Pi, a GPIO pin, or an I2C bus.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_LOG_NAME = "motion-player.log"

# Lines the engine already writes. Kept together so a change to any of them is
# one edit here, not a hunt.
_VIDEO_RE = re.compile(r"Video loaded: (?P<path>\S+) frames=(?P<frames>\d+) fps=(?P<fps>[\d.]+)")
_AUDIO_RE = re.compile(r"Audio loaded: (?P<path>\S+) duration=(?P<duration>[\d.]+)s")
_STEP_RE = re.compile(r"reverse_rate=(?P<rate>\S+) reverse_step=(?P<step>[\d.]+)")
_LIFT_RE = re.compile(r"transition sensor=(?P<sensor>\S+) event=lift .*accepted=true")
_REVERSE_RE = re.compile(r"Playback REVERSE: (?P<detail>.+)")


def log_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "motion-player" / _LOG_NAME


def read_log_lines(path: Path) -> list[str]:
    """The log as text. Decoded leniently — it can carry control bytes."""
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_log(lines: list[str]) -> dict[str, Any]:
    """Pull the facts the report needs out of the engine's own log lines."""
    facts: dict[str, Any] = {
        "frames": None,
        "fps": None,
        "audio_duration_s": None,
        "reverse_rate": None,
        "reverse_step": None,
        "lift_sensors": [],
        "reverse_seen": None,
    }
    for line in lines:
        match = _VIDEO_RE.search(line)
        if match:
            facts["frames"] = int(match.group("frames"))
            facts["fps"] = float(match.group("fps"))
        match = _AUDIO_RE.search(line)
        if match:
            facts["audio_duration_s"] = float(match.group("duration"))
        match = _STEP_RE.search(line)
        if match:
            facts["reverse_rate"] = match.group("rate")
            facts["reverse_step"] = float(match.group("step"))
        match = _LIFT_RE.search(line)
        if match:
            sensor = match.group("sensor")
            if sensor not in facts["lift_sensors"]:
                facts["lift_sensors"].append(sensor)
        match = _REVERSE_RE.search(line)
        if match:
            facts["reverse_seen"] = match.group("detail")
    return facts


def hold_seconds(frames: int | None, fps: float | None, step: float | None) -> float | None:
    """How long a visitor must hold on to reach the turn.

    The same arithmetic as VideoEngine.rewind_duration_s: each frame interval
    advances reverse_step frames, so covering the clip takes frame_count /
    reverse_step intervals of 1/fps each. Computed here from the log so the
    report needs neither OpenCV nor the media.
    """
    if not frames or not fps or not step:
        return None
    if frames <= 0 or fps <= 0 or step <= 0:
        return None
    return frames / (step * fps)


def format_report(sensor_cfg: dict[str, Any], audio_cfg: dict[str, Any],
                  hardware: str, facts: dict[str, Any]) -> str:
    """The whole report as text. Pure, so its wording is testable."""
    out: list[str] = []
    sensor_type = sensor_cfg.get("sensor_type", "?")
    out.append("Configured")
    out.append(f"  sensor_type   {sensor_type}")
    out.append(f"  engaged_when  {sensor_cfg.get('engaged_when', '?')}")
    if sensor_type == "capacitive":
        out.append(f"  i2c_address   {sensor_cfg.get('i2c_address') or '0x5a'}"
                   f"  channel {sensor_cfg.get('touch_channel', 0)}")
    else:
        out.append(f"  gpio_pin      {sensor_cfg.get('gpio_pin', '?')}"
                   f"  pull_up {sensor_cfg.get('pull_up', '?')}")
    out.append(f"  audio_mode    {audio_cfg.get('audio_mode', '?')}")
    out.append(f"  audio_sink    {audio_cfg.get('audio_sink', '?')}")
    out.append("")
    out.append("Hardware")
    out.append(f"  {hardware}")
    out.append("")

    hold = hold_seconds(facts.get("frames"), facts.get("fps"), facts.get("reverse_step"))
    out.append("The hold")
    if hold is None:
        out.append("  unknown — the log has no 'Video loaded' line yet; start the piece once")
    else:
        out.append(f"  a visitor must hold for {hold:.0f} seconds to reach the turn")
        out.append(f"  ({facts['frames']} frames at {facts['fps']:.2f} fps, "
                   f"reverse_rate={facts.get('reverse_rate')} step={facts.get('reverse_step')})")
        if hold > 120:
            out.append("  that is a long time to ask someone to keep still — raising")
            out.append("  playback.reverse_rate above 1.0 shortens it without touching the audio")
    out.append("")

    out.append("Verdicts")
    lifts = facts.get("lift_sensors") or []
    if lifts:
        out.append(f"  PASS  a lift has been accepted, from: {', '.join(lifts)}")
    else:
        out.append("  FAIL  no lift has ever been accepted — the sensor is still decorative")
    if facts.get("reverse_seen"):
        out.append(f"  PASS  the rewind has run: {facts['reverse_seen']}")
    else:
        out.append("  FAIL  no 'Playback REVERSE' line — the rewind has never been measured")
    return "\n".join(out)


def _i2c_report(bus: int, address: int) -> str:
    """Whether the touch chip answers on the bus."""
    try:
        result = subprocess.run(
            ["i2cdetect", "-y", str(bus)],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run i2cdetect ({exc}); install i2c-tools"
    wanted = f"{address:02x}"
    if wanted in result.stdout.replace("--", "").split():
        return f"MPR121 answers at 0x{wanted} on i2c-{bus}"
    return (f"nothing at 0x{wanted} on i2c-{bus} — check the wiring, and that "
            f"I2C is enabled (raspi-config)")


def _gpio_report(pin: int, pull_up: bool) -> str:
    try:
        from gpiozero import Button  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        return f"gpiozero unavailable ({exc}); no GPIO reading possible"
    try:
        button = Button(pin, pull_up=pull_up)
    except Exception as exc:  # noqa: BLE001
        return (f"GPIO {pin} could not be read ({exc}) — the engine may still hold it; "
                f"stop it with motion-player-toggle --stop")
    try:
        return f"GPIO {pin} reads {'closed' if button.is_pressed else 'open'} right now"
    finally:
        button.close()


def describe_hardware(sensor_cfg: dict[str, Any]) -> str:
    sensor_type = sensor_cfg.get("sensor_type", "")
    if sensor_type in {"keyboard", "none"}:
        return f"no hardware to check for sensor_type={sensor_type}"
    if sensor_type == "capacitive":
        return _i2c_report(int(sensor_cfg.get("i2c_bus", 1)),
                           int(sensor_cfg.get("i2c_address") or 0x5A))
    return _gpio_report(int(sensor_cfg.get("gpio_pin", 4)),
                        bool(sensor_cfg.get("pull_up", True)))


def _load_config() -> Any:
    import config as config_module

    return config_module.load()


def report() -> int:
    cfg = _load_config()
    sensor_cfg = {
        "sensor_type": cfg.sensor.sensor_type,
        "engaged_when": cfg.sensor.engaged_when,
        "gpio_pin": cfg.sensor.gpio_pin,
        "pull_up": cfg.sensor.pull_up,
        "i2c_address": cfg.sensor.i2c_address,
        "touch_channel": cfg.sensor.touch_channel,
        "i2c_bus": 1,
    }
    audio_cfg = {"audio_mode": cfg.audio.audio_mode, "audio_sink": cfg.audio.audio_sink}
    facts = parse_log(read_log_lines(log_path()))
    print(format_report(sensor_cfg, audio_cfg, describe_hardware(sensor_cfg), facts))
    return 0


def _watch_digital(pin: int, pull_up: bool, bounce_ms: int) -> None:
    from gpiozero import Button  # type: ignore[import-untyped]

    button = Button(pin, pull_up=pull_up, bounce_time=bounce_ms / 1000.0)
    contact_at: list[float] = []

    def on_press() -> None:
        contact_at.append(time.monotonic())
        print("contact", flush=True)

    def on_release() -> None:
        held = time.monotonic() - contact_at.pop() if contact_at else 0.0
        print(f"release  held {held:.2f}s{_hold_note(held)}", flush=True)

    button.when_pressed = on_press
    button.when_released = on_release
    print(f"watching GPIO {pin} — touch and let go; Ctrl+C to stop")
    print("now:", "closed" if button.is_pressed else "open")
    while True:
        time.sleep(0.1)


def _watch_capacitive(address: int, channel: int) -> None:
    import adafruit_mpr121  # type: ignore[import-untyped]
    import board  # type: ignore[import-untyped]
    import busio  # type: ignore[import-untyped]

    device = adafruit_mpr121.MPR121(busio.I2C(board.SCL, board.SDA), address=address)
    print(f"watching MPR121 0x{address:02x} channel {channel} — touch and let go; Ctrl+C to stop")
    last = False
    since = time.monotonic()
    while True:
        now = bool(device[channel].value)
        if now != last:
            if now:
                print("contact", flush=True)
                since = time.monotonic()
            else:
                held = time.monotonic() - since
                print(f"release  held {held:.2f}s{_hold_note(held)}", flush=True)
            last = now
        time.sleep(0.02)


def _hold_note(held: float) -> str:
    """A tap and a held contact drive the piece completely differently."""
    if held < 0.5:
        return "  <- a tap, not a held contact; the piece needs continuous contact"
    return ""


def _service(action: str) -> None:
    subprocess.run(["motion-player-toggle", f"--{action}"], check=False)


def probe() -> int:
    cfg = _load_config()
    sensor_type = cfg.sensor.sensor_type
    if sensor_type in {"keyboard", "none"}:
        print(f"sensor_type is {sensor_type}; there is no hardware to probe.")
        return 1

    print("Stopping the engine — it holds the sensor while it runs.")
    _service("stop")
    try:
        if sensor_type == "capacitive":
            _watch_capacitive(int(cfg.sensor.i2c_address or 0x5A), cfg.sensor.touch_channel)
        else:
            _watch_digital(cfg.sensor.gpio_pin, cfg.sensor.pull_up, cfg.sensor.bounce_time_ms)
    except KeyboardInterrupt:
        print()
    except Exception as exc:  # noqa: BLE001
        print(f"Probe failed: {exc}")
        return 1
    finally:
        print("Restarting the engine.")
        _service("start")
    return 0


USAGE = """motion-player-sensor — check the sensor the piece is configured to use.

  motion-player-sensor --report   what is configured, what is wired, what the log saw
  motion-player-sensor --probe    watch it live with the engine stopped, then restart it

--report changes nothing and is safe to run during the show. --probe stops the
engine for as long as it runs, so the piece is dark while you are watching.
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--probe" in argv:
        return probe()
    if "--report" in argv or not argv:
        return report()
    print(USAGE)
    return 0 if "--help" in argv or "-h" in argv else 2


if __name__ == "__main__":
    sys.exit(main())
