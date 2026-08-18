"""OpenCV video engine with sequential forward and pre-reversed playback."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import display
from playback_math import ScalePlan, compute_reverse_step, compute_scaling

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
        self._idle_mode = str(self._config.idle_mode)
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
        self._scaling = str(self._config.scaling)
        self._output_size: tuple[int, int] | None = None
        self._plan: ScalePlan | None = None
        self._canvas: Any = None

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

    def set_idle_mode(self, mode: str) -> None:
        """Override the configured idle behaviour for this run."""
        if mode == self._idle_mode:
            return
        LOGGER.info("Idle mode -> %s (was %s)", mode, self._idle_mode)
        self._idle_mode = mode
        if self._mode == "IDLE":
            self.set_mode("IDLE")

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
            if self._idle_mode == "hold_first_frame":
                self._current_index = 0.0
                self._show(self._first_frame)
            elif self._idle_mode == "black":
                self._render_black()
            elif self._idle_mode == "loop_forward":
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

    def _output_rect(self) -> tuple[int, int] | None:
        """Size of the surface we are drawing onto, once the window has one."""
        if self._output_size is not None:
            return self._output_size
        getter = getattr(self._cv2, "getWindowImageRect", None)
        if getter is None:
            return None
        try:
            _x, _y, width, height = getter(self._title)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not read the window rect: %s", exc)
            return None
        if width <= 0 or height <= 0:
            return None
        self._output_size = (width, height)
        LOGGER.info("Output surface %dx%d, scaling=%s", width, height, self._scaling)
        return self._output_size

    def _scale(self, frame: Any) -> Any:
        if self._scaling == "stretch":
            return frame
        output = self._output_rect()
        if output is None:
            return frame

        if self._plan is None:
            self._plan = compute_scaling(self._width, self._height, output[0], output[1], self._scaling)
            if self._plan is None:
                # Nothing to do for this pairing; stop re-planning every frame.
                self._scaling = "stretch"
                return frame

        plan = self._plan
        crop_x, crop_y, crop_w, crop_h = plan.crop
        cropped = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
        resized = self._cv2.resize(cropped, plan.size, interpolation=self._cv2.INTER_LINEAR)
        if plan.canvas is None:
            return resized

        canvas_w, canvas_h = plan.canvas
        if self._canvas is None:
            # Reused between frames; the pasted region is fully overwritten and
            # the padding around it stays black.
            self._canvas = self._np.zeros((canvas_h, canvas_w, 3), dtype=self._np.uint8)
        off_x, off_y = plan.offset
        self._canvas[off_y:off_y + plan.size[1], off_x:off_x + plan.size[0]] = resized
        return self._canvas

    def _show(self, frame: Any) -> None:
        if frame is None:
            self._render_black()
            return
        try:
            self._cv2.imshow(self._title, self._scale(frame))
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
    def rewind_duration_s(self) -> float:
        """How long a full rewind takes at the current reverse rate.

        Each frame interval advances reverse_step frames, so covering the clip
        takes frame_count / reverse_step intervals of 1/fps each.
        """
        if self._frame_count <= 0 or self._fps <= 0 or self._reverse_step <= 0:
            return 0.0
        return self._frame_count / (self._reverse_step * self._fps)

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
            if self._idle_mode == "loop_forward":
                self._current_index += 1
                if self._current_index >= self._frame_count:
                    self._current_index = 0.0
                    self._rewind(self._cap)
                self._advance_to(self._cap, int(self._current_index))
                self._show(self._last_frame)
            elif self._idle_mode == "hold_first_frame":
                self._show(self._first_frame)
            elif self._idle_mode == "black":
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
