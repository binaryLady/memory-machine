"""AudioEngine tests with a stubbed pygame so they run off the Pi."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest


class FakeSound:
    def __init__(self, path: str, length: float = 180.0) -> None:
        self.path = path
        self._length = length
        self.play_calls: list[dict[str, Any]] = []
        self.fadeouts: list[int] = []
        self.stops = 0
        self.volume = 0.0

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def get_length(self) -> float:
        return self._length

    def play(self, maxtime: int = 0) -> None:
        self.play_calls.append({"maxtime": maxtime})

    def stop(self) -> None:
        self.stops += 1

    def fadeout(self, ms: int) -> None:
        self.fadeouts.append(ms)


def install_pygame_stub(monkeypatch: pytest.MonkeyPatch, length: float = 180.0) -> types.ModuleType:
    pygame = types.ModuleType("pygame")
    mixer = types.SimpleNamespace()
    mixer.pre_init = lambda **kwargs: None
    mixer.init = lambda **kwargs: None
    mixer.get_busy = lambda: False
    mixer.Sound = lambda path: FakeSound(path, length)
    pygame.mixer = mixer
    monkeypatch.setitem(sys.modules, "pygame", pygame)
    return pygame


@dataclass
class FakeAudioConfig:
    audio_sink: str = "auto"
    volume: float = 0.8
    fade_out_ms: int = 400
    on_audio_end: str = "silence"


@dataclass
class FakeMedia:
    audio_file: Any


@dataclass
class FakeConfig:
    audio: FakeAudioConfig
    media: FakeMedia


def make_engine(monkeypatch: pytest.MonkeyPatch, tmp_path, length: float = 180.0) -> Any:
    install_pygame_stub(monkeypatch, length)
    import audio as audio_module

    wav = tmp_path / "piece.wav"
    wav.touch()
    return audio_module.AudioEngine(FakeConfig(FakeAudioConfig(), FakeMedia(wav)))


def test_audio_plays_uncapped_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = make_engine(monkeypatch, tmp_path)

    engine.play_from_start()

    assert engine._sound.play_calls == [{"maxtime": 0}]


def test_playback_is_capped_to_the_picture(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """180s of audio over a 65s rewind must stop with the picture."""
    engine = make_engine(monkeypatch, tmp_path, length=180.0)

    engine.set_max_duration(65.333)
    engine.play_from_start()

    assert engine._sound.play_calls == [{"maxtime": 65333}]


def test_audio_shorter_than_the_picture_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path, length=30.0)

    engine.set_max_duration(65.333)
    engine.play_from_start()

    assert engine._sound.play_calls == [{"maxtime": 0}]


def test_a_zero_cap_does_not_silence_playback(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A video that failed to load reports 0s; that must not mute the audio."""
    engine = make_engine(monkeypatch, tmp_path)

    engine.set_max_duration(0.0)
    engine.play_from_start()

    assert engine._sound.play_calls == [{"maxtime": 0}]
