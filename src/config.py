"""Configuration loader and validator for motion-player."""
from __future__ import annotations

import configparser
import dataclasses
import logging
import os
import re
import urllib.parse

import display
import playback_math
import schedule
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger("motion-player.config")


def _operator_home() -> Path:
    """The operator's home, even under sudo.

    The setup wizard re-execs itself as root to write /etc, then validates the
    config it wrote. Path.home() there is /root, so every relative media path
    "fails" validation against a folder nobody uses. The media lives with the
    user who runs the piece.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd

        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


MEDIA_DIR = _operator_home() / "memory-machine-media"


@dataclass(frozen=True)
class MediaConfig:
    video_file: Path
    audio_file: Path
    reverse_file: Path
    cuts: tuple[Path, ...]
    kaleidoscope_file: Path | None
    kaleidoscope_cuts: tuple[Path, ...]


@dataclass(frozen=True)
class PlaybackConfig:
    idle_mode: str
    reverse_rate: str
    on_rewind_end: str
    scaling: str
    fullscreen: bool
    display: str
    display_mode: str


@dataclass(frozen=True)
class LcdConfig:
    enabled: bool
    i2c_bus: int
    i2c_address: int
    idle_bpm: float
    engaged_bpm: float
    sleep_bpm: float
    title: str
    label_idle: str
    label_engaged: str
    label_reward: str
    label_hello: str
    label_sleep: str
    label_goodbye: str
    icon: str
    icon_full: tuple[int, ...] | None
    icon_small: tuple[int, ...] | None
    layout: str
    page_seconds: float
    pages: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class AudioConfig:
    audio_sink: str
    volume: float
    fade_out_ms: int
    on_audio_end: str
    audio_mode: str


@dataclass(frozen=True)
class GamepadConfig:
    """What each control on the pad is called, and what it does.

    numbers maps a control name to the number this pad reports for it; the four
    arrows are axes on most pads and stay None unless a number is given. jobs
    maps a job — "hold", "kaleidoscope", "audio_next", "audio_prev" — to the
    control names that drive it.
    """

    numbers: dict[str, int | None]
    jobs: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class SensorConfig:
    sensor_type: str
    sensor_combine: str
    engaged_when: str
    gpio_pin: int
    pull_up: bool
    trigger_pin: int
    echo_pin: int
    threshold_cm: float
    i2c_address: int | None
    touch_channel: int
    gamepad_device: str
    bounce_time_ms: int
    min_lift_ms: int
    min_replace_ms: int
    max_engaged_minutes: int


@dataclass(frozen=True)
class ScheduleConfig:
    enabled: bool
    sleep_start: str
    sleep_end: str


@dataclass(frozen=True)
class SystemConfig:
    mode: str
    log_level: str
    log_max_mb: int
    restart_on_crash: bool
    exit_after_s: int


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool
    endpoint_url: str
    interval_s: int
    batch_size: int
    timeout_s: int
    log_tail_lines: int


@dataclass(frozen=True)
class Config:
    media: MediaConfig
    playback: PlaybackConfig
    audio: AudioConfig
    lcd: LcdConfig
    lcd2: LcdConfig
    sensor: SensorConfig
    gamepad: GamepadConfig
    system: SystemConfig
    schedule: ScheduleConfig
    telemetry: TelemetryConfig
    source_path: Path

    def dump(self) -> str:
        lines = [f"# live config loaded from {self.source_path}", ""]
        for section_name, section in (
            ("media", self.media),
            ("playback", self.playback),
            ("audio", self.audio),
            ("lcd", self.lcd),
            ("lcd2", self.lcd2),
            ("sensor", self.sensor),
            ("schedule", self.schedule),
            ("system", self.system),
            ("telemetry", self.telemetry),
        ):
            lines.append(f"[{section_name}]")
            for field in dataclasses.fields(section):
                value = getattr(section, field.name)
                lines.append(f"{field.name} = {value}")
            lines.append("")
        return "\n".join(lines)


DEFAULTS: dict[str, dict[str, Any]] = {
    "media": {
        "video_file": "piece.mp4",
        "audio_file": "piece.wav",
        "reverse_file": "piece.reverse.mp4",
        "cuts": "",
        "kaleidoscope_file": "",
        "kaleidoscope_cuts": "",
    },
    "playback": {
        "idle_mode": "hold_first_frame",
        "reverse_rate": "native",
        "on_rewind_end": "resume_forward",
        "scaling": "fit",
        "fullscreen": True,
        "display": "auto",
        "display_mode": "auto",
    },
    "audio": {
        "audio_sink": "USB",
        "volume": 0.8,
        "fade_out_ms": 400,
        "on_audio_end": "silence",
        "audio_mode": "always",
    },
    "lcd": {
        "enabled": False,
        "i2c_bus": 1,
        "i2c_address": "0x27",
        "idle_bpm": 60.0,
        "engaged_bpm": 100.0,
        "sleep_bpm": 0.0,
        "title": "Memory<>Machine",
        "label_idle": "at rest",
        "label_engaged": "holding on",
        "label_reward": "I see you",
        "label_hello": "hello",
        "label_sleep": "goodnight",
        "label_goodbye": "goodbye",
        "icon": "heart",
        "icon_full": "",
        "icon_small": "",
        "layout": "status",
        "page_seconds": 6.0,
        "page_1": "",
        "page_2": "",
        "page_3": "",
        "page_4": "",
        "page_5": "",
        "page_6": "",
    },
    "sensor": {
        "sensor_type": "gamepad",
        "sensor_combine": "any",
        "engaged_when": "closed",
        "gpio_pin": 4,
        "pull_up": True,
        "trigger_pin": 23,
        "echo_pin": 24,
        "threshold_cm": 15.0,
        "i2c_address": None,
        "touch_channel": 0,
        "gamepad_device": "auto",
        "bounce_time_ms": 50,
        "min_lift_ms": 250,
        "min_replace_ms": 250,
        "max_engaged_minutes": 30,
    },
    "gamepad": {
        "a": 1,
        "b": 0,
        "select": 2,
        "start": 3,
        "up": "",
        "down": "",
        "left": "",
        "right": "",
        "hold": "start+select",
        "kaleidoscope": "a+b",
        "audio_next": "right+down",
        "audio_prev": "left+up",
    },
    "schedule": {
        "enabled": False,
        "sleep_start": "00:00",
        "sleep_end": "08:00",
    },
    "system": {
        "mode": "production",
        "log_level": "info",
        "log_max_mb": 20,
        "restart_on_crash": True,
        "exit_after_s": 0,
    },
    "telemetry": {
        "enabled": False,
        "endpoint_url": "https://lab.thetechmargin.com/memorymachine/api/telemetry",
        "interval_s": 60,
        "batch_size": 10,
        "timeout_s": 5,
        "log_tail_lines": 20,
    },
}

# The second panel — the visitor's instruction card — shares the heartbeat
# panel's whole vocabulary; only its bus and its job differ. It lives on the
# Pi 5's second hardware bus (dtoverlay=i2c3-pi5,pins_22_23 -> /dev/i2c-3)
# so both backpacks keep their factory 0x27 address, no solder bridge.
DEFAULTS["lcd2"] = dict(DEFAULTS["lcd"], i2c_bus=3, layout="instructions")

_VALID_IDLE_MODES = {"hold_first_frame", "loop_forward", "black"}
_VALID_REVERSE_RATE = {"native", "fit_to_audio"}
_VALID_ON_REWIND_END = {"hold", "loop_reverse", "resume_forward"}
_VALID_MODES = {"production", "test"}
_VALID_SCALING = {"fit", "fill", "stretch"}
_VALID_LCD_ICONS = {"heart", "star", "ring", "note", "eye", "none"}
_VALID_LCD_LAYOUTS = {"status", "art", "show", "instructions"}
_VALID_ON_AUDIO_END = {"silence", "loop"}
_VALID_AUDIO_MODE = {"always", "on_lift"}
_VALID_SENSOR_TYPES = {
    "none",
    "switch",
    "reed",
    "beam",
    "reflective",
    "capacitive",
    "distance",
    "hall",
    "pir",
    "mmwave",
    "gpio_raw",
    "gamepad",
    "keyboard",
}
_VALID_ENGAGED_WHEN = {"open", "closed"}
_VALID_GAMEPAD_DIRECTIONS = {"left", "right", "up", "down"}
# The face buttons by name, plus "any" for a pad that only ever holds.
_GAMEPAD_BUTTONS = ("a", "b", "select", "start")
_GAMEPAD_CONTROLS = {*_GAMEPAD_BUTTONS, "any"}
_GAMEPAD_JOBS = ("hold", "kaleidoscope", "audio_next", "audio_prev")
_VALID_SENSOR_COMBINE = {"any", "all"}


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if value is None:
        return default
    try:
        v = int(value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid integer %r; using default %s", value, default)
        return default
    if min_val is not None and v < min_val:
        LOGGER.warning("Clamping %s to minimum %s", v, min_val)
        return min_val
    if max_val is not None and v > max_val:
        LOGGER.warning("Clamping %s to maximum %s", v, max_val)
        return max_val
    return v


def _parse_float(value: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if value is None:
        # Absent key: older configs predate newer keys, which is not an error.
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid float %r; using default %s", value, default)
        return default
    if min_val is not None and v < min_val:
        LOGGER.warning("Clamping %s to minimum %s", v, min_val)
        return min_val
    if max_val is not None and v > max_val:
        LOGGER.warning("Clamping %s to maximum %s", v, max_val)
        return max_val
    return v


def _resolve_path(value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return MEDIA_DIR / p


def _path_list(value: Any) -> tuple[Path, ...]:
    """Comma-separated media paths; blank means none were offered."""
    if value is None or not str(value).strip():
        return ()
    return tuple(_resolve_path(part.strip()) for part in str(value).split(",") if part.strip())


def _parse_panel_text(value: Any, default: str) -> str:
    """Panel strings must be printable ASCII — the HD44780's A00 charset
    renders anything else as noise on the glass.

    An absent key means the shipped default; a key deliberately left empty
    means blank — an icon-only panel (portrait-mounted, where ROM text would
    lie sideways) says nothing at all.
    """
    if value is None:
        return default
    if not str(value).strip():
        return ""
    text = "".join(ch for ch in str(value) if 32 <= ord(ch) < 127).strip()
    if not text:
        LOGGER.warning("Panel text %r has no ASCII characters; using %r", value, default)
        return default
    if len(text) > 18:
        LOGGER.warning("Panel text %r is longer than 18 columns and will be cut", text)
    return text


def _parse_pages(raw: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    """page_1..page_6 as an instruction deck: pipe-separated lines, up to
    four per page, each printable ASCII on the full 20 columns."""
    pages: list[tuple[str, ...]] = []
    for number in range(1, 7):
        value = raw.get(f"page_{number}")
        if value is None or not str(value).strip():
            continue
        lines = []
        for part in str(value).split("|")[:4]:
            text = "".join(ch for ch in part if 32 <= ord(ch) < 127).strip()
            if len(text) > 20:
                LOGGER.warning("Page line %r is longer than 20 columns and will be cut", text)
                text = text[:20]
            lines.append(text)
        if any(lines):
            pages.append(tuple(lines))
    return tuple(pages)


def _parse_lcd_section(raw: dict[str, Any], section: str) -> LcdConfig:
    defaults = DEFAULTS[section]
    return LcdConfig(
        enabled=_parse_bool(raw.get("enabled"), defaults["enabled"]),
        i2c_bus=_parse_int(raw.get("i2c_bus"), defaults["i2c_bus"], 0),
        i2c_address=_parse_i2c_address(raw.get("i2c_address"))
        or int(str(defaults["i2c_address"]), 0),
        idle_bpm=_parse_float(raw.get("idle_bpm"), defaults["idle_bpm"], 1.0, 300.0),
        engaged_bpm=_parse_float(raw.get("engaged_bpm"), defaults["engaged_bpm"], 1.0, 300.0),
        sleep_bpm=_parse_float(raw.get("sleep_bpm"), defaults["sleep_bpm"], 0.0, 300.0),
        title=_parse_panel_text(raw.get("title"), defaults["title"]),
        label_idle=_parse_panel_text(raw.get("label_idle"), defaults["label_idle"]),
        label_engaged=_parse_panel_text(raw.get("label_engaged"), defaults["label_engaged"]),
        label_reward=_parse_panel_text(raw.get("label_reward"), defaults["label_reward"]),
        label_hello=_parse_panel_text(raw.get("label_hello"), defaults["label_hello"]),
        label_sleep=_parse_panel_text(raw.get("label_sleep"), defaults["label_sleep"]),
        label_goodbye=_parse_panel_text(raw.get("label_goodbye"), defaults["label_goodbye"]),
        icon=str(raw.get("icon", defaults["icon"])).strip().lower(),
        icon_full=_parse_glyph(raw.get("icon_full")),
        icon_small=_parse_glyph(raw.get("icon_small")),
        layout=str(raw.get("layout", defaults["layout"])).strip().lower(),
        page_seconds=_parse_float(raw.get("page_seconds"), defaults["page_seconds"], 1.0, 600.0),
        pages=_parse_pages(raw),
    )


def _parse_glyph(value: Any) -> tuple[int, ...] | None:
    """A hand-drawn 5x8 glyph: 8 comma-separated row values, each 0-31."""
    if value is None or not str(value).strip():
        return None
    try:
        rows = tuple(int(part.strip(), 0) for part in str(value).split(","))
    except ValueError:
        LOGGER.warning("Invalid glyph %r; expected 8 comma-separated numbers", value)
        return None
    if len(rows) != 8 or not all(0 <= row <= 31 for row in rows):
        LOGGER.warning("Invalid glyph %r; needs exactly 8 rows, each 0-31", value)
        return None
    return rows


def _is_gamepad_control(control: str) -> bool:
    """Whether the string names a control the gamepad backend can watch."""
    if control in _GAMEPAD_CONTROLS or control in _VALID_GAMEPAD_DIRECTIONS:
        return True
    return control.startswith("b") and control[1:].isdigit()


def _control_list(value: Any) -> tuple[str, ...]:
    """"a+b" as ("a", "b"). Empty means the job is switched off."""
    text = str(value or "").strip().lower()
    if not text:
        return ()
    return tuple(part.strip() for part in text.split("+") if part.strip())


def _optional_int(value: Any) -> int | None:
    """A control number, or None when the pad reports that control as an axis."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        LOGGER.warning("Invalid gamepad control number %r; treating as unset", value)
        return None


def _parse_i2c_address(value: Any) -> int | None:
    if value is None or str(value).lower() in {"", "none", "false", "0x"}:
        return None
    try:
        return int(str(value), 0)
    except ValueError:
        LOGGER.warning("Invalid i2c_address %r; treating as unset", value)
        return None


def load(path: str = "/etc/motion-player/config.ini") -> Config:
    source = Path(path)
    parser = configparser.ConfigParser()
    # Preserve case of keys so unknown-key detection works.
    parser.optionxform = str  # type: ignore[assignment]

    if source.exists():
        try:
            parser.read(source)
        except configparser.Error as exc:
            LOGGER.warning("Could not read %s: %s. Using all defaults.", source, exc)
            parser = configparser.ConfigParser()
            parser.optionxform = str  # type: ignore[assignment]
    else:
        LOGGER.warning("Config file not found at %s. Using defaults.", source)

    unknown_keys: list[str] = []
    for section in parser.sections():
        if section not in DEFAULTS:
            LOGGER.warning("Unknown config section [%s] ignored", section)
            continue
        for key in parser[section]:
            if key not in DEFAULTS[section]:
                unknown_keys.append(f"{section}.{key}")
    if unknown_keys:
        LOGGER.warning("Unknown config keys ignored: %s", ", ".join(unknown_keys))

    def _section(name: str) -> dict[str, Any]:
        return dict(parser[name]) if parser.has_section(name) else {}

    media_raw = _section("media")
    playback_raw = _section("playback")
    audio_raw = _section("audio")
    lcd_raw = _section("lcd")
    lcd2_raw = _section("lcd2")
    sensor_raw = _section("sensor")
    gamepad_raw = _section("gamepad")
    schedule_raw = _section("schedule")
    system_raw = _section("system")
    telemetry_raw = _section("telemetry")

    config = Config(
        media=MediaConfig(
            video_file=_resolve_path(str(media_raw.get("video_file", DEFAULTS["media"]["video_file"]))),
            audio_file=_resolve_path(str(media_raw.get("audio_file", DEFAULTS["media"]["audio_file"]))),
            reverse_file=_resolve_path(str(media_raw.get("reverse_file", DEFAULTS["media"]["reverse_file"]))),
            cuts=_path_list(media_raw.get("cuts")),
            kaleidoscope_file=(
                _resolve_path(str(media_raw.get("kaleidoscope_file")).strip())
                if str(media_raw.get("kaleidoscope_file", "")).strip() else None
            ),
            kaleidoscope_cuts=_path_list(media_raw.get("kaleidoscope_cuts")),
        ),
        playback=PlaybackConfig(
            idle_mode=str(playback_raw.get("idle_mode", DEFAULTS["playback"]["idle_mode"])),
            reverse_rate=str(playback_raw.get("reverse_rate", DEFAULTS["playback"]["reverse_rate"])),
            on_rewind_end=str(playback_raw.get("on_rewind_end", DEFAULTS["playback"]["on_rewind_end"])),
            scaling=str(playback_raw.get("scaling", DEFAULTS["playback"]["scaling"])),
            fullscreen=_parse_bool(playback_raw.get("fullscreen"), DEFAULTS["playback"]["fullscreen"]),
            display=str(playback_raw.get("display", DEFAULTS["playback"]["display"])),
            display_mode=str(playback_raw.get("display_mode", DEFAULTS["playback"]["display_mode"])),
        ),
        audio=AudioConfig(
            audio_sink=str(audio_raw.get("audio_sink", DEFAULTS["audio"]["audio_sink"])),
            volume=_parse_float(audio_raw.get("volume"), DEFAULTS["audio"]["volume"], 0.0, 1.0),
            fade_out_ms=_parse_int(audio_raw.get("fade_out_ms"), DEFAULTS["audio"]["fade_out_ms"], 0),
            on_audio_end=str(audio_raw.get("on_audio_end", DEFAULTS["audio"]["on_audio_end"])),
            audio_mode=str(audio_raw.get("audio_mode", DEFAULTS["audio"]["audio_mode"])),
        ),
        lcd=_parse_lcd_section(lcd_raw, "lcd"),
        lcd2=_parse_lcd_section(lcd2_raw, "lcd2"),
        sensor=SensorConfig(
            sensor_type=str(sensor_raw.get("sensor_type", DEFAULTS["sensor"]["sensor_type"])),
            sensor_combine=str(sensor_raw.get("sensor_combine", DEFAULTS["sensor"]["sensor_combine"])),
            engaged_when=str(sensor_raw.get("engaged_when", DEFAULTS["sensor"]["engaged_when"])),
            gpio_pin=_parse_int(sensor_raw.get("gpio_pin"), DEFAULTS["sensor"]["gpio_pin"], 0),
            pull_up=_parse_bool(sensor_raw.get("pull_up"), DEFAULTS["sensor"]["pull_up"]),
            trigger_pin=_parse_int(sensor_raw.get("trigger_pin"), DEFAULTS["sensor"]["trigger_pin"], 0),
            echo_pin=_parse_int(sensor_raw.get("echo_pin"), DEFAULTS["sensor"]["echo_pin"], 0),
            threshold_cm=_parse_float(sensor_raw.get("threshold_cm"), DEFAULTS["sensor"]["threshold_cm"], 0),
            i2c_address=_parse_i2c_address(sensor_raw.get("i2c_address", DEFAULTS["sensor"]["i2c_address"])),
            touch_channel=_parse_int(sensor_raw.get("touch_channel"), DEFAULTS["sensor"]["touch_channel"], 0),
            gamepad_device=str(sensor_raw.get("gamepad_device", DEFAULTS["sensor"]["gamepad_device"])).strip(),
            bounce_time_ms=_parse_int(sensor_raw.get("bounce_time_ms"), DEFAULTS["sensor"]["bounce_time_ms"], 0),
            min_lift_ms=_parse_int(sensor_raw.get("min_lift_ms"), DEFAULTS["sensor"]["min_lift_ms"], 0),
            min_replace_ms=_parse_int(sensor_raw.get("min_replace_ms"), DEFAULTS["sensor"]["min_replace_ms"], 0),
            max_engaged_minutes=_parse_int(
                sensor_raw.get("max_engaged_minutes"),
                DEFAULTS["sensor"]["max_engaged_minutes"],
                0,
            ),
        ),
        schedule=ScheduleConfig(
            enabled=_parse_bool(schedule_raw.get("enabled"), DEFAULTS["schedule"]["enabled"]),
            sleep_start=str(schedule_raw.get("sleep_start", DEFAULTS["schedule"]["sleep_start"])),
            sleep_end=str(schedule_raw.get("sleep_end", DEFAULTS["schedule"]["sleep_end"])),
        ),
        gamepad=GamepadConfig(
            numbers={
                name: _optional_int(gamepad_raw.get(name, DEFAULTS["gamepad"][name]))
                for name in (*_GAMEPAD_BUTTONS, *sorted(_VALID_GAMEPAD_DIRECTIONS))
            },
            jobs={
                job: _control_list(gamepad_raw.get(job, DEFAULTS["gamepad"][job]))
                for job in _GAMEPAD_JOBS
            },
        ),
        system=SystemConfig(
            mode=str(system_raw.get("mode", DEFAULTS["system"]["mode"])),
            log_level=str(system_raw.get("log_level", DEFAULTS["system"]["log_level"])),
            log_max_mb=_parse_int(system_raw.get("log_max_mb"), DEFAULTS["system"]["log_max_mb"], 1),
            restart_on_crash=_parse_bool(system_raw.get("restart_on_crash"), DEFAULTS["system"]["restart_on_crash"]),
            exit_after_s=_parse_int(system_raw.get("exit_after_s"), DEFAULTS["system"]["exit_after_s"], 0),
        ),
        telemetry=TelemetryConfig(
            enabled=_parse_bool(telemetry_raw.get("enabled"), DEFAULTS["telemetry"]["enabled"]),
            endpoint_url=str(telemetry_raw.get("endpoint_url", DEFAULTS["telemetry"]["endpoint_url"])),
            interval_s=_parse_int(telemetry_raw.get("interval_s"), DEFAULTS["telemetry"]["interval_s"], 1),
            batch_size=_parse_int(telemetry_raw.get("batch_size"), DEFAULTS["telemetry"]["batch_size"], 1),
            timeout_s=_parse_int(telemetry_raw.get("timeout_s"), DEFAULTS["telemetry"]["timeout_s"], 1),
            log_tail_lines=_parse_int(
                telemetry_raw.get("log_tail_lines"), DEFAULTS["telemetry"]["log_tail_lines"], 0
            ),
        ),
        source_path=source,
    )

    return config


def validate(config: Config) -> list[str]:
    problems: list[str] = []

    if config.playback.idle_mode not in _VALID_IDLE_MODES:
        problems.append(
            f"playback.idle_mode must be one of {_VALID_IDLE_MODES}; got {config.playback.idle_mode!r}"
        )
    if config.playback.on_rewind_end not in _VALID_ON_REWIND_END:
        problems.append(
            f"playback.on_rewind_end must be one of {_VALID_ON_REWIND_END}; got {config.playback.on_rewind_end!r}"
        )
    if config.audio.on_audio_end not in _VALID_ON_AUDIO_END:
        problems.append(
            f"audio.on_audio_end must be one of {_VALID_ON_AUDIO_END}; got {config.audio.on_audio_end!r}"
        )
    if config.audio.audio_mode not in _VALID_AUDIO_MODE:
        problems.append(
            f"audio.audio_mode must be one of {_VALID_AUDIO_MODE}; got {config.audio.audio_mode!r}"
        )
    if config.sensor.engaged_when not in _VALID_ENGAGED_WHEN:
        problems.append(
            f"sensor.engaged_when must be one of {_VALID_ENGAGED_WHEN}; got {config.sensor.engaged_when!r}"
        )
    if config.sensor.sensor_combine not in _VALID_SENSOR_COMBINE:
        problems.append(
            f"sensor.sensor_combine must be one of {_VALID_SENSOR_COMBINE}; got {config.sensor.sensor_combine!r}"
        )

    for job, controls in config.gamepad.jobs.items():
        unknown = [c for c in controls if not _is_gamepad_control(c)]
        if unknown:
            problems.append(
                f"gamepad.{job} names controls the pad has no idea about: {unknown}. "
                f"Use {sorted(_GAMEPAD_CONTROLS | _VALID_GAMEPAD_DIRECTIONS)}, "
                f"or a raw button as b<number>."
            )

    types = [t.strip() for t in config.sensor.sensor_type.split("+")]
    unknown = [t for t in types if t not in _VALID_SENSOR_TYPES]
    if unknown:
        problems.append(f"sensor.sensor_type contains unknown backends: {unknown}")
    if not types:
        problems.append("sensor.sensor_type is empty")

    if config.playback.scaling not in _VALID_SCALING:
        problems.append(
            f"playback.scaling must be one of {_VALID_SCALING}; got {config.playback.scaling!r}"
        )

    for section, panel in (("lcd", config.lcd), ("lcd2", config.lcd2)):
        if panel.icon not in _VALID_LCD_ICONS:
            art = MEDIA_DIR / "icons" / f"{panel.icon}.txt"
            if not art.exists():
                problems.append(
                    f"{section}.icon must be one of {sorted(_VALID_LCD_ICONS)} or name a "
                    f"pixel-art file; got {panel.icon!r} and {art} does not exist"
                )
            else:
                import lcd

                try:
                    lcd.parse_icon_art(art.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    problems.append(f"{section}.icon art {art} cannot be used: {exc}")
        if panel.layout not in _VALID_LCD_LAYOUTS:
            problems.append(
                f"{section}.layout must be one of {sorted(_VALID_LCD_LAYOUTS)}; got {panel.layout!r}"
            )
        if (panel.icon_full is None) != (panel.icon_small is None):
            problems.append(
                f"{section}.icon_full and {section}.icon_small come as a pair — the icon "
                "needs both its full and its relaxed shape to beat"
            )
    if (
        config.lcd.enabled
        and config.lcd2.enabled
        and (config.lcd.i2c_bus, config.lcd.i2c_address)
        == (config.lcd2.i2c_bus, config.lcd2.i2c_address)
    ):
        problems.append(
            f"lcd and lcd2 both claim bus {config.lcd.i2c_bus} address "
            f"0x{config.lcd.i2c_address:02X} — two panels need two addresses "
            "or two buses (lcd2 ships on bus 3, the i2c3-pi5 overlay)"
        )

    dm = config.playback.display_mode
    if dm != "auto" and not display.is_valid_mode(dm):
        problems.append(
            f"playback.display_mode must be 'auto' or WIDTHxHEIGHT[@RATE]; got {dm!r}"
        )

    rr = config.playback.reverse_rate
    if rr not in _VALID_REVERSE_RATE and not re.fullmatch(r"\d*\.?\d+", rr):
        problems.append(
            f"playback.reverse_rate must be 'native', 'fit_to_audio', or a float; got {rr!r}"
        )

    for name, path in (
        ("media.video_file", config.media.video_file),
        ("media.audio_file", config.media.audio_file),
        ("media.reverse_file", config.media.reverse_file),
    ):
        if not path.exists():
            problems.append(f"{name} not found: {path}")

    for cut in config.media.cuts:
        if not cut.exists():
            problems.append(f"media.cuts entry not found: {cut}")
            continue
        reverse = Path(playback_math.reverse_name(str(cut)))
        if not reverse.exists():
            problems.append(
                f"media.cuts entry {cut.name} has no reversed copy at {reverse.name}; "
                "build it with motion-player-reverse"
            )

    if config.system.log_max_mb < 1:
        problems.append("system.log_max_mb must be at least 1")

    if config.system.mode not in _VALID_MODES:
        problems.append(
            f"system.mode must be one of {_VALID_MODES}; got {config.system.mode!r}"
        )

    if config.schedule.enabled:
        for name, value in (
            ("schedule.sleep_start", config.schedule.sleep_start),
            ("schedule.sleep_end", config.schedule.sleep_end),
        ):
            if schedule.parse_hhmm(value) is None:
                problems.append(f"{name} must be HH:MM; got {value!r}")

    if config.telemetry.enabled:
        url = config.telemetry.endpoint_url
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            problems.append(
                f"telemetry.endpoint_url must be an http:// or https:// URL; got {url!r}"
            )

    return problems
