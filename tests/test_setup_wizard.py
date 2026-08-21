"""Setup wizard tests: the pure config-editing helpers and the --set path."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import setup_wizard
from setup_wizard import (
    apply_sensor_choice,
    parse_set_args,
    render_prepare_hint,
    run_questions,
    set_ini_value,
)

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


def test_the_opening_menu_lists_every_saved_run_by_name() -> None:
    from setup_wizard import setup_menu

    menu = setup_menu(["gallery-b", "show-opening"])

    assert menu[0].startswith("walk through")
    assert "gallery-b (saved setup)" in menu
    assert "show-opening (saved setup)" in menu
    assert any(c.startswith("save") for c in menu)
    assert any(c.startswith("duplicate") for c in menu)


def test_the_opening_menu_without_setups_still_offers_walk_and_save() -> None:
    from setup_wizard import setup_menu

    menu = setup_menu([])

    assert menu[0].startswith("walk through")
    assert any(c.startswith("save") for c in menu)
    assert not any(c.startswith("duplicate") for c in menu)


def test_menu_choices_map_back_to_their_setup_names() -> None:
    from setup_wizard import menu_choice_setup_name, setup_menu

    menu = setup_menu(["gallery-b"])

    assert menu_choice_setup_name("gallery-b (saved setup)") == "gallery-b"
    assert menu_choice_setup_name(menu[0]) is None
    assert menu_choice_setup_name("save the current config as a setup") is None
    assert menu_choice_setup_name(None) is None


def test_picking_a_run_from_the_menu_plays_that_run(tmp_path, monkeypatch) -> None:
    """The correct choice plays: choose gallery-b, gallery-b's config is live."""
    import setup_wizard
    from setup_wizard import list_setups, menu_choice_setup_name, setup_menu

    config = tmp_path / "config.ini"
    config.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "CONFIG_PATH", config)
    monkeypatch.setattr(setup_wizard, "setups_dir", lambda: tmp_path / "setups")

    opening = SAMPLE.replace("scaling             = fit", "scaling             = fill")
    gallery_b = SAMPLE.replace("sensor_type         = switch", "sensor_type         = keyboard")
    setup_wizard.save_setup(opening, "show-opening")
    setup_wizard.save_setup(gallery_b, "gallery-b")

    menu = setup_menu(list_setups(tmp_path / "setups"))
    choice = next(c for c in menu if c.startswith("gallery-b"))
    name = menu_choice_setup_name(choice)

    assert name == "gallery-b"
    assert setup_wizard.load_setup(name) == 0
    live = config.read_text(encoding="utf-8")
    assert live == gallery_b, "the chosen run's config, byte for byte"
    assert "keyboard" in live and "fill" not in live, "not the other setup"


FULL_CONFIG = """[media]
video_file          = piece.mp4

[playback]
scaling             = fit

[sensor]
sensor_type         = switch
engaged_when        = open
gpio_pin            = 4

[audio]
audio_sink          = USB
audio_mode          = always

[lcd]
enabled             = false

[schedule]
enabled             = false

[telemetry]
enabled             = false

[system]
mode                = production
"""


def test_apply_sensor_choice_sets_the_polarity_a_touch_pad_needs() -> None:
    result = apply_sensor_choice(FULL_CONFIG, "capacitive")

    assert "sensor_type         = capacitive" in result
    # A pad is engaged when its contact closes; left on "open" the piece would
    # run whenever nobody is touching it.
    assert "engaged_when        = closed" in result


def test_apply_sensor_choice_sets_the_polarity_a_cradle_switch_needs() -> None:
    result = apply_sensor_choice(apply_sensor_choice(FULL_CONFIG, "capacitive"), "switch")

    assert "sensor_type         = switch" in result
    assert "engaged_when        = open" in result
    assert "gpio_pin            = 4" in result


def test_apply_sensor_choice_leaves_pin_and_polarity_alone_for_the_pinless_backends() -> None:
    for sensor_type in ("keyboard", "none"):
        result = apply_sensor_choice(FULL_CONFIG, sensor_type)

        assert f"sensor_type         = {sensor_type}" in result
        assert "engaged_when        = open" in result, "polarity is meaningless here"


def test_apply_sensor_choice_ignores_a_backend_it_does_not_offer() -> None:
    assert apply_sensor_choice(FULL_CONFIG, "not-a-sensor") == FULL_CONFIG


def test_every_offered_sensor_is_a_backend_the_config_accepts() -> None:
    import config as config_module

    for value, _polarity, _pin, _address, label in setup_wizard.SENSOR_CHOICES:
        assert value in config_module._VALID_SENSOR_TYPES
        assert label.split(" ")[0] == value, "the caller takes the first token"


def test_pressing_enter_through_every_question_returns_the_config_untouched(monkeypatch) -> None:
    """HANDOFF's wizard smoke test, as a test rather than an instruction."""
    monkeypatch.setattr("builtins.input", lambda *_args: "")
    monkeypatch.setattr(setup_wizard, "detected_screens", lambda: [])
    monkeypatch.setattr(setup_wizard, "audio_device_names", lambda: [])
    monkeypatch.setattr(setup_wizard, "discover_renders", lambda _d: [])

    assert run_questions(FULL_CONFIG) == FULL_CONFIG


def test_apply_sensor_choice_points_the_pad_at_its_own_i2c_address() -> None:
    # One key, two backends: the MPR121 lives at 0x5a and the VL53L0X at 0x29,
    # so leaving the range-finder's address behind hides the pad completely.
    ranged = set_ini_value(FULL_CONFIG, "sensor", "i2c_address", "0x29")

    result = apply_sensor_choice(ranged, "capacitive")

    assert re.search(r"i2c_address\s*=\s*0x5a", result)
    assert "0x29" not in result


def test_the_packaged_ini_points_at_the_sensor_it_ships_with() -> None:
    import config as config_module

    cfg = config_module.load(str(Path(__file__).resolve().parent.parent
                                 / "config" / "config.default.ini"))

    assert cfg.sensor.sensor_type == "capacitive"
    assert cfg.sensor.i2c_address == 0x5A, "the MPR121's address, not the ToF's"
