"""Configuration loader and validator for motion-player."""
from __future__ import annotations

import configparser
import dataclasses
import logging
import os
import re
import urllib.parse

import display
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger("motion-player.config")

MEDIA_DIR = Path.home() / "memory-machine-media"


@dataclass(frozen=True)
class MediaConfig:
    video_file: Path
    audio_file: Path
    reverse_file: Path
    portrait_video_file: Path | None
    portrait_reverse_file: Path | None


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
class AudioConfig:
    audio_sink: str
    volume: float
    fade_out_ms: int
    on_audio_end: str


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
    bounce_time_ms: int
    min_lift_ms: int
    min_replace_ms: int
    max_engaged_minutes: int


@dataclass(frozen=True)
class SystemConfig:
    log_level: str
    log_max_mb: int
    restart_on_crash: bool


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
    sensor: SensorConfig
    system: SystemConfig
    telemetry: TelemetryConfig
    source_path: Path

    def dump(self) -> str:
        lines = [f"# live config loaded from {self.source_path}", ""]
        for section_name, section in (
            ("media", self.media),
            ("playback", self.playback),
            ("audio", self.audio),
            ("sensor", self.sensor),
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
        "portrait_video_file": "",
        "portrait_reverse_file": "",
    },
    "playback": {
        "idle_mode": "hold_first_frame",
        "reverse_rate": "native",
        "on_rewind_end": "hold",
        "scaling": "fit",
        "fullscreen": True,
        "display": "auto",
        "display_mode": "auto",
    },
    "audio": {
        "audio_sink": "auto",
        "volume": 0.8,
        "fade_out_ms": 400,
        "on_audio_end": "silence",
    },
    "sensor": {
        "sensor_type": "switch",
        "sensor_combine": "any",
        "engaged_when": "open",
        "gpio_pin": 4,
        "pull_up": True,
        "trigger_pin": 23,
        "echo_pin": 24,
        "threshold_cm": 15.0,
        "i2c_address": None,
        "touch_channel": 0,
        "bounce_time_ms": 50,
        "min_lift_ms": 250,
        "min_replace_ms": 250,
        "max_engaged_minutes": 30,
    },
    "system": {
        "log_level": "info",
        "log_max_mb": 20,
        "restart_on_crash": True,
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

_VALID_IDLE_MODES = {"hold_first_frame", "loop_forward", "black"}
_VALID_REVERSE_RATE = {"native", "fit_to_audio"}
_VALID_ON_REWIND_END = {"hold", "loop_reverse", "resume_forward"}
_VALID_SCALING = {"fit", "fill", "stretch"}
_VALID_ON_AUDIO_END = {"silence", "loop"}
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
    "keyboard",
}
_VALID_ENGAGED_WHEN = {"open", "closed"}
_VALID_SENSOR_COMBINE = {"any", "all"}


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
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


def _optional_path(value: Any) -> Path | None:
    """An unset or blank media path means the variant is not provided."""
    if value is None or not str(value).strip():
        return None
    return _resolve_path(str(value).strip())


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
    sensor_raw = _section("sensor")
    system_raw = _section("system")
    telemetry_raw = _section("telemetry")

    config = Config(
        media=MediaConfig(
            video_file=_resolve_path(str(media_raw.get("video_file", DEFAULTS["media"]["video_file"]))),
            audio_file=_resolve_path(str(media_raw.get("audio_file", DEFAULTS["media"]["audio_file"]))),
            reverse_file=_resolve_path(str(media_raw.get("reverse_file", DEFAULTS["media"]["reverse_file"]))),
            portrait_video_file=_optional_path(media_raw.get("portrait_video_file")),
            portrait_reverse_file=_optional_path(media_raw.get("portrait_reverse_file")),
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
        ),
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
            bounce_time_ms=_parse_int(sensor_raw.get("bounce_time_ms"), DEFAULTS["sensor"]["bounce_time_ms"], 0),
            min_lift_ms=_parse_int(sensor_raw.get("min_lift_ms"), DEFAULTS["sensor"]["min_lift_ms"], 0),
            min_replace_ms=_parse_int(sensor_raw.get("min_replace_ms"), DEFAULTS["sensor"]["min_replace_ms"], 0),
            max_engaged_minutes=_parse_int(
                sensor_raw.get("max_engaged_minutes"),
                DEFAULTS["sensor"]["max_engaged_minutes"],
                0,
            ),
        ),
        system=SystemConfig(
            log_level=str(system_raw.get("log_level", DEFAULTS["system"]["log_level"])),
            log_max_mb=_parse_int(system_raw.get("log_max_mb"), DEFAULTS["system"]["log_max_mb"], 1),
            restart_on_crash=_parse_bool(system_raw.get("restart_on_crash"), DEFAULTS["system"]["restart_on_crash"]),
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
    if config.sensor.engaged_when not in _VALID_ENGAGED_WHEN:
        problems.append(
            f"sensor.engaged_when must be one of {_VALID_ENGAGED_WHEN}; got {config.sensor.engaged_when!r}"
        )
    if config.sensor.sensor_combine not in _VALID_SENSOR_COMBINE:
        problems.append(
            f"sensor.sensor_combine must be one of {_VALID_SENSOR_COMBINE}; got {config.sensor.sensor_combine!r}"
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
        ("media.portrait_video_file", config.media.portrait_video_file),
        ("media.portrait_reverse_file", config.media.portrait_reverse_file),
    ):
        if path is not None and not path.exists():
            problems.append(f"{name} not found: {path}")

    portrait = (config.media.portrait_video_file, config.media.portrait_reverse_file)
    if any(portrait) and not all(portrait):
        problems.append(
            "media.portrait_video_file and media.portrait_reverse_file must be set together; "
            "a portrait clip needs its own reversed copy"
        )

    if config.system.log_max_mb < 1:
        problems.append("system.log_max_mb must be at least 1")

    if config.telemetry.enabled:
        url = config.telemetry.endpoint_url
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            problems.append(
                f"telemetry.endpoint_url must be an http:// or https:// URL; got {url!r}"
            )

    return problems
