"""USB gamepad backend — the visitor holds a button and the piece rewinds.

Read straight from the kernel's joystick device rather than through a library:
every event is the same eight bytes, it needs no window focus (the piece runs
fullscreen with nothing listening for keys), and the parsing is a pure function
that tests without a pad plugged in.

A pad is also the one input that survives being knocked: unplugged mid-hold it
releases rather than stranding the piece engaged, and it is picked up again as
soon as it is plugged back in, without a restart.
"""
from __future__ import annotations

import glob
import logging
import os
import select
import struct
import threading
import time
from pathlib import Path
from typing import Any

from .base import Sensor, SensorConfig

LOGGER = logging.getLogger("motion-player.sensor.gamepad")

# struct js_event: __u32 time, __s16 value, __u8 type, __u8 number.
_EVENT_FORMAT = "IhBB"
_EVENT_SIZE = struct.calcsize(_EVENT_FORMAT)
_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80

# The arrows are an axis pair on most pads, not buttons: held fully over reads
# ±32767, and half that is well past any resting drift.
_AXIS_THRESHOLD = 16384
_DIRECTIONS = ("left", "right", "up", "down")
# axis number -> (what its negative end is called, what its positive end is)
_AXIS_DIRECTIONS = {0: ("left", "right"), 1: ("up", "down")}

# A pad with nothing configured for it still holds: any button, no other job.
_DEFAULT_NUMBERS: dict[str, int | None] = {
    "a": 1, "b": 0, "select": 2, "start": 3,
    "up": None, "down": None, "left": None, "right": None,
}
_DEFAULT_JOBS: dict[str, tuple[str, ...]] = {"hold": ("any",)}

_DEVICE_GLOB = "/dev/input/js*"
_REOPEN_INTERVAL_S = 1.0
_SELECT_TIMEOUT_S = 0.5


def parse_js_event(data: bytes) -> tuple[str, int, int] | None:
    """One eight-byte joystick event as (kind, number, value).

    The kernel replays the current position of every control when the device is
    opened, flagged JS_EVENT_INIT. Those are dropped: a pad resting on a button
    at boot must not read as a visitor arriving.
    """
    if len(data) != _EVENT_SIZE:
        return None
    _timestamp, value, kind, number = struct.unpack(_EVENT_FORMAT, data)
    if kind & _JS_EVENT_INIT:
        return None
    if kind == _JS_EVENT_BUTTON:
        return ("button", number, value)
    if kind == _JS_EVENT_AXIS:
        return ("axis", number, value)
    return None


def controls_from_event(numbers: dict[str, int | None], kind: str, number: int,
                        value: int) -> list[tuple[str, bool]]:
    """Which named controls this event moves, and whether each is now held.

    A button moves one control. An axis carries both of its directions at once:
    pushed one way is the release of the other, which is how a thumb rolling
    from left to right lets go of left in the same event.
    """
    if kind == "button":
        for name, configured in numbers.items():
            if configured is not None and configured == number:
                return [(name, bool(value))]
        # A button nobody has named is still usable as b<number>.
        return [(f"b{number}", bool(value))]

    pair = _AXIS_DIRECTIONS.get(number)
    if pair is None:
        return []
    low, high = pair
    moved: list[tuple[str, bool]] = []
    # A direction given a number of its own is a button on this pad, not an axis.
    if numbers.get(low) is None:
        moved.append((low, value <= -_AXIS_THRESHOLD))
    if numbers.get(high) is None:
        moved.append((high, value >= _AXIS_THRESHOLD))
    return moved


def jobs_for(jobs: dict[str, tuple[str, ...]], control: str) -> list[str]:
    """The jobs a control drives. "any" in a job means any button, not an arrow."""
    out = []
    for job, controls in jobs.items():
        if control in controls or ("any" in controls and control not in _DIRECTIONS):
            out.append(job)
    return out


def find_device(configured: str) -> str | None:
    """The joystick device to read, or None if there is none to read."""
    configured = (configured or "auto").strip()
    if configured.lower() != "auto":
        return configured if Path(configured).exists() else None
    devices = sorted(glob.glob(_DEVICE_GLOB))
    return devices[0] if devices else None


def device_name(path: str) -> str:
    """What the pad calls itself, for the log and the report."""
    name = Path("/sys/class/input") / Path(path).name / "device" / "name"
    try:
        return name.read_text(encoding="utf-8", errors="replace").strip() or "unnamed pad"
    except OSError:
        return "unnamed pad"


class GamepadSensor(Sensor):
    """A USB gamepad read from /dev/input/js*."""

    def __init__(self, config: Any, gamepad: Any = None) -> None:
        super().__init__("gamepad", SensorConfig(
            engaged_when=config.engaged_when,
            bounce_time_ms=config.bounce_time_ms,
            min_lift_ms=config.min_lift_ms,
            min_replace_ms=config.min_replace_ms,
        ))
        self._configured = config.gamepad_device
        self._numbers = dict(getattr(gamepad, "numbers", None) or _DEFAULT_NUMBERS)
        self._jobs = dict(getattr(gamepad, "jobs", None) or _DEFAULT_JOBS)
        self._held: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Missing hardware is a warning, not a failure: the reader waits for the
        # pad instead of the piece falling back to a keyboard nobody has.
        path = find_device(self._configured)
        if path is None:
            LOGGER.warning("No gamepad at %s yet; waiting for one", self._configured)
        else:
            LOGGER.info("Gamepad: %s (%s), hold=%s", path, device_name(path),
                        "+".join(self._jobs.get("hold", ())) or "nothing")

    def _start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _open(self) -> int | None:
        path = find_device(self._configured)
        if path is None:
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            LOGGER.warning("Gamepad %s could not be opened (%s)", path, exc)
            return None
        LOGGER.info("Gamepad open: %s (%s)", path, device_name(path))
        return descriptor

    def _read_loop(self) -> None:
        descriptor: int | None = None
        while not self._stop_event.is_set():
            if descriptor is None:
                descriptor = self._open()
                if descriptor is None:
                    self._stop_event.wait(_REOPEN_INTERVAL_S)
                    continue
            try:
                ready, _, _ = select.select([descriptor], [], [], _SELECT_TIMEOUT_S)
                if not ready:
                    continue
                data = os.read(descriptor, _EVENT_SIZE)
            except (OSError, ValueError) as exc:
                LOGGER.warning("Gamepad went away (%s); waiting for it to come back", exc)
                data = b""
            if not data:
                os.close(descriptor)
                descriptor = None
                self._release_all()
                self._stop_event.wait(_REOPEN_INTERVAL_S)
                continue
            self._handle(parse_js_event(data))

        if descriptor is not None:
            os.close(descriptor)

    def _handle(self, event: tuple[str, int, int] | None) -> None:
        if event is None:
            return
        for control, pressed in controls_from_event(self._numbers, *event):
            jobs = jobs_for(self._jobs, control)
            if "hold" in jobs:
                self._apply_hold(control, pressed)
            if not pressed:
                # Every other job happens on the press. A release that also
                # ended a hold has already been dealt with above.
                continue
            for job in jobs:
                if job != "hold":
                    self._emit_action(job)

    def _apply_hold(self, control: str, pressed: bool) -> None:
        with self._lock:
            before = bool(self._held)
            if pressed:
                self._held.add(control)
            else:
                self._held.discard(control)
            after = bool(self._held)
        if after != before:
            self._on_raw_change(after)

    def _emit_action(self, name: str) -> None:
        """Put a one-shot action on the same queue the lifts travel on.

        The engine picks these off before the state machine sees them: choosing
        a sound or switching the picture is not a state the piece is in.
        """
        LOGGER.info("gamepad action=%s", name)
        if self._events is not None:
            self._events.put((name, time.monotonic(), self._name))

    def _release_all(self) -> None:
        """An unplugged pad lets go, rather than leaving the piece held open."""
        with self._lock:
            was_held = bool(self._held)
            self._held.clear()
        if was_held:
            self._on_raw_change(False)

    def is_engaged(self) -> bool:
        with self._lock:
            return bool(self._held)
