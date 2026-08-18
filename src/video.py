"""OpenCV video engine with sequential forward and pre-reversed playback."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import display
from playback_math import compute_reverse_step

LOGGER = logging.getLogger("motion-player.video")

# Local import only when cv2 is available; the module itself may be imported on
# laptops for config/status, so delay the heavy import until construction.


class VideoEngine:
    """Streams frames from the piece and from a pre-reversed copy of it.

    The rewind plays the pre-reversed clip forward, so no mode ever seeks per
    frame. Random seeks force an H.264 decoder back to the preceding keyframe,
    which is what puts high-resolution sources out of reach on a Pi.
    """

    def __init__(self, config: Any) -> None:
        import cv2  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]

        self._cv2 = cv2
        self._np = np
        self._config = config.playback
        self._video_path = Path(config.media.video_file)
        self._reverse_path = Path(config.media.reverse_file)
        self._title = "memory-machine"
        self._cap: Any = None
        self._reverse_cap: Any = None
        self._frame_count = 0
        self._fps = 30.0
        self._width = 0
        self._height = 0
        self._current_index = 0.0
        self._mode = "IDLE"
        self._interval = 1.0 / self._fps
        self._next_deadline = 0.0
        self._audio_duration = 0.0
        self._reverse_step = 1.0
        self._first_frame: Any = None
        self._last_frame: Any = None
        # Frames consumed from whichever capture the current mode reads. Reset
        # by _rewind() on every mode entry, so the two captures never share it.
        self._stream_pos = 0
        self._black_frame: Any = None

        self._display_mode = display.apply_mode(self._config.display, self._config.display_mode)
        self._load()
        self._create_window()

    def _open(self, path: Path, label: str) -> Any:
        if not path.exists():
            LOGGER.error("%s not found: %s", label, path)
            return None
        cap = self._cv2.VideoCapture(str(path))
        if not cap.isOpened():
            LOGGER.error("Could not open %s: %s", label, path)
            return None
        return cap

    def _load(self) -> None:
        self._cap = self._open(self._video_path, "Video file")
        if self._cap is None:
            self._mode = "BLACK"
            return

        self._frame_count = int(self._cap.get(self._cv2.CAP_PROP_FRAME_COUNT))
        self._fps = self._cap.get(self._cv2.CAP_PROP_FPS) or 30.0
        self._width = int(self._cap.get(self._cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT))
        if self._frame_count <= 0:
            LOGGER.error("Video has no frames: %s", self._video_path)
            self._mode = "BLACK"
            return

        self._interval = 1.0 / self._fps
        self._current_index = 0.0
        self._next_deadline = time.monotonic() + self._interval

        ok, frame = self._cap.read()
        if ok:
            self._first_frame = frame
            self._last_frame = frame
        self._stream_pos = 1

        self._reverse_cap = self._open(self._reverse_path, "Reverse clip")
        if self._reverse_cap is not None:
            reverse_count = int(self._reverse_cap.get(self._cv2.CAP_PROP_FRAME_COUNT))
            if abs(reverse_count - self._frame_count) > 1:
                LOGGER.warning(
                    "Reverse clip has %d frames but the piece has %d; regenerate it "
                    "with motion-player-reverse so the rewind matches",
                    reverse_count,
                    self._frame_count,
                )

        LOGGER.info(
            "Video loaded: %s frames=%s fps=%.2f size=%dx%d reverse=%s",
            self._video_path,
            self._frame_count,
            self._fps,
            self._width,
            self._height,
            self._reverse_cap is not None,
        )

    def _create_window(self) -> None:
        self._cv2.namedWindow(self._title, self._cv2.WINDOW_NORMAL)
        if self._config.fullscreen:
            self._cv2.setWindowProperty(
                self._title, self._cv2.WND_PROP_FULLSCREEN, self._cv2.WINDOW_FULLSCREEN
            )
        else:
            self._cv2.setWindowProperty(
                self._title, self._cv2.WND_PROP_FULLSCREEN, self._cv2.WINDOW_NORMAL
            )
        if self._config.display and self._config.display != "auto":
            # Best-effort move to the requested display (X11/Wayland XWayland).
            try:
                self._cv2.moveWindow(self._title, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        self._cv2.setMouseCallback(self._title, lambda *args: None)

    def set_audio_duration(self, duration_s: float) -> None:
        """Tell the video engine how long the audio is, used for fit_to_audio."""
        self._audio_duration = duration_s
        self._compute_reverse_step()

    def _compute_reverse_step(self) -> None:
        self._reverse_step = compute_reverse_step(
            self._frame_count,
            self._fps,
            self._audio_duration,
            str(self._config.reverse_rate),
        )
        LOGGER.info("reverse_rate=%s reverse_step=%.4f", self._config.reverse_rate, self._reverse_step)

    def set_mode(self, mode: str) -> None:
        mode = mode.upper()
        # Re-entering the current mode must still restart it: a re-lift while
        # already rewinding restarts the audio, so the video has to rewind from
        # the end again, and on_rewind_end=loop_reverse re-enters REVERSE.
        if mode != self._mode:
            LOGGER.info("Video mode -> %s", mode)
        self._mode = mode

        if mode == "REVERSE":
            self._current_index = float(max(self._frame_count - 1, 0))
            self._compute_reverse_step()
            self._next_deadline = time.monotonic() + self._interval
            if self._reverse_cap is None:
                self._render_black()
                return
            self._rewind(self._reverse_cap)
            self._advance_to(self._reverse_cap, 0)
            self._show(self._last_frame)
        elif mode == "FORWARD":
            self._current_index = 0.0
            self._next_deadline = time.monotonic() + self._interval
            self._rewind(self._cap)
        elif mode == "IDLE":
            if self._config.idle_mode == "hold_first_frame":
                self._current_index = 0.0
                self._show(self._first_frame)
            elif self._config.idle_mode == "black":
                self._render_black()
            elif self._config.idle_mode == "loop_forward":
                self._current_index = 0.0
                self._next_deadline = time.monotonic() + self._interval
                self._rewind(self._cap)

    def _rewind(self, cap: Any) -> None:
        """Seek one capture back to its first frame. Once per mode entry."""
        if cap is None:
            return
        cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
        self._stream_pos = 0

    def _advance_to(self, cap: Any, target: int) -> None:
        """Read forward until _last_frame holds `target`, without ever seeking.

        A reverse_step below 1.0 leaves the target where it already is, so the
        held frame is simply shown again; a step above 1.0 decodes and discards
        the frames in between, which is still far cheaper than a seek.
        """
        if cap is None:
            return
        while self._stream_pos <= target:
            ok, frame = cap.read()
            if not ok:
                break
            self._last_frame = frame
            self._stream_pos += 1

    def _show(self, frame: Any) -> None:
        if frame is None:
            self._render_black()
            return
        try:
            self._cv2.imshow(self._title, frame)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cv2.imshow failed: %s", exc)

    def _render_black(self) -> None:
        if self._black_frame is None:
            width = self._width or 1920
            height = self._height or 1080
            self._black_frame = self._np.zeros((height, width, 3), dtype=self._np.uint8)
        try:
            self._cv2.imshow(self._title, self._black_frame)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cv2.imshow failed: %s", exc)

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def at_start(self) -> bool:
        return self._mode == "REVERSE" and self._current_index <= 0

    def render_next(self) -> None:
        if self._mode == "BLACK" or self._frame_count <= 0:
            self._render_black()
            return

        now = time.monotonic()
        if now < self._next_deadline:
            return

        # Advance to the next frame deadline based on the previous one to
        # prevent drift over long runs.
        self._next_deadline += self._interval
        if self._next_deadline < now:
            # We fell behind; resync to now + one interval to avoid a burst.
            self._next_deadline = now + self._interval

        if self._mode == "IDLE":
            if self._config.idle_mode == "loop_forward":
                self._current_index += 1
                if self._current_index >= self._frame_count:
                    self._current_index = 0.0
                    self._rewind(self._cap)
                self._advance_to(self._cap, int(self._current_index))
                self._show(self._last_frame)
            elif self._config.idle_mode == "hold_first_frame":
                self._show(self._first_frame)
            elif self._config.idle_mode == "black":
                self._render_black()
            return

        if self._mode == "REVERSE":
            self._current_index -= self._reverse_step
            if self._current_index <= 0:
                self._current_index = 0.0
            if self._reverse_cap is None:
                self._render_black()
                return
            # The reversed clip runs the other way, so walking the piece's
            # timeline down means walking that clip's timeline up.
            self._advance_to(self._reverse_cap, int((self._frame_count - 1) - self._current_index))
            self._show(self._last_frame)
            return

        if self._mode == "FORWARD":
            self._current_index += 1
            if self._current_index >= self._frame_count:
                self._current_index = 0.0
                self._rewind(self._cap)
            self._advance_to(self._cap, int(self._current_index))
            self._show(self._last_frame)
            return

    def release(self) -> None:
        self._cv2.destroyAllWindows()
        for name in ("_cap", "_reverse_cap"):
            cap = getattr(self, name)
            if cap is not None:
                cap.release()
                setattr(self, name, None)
