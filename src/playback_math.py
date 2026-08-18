"""Pure playback-frame arithmetic used by video.py and tests."""
from __future__ import annotations

import logging
from dataclasses import dataclass

LOGGER = logging.getLogger("motion-player.playback_math")


def compute_reverse_step(frame_count: int, fps: float, audio_duration_s: float, reverse_rate: str) -> float:
    """Return the fractional frame step for one frame interval.

    - "native" advances exactly one frame per source frame interval.
    - "fit_to_audio" spreads the rewind over the audio duration.
    - A plain float is returned as-is.
    """
    rate = str(reverse_rate).lower()
    if rate == "native":
        return 1.0
    if rate == "fit_to_audio":
        if frame_count <= 0 or fps <= 0 or audio_duration_s <= 0:
            LOGGER.warning("fit_to_audio with invalid inputs; falling back to native")
            return 1.0
        # We must display frame_count frames over audio_duration_s seconds.
        # One native interval is 1/fps seconds, so the step per interval is:
        step = frame_count / (audio_duration_s * fps)
        return step
    try:
        return float(rate)
    except ValueError:
        LOGGER.warning("Invalid reverse_rate %r; falling back to native", reverse_rate)
        return 1.0


@dataclass(frozen=True)
class ScalePlan:
    """How to get a source frame onto the output surface.

    crop   region of the source to take, as (x, y, w, h)
    size   resize that region to this (w, h)
    offset where the resized region sits on the canvas
    canvas size of the black surface to paste onto, or None when the resized
           region already covers the output exactly
    """

    crop: tuple[int, int, int, int]
    size: tuple[int, int]
    offset: tuple[int, int]
    canvas: tuple[int, int] | None


def compute_scaling(
    src_w: int, src_h: int, dst_w: int, dst_h: int, mode: str
) -> ScalePlan | None:
    """Plan the scaling for one frame, or None to hand the frame over untouched.

    - "stretch" lets the display scale the frame, ignoring aspect ratio.
    - "fit" keeps the whole frame and pads the remainder with black.
    - "fill" covers the output and crops whatever overflows.

    Cropping before resizing keeps the work proportional to the output rather
    than to an oversized intermediate, which matters on a Pi.
    """
    if mode == "stretch" or min(src_w, src_h, dst_w, dst_h) <= 0:
        return None

    if (src_w, src_h) == (dst_w, dst_h):
        return None

    if mode == "fit":
        scale = min(dst_w / src_w, dst_h / src_h)
        out_w = max(1, round(src_w * scale))
        out_h = max(1, round(src_h * scale))
        return ScalePlan(
            crop=(0, 0, src_w, src_h),
            size=(out_w, out_h),
            offset=((dst_w - out_w) // 2, (dst_h - out_h) // 2),
            canvas=(dst_w, dst_h),
        )

    if mode == "fill":
        if src_w * dst_h > src_h * dst_w:
            # Source is wider than the output: trim the sides.
            crop_w = max(1, min(src_w, round(src_h * dst_w / dst_h)))
            crop_h = src_h
        else:
            crop_w = src_w
            crop_h = max(1, min(src_h, round(src_w * dst_h / dst_w)))
        return ScalePlan(
            crop=((src_w - crop_w) // 2, (src_h - crop_h) // 2, crop_w, crop_h),
            size=(dst_w, dst_h),
            offset=(0, 0),
            canvas=None,
        )

    LOGGER.warning("Unknown scaling mode %r; leaving the frame alone", mode)
    return None


def choose_cut(
    screen_w: int, screen_h: int, cuts: list[tuple[str, int, int]]
) -> str | None:
    """Pick the cut whose shape is closest to the screen's.

    Distance is the ratio between the two aspects, so it is symmetric and cares
    only about shape: a 720x720 cut is a perfect match for a 720x720 panel and
    an equally good one for any other square. Ties go to whichever was listed
    first. Returns None when nothing usable was offered.
    """
    if screen_w <= 0 or screen_h <= 0:
        return None

    screen_aspect = screen_w / screen_h
    best: str | None = None
    best_distance = 0.0

    for path, width, height in cuts:
        if width <= 0 or height <= 0:
            LOGGER.warning("Ignoring cut with unusable dimensions: %s", path)
            continue
        aspect = width / height
        distance = max(aspect, screen_aspect) / min(aspect, screen_aspect)
        if best is None or distance < best_distance:
            best, best_distance = path, distance

    return best


def reverse_name(path: str) -> str:
    """The reversed copy's filename, by the convention the tooling writes."""
    stem, dot, suffix = path.rpartition(".")
    if not dot:
        return path + ".reverse"
    return f"{stem}.reverse.{suffix}"
