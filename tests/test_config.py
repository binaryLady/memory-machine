from __future__ import annotations

import textwrap
from pathlib import Path

import config


def _write(tmp_path: Path, content: str) -> str:
    path = tmp_path / "config.ini"
    path.write_text(textwrap.dedent(content))
    return str(path)


def test_defaults_used_when_section_missing(tmp_path: Path) -> None:
    path = _write(tmp_path, "[system]\nlog_level = debug\n")
    cfg = config.load(path)
    assert cfg.playback.idle_mode == "hold_first_frame"
    assert cfg.audio.volume == 0.8


def test_missing_key_falls_back(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        [audio]
        volume = 0.5
        """,
    )
    cfg = config.load(path)
    assert cfg.audio.fade_out_ms == 400
    assert cfg.audio.volume == 0.5


def test_unknown_key_is_ignored(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        [playback]
        idle_mode = black
        unknown_key = 123
        [no_such_section]
        foo = bar
        """,
    )
    cfg = config.load(path)
    assert cfg.playback.idle_mode == "black"


def test_out_of_range_values_are_clamped(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        [audio]
        volume = 4.0
        [sensor]
        threshold_cm = -5
        """,
    )
    cfg = config.load(path)
    assert cfg.audio.volume == 1.0
    assert cfg.sensor.threshold_cm == 0.0


def test_relative_media_paths_resolve(tmp_path: Path) -> None:
    path = _write(tmp_path, "[media]\nvideo_file = custom.mp4\n")
    cfg = config.load(path)
    assert cfg.media.video_file == Path("/opt/motion-player/media/custom.mp4")


def test_validate_reports_missing_files(tmp_path: Path) -> None:
    path = _write(tmp_path, "[media]\nvideo_file = /no/such/file.mp4\n")
    cfg = config.load(path)
    problems = config.validate(cfg)
    assert any("not found" in p for p in problems)


def test_validate_invalid_idle_mode(tmp_path: Path) -> None:
    path = _write(tmp_path, "[playback]\nidle_mode = unsupported\n")
    cfg = config.load(path)
    problems = config.validate(cfg)
    assert any("idle_mode" in p for p in problems)
