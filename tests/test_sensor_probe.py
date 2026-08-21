"""motion-player-sensor tests: the pure log parsing, arithmetic, and wording."""
from __future__ import annotations

from sensor_probe import (
    GAMEPAD_SETTINGS,
    TOUCH_SETTINGS,
    fit_plan,
    format_report,
    hold_seconds,
    parse_log,
    settings_missing,
)


def fixture_log(overrides: list[str] | None = None) -> list[str]:
    lines = [
        "INFO Video loaded: /home/b/piece.mp4 frames=900 fps=30.00 size=1280x800 reverse=True",
        "INFO Audio loaded: /home/b/piece.wav duration=30.000s volume=0.80",
        "INFO reverse_rate=native reverse_step=1.0000",
    ]
    return lines + (overrides or [])


def test_parse_log_reads_the_engines_own_lines() -> None:
    facts = parse_log(fixture_log())

    assert facts["frames"] == 900
    assert facts["fps"] == 30.0
    assert facts["audio_duration_s"] == 30.0
    assert facts["reverse_rate"] == "native"
    assert facts["reverse_step"] == 1.0


def test_parse_log_finds_accepted_lifts_and_ignores_rejected_ones() -> None:
    facts = parse_log(fixture_log([
        "INFO transition sensor=capacitive intended_raw=engaged accepted=false reason=dwell",
        "INFO transition sensor=capacitive event=lift raw=engaged engaged_when=closed accepted=true ts=12.5",
    ]))

    assert facts["lift_sensors"] == ["capacitive"]


def test_parse_log_reports_no_lift_when_only_rejections_are_present() -> None:
    facts = parse_log(fixture_log([
        "INFO transition sensor=capacitive intended_raw=engaged accepted=false reason=dwell",
    ]))

    assert facts["lift_sensors"] == []


def test_hold_seconds_matches_the_engines_rewind_arithmetic() -> None:
    # 900 frames at 30fps, one frame per interval: 30 seconds of holding on.
    assert hold_seconds(900, 30.0, 1.0) == 30.0
    # Twice the step covers the clip in half the time.
    assert hold_seconds(900, 30.0, 2.0) == 15.0


def test_hold_seconds_is_none_when_the_log_has_not_said_yet() -> None:
    assert hold_seconds(None, 30.0, 1.0) is None
    assert hold_seconds(900, 0.0, 1.0) is None
    assert hold_seconds(900, 30.0, 0.0) is None


def sensor_fixture(**overrides: object) -> dict:
    base = {
        "sensor_type": "capacitive",
        "engaged_when": "closed",
        "gpio_pin": 4,
        "pull_up": True,
        "i2c_address": 0x5A,
        "touch_channel": 0,
        "i2c_bus": 1,
    }
    base.update(overrides)
    return base


def test_report_fails_both_verdicts_on_a_log_that_never_saw_a_lift() -> None:
    text = format_report(sensor_fixture(), {"audio_mode": "always", "audio_sink": "USB"},
                         "MPR121 answers at 0x5a on i2c-1", parse_log(fixture_log()))

    assert "FAIL  no lift has ever been accepted" in text
    assert "FAIL  no 'Playback REVERSE' line" in text


def test_report_passes_both_verdicts_once_the_hardware_has_run() -> None:
    facts = parse_log(fixture_log([
        "INFO transition sensor=capacitive event=lift raw=engaged engaged_when=closed accepted=true ts=1.0",
        "INFO Playback REVERSE: 29.9 fps target 30.0, frame mean 4.1ms worst 9.0ms, 0/300 late",
    ]))

    text = format_report(sensor_fixture(), {"audio_mode": "always", "audio_sink": "USB"},
                         "MPR121 answers at 0x5a on i2c-1", facts)

    assert "PASS  a lift has been accepted, from: capacitive" in text
    assert "PASS  the rewind has run" in text


def test_report_states_the_hold_in_seconds() -> None:
    text = format_report(sensor_fixture(), {"audio_mode": "always", "audio_sink": "USB"},
                         "MPR121 answers at 0x5a on i2c-1", parse_log(fixture_log()))

    assert "a visitor must hold for 30 seconds to reach the turn" in text


def test_report_warns_when_the_hold_is_longer_than_anyone_will_stay() -> None:
    facts = parse_log([
        "INFO Video loaded: /p.mp4 frames=9000 fps=30.00 size=1280x800 reverse=True",
        "INFO reverse_rate=native reverse_step=1.0000",
    ])

    text = format_report(sensor_fixture(), {"audio_mode": "always", "audio_sink": "USB"},
                         "MPR121 answers at 0x5a on i2c-1", facts)

    assert "a visitor must hold for 300 seconds" in text
    assert "reverse_rate above 1.0" in text


def test_report_shows_the_pin_for_a_digital_backend_and_the_bus_for_a_pad() -> None:
    digital = format_report(sensor_fixture(sensor_type="gpio_raw"), {"audio_mode": "on_lift",
                            "audio_sink": "USB"}, "GPIO 4 reads open right now", parse_log(fixture_log()))
    pad = format_report(sensor_fixture(), {"audio_mode": "always", "audio_sink": "USB"},
                        "MPR121 answers at 0x5a on i2c-1", parse_log(fixture_log()))

    assert "gpio_pin      4" in digital
    assert "i2c_address" in pad and "channel 0" in pad


def touch_config_fixture(**overrides: str) -> dict:
    base = {
        "sensor.sensor_type": "capacitive",
        "sensor.engaged_when": "closed",
        "sensor.i2c_address": "0x5a",
        "sensor.touch_channel": "0",
    }
    base.update(overrides)
    return base


def test_fit_plan_lists_only_what_the_machine_is_missing() -> None:
    assert fit_plan(i2c_ready=False, driver_ready=False, tools_ready=False,
                    config_ready=False) == ["i2c", "tools", "driver", "config"]
    assert fit_plan(i2c_ready=True, driver_ready=False, tools_ready=True,
                    config_ready=True) == ["driver"]


def test_fit_plan_is_empty_once_everything_is_in_place() -> None:
    assert fit_plan(i2c_ready=True, driver_ready=True, tools_ready=True,
                    config_ready=True) == []


def test_touch_settings_are_the_shipped_defaults() -> None:
    # engaged_when and i2c_address move together with sensor_type or the piece
    # breaks silently: a pad left on "open" runs whenever nobody touches it,
    # and 0x29 is the range-finder's address, not the pad's.
    assert dict(TOUCH_SETTINGS) == touch_config_fixture()


def test_touch_settings_missing_is_empty_when_the_config_already_matches() -> None:
    assert settings_missing(TOUCH_SETTINGS, touch_config_fixture()) == []


def test_touch_settings_missing_carries_the_polarity_and_address_with_the_sensor() -> None:
    switch = touch_config_fixture(**{"sensor.sensor_type": "switch",
                                     "sensor.engaged_when": "open",
                                     "sensor.i2c_address": "0x29"})

    assert settings_missing(TOUCH_SETTINGS, switch) == [
        ("sensor.sensor_type", "capacitive"),
        ("sensor.engaged_when", "closed"),
        ("sensor.i2c_address", "0x5a"),
    ]


def test_touch_settings_missing_treats_an_unset_address_as_missing() -> None:
    # The backend falls back to 0x5a when the key is unset, but the report and
    # the wizard both state it, so --fit writes it rather than leaving it blank.
    assert settings_missing(TOUCH_SETTINGS, touch_config_fixture(**{"sensor.i2c_address": ""})) == [
        ("sensor.i2c_address", "0x5a"),
    ]


def test_the_gamepad_carries_its_polarity_with_it() -> None:
    # A held button closes its contact; left on "open" the piece would run
    # whenever nobody is holding anything.
    assert dict(GAMEPAD_SETTINGS) == {
        "sensor.sensor_type": "gamepad",
        "sensor.engaged_when": "closed",
    }


def test_settings_missing_reads_the_wanted_set_it_is_given() -> None:
    pad_config = touch_config_fixture()

    assert settings_missing(GAMEPAD_SETTINGS, pad_config) == [
        ("sensor.sensor_type", "gamepad"),
    ]


def test_fit_config_names_the_sensor_it_is_fitting(monkeypatch, capsys) -> None:
    """The gamepad branch must not speak of the touch pad, and vice versa."""
    import sensor_probe

    monkeypatch.setattr(sensor_probe, "_run", lambda cmd: True)
    monkeypatch.setattr(sensor_probe.sys.stdin, "isatty", lambda: False)

    sensor_probe._fit_config([], "switch", "gamepad", "gamepad")
    out = capsys.readouterr().out
    assert "not the gamepad" in out
    assert "touch pad" not in out

    sensor_probe._fit_config([], "switch", "capacitive", "touch pad")
    out = capsys.readouterr().out
    assert "not the touch pad" in out


def test_fit_config_leaves_the_matching_sensor_unquestioned(monkeypatch, capsys) -> None:
    import sensor_probe

    monkeypatch.setattr(sensor_probe, "_run", lambda cmd: True)

    assert sensor_probe._fit_config([], "gamepad", "gamepad", "gamepad") == 0
    assert "not the" not in capsys.readouterr().out
