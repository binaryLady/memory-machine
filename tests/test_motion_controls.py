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
        self.switched_to: Path | None = None
        self._switches = switches

    def switch_to(self, path: Path) -> bool:
        self.switched_to = path
        return self._switches


class FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def record(self, name: str, **fields: Any) -> None:
        self.calls.append((name, fields))

    def set_extra(self, key: str, value: Any) -> None:
        self.calls.append((key, {"value": value}))


def config_with(audio: dict[str, Path]) -> Any:
    return SimpleNamespace(gamepad=SimpleNamespace(audio=audio))


def test_a_lift_is_left_for_the_state_machine() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("lift", video, audio, config_with({}),
                                          recorder, recorder)

    assert handled is False


def test_the_kaleidoscope_button_switches_the_picture() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("kaleidoscope", video, audio, config_with({}),
                                          recorder, recorder)

    assert handled is True
    assert video.showing is True
    assert ("kaleidoscope", {"showing": True}) in recorder.calls


def test_an_arrow_chooses_its_sound_and_retimes_the_rewind() -> None:
    # reverse_rate = fit_to_audio measures the rewind against the sound, so a
    # different sound has to be measured again.
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()
    chosen = Path("/media/second.wav")

    handled = motion_test._handle_control("audio_left", video, audio,
                                          config_with({"left": chosen}), recorder, recorder)

    assert handled is True
    assert audio.switched_to == chosen
    assert video.audio_duration == 12.0


def test_an_arrow_with_no_sound_behind_it_is_still_swallowed() -> None:
    # It was the pad's event, not the state machine's, whether or not it does
    # anything — passing it on would only be logged as an unknown transition.
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("audio_up", video, audio, config_with({}),
                                          recorder, recorder)

    assert handled is True
    assert audio.switched_to is None
