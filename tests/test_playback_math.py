from __future__ import annotations

import pytest
from playback_math import choose_cut, compute_reverse_step, compute_scaling, reverse_name


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


def test_no_cuts_offered_gives_nothing() -> None:
    assert choose_cut(1920, 1080, []) is None


def test_an_unknown_screen_size_gives_nothing() -> None:
    assert choose_cut(0, 0, [("a.mp4", 720, 720)]) is None


@pytest.mark.parametrize(
    "screen,expected",
    [
        ((720, 720), "square.mp4"),
        ((800, 1280), "portrait.mp4"),
        ((1280, 800), "wide.mp4"),
        ((800, 480), "five_three.mp4"),
        ((1920, 1080), "five_three.mp4"),
    ],
)
def test_each_panel_gets_its_nearest_cut(screen: tuple, expected: str) -> None:
    """The real fleet: square, portrait, 16:10 and 5:3 panels."""
    cuts = [
        ("square.mp4", 720, 720),
        ("portrait.mp4", 800, 1280),
        ("wide.mp4", 1280, 800),
        ("five_three.mp4", 800, 480),
    ]

    assert choose_cut(screen[0], screen[1], cuts) == expected


def test_shape_matters_not_resolution() -> None:
    """A 720x720 cut suits any square panel, whatever its pixel count."""
    cuts = [("square.mp4", 720, 720), ("wide.mp4", 1920, 1080)]

    assert choose_cut(2048, 2048, cuts) == "square.mp4"


def test_cuts_with_unusable_dimensions_are_ignored() -> None:
    cuts = [("broken.mp4", 0, 0), ("good.mp4", 800, 1280)]

    assert choose_cut(800, 1280, cuts) == "good.mp4"


def test_ties_go_to_the_first_listed() -> None:
    cuts = [("first.mp4", 720, 720), ("second.mp4", 1080, 1080)]

    assert choose_cut(500, 500, cuts) == "first.mp4"


def test_reverse_name_follows_the_tooling_convention() -> None:
    assert reverse_name("piece_portrait.mp4") == "piece_portrait.reverse.mp4"
    assert reverse_name("piece.800x1280.mp4") == "piece.800x1280.reverse.mp4"
    assert reverse_name("noextension") == "noextension.reverse"
