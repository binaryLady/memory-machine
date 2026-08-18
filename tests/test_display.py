"""Display helper tests. No hardware, no subprocesses actually run."""
from __future__ import annotations

from pathlib import Path

import display
import pytest


def fake_drm(tmp_path: Path, connectors: dict[str, str]) -> Path:
    """Build a /sys/class/drm lookalike: {"card1-HDMI-A-1": "connected"}."""
    for name, status in connectors.items():
        d = tmp_path / name
        d.mkdir()
        (d / "status").write_text(status + "\n")
    return tmp_path


@pytest.mark.parametrize(
    "mode,valid",
    [
        ("1920x1080", True),
        ("1920x1080@60", True),
        ("1920x1080@59.94", True),
        ("auto", False),
        ("1920", False),
        ("1920x", False),
        ("1920x1080@", False),
        ("; rm -rf /", False),
    ],
)
def test_mode_validation(mode: str, valid: bool) -> None:
    assert display.is_valid_mode(mode) is valid


def test_connected_outputs_ignores_disconnected(tmp_path: Path) -> None:
    root = fake_drm(tmp_path, {
        "card1-HDMI-A-1": "connected",
        "card1-HDMI-A-2": "disconnected",
    })

    assert display.connected_outputs(root) == ["HDMI-A-1"]


def test_connected_outputs_is_empty_with_no_screens(tmp_path: Path) -> None:
    root = fake_drm(tmp_path, {"card1-HDMI-A-1": "disconnected"})

    assert display.connected_outputs(root) == []


def test_auto_picks_the_first_connected_output(tmp_path: Path) -> None:
    root = fake_drm(tmp_path, {
        "card1-HDMI-A-1": "disconnected",
        "card1-HDMI-A-2": "connected",
    })

    assert display.resolve_connector("auto", root) == "HDMI-A-2"


def test_configured_connector_is_honoured_even_if_not_reported(tmp_path: Path) -> None:
    """A splitter can leave a connector looking unplugged; trust the operator."""
    root = fake_drm(tmp_path, {"card1-HDMI-A-1": "disconnected"})

    assert display.resolve_connector("HDMI-A-1", root) == "HDMI-A-1"


def test_auto_mode_does_no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("apply_mode must not shell out when set to auto")

    monkeypatch.setattr(display.subprocess, "run", explode)

    assert display.apply_mode("auto", "auto") == "auto"


def test_invalid_mode_is_rejected_before_shelling_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("apply_mode must not shell out on an invalid mode")

    monkeypatch.setattr(display.subprocess, "run", explode)

    assert display.apply_mode("HDMI-A-1", "1080p; reboot") == "invalid"


def test_wlr_randr_is_preferred_over_xrandr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display.shutil, "which", lambda name: "/usr/bin/" + name)

    assert display.mode_command("HDMI-A-1", "1920x1080@60") == [
        "wlr-randr", "--output", "HDMI-A-1", "--mode", "1920x1080@60"
    ]


def test_xrandr_fallback_drops_the_refresh_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        display.shutil, "which", lambda name: "/usr/bin/xrandr" if name == "xrandr" else None
    )

    assert display.mode_command("HDMI-A-1", "1920x1080@60") == [
        "xrandr", "--output", "HDMI-A-1", "--mode", "1920x1080"
    ]


def test_missing_randr_tools_report_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display.shutil, "which", lambda name: None)
    monkeypatch.setattr(display, "resolve_connector", lambda *a, **k: "HDMI-A-1")

    assert display.apply_mode("HDMI-A-1", "1920x1080@60") == "unavailable"


def test_a_failing_randr_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad mode must not stop the piece from playing."""
    monkeypatch.setattr(display.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(display, "resolve_connector", lambda *a, **k: "HDMI-A-1")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "unknown mode"

    monkeypatch.setattr(display.subprocess, "run", lambda *a, **k: Result())

    assert display.apply_mode("HDMI-A-1", "1920x1080@60") == "failed"


def test_success_reports_the_pinned_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(display, "resolve_connector", lambda *a, **k: "HDMI-A-1")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(display.subprocess, "run", lambda *a, **k: Result())

    assert display.apply_mode("HDMI-A-1", "1920x1080@60") == "HDMI-A-1@1920x1080@60"


def fake_modes(tmp_path: Path, connector: str, modes: list[str]) -> Path:
    d = tmp_path / f"card1-{connector}"
    d.mkdir(exist_ok=True)
    (d / "status").write_text("connected\n")
    (d / "modes").write_text("\n".join(modes) + "\n")
    return tmp_path


def test_preferred_mode_is_the_first_line(tmp_path: Path) -> None:
    root = fake_modes(tmp_path, "HDMI-A-1", ["1920x1080", "1280x720", "640x480"])

    assert display.preferred_mode("HDMI-A-1", root) == (1920, 1080)


def test_preferred_mode_is_none_without_a_sink(tmp_path: Path) -> None:
    assert display.preferred_mode("HDMI-A-1", tmp_path) is None


def test_a_pinned_mode_wins_over_the_sink(tmp_path: Path) -> None:
    """A forced mode is what the Pi will actually output, whatever EDID says."""
    root = fake_modes(tmp_path, "HDMI-A-1", ["1280x720"])

    assert display.output_resolution("HDMI-A-1", "1080x1920@60", root) == (1080, 1920)


def test_the_sink_is_used_when_no_mode_is_pinned(tmp_path: Path) -> None:
    root = fake_modes(tmp_path, "HDMI-A-1", ["1080x1920"])

    assert display.output_resolution("auto", "auto", root) == (1080, 1920)


def test_output_resolution_is_none_when_nothing_is_connected(tmp_path: Path) -> None:
    assert display.output_resolution("auto", "auto", tmp_path) is None


def test_a_malformed_mode_line_is_ignored(tmp_path: Path) -> None:
    root = fake_modes(tmp_path, "HDMI-A-1", ["not-a-mode"])

    assert display.preferred_mode("HDMI-A-1", root) is None
