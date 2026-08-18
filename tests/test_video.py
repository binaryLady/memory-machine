"""VideoEngine tests with a stubbed cv2 so they run off the Pi."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest


class FakeCapture:
    def __init__(self, frames: int = 100, fps: float = 30.0) -> None:
        self._frames = frames
        self._fps = fps
        self._pos = 0

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the cv2 API
        return True

    def get(self, prop: int) -> float:
        return {1001: self._frames, 1002: self._fps, 1003: 64, 1004: 48}[prop]

    def set(self, prop: int, value: float) -> bool:
        self._pos = int(value)
        return True

    def read(self) -> tuple[bool, Any]:
        if self._pos >= self._frames:
            return False, None
        self._pos += 1
        return True, ("frame", self._pos - 1)

    def release(self) -> None:
        pass


def install_cv2_stub(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    cv2 = types.ModuleType("cv2")
    cv2.CAP_PROP_FRAME_COUNT = 1001
    cv2.CAP_PROP_FPS = 1002
    cv2.CAP_PROP_FRAME_WIDTH = 1003
    cv2.CAP_PROP_FRAME_HEIGHT = 1004
    cv2.CAP_PROP_POS_FRAMES = 1005
    cv2.WINDOW_NORMAL = 0
    cv2.WINDOW_FULLSCREEN = 1
    cv2.WND_PROP_FULLSCREEN = 0
    cv2.shown = []
    cv2.VideoCapture = lambda path: FakeCapture()
    cv2.namedWindow = lambda *a, **k: None
    cv2.setWindowProperty = lambda *a, **k: None
    cv2.moveWindow = lambda *a, **k: None
    cv2.setMouseCallback = lambda *a, **k: None
    cv2.destroyAllWindows = lambda: None
    cv2.imshow = lambda title, frame: cv2.shown.append(frame)
    cv2.waitKey = lambda n: -1
    monkeypatch.setitem(sys.modules, "cv2", cv2)

    np = types.ModuleType("numpy")
    np.uint8 = "uint8"
    np.zeros = lambda shape, dtype=None: ("black", shape)
    monkeypatch.setitem(sys.modules, "numpy", np)
    return cv2


@dataclass
class FakePlayback:
    idle_mode: str = "hold_first_frame"
    reverse_rate: str = "native"
    on_rewind_end: str = "hold"
    preload_frames: str = "false"
    fullscreen: bool = True
    display: str = "auto"


@dataclass
class FakeMedia:
    video_file: Any
    audio_file: Any = "piece.wav"


@dataclass
class FakeConfig:
    playback: FakePlayback
    media: FakeMedia


def make_engine(monkeypatch: pytest.MonkeyPatch, video_file: Any, **playback: Any) -> Any:
    install_cv2_stub(monkeypatch)
    import video

    return video.VideoEngine(FakeConfig(FakePlayback(**playback), FakeMedia(video_file)))


def test_reverse_restarts_from_the_end_when_already_reversing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A re-lift restarts the audio, so the rewind must restart too."""
    clip = tmp_path / "piece.mp4"
    clip.touch()
    engine = make_engine(monkeypatch, clip)

    engine.set_mode("REVERSE")
    engine._current_index = 40.0
    engine.set_mode("REVERSE")

    assert engine._current_index == 99.0


def test_loop_reverse_does_not_stall_at_the_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    clip = tmp_path / "piece.mp4"
    clip.touch()
    engine = make_engine(monkeypatch, clip, on_rewind_end="loop_reverse")

    engine.set_mode("REVERSE")
    engine._current_index = 0.0
    assert engine.at_start

    engine.set_mode("REVERSE")  # what the state machine does on video_at_start
    assert not engine.at_start


@pytest.mark.parametrize("idle_mode", ["hold_first_frame", "black", "loop_forward"])
def test_missing_video_shows_black_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, idle_mode: str
) -> None:
    engine = make_engine(monkeypatch, "/nonexistent/piece.mp4", idle_mode=idle_mode)

    engine.set_mode("IDLE")
    engine._next_deadline = 0.0  # force the frame deadline to have passed
    engine.render_next()

    assert engine._black_frame is not None


def test_missing_video_survives_a_lift(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = make_engine(monkeypatch, "/nonexistent/piece.mp4")

    engine.set_mode("IDLE")
    engine.set_mode("REVERSE")
    engine._next_deadline = 0.0
    engine.render_next()

    assert engine._black_frame is not None
