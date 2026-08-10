"""Pure playback-frame arithmetic used by video.py and tests."""
from __future__ import annotations

import logging

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
