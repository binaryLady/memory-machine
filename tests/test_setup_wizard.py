"""Setup wizard tests: the pure config-editing helpers and the --set path."""
from __future__ import annotations

import pytest

from setup_wizard import parse_set_args, render_prepare_hint, set_ini_value

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


def test_the_reward_choices_map_to_real_config_values() -> None:
    """The menu speaks the visitor's language; the config speaks the engine's."""
    mapping = {"t": "resume_forward", "f": "hold", "s": "loop_reverse"}
    labels = ["turn and play forward - the reward for staying present",
              "fade to black and hold",
              "start the rewind over"]

    # Every menu label's first letter resolves to a valid engine mode.
    import config as config_module

    for label in labels:
        assert mapping[label[0]] in config_module._VALID_ON_REWIND_END


def test_audio_device_listing_degrades_to_empty_off_pi() -> None:
    """No pygame, no devices — the wizard skips the menu instead of crashing."""
    import setup_wizard

    assert isinstance(setup_wizard.audio_device_names(), list)


def test_parse_set_args_reads_section_key_and_value() -> None:
    pairs = parse_set_args([
        "media.video_file=piece.800x1280.mp4",
        "playback.scaling=fit",
    ])

    assert pairs == [
        ("media", "video_file", "piece.800x1280.mp4"),
        ("playback", "scaling", "fit"),
    ]


def test_parse_set_args_splits_on_the_first_equals_only() -> None:
    """A value may itself contain an equals sign."""
    pairs = parse_set_args(["system.extra=a=b"])

    assert pairs == [("system", "extra", "a=b")]


@pytest.mark.parametrize("bad", ["scaling=fit", "playback.scaling", "=fit", "playback.=x"])
def test_parse_set_args_rejects_malformed_input(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_set_args([bad])


def test_apply_settings_edits_the_config_and_backs_it_up(tmp_path, monkeypatch, capsys) -> None:
    """The prepare handoff: values land in the file, the old file survives."""
    import setup_wizard

    config = tmp_path / "config.ini"
    config.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "CONFIG_PATH", config)

    result = setup_wizard.apply_settings(
        [("media", "video_file", "piece.800x1280.mp4"), ("playback", "scaling", "fill")]
    )

    assert result == 0
    written = config.read_text(encoding="utf-8")
    assert "video_file = piece.800x1280.mp4" in written
    assert "scaling             = fill" in written
    backups = list(tmp_path.glob("config.ini.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == SAMPLE


def test_test_mode_renders_exactly_like_the_show() -> None:
    """Test mode is observability, never a different picture."""
    from setup_wizard import apply_run_mode

    result = apply_run_mode(SAMPLE, gallery=False)

    assert "fullscreen          = true" in result
    assert "mode = test" in result
    assert "false" not in result.split("fullscreen")[1].splitlines()[0]


def test_gallery_mode_asserts_fullscreen_and_clears_soak() -> None:
    from setup_wizard import apply_run_mode

    result = apply_run_mode(SAMPLE, gallery=True)

    assert "fullscreen          = true" in result
    assert "mode = production" in result
    assert "exit_after_s = 0" in result


def test_either_mode_repairs_a_config_that_test_mode_once_windowed() -> None:
    """Old configs have fullscreen=false baked in from the old test mode."""
    from setup_wizard import apply_run_mode, set_ini_value

    stale = set_ini_value(SAMPLE, "playback", "fullscreen", "false")

    for gallery in (True, False):
        assert "fullscreen          = true" in apply_run_mode(stale, gallery=gallery)
