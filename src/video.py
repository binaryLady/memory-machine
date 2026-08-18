"""OpenCV video engine with reverse/forward playback."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from playback_math import compute_reverse_step

LOGGER = logging.getLogger("motion-player.video")

# Local import only when cv2 is available; the module itself may be imported on
# laptops for config/status, so delay the heavy import until construction.


class VideoEngine:
    """Loads a clip and renders frames on the main thread."""

    def __init__(self, config: Any) -> None:
        import cv2  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]

        self._cv2 = cv2
        self._np = np
        self._config = config.playback
        self._video_path = Path(config.media.video_file)
        self._title = "memory-machine"
        self._cap: Any = None
        self._frames: list[Any] | None = None
        self._frame_count = 0
        self._fps = 30.0
        self._width = 0
        self._height = 0
        self._current_index = 0.0
        self._mode = "IDLE"
        self._interval = 1.0 / self._fps
        self._next_deadline = 0.0
        self._epoch = 0.0
        self._preload = False
        self._audio_duration = 0.0
        self._reverse_step = 1.0
        self._black_frame: Any = None

        self._load()
        self._create_window()

    def _total_memory_bytes(self) -> int:
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (AttributeError, ValueError):
            return 4 * 1024**3  # fallback 4 GB

    def _load(self) -> None:
        if not self._video_path.exists():
            LOGGER.error("Video file not found: %s", self._video_path)
            self._mode = "BLACK"
            return

        self._cap = self._cv2.VideoCapture(str(self._video_path))
        if not self._cap.isOpened():
            LOGGER.error("Could not open video file: %s", self._video_path)
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
        self._epoch = time.monotonic()
        self._next_deadline = self._epoch + self._interval

        self._maybe_preload()

        LOGGER.info(
            "Video loaded: %s frames=%s fps=%.2f size=%dx%d preload=%s",
            self._video_path,
            self._frame_count,
            self._fps,
            self._width,
            self._height,
            self._preload,
        )

    def _maybe_preload(self) -> None:
        want = self._config.preload_frames.lower()
        if want == "false":
            self._preload = False
            LOGGER.info("Frame preloading disabled by config")
            return

        # Rough memory estimate: BGR frame = width * height * 3 bytes.
        estimated = self._frame_count * self._width * self._height * 3
        total = self._total_memory_bytes()
        threshold = total * 0.40

        if want == "auto" and estimated > threshold:
            LOGGER.warning(
                "Estimated preload size %.1f MB exceeds 40%% of RAM (%.1f MB); falling back to seeking",
                estimated / (1024 * 1024),
                threshold / (1024 * 1024),
            )
            self._preload = False
            return

        frames: list[Any] = []
        while True:
            ok, frame = self._cap.read()
            if not ok:
                break
            frames.append(frame)
        if len(frames) < self._frame_count:
            LOGGER.warning(
                "Only decoded %d/%d frames; playback may stutter", len(frames), self._frame_count
            )
        if frames:
            self._frames = frames
            self._preload = True
            LOGGER.info(
                "Preloaded %d frames (%.1f MB)", len(frames), estimated / (1024 * 1024)
            )
        else:
            self._preload = False

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
            self._current_index = float(self._frame_count - 1)
            self._compute_reverse_step()
            self._next_deadline = time.monotonic() + self._interval
            self._render_frame_at(int(self._current_index))
        elif mode == "FORWARD":
            self._current_index = 0.0
            self._next_deadline = time.monotonic() + self._interval
        elif mode == "IDLE":
            if self._config.idle_mode == "hold_first_frame":
                self._current_index = 0.0
                self._render_frame_at(0)
            elif self._config.idle_mode == "black":
                self._render_black()
            elif self._config.idle_mode == "loop_forward":
                self._current_index = 0.0
                self._next_deadline = time.monotonic() + self._interval

    def _frame_at(self, index: int) -> Any:
        if self._frames is not None:
            return self._frames[index]
        if self._cap is None:
            return None
        self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._cap.read()
        if not ok:
            return self._black_frame
        return frame

    def _render_frame_at(self, index: int) -> None:
        if self._mode == "BLACK":
            self._render_black()
            return
        frame = self._frame_at(index)
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
    def at_start(self) -> bool:
        return self._mode == "REVERSE" and self._current_index <= 0

    def render_next(self) -> None:
        if self._mode == "BLACK" or self._frame_count <= 0:
            self._render_black()
            return

        now = time.monotonic()
        if now < self._next_deadline:
            return

        # Advance to the next frame deadline based on the original epoch to
        # prevent drift over long runs.
        self._next_deadline += self._interval
        if self._next_deadline < now:
            # We fell behind; resync to now + one interval to avoid a burst.
            self._next_deadline = now + self._interval

        if self._mode == "IDLE":
            if self._config.idle_mode == "loop_forward":
                self._current_index = (self._current_index + 1) % self._frame_count
                self._render_frame_at(int(self._current_index))
            elif self._config.idle_mode == "hold_first_frame":
                self._render_frame_at(0)
            elif self._config.idle_mode == "black":
                self._render_black()
            return

        if self._mode == "REVERSE":
            self._current_index -= self._reverse_step
            if self._current_index <= 0:
                self._current_index = 0.0
            self._render_frame_at(int(self._current_index))
            return

        if self._mode == "FORWARD":
            self._current_index += 1
            if self._current_index >= self._frame_count:
                self._current_index = 0.0
            self._render_frame_at(int(self._current_index))
            return

    def release(self) -> None:
        self._cv2.destroyAllWindows()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
