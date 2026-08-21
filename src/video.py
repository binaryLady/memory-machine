"""OpenCV video engine with sequential forward and pre-reversed playback."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import display
from playback_math import (
    ScalePlan,
    choose_cut,
    compute_reverse_step,
    compute_scaling,
    reverse_name,
)

LOGGER = logging.getLogger("motion-player.video")

# Roughly once a second at 30fps.
_RECT_RECHECK_FRAMES = 30
# A window smaller than this has not been mapped to the screen yet; scaling into
# it would render the piece as a postage stamp.
_MIN_PLAUSIBLE_AREA = 320 * 240
_FULLSCREEN_ATTEMPTS = 10
# How often to report achieved frame rate, in seconds.
_TIMING_REPORT_S = 10.0

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
        self._cuts = tuple(config.media.cuts)
        self._kaleidoscope_path = config.media.kaleidoscope_file
        self._kaleidoscope_cuts = tuple(config.media.kaleidoscope_cuts)
        self._plain_path: Path | None = None
        self._showing_kaleidoscope = False
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
        self._plan_for: tuple[int, int] | None = None
        self._canvas: Any = None
        self._frames_since_rect_check = 0
        self._fullscreen_settled = False
        self._fullscreen_attempts = 0
        self._timing_started = 0.0
        self._timing_frames = 0
        self._timing_total_s = 0.0
        self._timing_worst_s = 0.0
        self._timing_late = 0
        self._last_source: Any = None
        self._force_redraw = True
        self._last_timing: dict[str, Any] | None = None

        self._display_mode = display.apply_mode(self._config.display, self._config.display_mode)
        self._select_variant()
        self._select_kaleidoscope()
        self._plain_path = self._video_path
        self._load()
        self._create_window()

    def _probe_size(self, path: Path) -> tuple[int, int] | None:
        """Read a clip's dimensions without keeping it open."""
        cap = self._cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                return None
            width = int(cap.get(self._cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()
        if width <= 0 or height <= 0:
            return None
        return width, height

    def _select_variant(self) -> None:
        """Use whichever cut is closest in shape to the attached screen.

        This runs before the window exists, so the screen size comes from the
        pinned mode or the sink itself rather than from the window.
        """
        if not self._cuts:
            return

        size = display.output_resolution(self._config.display, self._config.display_mode)
        if size is None:
            LOGGER.info("Screen size unknown; using %s", self._video_path.name)
            return

        candidates: list[tuple[str, int, int]] = []
        for cut in self._cuts:
            reverse = Path(reverse_name(str(cut)))
            if not cut.exists() or not reverse.exists():
                LOGGER.error("Skipping cut %s: it or its reversed copy is missing", cut.name)
                continue
            probed = self._probe_size(cut)
            if probed is None:
                LOGGER.error("Skipping cut %s: could not read its dimensions", cut.name)
                continue
            candidates.append((str(cut), probed[0], probed[1]))

        default = self._probe_size(self._video_path)
        if default is not None:
            candidates.append((str(self._video_path), default[0], default[1]))

        width, height = size
        chosen = choose_cut(width, height, candidates)
        if chosen is None or chosen == str(self._video_path):
            LOGGER.info("Screen is %dx%d; using %s", width, height, self._video_path.name)
            return

        self._video_path = Path(chosen)
        self._reverse_path = Path(reverse_name(chosen))
        LOGGER.info("Screen is %dx%d; using the closest cut %s", width, height, self._video_path.name)

    def _select_kaleidoscope(self) -> None:
        """Pick the kaleidoscope twin that matches the screen, as the cuts do.

        Same shape matching, run over the parallel list: a portrait screen gets
        the portrait kaleidoscope, not the square one.
        """
        if not self._kaleidoscope_cuts:
            return
        size = display.output_resolution(self._config.display, self._config.display_mode)
        if size is None:
            return

        candidates: list[tuple[str, int, int]] = []
        for cut in self._kaleidoscope_cuts:
            if not cut.exists() or not Path(reverse_name(str(cut))).exists():
                LOGGER.error("Skipping kaleidoscope cut %s: it or its reversed copy is missing",
                             cut.name)
                continue
            probed = self._probe_size(cut)
            if probed is None:
                continue
            candidates.append((str(cut), probed[0], probed[1]))
        if not candidates:
            return

        chosen = choose_cut(size[0], size[1], candidates)
        if chosen is not None:
            self._kaleidoscope_path = Path(chosen)
            LOGGER.info("Kaleidoscope twin: %s", self._kaleidoscope_path.name)

    @property
    def showing_kaleidoscope(self) -> bool:
        return self._showing_kaleidoscope

    def toggle_kaleidoscope(self) -> bool:
        """Switch the picture between the plain render and its kaleidoscope twin.

        The twin is the same footage at the same length, so the visitor keeps
        their place: a rewind three-quarters of the way back carries on from
        three-quarters of the way back, in the other render.
        """
        if self._kaleidoscope_path is None or self._plain_path is None:
            LOGGER.info("No kaleidoscope twin configured; nothing to switch to")
            return self._showing_kaleidoscope
        wanted = self._plain_path if self._showing_kaleidoscope else self._kaleidoscope_path
        if not wanted.exists():
            LOGGER.error("Kaleidoscope twin missing: %s", wanted)
            return self._showing_kaleidoscope
        self._showing_kaleidoscope = not self._showing_kaleidoscope
        self._swap_clip(wanted)
        return self._showing_kaleidoscope

    def _swap_clip(self, path: Path) -> None:
        """Reopen on another render of the same piece, holding mode and place."""
        mode = self._mode
        index = self._current_index
        for cap in (self._cap, self._reverse_cap):
            if cap is not None:
                cap.release()
        self._cap = None
        self._reverse_cap = None
        self._video_path = path
        self._reverse_path = Path(reverse_name(str(path)))
        self._plan = None
        self._plan_for = None
        self._load()
        self.set_mode(mode)
        # set_mode starts the mode from its own end; walk back to where the
        # visitor actually was.
        if mode in {"REVERSE", "FORWARD"} and self._frame_count:
            self._current_index = min(index, float(max(self._frame_count - 1, 0)))
            if mode == "REVERSE":
                cap = self._reverse_cap
                # The reverse clip runs the other way: the same moment of the
                # piece is that far in from its own start.
                target = int((self._frame_count - 1) - self._current_index)
            else:
                cap = self._cap
                target = int(self._current_index)
            self._advance_to(cap, target)
            self._show(self._last_frame)

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
            self._apply_fullscreen()
        else:
            self._cv2.setWindowProperty(
                self._title, self._cv2.WND_PROP_FULLSCREEN, self._cv2.WINDOW_NORMAL
            )
            self._fullscreen_settled = True
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
        self._force_redraw = True

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

    def _apply_fullscreen(self) -> None:
        """Ask for fullscreen again.

        Several window managers ignore the property until the window has been
        mapped with content, leaving a placeholder-sized window behind. One call
        at construction is not enough, so this is re-asserted until the window
        actually has a sensible size.
        """
        if self._fullscreen_settled or self._fullscreen_attempts >= _FULLSCREEN_ATTEMPTS:
            return
        self._fullscreen_attempts += 1
        self._force_redraw = True
        try:
            self._cv2.setWindowProperty(
                self._title, self._cv2.WND_PROP_FULLSCREEN, self._cv2.WINDOW_FULLSCREEN
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not set fullscreen: %s", exc)

    def _output_rect(self) -> tuple[int, int] | None:
        """Size of the surface we are drawing onto.

        Re-read periodically rather than cached once: the window reports a
        placeholder size until the compositor has mapped it fullscreen, and
        pinning the first answer scales every later frame to that placeholder.
        Re-reading also picks up a genuine mode change under the running piece.
        """
        self._frames_since_rect_check += 1
        if self._output_size is not None and self._frames_since_rect_check < _RECT_RECHECK_FRAMES:
            return self._output_size
        self._frames_since_rect_check = 0

        getter = getattr(self._cv2, "getWindowImageRect", None)
        if getter is None:
            return self._output_size
        try:
            _x, _y, width, height = getter(self._title)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not read the window rect: %s", exc)
            return self._output_size
        if width <= 0 or height <= 0:
            return self._output_size

        if width * height < _MIN_PLAUSIBLE_AREA and self._config.fullscreen:
            if self._fullscreen_attempts < _FULLSCREEN_ATTEMPTS:
                LOGGER.warning(
                    "Window is only %dx%d; re-asserting fullscreen (attempt %d)",
                    width,
                    height,
                    self._fullscreen_attempts + 1,
                )
            self._apply_fullscreen()
            # Don't plan against a window that has not been mapped yet.
            return None

        self._fullscreen_settled = True
        if (width, height) != self._output_size:
            LOGGER.info("Output surface %dx%d, scaling=%s", width, height, self._scaling)
            self._output_size = (width, height)
            self._force_redraw = True
        return self._output_size

    def _scale(self, frame: Any) -> Any:
        if self._scaling == "stretch":
            return frame
        output = self._output_rect()
        if output is None:
            return frame

        if self._plan_for != output:
            self._plan = compute_scaling(self._width, self._height, output[0], output[1], self._scaling)
            self._plan_for = output
            self._canvas = None
        if self._plan is None:
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
        # A held frame, or a reverse_step below 1.0, presents the same frame
        # repeatedly. Scaling and uploading it again changes nothing on screen,
        # and an installation spends most of its life idle on one frame.
        if frame is self._last_source and not self._force_redraw:
            return
        try:
            self._cv2.imshow(self._title, self._scale(frame))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cv2.imshow failed: %s", exc)
            return
        self._last_source = frame
        self._force_redraw = False

    def _render_black(self) -> None:
        self._last_source = None
        if self._black_frame is None:
            width = self._width or 1920
            height = self._height or 1080
            self._black_frame = self._np.zeros((height, width, 3), dtype=self._np.uint8)
        try:
            self._cv2.imshow(self._title, self._black_frame)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cv2.imshow failed: %s", exc)

    @property
    def last_timing(self) -> dict[str, Any] | None:
        """The most recently completed timing window, or None before the first."""
        return self._last_timing

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
    def mode(self) -> str:
        return self._mode

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def at_start(self) -> bool:
        return self._mode == "REVERSE" and self._current_index <= 0

    def _record_frame(self, started: float, was_late: bool) -> None:
        """Track how long frames actually take, so stutter can be measured."""
        elapsed = time.monotonic() - started
        if self._timing_started == 0.0:
            self._timing_started = started
        self._timing_frames += 1
        self._timing_total_s += elapsed
        self._timing_worst_s = max(self._timing_worst_s, elapsed)
        self._timing_late += int(was_late)

        window = started - self._timing_started
        if window <= 0 or window < _TIMING_REPORT_S:
            return

        # Retained for telemetry: the reset below is destructive, and the log
        # line is unreadable to a remote monitor.
        self._last_timing = {
            "mode": self._mode,
            "fps": round(self._timing_frames / window, 1),
            "target_fps": round(self._fps, 1),
            "frame_mean_ms": round((self._timing_total_s / self._timing_frames) * 1000, 1),
            "frame_worst_ms": round(self._timing_worst_s * 1000, 1),
            "late": self._timing_late,
            "frames": self._timing_frames,
        }
        LOGGER.info(
            "Playback %s: %.1f fps target %.1f, frame mean %.1fms worst %.1fms, %d/%d late",
            self._mode,
            self._timing_frames / window,
            self._fps,
            (self._timing_total_s / self._timing_frames) * 1000,
            self._timing_worst_s * 1000,
            self._timing_late,
            self._timing_frames,
        )
        self._timing_started = 0.0
        self._timing_frames = 0
        self._timing_total_s = 0.0
        self._timing_worst_s = 0.0
        self._timing_late = 0

    def render_next(self) -> None:
        if self._mode == "BLACK" or self._frame_count <= 0:
            self._render_black()
            return

        started = time.monotonic()
        now = started
        if now < self._next_deadline:
            return

        # Advance to the next frame deadline based on the previous one to
        # prevent drift over long runs.
        self._next_deadline += self._interval
        was_late = self._next_deadline < now
        if was_late:
            # We fell behind; resync to now + one interval to avoid a burst.
            self._next_deadline = now + self._interval

        self._render_for_mode()
        self._record_frame(started, was_late)

    def _render_for_mode(self) -> None:
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
