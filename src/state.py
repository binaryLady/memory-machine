"""State machine that drives audio and video in sync."""
from __future__ import annotations

import logging
import time
from typing import Any

LOGGER = logging.getLogger("motion-player.state")

# States and events are plain strings for clarity in logs and tests.
IDLE = "IDLE"
ENGAGED = "ENGAGED"

LIFT = "lift"
REPLACE = "replace"
VIDEO_AT_START = "video_at_start"
AUDIO_END = "audio_end"
TICK = "tick"


class StateMachine:
    """Implements PROMPT.md Part 5c as an explicit table."""

    def __init__(self, config: Any, audio: Any, video: Any, stats: Any) -> None:
        self._config = config
        self._audio = audio
        self._video = video
        self._stats = stats
        self._state = IDLE
        self._engaged_at: float | None = None
        self._was_audio_playing = False
        self._max_engaged_seconds = config.sensor.max_engaged_minutes * 60

    @property
    def state(self) -> str:
        return self._state

    def handle(self, event: str) -> None:
        now = time.monotonic()
        handler = self._transitions.get((self._state, event))
        if handler is None:
            LOGGER.debug("No transition for (%s, %s); staying in %s", self._state, event, self._state)
            return
        LOGGER.debug("Transition: (%s, %s)", self._state, event)
        handler(self, now)

    # -------------------------------------------------------------------------
    # Transition table: (current_state, event) -> method
    # -------------------------------------------------------------------------
    def _on_idle_lift(self, now: float) -> None:
        audio_start = time.monotonic()
        self._audio.play_from_start()
        self._video.set_mode("REVERSE")
        video_start = time.monotonic()
        LOGGER.info(
            "Lift handled dispatch_ms=%.3f",
            (video_start - audio_start) * 1000,
        )
        self._state = ENGAGED
        self._engaged_at = now
        self._stats.lift_accepted()
        self._was_audio_playing = True

    def _on_idle_replace(self, now: float) -> None:
        # Already idle; ignore.
        pass

    def _on_engaged_replace(self, now: float) -> None:
        self._audio.fade_out(self._config.audio.fade_out_ms)
        self._video.set_mode("IDLE")
        self._state = IDLE
        self._engaged_at = None

    def _on_engaged_lift(self, now: float) -> None:
        # Lifting again mid-fade restarts cleanly from the top.
        audio_start = time.monotonic()
        self._audio.play_from_start()
        self._video.set_mode("REVERSE")
        video_start = time.monotonic()
        LOGGER.info(
            "Re-lift handled dispatch_ms=%.3f",
            (video_start - audio_start) * 1000,
        )
        self._engaged_at = now
        self._stats.lift_accepted()
        self._was_audio_playing = True

    def _on_engaged_video_at_start(self, now: float) -> None:
        action = self._config.playback.on_rewind_end
        if action == "hold":
            # The picture has stopped, so the sound stops with it rather than
            # playing on over a black screen.
            self._audio.fade_out(self._config.audio.fade_out_ms)
            self._video.set_mode("BLACK")
        elif action == "loop_reverse":
            self._video.set_mode("REVERSE")
        elif action == "resume_forward":
            self._video.set_mode("FORWARD")
        # State remains ENGAGED; audio continues wherever the picture does.

    def _on_engaged_audio_end(self, now: float) -> None:
        action = self._config.audio.on_audio_end
        if action == "loop":
            self._audio.play_from_start()
            self._was_audio_playing = True
        # else silence; video untouched.

    def _on_engaged_tick(self, now: float) -> None:
        if self._engaged_at is not None and (now - self._engaged_at) > self._max_engaged_seconds:
            LOGGER.warning(
                "Engaged for longer than %d minutes; forcing idle",
                self._config.sensor.max_engaged_minutes,
            )
            self._audio.fade_out(self._config.audio.fade_out_ms)
            self._video.set_mode("IDLE")
            self._state = IDLE
            self._engaged_at = None

    _transitions = {
        (IDLE, LIFT): _on_idle_lift,
        (IDLE, REPLACE): _on_idle_replace,
        (ENGAGED, REPLACE): _on_engaged_replace,
        (ENGAGED, LIFT): _on_engaged_lift,
        (ENGAGED, VIDEO_AT_START): _on_engaged_video_at_start,
        (ENGAGED, AUDIO_END): _on_engaged_audio_end,
        (ENGAGED, TICK): _on_engaged_tick,
    }

    def tick(self, now: float) -> None:
        """Periodic timer check. Also emits audio_end when playback finishes."""
        audio_playing = self._audio.is_playing
        if self._was_audio_playing and not audio_playing:
            self.handle(AUDIO_END)
        self._was_audio_playing = audio_playing

        self.handle(TICK)

    def mark_audio_playing(self) -> None:
        self._was_audio_playing = self._audio.is_playing
