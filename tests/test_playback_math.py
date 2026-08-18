from __future__ import annotations

import pytest
from playback_math import compute_reverse_step, compute_scaling


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


def test_stretch_leaves_the_frame_to_the_display() -> None:
    assert compute_scaling(1280, 1280, 1920, 1080, "stretch") is None


def test_an_exact_match_needs_no_work() -> None:
    assert compute_scaling(1920, 1080, 1920, 1080, "fit") is None


def test_fit_pillarboxes_a_square_source() -> None:
    plan = compute_scaling(1280, 1280, 1920, 1080, "fit")

    assert plan is not None
    assert plan.crop == (0, 0, 1280, 1280), "fit keeps the whole frame"
    assert plan.size == (1080, 1080), "scaled to the limiting dimension"
    assert plan.offset == (420, 0), "centred, 420px of black each side"
    assert plan.canvas == (1920, 1080)


def test_fill_crops_a_square_source_to_cover() -> None:
    plan = compute_scaling(1280, 1280, 1920, 1080, "fill")

    assert plan is not None
    assert plan.crop == (0, 280, 1280, 720), "centred 16:9 band out of the square"
    assert plan.size == (1920, 1080)
    assert plan.canvas is None, "the result already covers the output"


def test_fill_trims_the_sides_of_a_wide_source() -> None:
    plan = compute_scaling(2560, 1080, 1920, 1080, "fill")

    assert plan is not None
    x, y, w, h = plan.crop
    assert (w, h) == (1920, 1080)
    assert (x, y) == (320, 0), "equal trim from both sides"


def test_fit_letterboxes_a_wide_source() -> None:
    plan = compute_scaling(2560, 1080, 1920, 1080, "fit")

    assert plan is not None
    assert plan.size == (1920, 810)
    assert plan.offset == (0, 135)


@pytest.mark.parametrize("mode", ["fit", "fill", "stretch", "nonsense"])
def test_zero_dimensions_never_plan(mode: str) -> None:
    assert compute_scaling(0, 0, 1920, 1080, mode) is None
    assert compute_scaling(1280, 1280, 0, 0, mode) is None


def test_an_unknown_mode_is_ignored() -> None:
    assert compute_scaling(1280, 1280, 1920, 1080, "cover-ish") is None
