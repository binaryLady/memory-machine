"""Setup wizard tests: the pure config-editing helpers only."""
from __future__ import annotations

from setup_wizard import render_prepare_hint, set_ini_value

SAMPLE = """; the shipped comment survives edits
[playback]
; how the frame meets the screen
scaling             = fit
fullscreen          = true

[sensor]
sensor_type         = switch
"""


def test_set_ini_value_edits_a_key_in_place_and_keeps_the_comments() -> None:
    result = set_ini_value(SAMPLE, "playback", "scaling", "fill")

    assert "scaling             = fill" in result
    assert "; how the frame meets the screen" in result
    assert "; the shipped comment survives edits" in result
    assert result.count("scaling") == 1, "edited in place, not duplicated"


def test_set_ini_value_appends_a_missing_key_to_its_section() -> None:
    result = set_ini_value(SAMPLE, "playback", "idle_mode", "loop_forward")

    playback = result.split("[sensor]")[0]
    assert "idle_mode = loop_forward" in playback, "the key lands in its own section"


def test_set_ini_value_creates_a_missing_section_for_old_configs() -> None:
    """A config from before [schedule] existed must still be editable."""
    result = set_ini_value(SAMPLE, "schedule", "enabled", "true")

    assert "[schedule]" in result
    assert "enabled = true" in result.split("[schedule]")[1]


def test_edits_do_not_leak_into_the_wrong_section() -> None:
    both = SAMPLE + "\n[lcd]\nenabled = false\n"

    result = set_ini_value(both, "schedule", "enabled", "true")

    lcd_part = result.split("[lcd]")[1].split("[schedule]")[0]
    assert "enabled = false" in lcd_part, "the lcd key is untouched"


def test_repeated_edits_are_idempotent() -> None:
    once = set_ini_value(SAMPLE, "schedule", "enabled", "true")
    twice = set_ini_value(once, "schedule", "enabled", "true")

    assert once == twice


def test_the_strip_preset_hint_uses_fill() -> None:
    hint = render_prepare_hint("~/memory-machine-media/piece.mp4", 1920, 480, "fill")

    assert "--size 1920x480" in hint
    assert "--mode fill" in hint


def test_the_square_preset_hint_uses_fit() -> None:
    hint = render_prepare_hint("~/memory-machine-media/piece.mp4", 720, 720, "fit")

    assert "--mode fit" in hint
