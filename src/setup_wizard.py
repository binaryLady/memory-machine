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


def parse_set_args(args: list[str]) -> list[tuple[str, str, str]]:
    """--set arguments as (section, key, value) triples.

    Each looks like media.video_file=piece.800x1280.mp4 — section.key, then
    the value after the first equals sign.
    """
    pairs = []
    for arg in args:
        target, sep, value = arg.partition("=")
        section, dot, key = target.partition(".")
        if not sep or not dot or not section or not key:
            raise ValueError(f"--set takes section.key=value; got {arg!r}")
        pairs.append((section, key, value))
    return pairs


def apply_run_mode(text: str, gallery: bool) -> str:
    """Gallery vs test, as config edits.

    Both modes render identically — test mode changes observability, never the
    picture: the piece must look exactly as it will in the show, or the test
    tests nothing. Asserting fullscreen here also repairs configs written back
    when test mode forced a window.
    """
    text = set_ini_value(text, "playback", "fullscreen", "true")
    if gallery:
        text = set_ini_value(text, "system", "mode", "production")
        # Always reset: a forgotten soak value must never stop the show.
        text = set_ini_value(text, "system", "exit_after_s", "0")
    else:
        text = set_ini_value(text, "system", "mode", "test")
        text = set_ini_value(text, "sensor", "sensor_type", "keyboard")
        text = set_ini_value(text, "playback", "idle_mode", "loop_forward")
    return text


def discover_renders(media_dir: Path) -> list[str]:
    """Playable renders in the media folder: clips whose reverse exists.

    Reverse copies themselves are not offered — they are halves of a render,
    not renders.
    """
    import playback_math

    names = []
    for clip in sorted(media_dir.glob("*.mp4")):
        if clip.name.endswith(".reverse.mp4"):
            continue
        if (media_dir / playback_math.reverse_name(clip.name)).exists():
            names.append(clip.name)
    return names


def parse_picks(raw: str, count: int) -> list[int]:
    """"2" or "1,3" as unique 1-based indexes; raises ValueError otherwise."""
    picks: list[int] = []
    for part in raw.replace(",", " ").split():
        if not part.isdigit() or not 1 <= int(part) <= count:
            raise ValueError(part)
        if int(part) not in picks:
            picks.append(int(part))
    if not picks:
        raise ValueError(raw)
    return picks


def apply_render_choice(text: str, renders: list[str], picks: list[int]) -> str:
    """One pick plays outright; several become a shape-matched cut set."""
    import playback_math

    if len(picks) == 1:
        chosen = renders[picks[0] - 1]
        text = set_ini_value(text, "media", "video_file", chosen)
        text = set_ini_value(text, "media", "reverse_file", playback_math.reverse_name(chosen))
        # A single choice is a curator's choice; nothing may second-guess it.
        text = set_ini_value(text, "media", "cuts", "")
    else:
        text = set_ini_value(text, "media", "cuts",
                             ", ".join(renders[p - 1] for p in picks))
    return text


# The sensor choices the wizard offers. Each label must lead with the config
# value — the caller takes the first token. engaged_when is per-backend and is
# the subtle one: a touch pad is engaged when its contact CLOSES, but a cradle
# switch is lifted when its contact OPENS, so one shared default silently
# inverts whichever it was not written for.
SENSOR_CHOICES: list[tuple[str, str | None, bool, str | None, str]] = [
    # (value, engaged_when, sets_pin, i2c_address, label)
    ("gamepad", "closed", False, None, "gamepad (USB controller, hold a button) - what the show uses"),
    ("capacitive", "closed", False, "0x5a", "capacitive (touch pad, MPR121 over I2C)"),
    ("gpio_raw", "closed", True, None, "gpio_raw (touch pad or any digital module on GPIO 4)"),
    ("switch", "open", True, None, "switch (headphone cradle on GPIO 4)"),
    ("mmwave", "open", True, None, "mmwave (24GHz radar presence pin)"),
    ("keyboard", None, False, None, "keyboard (spacebar, for testing)"),
    ("none", None, False, None, "none (loop forever, no rewind)"),
]


def sensor_labels() -> list[str]:
    return [label for *_rest, label in SENSOR_CHOICES]


def apply_sensor_choice(text: str, sensor_type: str) -> str:
    """Write one sensor choice, with the polarity and address that go with it.

    sensor.i2c_address is one key read by whichever backend sensor_type names —
    the MPR121 at 0x5a, the VL53L0X at 0x29 — so it has to move with the sensor
    or the pad is looked for at the range-finder's address.
    """
    for value, polarity, sets_pin, address, _label in SENSOR_CHOICES:
        if value != sensor_type:
            continue
        text = set_ini_value(text, "sensor", "sensor_type", value)
        if polarity is not None:
            text = set_ini_value(text, "sensor", "engaged_when", polarity)
        if sets_pin:
            text = set_ini_value(text, "sensor", "gpio_pin", "4")
        if address is not None:
            text = set_ini_value(text, "sensor", "i2c_address", address)
        return text
    return text


def sanitize_setup_name(raw: str) -> str | None:
    """A setup name as a safe filename stem, or None if nothing usable remains.

    Lowercased, spaces become dashes, and only [a-z0-9-] survives — a name is
    a label, never a path.
    """
    name = re.sub(r"[^a-z0-9-]", "", raw.strip().lower().replace(" ", "-"))
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or None


def setups_dir() -> Path:
    import config as config_module

    return config_module.MEDIA_DIR / "setups"


def list_setups(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.ini"))


def _chown_to_operator(*paths: Path) -> None:
    """Setups belong to the operator, not root — the wizard runs under sudo,
    but the media folder (and everything that travels with it) is hers."""
    operator = os.environ.get("SUDO_USER")
    if not operator:
        return
    try:
        record = pwd.getpwnam(operator)
    except KeyError:
        return
    for path in paths:
        try:
            os.chown(path, record.pw_uid, record.pw_gid)
        except OSError:
            pass


def save_setup(text: str, name: str) -> Path:
    """Store a config snapshot as a named setup in the media folder."""
    directory = setups_dir()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{name}.ini"
    destination.write_text(text, encoding="utf-8")
    _chown_to_operator(directory, destination)
    return destination


def load_setup(name: str) -> int:
    """Apply a saved setup as the live config, through the usual safe write."""
    source = setups_dir() / f"{name}.ini"
    if not source.exists():
        known = ", ".join(list_setups(setups_dir())) or "none saved yet"
        print(f"No setup named {name!r} (have: {known})")
        return 1
    print(f"Loading setup {name}:")
    return _finish(source.read_text(encoding="utf-8"))


def duplicate_setup(name: str, new_name: str) -> int:
    source = setups_dir() / f"{name}.ini"
    if not source.exists():
        print(f"No setup named {name!r}")
        return 1
    destination = save_setup(source.read_text(encoding="utf-8"), new_name)
    print(f"Duplicated {name} -> {destination.stem}")
    return 0


def parse_alsa_cards(text: str) -> list[str]:
    """Card names from /proc/asound/cards content.

    A line reads ` 2 [Device ]: USB-Audio - USB Audio Device`; the part after
    the last ` - ` is the human name, and the engine's substring matching
    means it works as an audio_sink value directly.
    """
    names = []
    for line in text.splitlines():
        match = re.match(r"\s*\d+\s+\[.+?\]:\s*(.+)", line)
        if match:
            names.append(match.group(1).split(" - ")[-1].strip())
    return names


def alsa_cards() -> list[str]:
    """Sound cards the kernel sees, even when SDL's enumeration misses one."""
    try:
        return parse_alsa_cards(Path("/proc/asound/cards").read_text(encoding="utf-8"))
    except OSError:
        return []


_SETUP_SUFFIX = " (saved setup)"


def setup_menu(saved: list[str]) -> list[str]:
    """The wizard's opening menu: every saved run pickable by its own number.

    The run choice is the first thing setup asks, with each option in view —
    picking a name loads it outright, no submenu.
    """
    choices = ["walk through the questions (current config)"]
    choices += [f"{name}{_SETUP_SUFFIX}" for name in saved]
    choices.append("save the current config as a setup")
    if saved:
        choices.append("duplicate a saved setup")
    return choices


def menu_choice_setup_name(choice: str | None) -> str | None:
    """The saved-setup name a menu choice refers to, or None for other actions."""
    if choice and choice.endswith(_SETUP_SUFFIX):
        return choice.removesuffix(_SETUP_SUFFIX)
    return None


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


def run_questions(text: str) -> str:
    """Ask every configuration question and return the edited config text.

    Pure with respect to the filesystem: it reads no file and writes none, so
    the wizard's smoke test — Enter through everything and the config must come
    back byte-identical — is a test rather than an instruction.
    """
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

    # 2b. Which render plays. Prepare leaves finished variants side by side in
    # the media folder; this is where one of them is chosen for the screen.
    import config as config_module

    renders = discover_renders(config_module.MEDIA_DIR)
    if renders:
        print("\nRenders in the media folder (each with its reverse):")
        for index, name in enumerate(renders, start=1):
            print(f"  {index}. {name}")
        raw = input("Which plays? One number, or several separated by commas "
                    "for a shape-matched set [Enter keeps current]: ").strip()
        while raw:
            try:
                picks = parse_picks(raw, len(renders))
            except ValueError:
                raw = input(f"Numbers 1-{len(renders)}, comma-separated: ").strip()
                continue
            text = apply_render_choice(text, renders, picks)
            break

    # 3. Sensor.
    sensor = _ask("What starts the piece?", sensor_labels())
    if sensor:
        text = apply_sensor_choice(text, sensor.split(" ")[0])

    # 3a. Whether the sound is tied to that sensor at all.
    sound = _ask(
        "When does the sound play?",
        ["always (it loops from boot; the sensor drives only the picture)",
         "on_lift (it starts when someone engages the sensor, and fades when they let go)"],
    )
    if sound:
        text = set_ini_value(text, "audio", "audio_mode", sound.split(" ")[0])

    # 3b. Audio sink: pin it, so audio can never wander to a screen's speakers.
    # SDL's enumeration can miss a card the kernel sees (the USB adapter, on
    # the first hardware night), so the kernel's own list is merged in and a
    # by-hand entry is always offered. Matching is substring-based in the
    # engine, so "USB Audio Device" — or just "USB" — finds the adapter.
    devices = audio_device_names()
    cards = [
        card for card in alsa_cards()
        if not any(card.lower() in dev.lower() or dev.lower() in card.lower()
                   for dev in devices)
    ]
    options = (
        devices
        + [f"{card} (sound card)" for card in cards]
        + ["auto (first non-HDMI output)", "type a device name by hand"]
    )
    sink = _ask("Where does the audio come out?", options)
    if sink:
        if sink.startswith("type"):
            raw = input("Device name (matched as a substring, e.g. USB): ").strip()
            if raw:
                text = set_ini_value(text, "audio", "audio_sink", raw)
        else:
            value = "auto" if sink.startswith("auto") else sink.removesuffix(" (sound card)")
            text = set_ini_value(text, "audio", "audio_sink", value)

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

            # The panel's voice — layout, title, state words, and the icon.
            if input("Customise the panel's text and icon? [y/N]: ").strip().lower() == "y":
                style = _ask(
                    "Panel style?",
                    ["status (icon, words, health figures)",
                     "art (icon centered, stars twinkling, no text)",
                     "show (title always up, icon + stars, state personalities)"],
                )
                if style:
                    text = set_ini_value(text, "lcd", "layout", style.split(" ")[0])
                for key, prompt in (
                    ("title", "Title line (up to 18 characters)"),
                    ("label_idle", "Word for at rest"),
                    ("label_engaged", "Word for listening"),
                    ("label_reward", "Word for the turn (the reward)"),
                    ("label_hello", "Word on waking"),
                    ("label_sleep", "Word overnight"),
                    ("label_goodbye", "Word at shutdown"),
                ):
                    answer = input(f"{prompt} [Enter keeps, - for blank]: ").strip()
                    if answer == "-":
                        text = set_ini_value(text, "lcd", key, "")
                    elif answer:
                        text = set_ini_value(text, "lcd", key, answer)
                import lcd as lcd_module

                art_dir = config_module.MEDIA_DIR / "icons"
                art = sorted(p.stem for p in art_dir.glob("*.txt")) if art_dir.is_dir() else []
                icons = (
                    sorted(lcd_module.GLYPHS)
                    + [f"{name} (your pixel art)" for name in art]
                    + ["none (bare column)",
                       "custom (draw your own, up to 10x16 pixels)"]
                )
                icon = _ask("Which icon beats beside the title?", icons)
                if icon and icon.startswith("custom"):
                    print(
                        "\nDraw it as pixel art in "
                        f"{art_dir}/<name>.txt:"
                        "\n# for lit, . for dark; 5 or 10 pixels wide, 8 or 16 tall;"
                        "\nthe full shape, a line of ---, then the relaxed shape it"
                        "\nbeats against. Rerun setup and it appears in this menu."
                    )
                elif icon:
                    text = set_ini_value(text, "lcd", "icon", icon.split(" ")[0])

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
        ["gallery (ready for the show)",
         "test (verbose logs, spacebar triggers, loops)"],
    )
    if mode:
        text = apply_run_mode(text, gallery=mode.startswith("gallery"))
        if not mode.startswith("gallery"):
            soak = input("\nStop automatically after N seconds? [Enter = run until quit]: ").strip()
            if soak.isdigit() and int(soak) > 0:
                text = set_ini_value(text, "system", "exit_after_s", soak)

    return text


def main() -> int:
    # Listing and saving read the world-readable config and write to the
    # operator's own media folder — neither needs root, so they run before
    # the sudo re-exec.
    if "--list-setups" in sys.argv:
        for name in list_setups(setups_dir()):
            print(name)
        return 0

    if "--save-setup" in sys.argv:
        args = sys.argv[1:]
        if len(args) != 2 or args[0] != "--save-setup":
            print("Usage: motion-player-setup --save-setup NAME")
            return 2
        name = sanitize_setup_name(args[1])
        if not name:
            print(f"Unusable setup name: {args[1]!r}")
            return 2
        if not CONFIG_PATH.exists():
            print(f"No config at {CONFIG_PATH} to save.")
            return 1
        print(f"Saved setup: {save_setup(CONFIG_PATH.read_text(encoding='utf-8'), name)}")
        return 0

    if os.geteuid() != 0:
        print("The config file is root-owned; re-running under sudo.")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    if "--load-setup" in sys.argv:
        args = sys.argv[1:]
        if len(args) != 2 or args[0] != "--load-setup":
            print("Usage: motion-player-setup --load-setup NAME")
            return 2
        name = sanitize_setup_name(args[1])
        if not name:
            print(f"Unusable setup name: {args[1]!r}")
            return 2
        return load_setup(name)

    if "--set" in sys.argv:
        args = sys.argv[1:]
        values = [args[i + 1] for i, arg in enumerate(args)
                  if arg == "--set" and i + 1 < len(args)]
        leftovers = [arg for i, arg in enumerate(args)
                     if arg != "--set" and (i == 0 or args[i - 1] != "--set")]
        if leftovers or len(values) != args.count("--set"):
            print("Usage: motion-player-setup [--set section.key=value ...]")
            return 2
        try:
            pairs = parse_set_args(values)
        except ValueError as exc:
            print(exc)
            return 2
        return apply_settings(pairs)

    source = CONFIG_PATH if CONFIG_PATH.exists() else PACKAGED_DEFAULT
    if not source.exists():
        print(f"No config found at {CONFIG_PATH} or {PACKAGED_DEFAULT}.")
        return 1
    text = source.read_text(encoding="utf-8")

    print("memory-machine setup")
    print("====================")

    # 0. Which run? Every saved setup is its own numbered option, so the
    # first question setup asks is the one that matters. Duplication is a
    # workflow, not a button: load, walk the questions to tweak, save under
    # the new name at the end.
    saved = list_setups(setups_dir())
    action = _ask("Which run does this Pi play?", setup_menu(saved))
    picked = menu_choice_setup_name(action)
    if picked:
        code = load_setup(picked)
        if code != 0:
            return code
        if input("\nWalk through the questions to tweak it? [y/N]: ").strip().lower() != "y":
            return 0
        text = CONFIG_PATH.read_text(encoding="utf-8")
    elif action and action.startswith("save"):
        name = sanitize_setup_name(input("Name for this setup: ").strip())
        if not name:
            print("That name had nothing usable in it; nothing saved.")
            return 2
        print(f"Saved setup: {save_setup(text, name)}")
        return 0
    elif action and action.startswith("duplicate"):
        pick = _ask("Duplicate which setup?", saved)
        if not pick:
            return 0
        name = sanitize_setup_name(input("New name: ").strip())
        if not name:
            print("That name had nothing usable in it; nothing duplicated.")
            return 2
        return duplicate_setup(pick, name)

    text = run_questions(text)

    code = _finish(text)
    if sys.stdin.isatty():
        raw = input("\nSave this setup for re-use? name [Enter skips]: ").strip()
        if raw:
            name = sanitize_setup_name(raw)
            if name:
                print(f"Saved setup: {save_setup(text, name)}")
            else:
                print("That name had nothing usable in it; not saved.")
    return code


def _finish(text: str) -> int:
    """Write, validate, offer a restart. The ending both entry points share."""
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

    if not sys.stdin.isatty():
        print("Apply with: motion-player-toggle --stop && motion-player-toggle --start")
        return 0
    if input("\nRestart the piece now? [y/N]: ").strip().lower() == "y":
        _restart_service()
    else:
        print("Apply later with: motion-player-toggle --stop && motion-player-toggle --start")
    return 0


def apply_settings(pairs: list[tuple[str, str, str]]) -> int:
    """Write the given values without asking anything — the tools' entry point.

    motion-player-prepare knows the exact media names it just rendered; this
    lets it hand them straight to the config instead of asking the operator to
    retype them.
    """
    source = CONFIG_PATH if CONFIG_PATH.exists() else PACKAGED_DEFAULT
    if not source.exists():
        print(f"No config found at {CONFIG_PATH} or {PACKAGED_DEFAULT}.")
        return 1
    text = source.read_text(encoding="utf-8")
    for section, key, value in pairs:
        text = set_ini_value(text, section, key, value)
        print(f"  {section}.{key} = {value}")
    return _finish(text)


if __name__ == "__main__":
    sys.exit(main())
