"""Host health reader tests: tmp_path fixtures, no real hardware."""
from __future__ import annotations

from pathlib import Path

import sysinfo


def test_mem_available_is_read_from_a_meminfo_snapshot(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:  4045816 kB\nMemFree:  123456 kB\nMemAvailable:  2048000 kB\n")

    assert sysinfo.read_mem_available_mb(str(meminfo)) == 2000.0


def test_mem_available_falls_back_to_zero_when_unreadable(tmp_path: Path) -> None:
    assert sysinfo.read_mem_available_mb(str(tmp_path / "absent")) == 0.0


def test_load_average_is_the_first_field(tmp_path: Path) -> None:
    loadavg = tmp_path / "loadavg"
    loadavg.write_text("1.42 0.98 0.75 2/345 6789\n")

    assert sysinfo.read_load_1m(str(loadavg)) == 1.42


def test_load_average_falls_back_to_zero_when_unreadable(tmp_path: Path) -> None:
    assert sysinfo.read_load_1m(str(tmp_path / "absent")) == 0.0


def test_throttled_is_none_when_vcgencmd_is_missing(monkeypatch) -> None:
    """Off-Pi development machines have no vcgencmd; that is not an error."""
    def missing(*args, **kwargs):
        raise FileNotFoundError("vcgencmd")

    monkeypatch.setattr(sysinfo.subprocess, "run", missing)

    assert sysinfo.read_throttled() is None


def test_throttled_reports_the_firmware_flags(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "throttled=0x50000\n"

    monkeypatch.setattr(sysinfo.subprocess, "run", lambda *a, **k: Result())

    assert sysinfo.read_throttled() == "0x50000"


def test_version_comes_from_build_info_and_degrades_to_unknown(tmp_path: Path) -> None:
    build_info = tmp_path / "BUILD_INFO"
    build_info.write_text("built=2026-08-19\nversion=1.0.1~git71.f94a033\n")

    assert sysinfo.read_version(build_info) == "1.0.1~git71.f94a033"
    # Missing BUILD_INFO falls back to the repo VERSION file during development.
    assert sysinfo.read_version(tmp_path / "absent") not in ("", None)


def test_disk_free_is_zero_for_a_nonexistent_path(tmp_path: Path) -> None:
    assert sysinfo.disk_free_mb(tmp_path / "absent") == 0.0
    assert sysinfo.disk_free_mb(tmp_path) > 0.0
