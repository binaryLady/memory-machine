"""The pad's one-shot controls, routed by the main loop rather than the state machine."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import motion_test


class FakeVideo:
    def __init__(self) -> None:
        self.showing = False
        self.audio_duration: float | None = None

    def toggle_kaleidoscope(self) -> bool:
        self.showing = not self.showing
        return self.showing

    def set_audio_duration(self, seconds: float) -> None:
        self.audio_duration = seconds


class FakeAudio:
    duration_s = 12.0

    def __init__(self, switches: bool = True) -> None:
        self.steps: list[int] = []
        self.audio_path = Path("/media/second.wav")
        self._switches = switches

    def cycle(self, step: int) -> bool:
        self.steps.append(step)
        return self._switches


class FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def record(self, name: str, **fields: Any) -> None:
        self.calls.append((name, fields))

    def set_extra(self, key: str, value: Any) -> None:
        self.calls.append((key, {"value": value}))


def config_with() -> Any:
    return SimpleNamespace(gamepad=SimpleNamespace())


def test_a_lift_is_left_for_the_state_machine() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("lift", video, audio, config_with(),
                                          recorder, recorder)

    assert handled is False


def test_the_kaleidoscope_button_switches_the_picture() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("kaleidoscope", video, audio, config_with(),
                                          recorder, recorder)

    assert handled is True
    assert video.showing is True
    assert ("kaleidoscope", {"showing": True}) in recorder.calls


def test_an_arrow_turns_to_the_next_sound_and_retimes_the_rewind() -> None:
    # reverse_rate = fit_to_audio measures the rewind against the sound, so a
    # different sound has to be measured again.
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("audio_next", video, audio, config_with(),
                                          recorder, recorder)

    assert handled is True
    assert audio.steps == [1]
    assert video.audio_duration == 12.0
    assert ("audio_chosen", {"file": "second.wav"}) in recorder.calls


def test_the_other_arrow_turns_back() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    motion_test._handle_control("audio_prev", video, audio, config_with(), recorder, recorder)

    assert audio.steps == [-1]


def test_an_arrow_with_nowhere_to_turn_is_still_swallowed() -> None:
    # It was the pad's event, not the state machine's, whether or not it did
    # anything — passing it on would only be logged as an unknown transition.
    video, audio, recorder = FakeVideo(), FakeAudio(switches=False), FakeRecorder()

    handled = motion_test._handle_control("audio_next", video, audio, config_with(),
                                          recorder, recorder)

    assert handled is True
    assert video.audio_duration is None
    assert recorder.calls == []
