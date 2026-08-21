"""Host health readers shared by the LCD panel, telemetry, and status.

Every reader swallows its errors and returns a safe zero or None: the gallery
rule is that a missing /proc file or absent vcgencmd must never take the piece
down, only leave a gap in the figures.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

LOGGER = logging.getLogger("motion-player.sysinfo")


def read_cpu_percent(previous: tuple[int, int] | None) -> tuple[float, tuple[int, int]]:
    """CPU use since the last call, from /proc/stat totals."""
    try:
        with open("/proc/stat", encoding="utf-8") as handle:
            fields = handle.readline().split()[1:]
    except OSError:
        return 0.0, previous or (0, 0)

    values = [int(v) for v in fields[:8]]
    idle = values[3] + values[4]
    total = sum(values)
    if previous is None:
        return 0.0, (idle, total)

    idle_delta = idle - previous[0]
    total_delta = total - previous[1]
    if total_delta <= 0:
        return 0.0, (idle, total)
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), (idle, total)


def read_temperature_c() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as handle:
            return int(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        return 0.0


def read_fan_level(path: str = "/sys/class/thermal/cooling_device0/cur_state") -> int | None:
    """The firmware-driven fan step of the official Active Cooler, 0 (off) to 4.

    None when no fan is fitted or off-Pi. The firmware owns the curve; this is
    read-only so the status file can show the cooler is pulling its weight.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def read_mem_available_mb(path: str = "/proc/meminfo") -> float:
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def read_load_1m(path: str = "/proc/loadavg") -> float:
    try:
        with open(path, encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def read_throttled() -> str | None:
    """The Pi firmware's throttle flags, e.g. "0x0", or None off-Pi.

    A non-zero value means the SoC has throttled or browned out at some point —
    the single most useful figure for an enclosed installation.
    """
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    _, _, value = result.stdout.strip().partition("=")
    return value or None


def disk_free_mb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / (1024 * 1024)
    except OSError:
        return 0.0


def read_version(build_info: Path = Path("/opt/motion-player/BUILD_INFO")) -> str:
    """The installed package version, for correlating telemetry with releases."""
    try:
        for line in build_info.read_text(encoding="utf-8").splitlines():
            if line.startswith("version="):
                return line.partition("=")[2].strip() or "unknown"
    except OSError:
        pass
    try:
        repo_version = Path(__file__).resolve().parent.parent / "VERSION"
        return repo_version.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"
