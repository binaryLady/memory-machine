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


def test_discover_renders_lists_only_clips_with_a_reverse(tmp_path) -> None:
    from setup_wizard import discover_renders

    for name in ("piece.mp4", "piece.reverse.mp4",
                 "piece.kaleidoscope.1280x800.mp4", "piece.kaleidoscope.1280x800.reverse.mp4",
                 "orphan.mp4"):
        (tmp_path / name).touch()

    assert discover_renders(tmp_path) == ["piece.kaleidoscope.1280x800.mp4", "piece.mp4"]


def test_parse_picks_accepts_one_or_several() -> None:
    from setup_wizard import parse_picks

    assert parse_picks("2", 3) == [2]
    assert parse_picks("1,3", 3) == [1, 3]
    assert parse_picks("3, 1, 3", 3) == [3, 1]


@pytest.mark.parametrize("bad", ["0", "4", "x", "1 x", ""])
def test_parse_picks_rejects_out_of_range_and_garbage(bad: str) -> None:
    from setup_wizard import parse_picks

    with pytest.raises(ValueError):
        parse_picks(bad, 3)


def test_a_single_render_choice_is_authoritative() -> None:
    """One pick sets the file pair and clears cuts so nothing second-guesses it."""
    from setup_wizard import apply_render_choice

    renders = ["piece.kaleidoscope.1280x800.mp4", "piece.mp4"]
    result = apply_render_choice(SAMPLE, renders, [1])

    assert "video_file = piece.kaleidoscope.1280x800.mp4" in result
    assert "reverse_file = piece.kaleidoscope.1280x800.reverse.mp4" in result
    cuts_lines = [line for line in result.splitlines() if line.startswith("cuts")]
    assert cuts_lines == ["cuts = "], "cuts is cleared, not left pointing elsewhere"


def test_several_render_choices_become_the_cut_set() -> None:
    from setup_wizard import apply_render_choice

    renders = ["piece_portrait.800x1280.mp4", "piece.1280x800.mp4", "piece.mp4"]
    result = apply_render_choice(SAMPLE, renders, [1, 2])

    assert "cuts = piece_portrait.800x1280.mp4, piece.1280x800.mp4" in result


def test_sanitize_setup_name_normalises_and_rejects_paths() -> None:
    from setup_wizard import sanitize_setup_name

    assert sanitize_setup_name("Gallery B / Portrait") == "gallery-b-portrait"
    assert sanitize_setup_name("vsdisplay-portrait") == "vsdisplay-portrait"
    assert sanitize_setup_name("../../etc/passwd") == "etcpasswd"
    assert sanitize_setup_name("///") is None
    assert sanitize_setup_name("   ") is None


def test_setups_save_load_roundtrip(tmp_path, monkeypatch) -> None:
    """A saved setup applies back verbatim through the safe write path."""
    import setup_wizard

    config = tmp_path / "config.ini"
    config.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "CONFIG_PATH", config)
    monkeypatch.setattr(setup_wizard, "setups_dir", lambda: tmp_path / "setups")

    saved = setup_wizard.save_setup(SAMPLE, "gallery-a")
    assert saved == tmp_path / "setups" / "gallery-a.ini"
    assert saved.read_text(encoding="utf-8") == SAMPLE
    assert setup_wizard.list_setups(tmp_path / "setups") == ["gallery-a"]

    config.write_text("[playback]\nscaling = fill\n", encoding="utf-8")
    assert setup_wizard.load_setup("gallery-a") == 0
    assert config.read_text(encoding="utf-8") == SAMPLE
    assert list(tmp_path.glob("config.ini.bak-*")), "the overwritten config was backed up"


def test_loading_a_missing_setup_names_the_ones_that_exist(tmp_path, monkeypatch, capsys) -> None:
    import setup_wizard

    monkeypatch.setattr(setup_wizard, "setups_dir", lambda: tmp_path / "setups")
    setup_wizard.save_setup(SAMPLE, "gallery-a")

    assert setup_wizard.load_setup("nope") == 1
    assert "gallery-a" in capsys.readouterr().out


def test_duplicate_setup_copies_without_touching_the_original(tmp_path, monkeypatch) -> None:
    import setup_wizard

    monkeypatch.setattr(setup_wizard, "setups_dir", lambda: tmp_path / "setups")
    setup_wizard.save_setup(SAMPLE, "gallery-a")

    assert setup_wizard.duplicate_setup("gallery-a", "gallery-b") == 0
    names = setup_wizard.list_setups(tmp_path / "setups")
    assert names == ["gallery-a", "gallery-b"]
    a = (tmp_path / "setups" / "gallery-a.ini").read_text(encoding="utf-8")
    b = (tmp_path / "setups" / "gallery-b.ini").read_text(encoding="utf-8")
    assert a == b == SAMPLE


ALSA_CARDS = """\
 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1
                      vc4-hdmi-1
 2 [Device         ]: USB-Audio - USB Audio Device
                      C-Media Electronics Inc. USB Audio Device at usb-0000:01:00.0-1.3
"""


def test_alsa_cards_parse_includes_the_usb_adapter() -> None:
    from setup_wizard import parse_alsa_cards

    assert parse_alsa_cards(ALSA_CARDS) == ["vc4-hdmi-0", "vc4-hdmi-1", "USB Audio Device"]


def test_alsa_cards_parse_survives_garbage() -> None:
    from setup_wizard import parse_alsa_cards

    assert parse_alsa_cards("") == []
    assert parse_alsa_cards("no cards at all\n") == []


def test_alsa_cards_degrade_to_empty_off_pi() -> None:
    import setup_wizard

    assert isinstance(setup_wizard.alsa_cards(), list)
