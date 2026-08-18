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
        self.set_calls = 0
        self.read_calls = 0

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the cv2 API
        return True

    def get(self, prop: int) -> float:
        return {1001: self._frames, 1002: self._fps, 1003: 64, 1004: 48}[prop]

    def set(self, prop: int, value: float) -> bool:
        self.set_calls += 1
        self._pos = int(value)
        return True

    def read(self) -> tuple[bool, Any]:
        self.read_calls += 1
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
    cv2.captures = []

    def _capture(path: str) -> FakeCapture:
        cap = FakeCapture()
        cv2.captures.append(cap)
        return cap

    cv2.VideoCapture = _capture
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
    scaling: str = "stretch"
    fullscreen: bool = True
    display: str = "auto"
    display_mode: str = "auto"


@dataclass
class FakeMedia:
    video_file: Any
    reverse_file: Any
    audio_file: Any = "piece.wav"


@dataclass
class FakeConfig:
    playback: FakePlayback
    media: FakeMedia


def make_clips(tmp_path: Any) -> tuple[Any, Any]:
    clip = tmp_path / "piece.mp4"
    clip.touch()
    reverse = tmp_path / "piece.reverse.mp4"
    reverse.touch()
    return clip, reverse


def make_engine(
    monkeypatch: pytest.MonkeyPatch, video_file: Any, reverse_file: Any = "/nonexistent/rev.mp4", **playback: Any
) -> Any:
    install_cv2_stub(monkeypatch)
    import video

    return video.VideoEngine(FakeConfig(FakePlayback(**playback), FakeMedia(video_file, reverse_file)))


def tick(engine: Any) -> None:
    """Force the frame deadline to have passed and render one frame."""
    engine._next_deadline = 0.0
    engine.render_next()


def test_reverse_restarts_from_the_end_when_already_reversing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A re-lift restarts the audio, so the rewind must restart too."""
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)

    engine.set_mode("REVERSE")
    engine._current_index = 40.0
    engine.set_mode("REVERSE")

    assert engine._current_index == 99.0


def test_loop_reverse_does_not_stall_at_the_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse, on_rewind_end="loop_reverse")

    engine.set_mode("REVERSE")
    engine._current_index = 0.0
    assert engine.at_start

    engine.set_mode("REVERSE")  # what the state machine does on video_at_start
    assert not engine.at_start


def test_rewind_never_seeks_per_frame(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The whole point of the pre-reversed clip: sequential reads, no seeking."""
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)
    import cv2  # the stub installed above

    reverse_cap = cv2.captures[1]
    engine.set_mode("REVERSE")
    seeks_after_entry = reverse_cap.set_calls

    for _ in range(20):
        tick(engine)

    assert seeks_after_entry == 1, "mode entry should rewind the reversed clip exactly once"
    assert reverse_cap.set_calls == seeks_after_entry, "no seeking once the rewind is running"


def test_rewind_walks_the_reversed_clip_forward(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)
    import cv2

    engine.set_mode("REVERSE")
    for _ in range(5):
        tick(engine)

    # Frame 0 of the reversed clip is the last frame of the piece.
    assert cv2.shown[-1] == ("frame", 5)
    assert engine._current_index == 94.0


def test_slow_rewind_repeats_frames_instead_of_decoding_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """reverse_step below 1.0 must hold frames, not read ahead."""
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)
    import cv2

    reverse_cap = cv2.captures[1]
    engine.set_mode("REVERSE")
    engine._reverse_step = 0.5
    reads_after_entry = reverse_cap.read_calls

    for _ in range(8):
        tick(engine)

    assert reverse_cap.read_calls - reads_after_entry == 4


def test_missing_reverse_clip_falls_back_to_black(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    clip = tmp_path / "piece.mp4"
    clip.touch()
    engine = make_engine(monkeypatch, clip)

    engine.set_mode("REVERSE")
    tick(engine)

    assert engine._reverse_cap is None
    assert engine._black_frame is not None


@pytest.mark.parametrize("idle_mode", ["hold_first_frame", "black", "loop_forward"])
def test_missing_video_shows_black_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, idle_mode: str
) -> None:
    engine = make_engine(monkeypatch, "/nonexistent/piece.mp4", idle_mode=idle_mode)

    engine.set_mode("IDLE")
    tick(engine)

    assert engine._black_frame is not None


def test_missing_video_survives_a_lift(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = make_engine(monkeypatch, "/nonexistent/piece.mp4")

    engine.set_mode("IDLE")
    engine.set_mode("REVERSE")
    tick(engine)

    assert engine._black_frame is not None


def test_idle_mode_can_be_overridden_at_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """With no sensor the piece loops forward instead of holding a still frame."""
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)
    import cv2

    engine.set_mode("IDLE")
    engine.set_idle_mode("loop_forward")

    before = len(cv2.shown)
    for _ in range(4):
        tick(engine)

    assert engine._current_index == 4.0
    assert len(cv2.shown) > before


def test_overriding_to_the_same_mode_is_a_no_op(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse)

    engine.set_mode("IDLE")
    engine.set_idle_mode("hold_first_frame")

    assert engine._idle_mode == "hold_first_frame"


def test_scaling_is_skipped_when_the_window_size_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """No getWindowImageRect means no reliable output size; pass frames through."""
    clip, reverse = make_clips(tmp_path)
    engine = make_engine(monkeypatch, clip, reverse, scaling="fit")

    frame = ("frame", 7)

    assert engine._scale(frame) is frame
    assert engine._output_rect() is None
