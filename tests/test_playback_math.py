from __future__ import annotations

import pytest
from playback_math import compute_reverse_step


def test_native_reverse_step_is_one() -> None:
    assert compute_reverse_step(frame_count=100, fps=25.0, audio_duration_s=10.0, reverse_rate="native") == 1.0


def test_fit_to_audio_spread_over_audio_duration() -> None:
    # 100 frames @ 25 fps => 4 s of video.  Fit to 10 s audio => play 1/2.5 as fast.
    step = compute_reverse_step(frame_count=100, fps=25.0, audio_duration_s=10.0, reverse_rate="fit_to_audio")
    assert step == pytest.approx(100 / (10.0 * 25.0))
    assert step < 1.0


def test_fit_to_audio_falls_back_when_no_audio_duration() -> None:
    assert compute_reverse_step(frame_count=100, fps=25.0, audio_duration_s=0.0, reverse_rate="fit_to_audio") == 1.0


def test_float_rate_is_applied_directly() -> None:
    assert compute_reverse_step(frame_count=100, fps=25.0, audio_duration_s=10.0, reverse_rate="2.5") == pytest.approx(2.5)
