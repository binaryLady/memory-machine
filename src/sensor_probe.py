#!/usr/bin/env python3
"""motion-player-sensor: check the sensor the piece is configured to use.

Two questions have been answered by hand in a markdown file for weeks: has a
lift ever actually been accepted from real hardware, and has the rewind ever
run end to end. Both are already in the log; this reads them out and says so
plainly, so the answer is a command rather than a memory.

The parsing and formatting below are pure functions over log lines, so they are
tested without a Pi, a GPIO pin, or an I2C bus.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_LOG_NAME = "motion-player.log"

# Lines the engine already writes. Kept together so a change to any of them is
# one edit here, not a hunt.
_VIDEO_RE = re.compile(r"Video loaded: (?P<path>\S+) frames=(?P<frames>\d+) fps=(?P<fps>[\d.]+)")
_AUDIO_RE = re.compile(r"Audio loaded: (?P<path>\S+) duration=(?P<duration>[\d.]+)s")
_STEP_RE = re.compile(r"reverse_rate=(?P<rate>\S+) reverse_step=(?P<step>[\d.]+)")
_LIFT_RE = re.compile(r"transition sensor=(?P<sensor>\S+) event=lift .*accepted=true")
_REVERSE_RE = re.compile(r"Playback REVERSE: (?P<detail>.+)")


def log_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "motion-player" / _LOG_NAME


def read_log_lines(path: Path) -> list[str]:
    """The log as text. Decoded leniently — it can carry control bytes."""
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_log(lines: list[str]) -> dict[str, Any]:
    """Pull the facts the report needs out of the engine's own log lines."""
    facts: dict[str, Any] = {
        "frames": None,
        "fps": None,
        "audio_duration_s": None,
        "reverse_rate": None,
        "reverse_step": None,
        "lift_sensors": [],
        "reverse_seen": None,
    }
    for line in lines:
        match = _VIDEO_RE.search(line)
        if match:
            facts["frames"] = int(match.group("frames"))
            facts["fps"] = float(match.group("fps"))
        match = _AUDIO_RE.search(line)
        if match:
            facts["audio_duration_s"] = float(match.group("duration"))
        match = _STEP_RE.search(line)
        if match:
            facts["reverse_rate"] = match.group("rate")
            facts["reverse_step"] = float(match.group("step"))
        match = _LIFT_RE.search(line)
        if match:
            sensor = match.group("sensor")
            if sensor not in facts["lift_sensors"]:
                facts["lift_sensors"].append(sensor)
        match = _REVERSE_RE.search(line)
        if match:
            facts["reverse_seen"] = match.group("detail")
    return facts


def hold_seconds(frames: int | None, fps: float | None, step: float | None) -> float | None:
    """How long a visitor must hold on to reach the turn.

    The same arithmetic as VideoEngine.rewind_duration_s: each frame interval
    advances reverse_step frames, so covering the clip takes frame_count /
    reverse_step intervals of 1/fps each. Computed here from the log so the
    report needs neither OpenCV nor the media.
    """
    if not frames or not fps or not step:
        return None
    if frames <= 0 or fps <= 0 or step <= 0:
        return None
    return frames / (step * fps)


def format_report(sensor_cfg: dict[str, Any], audio_cfg: dict[str, Any],
                  hardware: str, facts: dict[str, Any]) -> str:
    """The whole report as text. Pure, so its wording is testable."""
    out: list[str] = []
    sensor_type = sensor_cfg.get("sensor_type", "?")
    out.append("Configured")
    out.append(f"  sensor_type   {sensor_type}")
    out.append(f"  engaged_when  {sensor_cfg.get('engaged_when', '?')}")
    if sensor_type == "capacitive":
        out.append(f"  i2c_address   {sensor_cfg.get('i2c_address') or '0x5a'}"
                   f"  channel {sensor_cfg.get('touch_channel', 0)}")
    elif sensor_type == "gamepad":
        out.append(f"  device        {sensor_cfg.get('gamepad_device', 'auto')}")
        for job, controls in (sensor_cfg.get("gamepad_jobs") or {}).items():
            out.append(f"  {job:<13} {'+'.join(controls) or 'nothing'}")
    else:
        out.append(f"  gpio_pin      {sensor_cfg.get('gpio_pin', '?')}"
                   f"  pull_up {sensor_cfg.get('pull_up', '?')}")
    out.append(f"  audio_mode    {audio_cfg.get('audio_mode', '?')}")
    out.append(f"  audio_sink    {audio_cfg.get('audio_sink', '?')}")
    out.append("")
    out.append("Hardware")
    out.append(f"  {hardware}")
    out.append("")

    hold = hold_seconds(facts.get("frames"), facts.get("fps"), facts.get("reverse_step"))
    out.append("The hold")
    if hold is None:
        out.append("  unknown — the log has no 'Video loaded' line yet; start the piece once")
    else:
        out.append(f"  a visitor must hold for {hold:.0f} seconds to reach the turn")
        out.append(f"  ({facts['frames']} frames at {facts['fps']:.2f} fps, "
                   f"reverse_rate={facts.get('reverse_rate')} step={facts.get('reverse_step')})")
        if hold > 120:
            out.append("  that is a long time to ask someone to keep still — raising")
            out.append("  playback.reverse_rate above 1.0 shortens it without touching the audio")
    out.append("")

    out.append("Verdicts")
    lifts = facts.get("lift_sensors") or []
    if lifts:
        out.append(f"  PASS  a lift has been accepted, from: {', '.join(lifts)}")
    else:
        out.append("  FAIL  no lift has ever been accepted — the sensor is still decorative")
    if facts.get("reverse_seen"):
        out.append(f"  PASS  the rewind has run: {facts['reverse_seen']}")
    else:
        out.append("  FAIL  no 'Playback REVERSE' line — the rewind has never been measured")
    return "\n".join(out)


def _i2c_report(bus: int, address: int) -> str:
    """Whether the touch chip answers on the bus."""
    try:
        result = subprocess.run(
            ["i2cdetect", "-y", str(bus)],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run i2cdetect ({exc}); install i2c-tools"
    wanted = f"{address:02x}"
    if wanted in result.stdout.replace("--", "").split():
        return f"MPR121 answers at 0x{wanted} on i2c-{bus}"
    return (f"nothing at 0x{wanted} on i2c-{bus} — check the wiring, and that "
            f"I2C is enabled (raspi-config)")


def _gamepad_report(configured: str) -> str:
    """Which pad is plugged in, or why none can be read."""
    from sensors.gamepad import device_name, find_device

    path = find_device(configured)
    if path is None:
        hint = ""
        if Path("/proc/bus/input/devices").exists() and not Path("/dev/input").glob("js*"):
            hint = " (if the pad is plugged in, the joystick driver may be missing: modprobe joydev)"
        return f"no gamepad at {configured} — plug one into a USB port{hint}"
    if not os.access(path, os.R_OK):
        return (f"{device_name(path)} at {path}, but it is not readable — "
                f"sudo usermod -aG input $USER, then log out and back in")
    return f"{device_name(path)} at {path}"


def _gpio_report(pin: int, pull_up: bool) -> str:
    try:
        from gpiozero import Button  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        return f"gpiozero unavailable ({exc}); no GPIO reading possible"
    try:
        button = Button(pin, pull_up=pull_up)
    except Exception as exc:  # noqa: BLE001
        return (f"GPIO {pin} could not be read ({exc}) — the engine may still hold it; "
                f"stop it with motion-player-toggle --stop")
    try:
        return f"GPIO {pin} reads {'closed' if button.is_pressed else 'open'} right now"
    finally:
        button.close()


def describe_hardware(sensor_cfg: dict[str, Any]) -> str:
    sensor_type = sensor_cfg.get("sensor_type", "")
    if sensor_type in {"keyboard", "none"}:
        return f"no hardware to check for sensor_type={sensor_type}"
    if sensor_type == "capacitive":
        return _i2c_report(int(sensor_cfg.get("i2c_bus", 1)),
                           int(sensor_cfg.get("i2c_address") or 0x5A))
    if sensor_type == "gamepad":
        return _gamepad_report(str(sensor_cfg.get("gamepad_device", "auto")))
    return _gpio_report(int(sensor_cfg.get("gpio_pin", 4)),
                        bool(sensor_cfg.get("pull_up", True)))


def _load_config() -> Any:
    import config as config_module

    return config_module.load()


def report() -> int:
    cfg = _load_config()
    sensor_cfg = {
        "sensor_type": cfg.sensor.sensor_type,
        "engaged_when": cfg.sensor.engaged_when,
        "gpio_pin": cfg.sensor.gpio_pin,
        "pull_up": cfg.sensor.pull_up,
        "i2c_address": cfg.sensor.i2c_address,
        "touch_channel": cfg.sensor.touch_channel,
        "gamepad_device": cfg.sensor.gamepad_device,
        "gamepad_jobs": cfg.gamepad.jobs,
        "gamepad_numbers": cfg.gamepad.numbers,
        "i2c_bus": 1,
    }
    audio_cfg = {"audio_mode": cfg.audio.audio_mode, "audio_sink": cfg.audio.audio_sink}
    facts = parse_log(read_log_lines(log_path()))
    print(format_report(sensor_cfg, audio_cfg, describe_hardware(sensor_cfg), facts))
    return 0


def _watch_digital(pin: int, pull_up: bool, bounce_ms: int) -> None:
    from gpiozero import Button  # type: ignore[import-untyped]

    button = Button(pin, pull_up=pull_up, bounce_time=bounce_ms / 1000.0)
    contact_at: list[float] = []

    def on_press() -> None:
        contact_at.append(time.monotonic())
        print("contact", flush=True)

    def on_release() -> None:
        held = time.monotonic() - contact_at.pop() if contact_at else 0.0
        print(f"release  held {held:.2f}s{_hold_note(held)}", flush=True)

    button.when_pressed = on_press
    button.when_released = on_release
    print(f"watching GPIO {pin} — touch and let go; Ctrl+C to stop")
    print("now:", "closed" if button.is_pressed else "open")
    while True:
        time.sleep(0.1)


def _watch_capacitive(address: int, channel: int) -> None:
    import adafruit_mpr121  # type: ignore[import-untyped]
    import board  # type: ignore[import-untyped]
    import busio  # type: ignore[import-untyped]

    device = adafruit_mpr121.MPR121(busio.I2C(board.SCL, board.SDA), address=address)
    print(f"watching MPR121 0x{address:02x} channel {channel} — touch and let go; Ctrl+C to stop")
    last = False
    since = time.monotonic()
    while True:
        now = bool(device[channel].value)
        if now != last:
            if now:
                print("contact", flush=True)
                since = time.monotonic()
            else:
                held = time.monotonic() - since
                print(f"release  held {held:.2f}s{_hold_note(held)}", flush=True)
            last = now
        time.sleep(0.02)


def _hold_note(held: float) -> str:
    """A tap and a held contact drive the piece completely differently."""
    if held < 0.5:
        return "  <- a tap, not a held contact; the piece needs continuous contact"
    return ""


def _service(action: str) -> None:
    subprocess.run(["motion-player-toggle", f"--{action}"], check=False)


def what_a_control_does(gamepad: Any, control: str) -> str:
    """The jobs a control drives, as the probe prints them — "hold", "audio_next"…"""
    from sensors.gamepad import jobs_for

    return ", ".join(jobs_for(gamepad.jobs, control)) or "nothing"


def _watch_gamepad(configured: str, gamepad: Any) -> None:
    """Watch the pad live, naming every control and saying what it does.

    Every press is printed, named where the config has named it and as a bare
    number where it has not — which is how a pad that disagrees with the
    shipped numbers gets corrected from something somebody actually saw.
    """
    import select

    from sensors.gamepad import controls_from_event, device_name, find_device, jobs_for, parse_js_event

    path = find_device(configured)
    if path is None:
        print(f"no gamepad at {configured}; plug one in and try again")
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    print(f"watching {device_name(path)} at {path} — press and hold; Ctrl+C to stop")
    held: dict[str, float] = {}
    try:
        while True:
            ready, _, _ = select.select([descriptor], [], [], 0.5)
            if not ready:
                continue
            event = parse_js_event(os.read(descriptor, 8))
            if event is None:
                continue
            for control, pressed in controls_from_event(gamepad.numbers, *event):
                jobs = jobs_for(gamepad.jobs, control)
                does = what_a_control_does(gamepad, control)
                if pressed:
                    held[control] = time.monotonic()
                    print(f"contact  {control:<6} ({does})", flush=True)
                elif control in held:
                    seconds = time.monotonic() - held.pop(control)
                    note = _hold_note(seconds) if "hold" in jobs else ""
                    print(f"release  {control:<6} held {seconds:.2f}s{note}", flush=True)
    finally:
        os.close(descriptor)


def probe() -> int:
    cfg = _load_config()
    sensor_type = cfg.sensor.sensor_type
    if sensor_type in {"keyboard", "none"}:
        print(f"sensor_type is {sensor_type}; there is no hardware to probe.")
        return 1

    print("Stopping the engine — it holds the sensor while it runs.")
    _service("stop")
    try:
        if sensor_type == "capacitive":
            _watch_capacitive(int(cfg.sensor.i2c_address or 0x5A), cfg.sensor.touch_channel)
        elif sensor_type == "gamepad":
            _watch_gamepad(cfg.sensor.gamepad_device, cfg.gamepad)
        else:
            _watch_digital(cfg.sensor.gpio_pin, cfg.sensor.pull_up, cfg.sensor.bounce_time_ms)
    except KeyboardInterrupt:
        print()
    except Exception as exc:  # noqa: BLE001
        print(f"Probe failed: {exc}")
        return 1
    finally:
        print("Restarting the engine.")
        _service("start")
    return 0


# --- fitting the sensor ------------------------------------------------------

# Blinka and the MPR121 driver. Neither is packaged for apt, so the deb cannot
# depend on them, and without them a correctly wired pad still does nothing:
# the backend fails to initialise and the engine falls back to the keyboard.
_DRIVER_MODULES = ("board", "busio", "adafruit_mpr121")
_DRIVER_PACKAGE = "adafruit-circuitpython-mpr121"
_I2C_DEVICE = Path("/dev/i2c-1")
# The bus only appears after a reboot, so a fit that enables it stops there.
_REBOOT_FIRST = 2

# What the shipped pad wants in the config. i2c_address is one key read by
# whichever backend sensor_type names — the MPR121 at 0x5a, the VL53L0X at
# 0x29 — so it has to move with the sensor or the pad is looked for at the
# range-finder's address.
TOUCH_SETTINGS: tuple[tuple[str, str], ...] = (
    ("sensor.sensor_type", "capacitive"),
    ("sensor.engaged_when", "closed"),
    ("sensor.i2c_address", "0x5a"),
    ("sensor.touch_channel", "0"),
)


# What the shipped gamepad wants. A held button closes its contact, the same
# polarity as the pad — left on "open" the piece would run whenever nobody is
# holding anything.
GAMEPAD_SETTINGS: tuple[tuple[str, str], ...] = (
    ("sensor.sensor_type", "gamepad"),
    ("sensor.engaged_when", "closed"),
)


def settings_missing(wanted: tuple[tuple[str, str], ...],
                     current: dict[str, str]) -> list[tuple[str, str]]:
    """The settings the config does not already carry, in file order."""
    return [(key, value) for key, value in wanted if current.get(key) != value]


def fit_plan(i2c_ready: bool, driver_ready: bool, tools_ready: bool,
             config_ready: bool) -> list[str]:
    """The work left between a wired pad and one the engine can read.

    In order, and each step drops out once the machine already has it — so a
    second --fit run does nothing, and a run after a reboot picks up where the
    first one stopped.
    """
    steps = []
    if not i2c_ready:
        steps.append("i2c")
    if not tools_ready:
        steps.append("tools")
    if not driver_ready:
        steps.append("driver")
    if not config_ready:
        steps.append("config")
    return steps


def _current_settings(cfg: Any) -> dict[str, str]:
    address = cfg.sensor.i2c_address
    return {
        "sensor.sensor_type": cfg.sensor.sensor_type,
        "sensor.engaged_when": cfg.sensor.engaged_when,
        "sensor.i2c_address": f"0x{address:02x}" if address else "",
        "sensor.touch_channel": str(cfg.sensor.touch_channel),
    }


def _driver_ready() -> bool:
    """Whether the driver imports would resolve, without paying for them."""
    try:
        return all(importlib.util.find_spec(module) is not None for module in _DRIVER_MODULES)
    except (ImportError, ValueError):
        return False


def _sudo(cmd: list[str]) -> list[str]:
    return cmd if os.geteuid() == 0 else ["sudo", *cmd]


def _run(cmd: list[str]) -> bool:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode == 0


def _fit_i2c() -> int:
    """Turn the bus on. Returns 2 when the machine has to reboot first."""
    if not shutil.which("raspi-config"):
        print(f"  no {_I2C_DEVICE} and no raspi-config to enable it — turn I2C on by hand")
        return 1
    if not _run(_sudo(["raspi-config", "nonint", "do_i2c", "0"])):
        print("  could not enable I2C")
        return 1
    print("  I2C enabled. Reboot, then run motion-player-sensor --fit again.")
    return _REBOOT_FIRST


def _fit_tools() -> int:
    return 0 if _run(_sudo(["apt-get", "install", "-y", "i2c-tools"])) else 1


def _fit_driver() -> int:
    """Install Blinka and the MPR121 driver into the system python.

    The engine runs under /usr/bin/python3, so the driver has to land there
    too; a venv the service never sources would leave the pad dead.
    """
    if _run(_sudo(["pip3", "install", "--break-system-packages", _DRIVER_PACKAGE])):
        return 0
    # A pip too old to know that flag rejects the whole command; the plain form
    # is what works there.
    if _run(_sudo(["pip3", "install", _DRIVER_PACKAGE])):
        return 0
    print(f"  could not install {_DRIVER_PACKAGE}")
    return 1


def _fit_config(missing: list[tuple[str, str]], sensor_type: str,
                target: str, target_word: str) -> int:
    """Hand the pad's settings to the wizard, which validates and restarts.

    A sensor_type that is neither the pad nor empty was somebody's decision, so
    it is asked about rather than overwritten — except with nobody at the
    keyboard, where replacing it is the whole point of the command.
    """
    if sensor_type not in {target, ""}:
        print(f"  the config says sensor_type = {sensor_type}, not the {target_word}")
        if sys.stdin.isatty():
            if input(f"  Change it to {target}? [y/N]: ").strip().lower() != "y":
                print("  left alone; nothing changed")
                return 1
        else:
            print("  changing it — that is what --fit is for")
    args = [arg for key, value in missing for arg in ("--set", f"{key}={value}")]
    return 0 if _run(["motion-player-setup", *args]) else 1


def _fit_touch(cfg: Any) -> int:
    """The touch pad: a bus to enable, a driver to install, a polarity to write."""
    current = _current_settings(cfg)
    missing = settings_missing(TOUCH_SETTINGS, current)
    steps = fit_plan(_I2C_DEVICE.exists(), _driver_ready(),
                     shutil.which("i2cdetect") is not None, not missing)

    print("Fitting the touch pad — MPR121 at 0x5a, electrode 0\n")
    if not steps:
        print("Nothing to do: the bus, the driver and the config are all in place.\n")

    for step in steps:
        if step == "i2c":
            print("Enabling the I2C bus")
            code = _fit_i2c()
        elif step == "tools":
            print("Installing i2c-tools")
            code = _fit_tools()
        elif step == "driver":
            print(f"Installing {_DRIVER_PACKAGE}")
            code = _fit_driver()
        else:
            print("Writing the touch pad's config")
            code = _fit_config(missing, current["sensor.sensor_type"],
                               "capacitive", "touch pad")
        if code == _REBOOT_FIRST:
            return 0
        if code:
            return code
        print()

    print("Hardware")
    hardware = describe_hardware({"sensor_type": "capacitive", "i2c_bus": 1,
                                  "i2c_address": 0x5A})
    print(f"  {hardware}")
    if _I2C_DEVICE.exists() and not os.access(_I2C_DEVICE, os.R_OK | os.W_OK):
        print(f"  {_I2C_DEVICE} is not readable by {os.environ.get('USER', 'this user')} — "
              f"sudo usermod -aG i2c $USER, then log out and back in")
    print("\nNext: motion-player-sensor --probe, then touch and hold the pad.")
    return 0


def _fit_gamepad(cfg: Any) -> int:
    """The gamepad: nothing to install, only a pad to find and a config to write.

    The kernel's joystick driver is already there, so fitting one is finding it,
    checking this user may read it, and pointing the config at it.
    """
    from sensors.gamepad import device_name, find_device

    current = _current_settings(cfg)
    missing = settings_missing(GAMEPAD_SETTINGS, current)

    print("Fitting the gamepad — a USB controller, held to rewind\n")
    path = find_device(cfg.sensor.gamepad_device)
    if path is None:
        print(f"No pad at {cfg.sensor.gamepad_device}. Plug one into a USB port and run")
        print("this again — the kernel needs no driver for it.")
        return 1
    print(f"Found {device_name(path)} at {path}")
    if not os.access(path, os.R_OK):
        print(f"  {path} is not readable by {os.environ.get('USER', 'this user')} — "
              f"sudo usermod -aG input $USER, then log out and back in")

    if missing:
        print("\nWriting the gamepad's config")
        code = _fit_config(missing, current["sensor.sensor_type"],
                           "gamepad", "gamepad")
        if code:
            return code
    else:
        print("The config already names the gamepad.")

    print("\nNext: motion-player-sensor --probe, then press and hold a button.")
    return 0


def fit() -> int:
    """Fit the sensor the config names, or the shipped gamepad if it names neither."""
    cfg = _load_config()
    if cfg.sensor.sensor_type == "capacitive":
        return _fit_touch(cfg)
    return _fit_gamepad(cfg)


USAGE = """motion-player-sensor — check the sensor the piece is configured to use.

  motion-player-sensor --report   what is configured, what is wired, what the log saw
  motion-player-sensor --probe    watch it live with the engine stopped, then restart it
  motion-player-sensor --fit      find the pad, check it, and point the config at it

--report changes nothing and is safe to run during the show. --probe stops the
engine for as long as it runs, so the piece is dark while you are watching.
--fit fits the sensor the config names: a gamepad is found and pointed at, a
touch pad also gets I2C enabled and its MPR121 driver installed. It skips
whatever is already done, so it is safe to run twice.
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--probe" in argv:
        return probe()
    if "--fit" in argv:
        return fit()
    if "--report" in argv or not argv:
        return report()
    print(USAGE)
    return 0 if "--help" in argv or "-h" in argv else 2


if __name__ == "__main__":
    sys.exit(main())
