"""motion-player-setup: a guided launch sequence for the installation.

Asks a handful of questions — screen shape, sensor, sleep hours, telemetry,
gallery or test mode — and writes /etc/motion-player/config.ini. The systemd
unit passes no arguments, so configuration is how a choice persists across
boots; this wizard is the friendly way to make those choices.

All the text manipulation lives in pure functions so it can be tested without
a terminal or root.
"""
from __future__ import annotations

import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path("/etc/motion-player/config.ini")
PACKAGED_DEFAULT = Path("/opt/motion-player/config.default.ini")

# Shape presets: scaling mode plus the prepare hint. fill suits shapes that
# want to own the whole panel; fit is the honest default that never crops.
PRESETS = {
    "square": {"scaling": "fit"},
    "portrait": {"scaling": "fit"},
    "landscape": {"scaling": "fit"},
    "strip": {"scaling": "fill"},
}


def set_ini_value(text: str, section: str, key: str, value: str) -> str:
    """Set one key in one section, editing in place and keeping comments.

    A key that exists is rewritten on its own line; a missing key is appended
    at the end of its section; a missing section (an old config predating it)
    is appended at the end of the file.
    """
    lines = text.splitlines()
    header = f"[{section}]"
    key_re = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*).*$")

    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break

    if start is None:
        tail = [""] if lines and lines[-1].strip() else []
        return "\n".join(lines + tail + [header, f"{key} = {value}"]) + "\n"

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("["):
            end = index
            break

    for index in range(start + 1, end):
        match = key_re.match(lines[index])
        if match:
            lines[index] = f"{match.group(1)}{value}"
            return "\n".join(lines) + "\n"

    # Append inside the section, before any blank lines that pad its end.
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def render_prepare_hint(source: str, width: int, height: int, scaling: str) -> str:
    """The prepare command to print for a chosen screen — never run for them."""
    mode = "fill" if scaling == "fill" else "fit"
    return f"motion-player-prepare {source} --size {width}x{height} --mode {mode}"


def audio_device_names() -> list[str]:
    """Playback sinks as pygame sees them; empty when it cannot say."""
    try:
        import pygame  # type: ignore[import-untyped]

        pygame.mixer.init()
        from pygame._sdl2.audio import get_audio_device_names  # type: ignore[import-untyped]

        return list(get_audio_device_names(False))
    except Exception:  # noqa: BLE001
        return []


def detected_screens() -> list[tuple[str, str]]:
    """(connector, preferred mode) for every connected output."""
    import display

    screens = []
    for connector in display.connected_outputs():
        mode = display.preferred_mode(connector)
        screens.append((connector, f"{mode[0]}x{mode[1]}" if mode else "unknown"))
    return screens


def _ask(prompt: str, choices: list[str], current: str | None = None) -> str | None:
    """Numbered picklist; Enter keeps the current value. Returns None for keep."""
    print(f"\n{prompt}")
    for index, choice in enumerate(choices, start=1):
        print(f"  {index}. {choice}")
    suffix = f" [Enter keeps: {current}]" if current else " [Enter skips]"
    while True:
        raw = input(f"Choose 1-{len(choices)}{suffix}: ").strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print("Sorry, that isn't one of the numbers above.")


def _ask_time(prompt: str, current: str) -> str:
    import schedule

    while True:
        raw = input(f"{prompt} [Enter keeps {current}]: ").strip()
        if not raw:
            return current
        if schedule.parse_hhmm(raw) is not None:
            return raw
        print("Times look like 23:30 — hours 00-23, minutes 00-59.")


def _restart_service() -> None:
    """Restart the operator's user service, not root's.

    The wizard runs under sudo, where a bare `systemctl --user` would talk to
    root's (nonexistent) session manager instead of the operator's.
    """
    operator = os.environ.get("SUDO_USER") or os.environ.get("USER") or "pi"
    try:
        uid = pwd.getpwnam(operator).pw_uid
    except KeyError:
        print(f"Could not find user {operator}; restart by hand with motion-player-toggle.")
        return
    env = {"XDG_RUNTIME_DIR": f"/run/user/{uid}"}
    for step in ("daemon-reload", "restart motion-player.service"):
        result = subprocess.run(
            ["sudo", "-u", operator, "env", f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
             "systemctl", "--user", *step.split()],
            check=False,
        )
        if result.returncode != 0:
            print("Restart failed; do it from the desktop icon or motion-player-toggle.")
            return
    print("Restarted.")


def main() -> int:
    if os.geteuid() != 0:
        print("The config file is root-owned; re-running under sudo.")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    source = CONFIG_PATH if CONFIG_PATH.exists() else PACKAGED_DEFAULT
    if not source.exists():
        print(f"No config found at {CONFIG_PATH} or {PACKAGED_DEFAULT}.")
        return 1
    text = source.read_text(encoding="utf-8")

    print("memory-machine setup")
    print("====================")

    # 1. What is attached.
    screens = detected_screens()
    if screens:
        for connector, mode in screens:
            print(f"Detected screen: {connector} at {mode}")
    else:
        print("No display detected — is the screen connected and powered?")

    # 2. Shape preset.
    shape = _ask(
        "What shape is the screen this Pi drives?",
        ["square", "portrait", "landscape", "strip (very wide, like 1920x480)"],
    )
    if shape:
        preset = shape.split(" ")[0]
        text = set_ini_value(text, "playback", "scaling", PRESETS[preset]["scaling"])
        if screens and screens[0][1] != "unknown":
            width, height = (int(v) for v in screens[0][1].split("x"))
            hint = render_prepare_hint("~/memory-machine-media/piece.mp4", width, height,
                                       PRESETS[preset]["scaling"])
            print(f"\nTo render the media for this screen, run:\n  {hint}")

    # 3. Sensor.
    sensor = _ask(
        "What starts the piece?",
        ["switch (headphone sensor on GPIO 4)", "keyboard (spacebar, for testing)",
         "none (loop forever, no rewind)"],
    )
    if sensor:
        sensor_type = sensor.split(" ")[0]
        text = set_ini_value(text, "sensor", "sensor_type", sensor_type)
        if sensor_type == "switch":
            text = set_ini_value(text, "sensor", "gpio_pin", "4")

    # 3b. Audio sink: pin it, so audio can never wander to a screen's speakers.
    devices = audio_device_names()
    if devices:
        sink = _ask("Where does the audio come out?", devices + ["auto (first non-HDMI output)"])
        if sink:
            text = set_ini_value(text, "audio", "audio_sink",
                                 "auto" if sink.startswith("auto") else sink)
    else:
        print("\n(Could not list audio devices here; audio_sink stays as configured.)")

    # 3c. The forward reward.
    reward = _ask(
        "When a visitor stays through the whole rewind, the piece should:",
        ["turn and play forward - the reward for staying present",
         "fade to black and hold",
         "start the rewind over"],
    )
    if reward:
        value = {"t": "resume_forward", "f": "hold", "s": "loop_reverse"}[reward[0]]
        text = set_ini_value(text, "playback", "on_rewind_end", value)

    # 3d. The heartbeat panel.
    lcd = _ask("Is the little LCD heartbeat panel connected?", ["yes", "no"])
    if lcd:
        text = set_ini_value(text, "lcd", "enabled", "true" if lcd == "yes" else "false")
        if lcd == "yes":
            address = input("Its I2C address [Enter keeps 0x27]: ").strip()
            if re.fullmatch(r"0x[0-9a-fA-F]{2}", address or "0x27"):
                text = set_ini_value(text, "lcd", "i2c_address", address or "0x27")
            else:
                print("That doesn't look like an address; keeping 0x27.")
                text = set_ini_value(text, "lcd", "i2c_address", "0x27")

    # 4. Sleep hours.
    wants_sleep = _ask("Sleep the piece overnight?", ["yes", "no"])
    if wants_sleep == "yes":
        start = _ask_time("Sleep from", "00:00")
        end = _ask_time("Wake at", "08:00")
        text = set_ini_value(text, "schedule", "enabled", "true")
        text = set_ini_value(text, "schedule", "sleep_start", start)
        text = set_ini_value(text, "schedule", "sleep_end", end)
    elif wants_sleep == "no":
        text = set_ini_value(text, "schedule", "enabled", "false")

    # 5. Telemetry.
    wants_telemetry = _ask("Send health reports to the remote endpoint?", ["yes", "no"])
    if wants_telemetry:
        text = set_ini_value(text, "telemetry", "enabled",
                             "true" if wants_telemetry == "yes" else "false")

    # 6. Gallery or test mode.
    mode = _ask(
        "Run mode?",
        ["gallery (fullscreen, ready for the show)",
         "test (windowed, spacebar triggers, loops)"],
    )
    if mode:
        if mode.startswith("gallery"):
            text = set_ini_value(text, "system", "mode", "production")
            text = set_ini_value(text, "playback", "fullscreen", "true")
            # Always reset: a forgotten soak value must never stop the show.
            text = set_ini_value(text, "system", "exit_after_s", "0")
        else:
            text = set_ini_value(text, "system", "mode", "test")
            text = set_ini_value(text, "playback", "fullscreen", "false")
            text = set_ini_value(text, "sensor", "sensor_type", "keyboard")
            text = set_ini_value(text, "playback", "idle_mode", "loop_forward")
            soak = input("\nStop automatically after N seconds? [Enter = run until quit]: ").strip()
            if soak.isdigit() and int(soak) > 0:
                text = set_ini_value(text, "system", "exit_after_s", soak)

    # 7. Write, validate, offer a restart.
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.with_name(
            f"config.ini.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\nBacked up the old config to {backup}")

    tmp = CONFIG_PATH.with_suffix(".ini.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, CONFIG_PATH)
    print(f"Wrote {CONFIG_PATH}")

    import config as config_module

    cfg = config_module.load(str(CONFIG_PATH))
    problems = config_module.validate(cfg)
    if problems:
        print("\nThe config has problems — the piece will report them at start:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("Config OK")

    if input("\nRestart the piece now? [y/N]: ").strip().lower() == "y":
        _restart_service()
    else:
        print("Apply later with: motion-player-toggle --stop && motion-player-toggle --start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
