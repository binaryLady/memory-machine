"""Sleep/wake transition tests, with fakes in the test_state_machine style."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import motion_test


@dataclass
class FakeAudioCfg:
    fade_out_ms: int = 400


@dataclass
class FakeCfg:
    audio: FakeAudioCfg = field(default_factory=FakeAudioCfg)


class FakeState:
    def __init__(self, state: str = "IDLE") -> None:
        self.state = state
        self.handled: list[str] = []
        self.audio_marked = 0

    def handle(self, event: str) -> None:
        self.handled.append(event)
        if event == "replace":
            self.state = "IDLE"

    def mark_audio_playing(self) -> None:
        self.audio_marked += 1


class FakeVideo:
    def __init__(self) -> None:
        self.modes: list[str] = []

    def set_mode(self, mode: str) -> None:
        self.modes.append(mode)


class FakeAudio:
    def __init__(self) -> None:
        self.fadeouts: list[int] = []

    def fade_out(self, ms: int) -> None:
        self.fadeouts.append(ms)


class FakeTelemetry:
    def __init__(self) -> None:
        self.events: list[str] = []

    def event(self, event_type: str, **kwargs: Any) -> None:
        self.events.append(event_type)


def apply(transition: str | None, state: FakeState) -> tuple[FakeVideo, FakeAudio, FakeTelemetry]:
    video, audio, telemetry = FakeVideo(), FakeAudio(), FakeTelemetry()
    motion_test._apply_schedule_transition(transition, state, video, audio, telemetry, FakeCfg())
    return video, audio, telemetry


def test_going_to_sleep_while_engaged_fades_the_audio_before_the_screen_goes_black() -> None:
    """Cutting a listener off without the fade would be a jolt."""
    state = FakeState("ENGAGED")

    video, _audio, _ = apply("sleep", state)

    assert state.handled == ["replace"], "the existing fade path handles the audio"
    assert video.modes == ["BLACK"]


def test_going_to_sleep_from_idle_blacks_the_screen_and_reports_sleep_start() -> None:
    state = FakeState("IDLE")

    video, audio, telemetry = apply("sleep", state)

    assert video.modes == ["BLACK"]
    assert audio.fadeouts == [400], "idle audio may still be fading; silence it"
    assert telemetry.events == ["sleep_start"]


def test_waking_re_enters_idle_and_reports_sleep_end() -> None:
    """set_mode('IDLE') re-reads the engine's idle mode, so a degraded
    loop_forward override is restored without any bookkeeping here."""
    state = FakeState("IDLE")

    video, _audio, telemetry = apply("wake", state)

    assert video.modes == ["IDLE"]
    assert state.audio_marked == 1
    assert telemetry.events == ["sleep_end"]


def test_no_transition_touches_nothing() -> None:
    state = FakeState("IDLE")

    video, audio, telemetry = apply(None, state)

    assert video.modes == []
    assert audio.fadeouts == []
    assert telemetry.events == []
    assert state.handled == []
