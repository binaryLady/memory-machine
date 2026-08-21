"""Audio engine using pygame.mixer (low latency, simple fade)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("motion-player.audio")

# Suppress the startup banner that pygame prints to stdout/stderr.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


class AudioEngine:
    """Preloads a sound and plays/fades it on a pinned sink."""

    def __init__(self, config: Any) -> None:
        import pygame  # type: ignore[import-untyped]

        self._pygame = pygame
        self._config = config.audio
        self._audio_path = Path(config.media.audio_file)
        self._volume = config.audio.volume
        self._sink = config.audio.audio_sink
        self._sound: Any = None
        self._resolved_sink = "default"
        self._duration_s = 0.0
        self._max_duration_s = 0.0
        self._looping = False

        self._init_mixer()
        self._load()

    def _list_devices(self) -> list[str]:
        try:
            from pygame._sdl2.audio import get_audio_device_names  # type: ignore[import-untyped]

            return get_audio_device_names(iscapture=False)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Could not enumerate audio devices: %s", exc)
            return []

    def _choose_device(self) -> str | None:
        devices = self._list_devices()
        if not devices:
            return None

        if self._sink and self._sink != "auto":
            # Exact match first, then substring.
            for dev in devices:
                if dev.lower() == self._sink.lower():
                    return dev
            for dev in devices:
                if self._sink.lower() in dev.lower():
                    return dev
            LOGGER.error(
                "Configured audio_sink %r not found. Available: %s",
                self._sink,
                devices,
            )
            return None

        # Auto: prefer first non-HDMI output, then anything other than the
        # empty/default placeholder, finally the default device.
        for dev in devices:
            if "hdmi" not in dev.lower() and dev:
                return dev
        for dev in devices:
            if dev:
                return dev
        return devices[0] if devices else None

    def _init_mixer(self) -> None:
        self._pygame.mixer.pre_init(frequency=48000, size=-16, channels=2, buffer=512)
        chosen = self._choose_device()
        if chosen:
            try:
                self._pygame.mixer.init(devicename=chosen)
                self._resolved_sink = chosen
                LOGGER.info("Audio mixer initialised on sink: %s", chosen)
                return
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("Failed to open sink %r: %s", chosen, exc)
        try:
            self._pygame.mixer.init()
            self._resolved_sink = "default"
            LOGGER.info("Audio mixer initialised on default sink")
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to initialise audio mixer: %s", exc)
            self._resolved_sink = "none"

    def _load(self) -> None:
        if not self._audio_path.exists():
            LOGGER.error("Audio file not found: %s", self._audio_path)
            return
        try:
            self._sound = self._pygame.mixer.Sound(str(self._audio_path))
            self._sound.set_volume(self._volume)
            self._duration_s = self._sound.get_length()
            LOGGER.info(
                "Audio loaded: %s duration=%.3fs volume=%.2f",
                self._audio_path,
                self._duration_s,
                self._volume,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Could not load audio %s: %s", self._audio_path, exc)

    def set_max_duration(self, seconds: float) -> None:
        """Cap playback so the audio can never outlast the picture.

        A wav longer than the clip would otherwise keep playing over a held or
        black frame once the rewind has finished.
        """
        self._max_duration_s = max(0.0, seconds)
        if 0 < self._max_duration_s < self._duration_s:
            LOGGER.info(
                "Audio is %.1fs but the picture lasts %.1fs; playback will stop with it",
                self._duration_s,
                self._max_duration_s,
            )

    def play_from_start(self) -> None:
        if self._sound is None:
            return
        # Cancel any in-flight fade before restarting.
        self._sound.stop()
        self._sound.set_volume(self._volume)
        maxtime = 0
        if 0 < self._max_duration_s < self._duration_s:
            maxtime = int(self._max_duration_s * 1000)
        self._sound.play(maxtime=maxtime)
        self._looping = False
        LOGGER.debug("Audio started from start (maxtime=%dms)", maxtime)

    def play_looping(self) -> None:
        """Play the sound end to end, for ever.

        Used when the sound is not tied to the sensor: it starts at boot and
        the sensor drives only the picture. No maxtime here — the cap exists to
        stop the audio outlasting the picture, and there is no picture to
        outlast when the sound is the constant.
        """
        if self._sound is None:
            return
        self._sound.stop()
        self._sound.set_volume(self._volume)
        self._sound.play(loops=-1)
        self._looping = True
        LOGGER.info("Audio looping continuously (audio_mode=always)")

    def fade_out(self, ms: int) -> None:
        if self._sound is None:
            return
        self._sound.fadeout(ms)
        LOGGER.debug("Audio fading out over %d ms", ms)

    def switch_to(self, path: Path) -> bool:
        """Play a different sound, in whatever way the current one was playing.

        The sounds are alternative accompaniments to one piece, not a playlist:
        the new one starts from its own beginning, and if the old one was
        looping under audio_mode=always the new one loops too.
        """
        if path == self._audio_path:
            return False
        if not path.exists():
            LOGGER.error("Audio not found, keeping %s: %s", self._audio_path.name, path)
            return False

        was_playing, was_looping = self.is_playing, self._looping
        previous, previous_sound = self._audio_path, self._sound
        if previous_sound is not None:
            previous_sound.stop()
        self._audio_path = path
        self._load()
        if self._sound is None:
            # A sound that will not load leaves the piece silent; go back to the
            # one that was working rather than to nothing.
            LOGGER.error("Could not load %s; returning to %s", path.name, previous.name)
            self._audio_path, self._sound = previous, previous_sound
            self._duration_s = previous_sound.get_length() if previous_sound else 0.0

        if was_playing:
            self.play_looping() if was_looping else self.play_from_start()
        LOGGER.info("Audio switched to %s", self._audio_path.name)
        return True

    @property
    def is_playing(self) -> bool:
        return bool(self._pygame.mixer.get_busy())

    @property
    def duration_s(self) -> float:
        return self._duration_s

    @property
    def resolved_sink(self) -> str:
        return self._resolved_sink


class AlwaysOnAudio:
    """An AudioEngine that ignores being started and stopped.

    When audio_mode is "always" the sound is already looping and the sensor
    drives only the picture, but the state machine still calls play_from_start
    on every lift and fade_out on every release. Swallowing those two here
    keeps state.py free of a mode it does not otherwise care about.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def play_from_start(self) -> None:
        pass

    def fade_out(self, ms: int) -> None:
        pass

    def switch_to(self, path: Any) -> bool:
        """Choosing a different sound is not the state machine starting one."""
        return self._engine.switch_to(path)

    @property
    def is_playing(self) -> bool:
        return self._engine.is_playing

    @property
    def duration_s(self) -> float:
        return self._engine.duration_s
