"""AudioEngine tests with a stubbed pygame so they run off the Pi."""
from __future__ import annotations

import sys
from pathlib import Path
import types
from dataclasses import dataclass
from typing import Any

import pytest


class FakeSound:
    def __init__(self, path: str, length: float = 180.0) -> None:
        self.path = path
        self._length = length
        self.play_calls: list[dict[str, Any]] = []
        self.loops: list[int] = []
        self.fadeouts: list[int] = []
        self.stops = 0
        self.volume = 0.0

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def get_length(self) -> float:
        return self._length

    def play(self, maxtime: int = 0, loops: int = 0) -> None:
        self.play_calls.append({"maxtime": maxtime})
        self.loops.append(loops)

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
    audio_mode: str = "on_lift"


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


def test_the_cap_leaves_room_for_the_fade(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A cap at exactly the picture's end clips the hold-fade into a click."""
    engine = make_engine(monkeypatch, tmp_path, length=180.0)

    engine.set_max_duration(65.333 + 0.4)
    engine.play_from_start()

    assert engine._sound.play_calls == [{"maxtime": 65733}]


def test_looping_playback_never_ends_and_is_never_capped(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)
    # A cap would normally apply; under always-on there is no picture to
    # outlast, so the loop must ignore it.
    engine.set_max_duration(5.0)

    engine.play_looping()

    assert engine._sound.play_calls == [{"maxtime": 0}], "no cap under always-on"
    assert engine._sound.loops == [-1], "plays for ever"


def test_looping_playback_restarts_cleanly_over_an_in_flight_fade(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)
    engine.fade_out(400)

    engine.play_looping()

    assert engine._sound.stops == 1, "the fade is cancelled before restarting"
    assert engine._sound.volume == 0.8


class SpyEngine:
    def __init__(self) -> None:
        self.started = 0
        self.faded: list[int] = []
        self.is_playing = True
        self.duration_s = 30.0

    def play_from_start(self) -> None:
        self.started += 1

    def fade_out(self, ms: int) -> None:
        self.faded.append(ms)


def test_always_on_audio_swallows_the_state_machines_starts_and_fades() -> None:
    import audio as audio_module

    spy = SpyEngine()
    wrapped = audio_module.AlwaysOnAudio(spy)

    wrapped.play_from_start()
    wrapped.fade_out(400)

    assert spy.started == 0, "a lift must not restart sound that never stopped"
    assert spy.faded == [], "letting go must not silence sound the sensor does not own"


def test_always_on_audio_still_reports_the_real_engines_state() -> None:
    import audio as audio_module

    spy = SpyEngine()
    wrapped = audio_module.AlwaysOnAudio(spy)

    assert wrapped.is_playing is True
    assert wrapped.duration_s == 30.0

    spy.is_playing = False
    assert wrapped.is_playing is False


def test_switching_sound_loops_the_new_one_when_the_old_one_was_looping(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)
    other = tmp_path / "second.wav"
    other.touch()
    engine.play_looping()

    assert engine.switch_to(other) is True
    assert engine._audio_path == other
    assert engine._looping is True, "audio_mode=always keeps looping across a switch"


def test_switching_to_the_sound_already_playing_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)

    assert engine.switch_to(engine._audio_path) is False


def test_a_missing_sound_leaves_the_one_that_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)
    playing = engine._audio_path

    assert engine.switch_to(tmp_path / "never-rendered.wav") is False
    assert engine._audio_path == playing


def test_the_library_is_every_sound_in_the_folder_in_name_order(tmp_path) -> None:
    import audio as audio_module

    for name in ("piece.wav", "b-side.mp3", "notes.txt", "a-side.WAV"):
        (tmp_path / name).touch()
    (tmp_path / "renders").mkdir()

    assert [p.name for p in audio_module.sound_library(tmp_path)] == [
        "a-side.WAV", "b-side.mp3", "piece.wav",
    ]


def test_the_deck_wraps_at_both_ends() -> None:
    import audio as audio_module

    deck = [Path("/m/a.wav"), Path("/m/b.wav"), Path("/m/c.wav")]

    assert audio_module.neighbour_sound(deck, deck[2], 1) == deck[0]
    assert audio_module.neighbour_sound(deck, deck[0], -1) == deck[2]
    assert audio_module.neighbour_sound(deck, deck[0], 1) == deck[1]


def test_a_sound_outside_the_deck_starts_it_from_the_top() -> None:
    import audio as audio_module

    deck = [Path("/m/a.wav"), Path("/m/b.wav")]

    assert audio_module.neighbour_sound(deck, Path("/elsewhere/x.wav"), 1) == deck[0]
    assert audio_module.neighbour_sound(deck, Path("/elsewhere/x.wav"), -1) == deck[1]


def test_one_sound_or_none_has_nowhere_to_go() -> None:
    import audio as audio_module

    only = Path("/m/a.wav")
    assert audio_module.neighbour_sound([only], only, 1) is None
    assert audio_module.neighbour_sound([], only, 1) is None


def test_cycling_switches_to_the_next_sound_beside_the_current_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)
    (tmp_path / "second.wav").touch()
    engine.play_looping()

    assert engine.cycle(1) is True
    assert engine.audio_path == tmp_path / "second.wav"
    assert engine.cycle(1) is True, "wraps back round"
    assert engine.audio_path == tmp_path / "piece.wav"


def test_cycling_with_a_single_sound_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = make_engine(monkeypatch, tmp_path)

    assert engine.cycle(1) is False
    assert engine.audio_path == tmp_path / "piece.wav"
