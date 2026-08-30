"""The pad's one-shot controls, routed by the main loop rather than the state machine."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import motion_test


class FakeVideo:
    def __init__(self, has_twin: bool = True) -> None:
        self.showing = False
        self.audio_duration: float | None = None
        self._has_twin = has_twin

    directions: list[bool] = []

    @property
    def showing_kaleidoscope(self) -> bool:
        return self.showing

    def set_kaleidoscope(self, wanted: bool) -> bool:
        if self._has_twin:
            self.showing = wanted
        return self.showing

    def set_direction(self, forward: bool) -> None:
        self.directions.append(forward)

    def toggle_kaleidoscope(self) -> bool:
        if self._has_twin:
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


class FakePanel:
    def __init__(self) -> None:
        self.notices: list[str] = []

    def set_notice(self, text: str) -> None:
        self.notices.append(text)


def config_with() -> Any:
    return SimpleNamespace(gamepad=SimpleNamespace())


def test_a_lift_is_left_for_the_state_machine() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    handled = motion_test._handle_control("lift", video, audio, config_with(),
                                          recorder, recorder, FakePanel())

    assert handled is False


def test_the_kaleidoscope_button_switches_the_picture() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    panel = FakePanel()
    handled = motion_test._handle_control("kaleidoscope", video, audio, config_with(),
                                          recorder, recorder, panel)

    assert handled is True
    assert video.showing is True
    assert ("kaleidoscope", {"showing": True}) in recorder.calls
    assert panel.notices == [motion_test.NOTICE_LABELS["kaleidoscope_on"]]


def test_a_missing_twin_leaves_the_panel_and_journal_alone() -> None:
    video, audio, recorder = FakeVideo(has_twin=False), FakeAudio(), FakeRecorder()
    panel = FakePanel()

    handled = motion_test._handle_control("kaleidoscope", video, audio, config_with(),
                                          recorder, recorder, panel)

    assert handled is True
    assert recorder.calls == []
    assert panel.notices == []


def test_the_directional_pair_is_idempotent_on_the_panel_too() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()
    panel = FakePanel()

    motion_test._handle_control("kaleidoscope_on", video, audio, config_with(),
                                recorder, recorder, panel)
    motion_test._handle_control("kaleidoscope_on", video, audio, config_with(),
                                recorder, recorder, panel)

    assert video.showing is True
    assert panel.notices == [motion_test.NOTICE_LABELS["kaleidoscope_on"]], \
        "a repeat that changed nothing says nothing"


def test_the_transport_arrows_answer_in_the_premise() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()
    video.directions = []
    panel = FakePanel()

    handled = motion_test._handle_control("forward", video, audio, config_with(),
                                          recorder, recorder, panel)
    motion_test._handle_control("reverse", video, audio, config_with(),
                                recorder, recorder, panel)

    assert handled is True
    assert video.directions == [True, False]
    assert panel.notices == [motion_test.NOTICE_LABELS["forward"],
                             motion_test.NOTICE_LABELS["reverse"]]


def test_an_arrow_turns_to_the_next_sound_and_retimes_the_rewind() -> None:
    # reverse_rate = fit_to_audio measures the rewind against the sound, so a
    # different sound has to be measured again.
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    panel = FakePanel()
    handled = motion_test._handle_control("audio_next", video, audio, config_with(),
                                          recorder, recorder, panel)

    assert handled is True
    assert audio.steps == [1]
    assert video.audio_duration == 12.0
    assert ("audio_chosen", {"file": "second.wav"}) in recorder.calls
    assert panel.notices == [motion_test.NOTICE_LABELS["audio"]]


def test_the_other_arrow_turns_back() -> None:
    video, audio, recorder = FakeVideo(), FakeAudio(), FakeRecorder()

    motion_test._handle_control("audio_prev", video, audio, config_with(), recorder, recorder,
                                FakePanel())

    assert audio.steps == [-1]


def test_an_arrow_with_nowhere_to_turn_is_still_swallowed() -> None:
    # It was the pad's event, not the state machine's, whether or not it did
    # anything — passing it on would only be logged as an unknown transition.
    video, audio, recorder = FakeVideo(), FakeAudio(switches=False), FakeRecorder()

    panel = FakePanel()
    handled = motion_test._handle_control("audio_next", video, audio, config_with(),
                                          recorder, recorder, panel)

    assert handled is True
    assert video.audio_duration is None
    assert recorder.calls == []
    assert panel.notices == []
