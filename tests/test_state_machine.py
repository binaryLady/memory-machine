from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import state
from state import ENGAGED, IDLE, StateMachine


@dataclass
class FakeConfig:
    playback: Any
    audio: Any
    sensor: Any


@dataclass
class FakePlayback:
    on_rewind_end: str = "hold"


@dataclass
class FakeAudio:
    fade_out_ms: int = 400
    on_audio_end: str = "silence"


@dataclass
class FakeSensorConfig:
    max_engaged_minutes: int = 30


class FakeAudioEngine:
    def __init__(self) -> None:
        self.play_calls = 0
        self.fade_calls = 0
        self._playing = False

    def play_from_start(self) -> None:
        self.play_calls += 1
        self._playing = True

    def fade_out(self, ms: int) -> None:
        self.fade_calls += 1
        self._playing = False

    @property
    def is_playing(self) -> bool:
        return self._playing


class FakeVideoEngine:
    def __init__(self) -> None:
        self.mode = "IDLE"
        self.at_start = False

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def set_audio_duration(self, duration_s: float) -> None:
        pass


class FakeStats:
    def lift_accepted(self) -> None:
        pass


def _make_sm(rewind_end: str = "hold", audio_end: str = "silence", max_min: int = 30) -> tuple:
    cfg = FakeConfig(
        playback=FakePlayback(on_rewind_end=rewind_end),
        audio=FakeAudio(on_audio_end=audio_end),
        sensor=FakeSensorConfig(max_engaged_minutes=max_min),
    )
    audio = FakeAudioEngine()
    video = FakeVideoEngine()
    sm = StateMachine(cfg, audio, video, FakeStats())
    return sm, audio, video


def test_lift_from_idle_starts_audio_and_reverse() -> None:
    sm, audio, video = _make_sm()
    assert sm.state == IDLE
    sm.handle("lift")
    assert sm.state == ENGAGED
    assert audio.play_calls == 1
    assert video.mode == "REVERSE"


def test_replace_returns_to_idle() -> None:
    sm, audio, video = _make_sm()
    sm.handle("lift")
    sm.handle("replace")
    assert sm.state == IDLE
    assert audio.fade_calls == 1
    assert video.mode == "IDLE"


def test_lift_during_engaged_restarts_cleanly() -> None:
    sm, audio, video = _make_sm()
    sm.handle("lift")
    sm.handle("lift")
    assert sm.state == ENGAGED
    assert audio.play_calls == 2
    assert video.mode == "REVERSE"


def test_video_at_start_while_engaged_uses_on_rewind_end() -> None:
    sm, audio, video = _make_sm(rewind_end="loop_reverse")
    sm.handle("lift")
    video.at_start = True
    sm.handle("video_at_start")
    assert sm.state == ENGAGED
    assert audio.play_calls == 1  # audio untouched
    assert video.mode == "REVERSE"


def test_audio_end_while_engaged_loops_when_configured() -> None:
    sm, audio, video = _make_sm(audio_end="loop")
    sm.handle("lift")
    audio._playing = False
    sm.tick(0.0)
    assert sm.state == ENGAGED
    assert audio.play_calls == 2  # initial + loop


def test_stuck_engaged_timeout_forces_idle() -> None:
    sm, audio, video = _make_sm(max_min=0)
    sm.handle("lift")
    sm.tick(1.0)
    assert sm.state == IDLE
    assert audio.fade_calls == 1
    assert video.mode == "IDLE"
