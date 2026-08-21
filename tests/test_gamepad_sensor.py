"""Gamepad backend tests: the event parsing, and what each control does.

Both are pure functions over the kernel's eight-byte joystick events, so the
whole decision the piece makes about a visitor's thumb is tested with no pad
plugged in.
"""
from __future__ import annotations

import queue
import struct
from types import SimpleNamespace

from sensors.gamepad import (
    GamepadSensor,
    controls_from_event,
    device_name,
    find_device,
    jobs_for,
    parse_js_event,
)

_BUTTON = 0x01
_AXIS = 0x02
_INIT = 0x80

# What the shipped config says this pad reports, arrows left as axes.
NUMBERS = {"a": 1, "b": 0, "select": 2, "start": 3,
           "up": None, "down": None, "left": None, "right": None}
JOBS = {"hold": ("start", "select"), "kaleidoscope": ("a", "b"),
        "audio_next": ("right", "down"), "audio_prev": ("left", "up")}


def js_event(kind: int, number: int, value: int, timestamp: int = 0) -> bytes:
    return struct.pack("IhBB", timestamp, value, kind, number)


def test_parse_reads_a_button_press_and_release() -> None:
    assert parse_js_event(js_event(_BUTTON, 1, 1)) == ("button", 1, 1)
    assert parse_js_event(js_event(_BUTTON, 1, 0)) == ("button", 1, 0)


def test_parse_reads_an_arrow_as_an_axis() -> None:
    assert parse_js_event(js_event(_AXIS, 0, -32767)) == ("axis", 0, -32767)


def test_parse_drops_the_replay_the_kernel_sends_on_open() -> None:
    # A pad resting on a button at boot must not read as a visitor arriving.
    assert parse_js_event(js_event(_BUTTON | _INIT, 1, 1)) is None
    assert parse_js_event(js_event(_AXIS | _INIT, 0, 0)) is None


def test_parse_ignores_a_short_read() -> None:
    assert parse_js_event(b"\x00\x00\x00") is None


def test_a_button_is_named_by_the_number_the_pad_reports() -> None:
    assert controls_from_event(NUMBERS, "button", 1, 1) == [("a", True)]
    assert controls_from_event(NUMBERS, "button", 3, 0) == [("start", False)]


def test_a_button_nobody_named_is_still_usable_by_number() -> None:
    assert controls_from_event(NUMBERS, "button", 7, 1) == [("b7", True)]


def test_an_axis_carries_both_of_its_directions() -> None:
    # Rolling from left to right lets go of left in the same event as it takes
    # hold of right, which no per-direction reading would catch.
    assert controls_from_event(NUMBERS, "axis", 0, -32767) == [("left", True), ("right", False)]
    assert controls_from_event(NUMBERS, "axis", 0, 32767) == [("left", False), ("right", True)]
    assert controls_from_event(NUMBERS, "axis", 0, 0) == [("left", False), ("right", False)]


def test_a_direction_given_a_number_is_read_as_a_button_instead() -> None:
    numbers = {**NUMBERS, "up": 12}

    assert controls_from_event(numbers, "button", 12, 1) == [("up", True)]
    # Axis 1 now only carries the direction still left on it.
    assert controls_from_event(numbers, "axis", 1, 32767) == [("down", True)]


def test_an_unknown_axis_moves_nothing() -> None:
    assert controls_from_event(NUMBERS, "axis", 5, 32767) == []


def test_jobs_are_looked_up_by_control_name() -> None:
    assert jobs_for(JOBS, "start") == ["hold"]
    assert jobs_for(JOBS, "a") == ["kaleidoscope"]
    assert jobs_for(JOBS, "left") == ["audio_prev"]


def test_any_means_any_button_but_never_an_arrow() -> None:
    jobs = {"hold": ("any",)}

    assert jobs_for(jobs, "a") == ["hold"]
    assert jobs_for(jobs, "b7") == ["hold"]
    assert jobs_for(jobs, "left") == []


def test_a_named_device_is_used_only_when_it_is_there(tmp_path) -> None:
    pad = tmp_path / "js9"
    assert find_device(str(pad)) is None
    pad.write_bytes(b"")
    assert find_device(str(pad)) == str(pad)


def test_a_pad_that_cannot_say_its_name_still_has_one() -> None:
    assert device_name("/dev/input/js-nothing-here") == "unnamed pad"


def sensor_config(**overrides: object) -> SimpleNamespace:
    base = {
        "engaged_when": "closed",
        "bounce_time_ms": 0,
        "min_lift_ms": 0,
        "min_replace_ms": 0,
        "gamepad_device": "/nowhere/js0",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def gamepad_config(**overrides: object) -> SimpleNamespace:
    base = {"numbers": NUMBERS, "jobs": JOBS}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_holding_a_second_hold_button_does_not_release_the_piece() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config())

    sensor._handle(("button", 3, 1))
    assert sensor.is_engaged()
    sensor._handle(("button", 2, 1))
    sensor._handle(("button", 3, 0))
    # One thumb left the pad; the other is still holding it.
    assert sensor.is_engaged()
    sensor._handle(("button", 2, 0))
    assert not sensor.is_engaged()


def test_a_button_with_another_job_does_not_hold_the_piece() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config())

    sensor._handle(("button", 1, 1))

    assert not sensor.is_engaged(), "A is the kaleidoscope, not the rewind"


def test_the_kaleidoscope_fires_once_on_the_press() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config())
    events: queue.Queue = queue.Queue()
    sensor._events = events

    sensor._handle(("button", 1, 1))
    sensor._handle(("button", 1, 0))

    assert events.get_nowait()[0] == "kaleidoscope"
    assert events.empty(), "letting go is not a second toggle"


def test_the_arrows_turn_the_sound_deck_either_way() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config())
    events: queue.Queue = queue.Queue()
    sensor._events = events

    sensor._handle(("axis", 0, -32767))
    sensor._handle(("axis", 0, 0))
    sensor._handle(("axis", 1, 32767))

    assert events.get_nowait()[0] == "audio_prev"
    assert events.get_nowait()[0] == "audio_next"
    assert events.empty(), "letting an arrow go is not another turn"


def test_an_arrow_given_no_job_says_nothing() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config(jobs={"hold": ("any",)}))
    events: queue.Queue = queue.Queue()
    sensor._events = events

    sensor._handle(("axis", 0, -32767))

    assert events.empty()


def test_an_unplugged_pad_lets_go() -> None:
    sensor = GamepadSensor(sensor_config(), gamepad_config())
    sensor._handle(("button", 3, 1))

    sensor._release_all()

    assert not sensor.is_engaged()
