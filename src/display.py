"""Display output discovery and mode pinning.

The gallery must come up on whatever screens are attached, so every function
here degrades to a logged message rather than raising: a wrong or missing mode
should never stop the piece from playing.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

LOGGER = logging.getLogger("motion-player.display")

DRM_ROOT = Path("/sys/class/drm")
_MODE_RE = re.compile(r"^\d+x\d+(@\d+(\.\d+)?)?$")


def is_valid_mode(mode: str) -> bool:
    """True for WIDTHxHEIGHT or WIDTHxHEIGHT@RATE."""
    return bool(_MODE_RE.match(mode))


def connected_outputs(drm_root: Path = DRM_ROOT) -> list[str]:
    """Names of connected DRM connectors, e.g. ["HDMI-A-1"]."""
    names: list[str] = []
    for status in sorted(drm_root.glob("card*-*/status")):
        try:
            if status.read_text().strip() != "connected":
                continue
        except OSError:
            continue
        # Directory names look like card1-HDMI-A-1; drop the card prefix.
        _, _, connector = status.parent.name.partition("-")
        if connector:
            names.append(connector)
    return names


def resolve_connector(configured: str, drm_root: Path = DRM_ROOT) -> str | None:
    outputs = connected_outputs(drm_root)
    if configured and configured != "auto":
        if configured not in outputs:
            LOGGER.warning(
                "Configured display %r is not reported as connected (connected: %s); trying it anyway",
                configured,
                outputs or "none",
            )
        return configured
    if not outputs:
        return None
    if len(outputs) > 1:
        LOGGER.info("Several outputs connected (%s); using %s", outputs, outputs[0])
    return outputs[0]


def mode_command(connector: str, mode: str) -> list[str] | None:
    """The randr invocation for this session, or None if neither tool exists."""
    if shutil.which("wlr-randr"):
        return ["wlr-randr", "--output", connector, "--mode", mode]
    if shutil.which("xrandr"):
        # xrandr takes the refresh rate separately, so drop it.
        return ["xrandr", "--output", connector, "--mode", mode.split("@")[0]]
    return None


def apply_mode(configured_display: str, mode: str) -> str:
    """Pin the output mode. Returns a short status string for logs and status.json."""
    if not mode or mode == "auto":
        return "auto"

    if not is_valid_mode(mode):
        LOGGER.error("Invalid display_mode %r; expected WIDTHxHEIGHT[@RATE]", mode)
        return "invalid"

    connector = resolve_connector(configured_display)
    if connector is None:
        LOGGER.error("No connected output found; leaving the display mode alone")
        return "no-output"

    cmd = mode_command(connector, mode)
    if cmd is None:
        LOGGER.warning("Neither wlr-randr nor xrandr is installed; cannot pin the display mode")
        return "unavailable"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        LOGGER.error("Could not run %s: %s", cmd[0], exc)
        return "failed"

    if result.returncode != 0:
        LOGGER.error("%s failed: %s", cmd[0], (result.stderr or result.stdout).strip())
        return "failed"

    LOGGER.info("Display %s pinned to %s via %s", connector, mode, cmd[0])
    return f"{connector}@{mode}"


def preferred_mode(connector: str, drm_root: Path = DRM_ROOT) -> tuple[int, int] | None:
    """First mode the sink advertises, which is the one it asks to be driven at."""
    for modes in sorted(drm_root.glob(f"card*-{connector}/modes")):
        try:
            first = modes.read_text().splitlines()
        except OSError:
            continue
        if not first:
            continue
        width, _, height = first[0].strip().partition("x")
        try:
            return int(width), int(height)
        except ValueError:
            continue
    return None


def output_resolution(
    configured_display: str, configured_mode: str, drm_root: Path = DRM_ROOT
) -> tuple[int, int] | None:
    """The screen size, worked out without needing a window to exist yet.

    Media has to be chosen before the window is mapped, so the window cannot be
    asked. A pinned display_mode is authoritative; otherwise fall back to what
    the connected sink advertises.
    """
    if configured_mode and configured_mode != "auto" and is_valid_mode(configured_mode):
        size, _, _rate = configured_mode.partition("@")
        width, _, height = size.partition("x")
        return int(width), int(height)

    connector = resolve_connector(configured_display, drm_root)
    if connector is None:
        return None
    return preferred_mode(connector, drm_root)
