#!/usr/bin/env python3
"""Entry point for the motion-player gallery installation."""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import queue
import signal
import sys
import time
import traceback
from pathlib import Path

import config
import logging_setup
import status as status_module
from audio import AudioEngine
from sensors import make_sensor
from state import StateMachine
from telemetry import Telemetry
from video import VideoEngine

LOGGER = logging.getLogger("motion-player")


def _acquire_lock(state_dir: Path) -> int:
    """File-descriptor flock; survives SIGKILL / power cut."""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "instance.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        # Non-zero: exiting 0 here reads as a clean run, so a supervisor with
        # Restart= would loop back into the same collision without saying why.
        LOGGER.warning("Another instance already holds %s; exiting.", lock_path)
        os.close(fd)
        sys.exit(3)
    return fd


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except (IOError, OSError):
        pass


def _preflight(cfg: config.Config, video: VideoEngine, audio: AudioEngine) -> list[str]:
    problems = []
    if not cfg.media.video_file.exists():
        problems.append(f"Video missing: {cfg.media.video_file}")
    if not cfg.media.audio_file.exists():
        problems.append(f"Audio missing: {cfg.media.audio_file}")
    if not cfg.media.reverse_file.exists():
        problems.append(
            f"Reverse clip missing: {cfg.media.reverse_file}. Build it with motion-player-reverse."
        )
    if audio.resolved_sink == "none":
        problems.append("Audio mixer could not be initialised")
    LOGGER.info("Preflight: video_exists=%s audio_exists=%s reverse_exists=%s audio_sink=%s",
                cfg.media.video_file.exists(),
                cfg.media.audio_file.exists(),
                cfg.media.reverse_file.exists(),
                audio.resolved_sink)
    return problems


def _main_loop(cfg: config.Config, sensor, video: VideoEngine, audio: AudioEngine, state: StateMachine,
               status: status_module.StatusWriter, telemetry: Telemetry, lock_fd: int) -> int:
    events: queue.Queue = queue.Queue()
    sensor.start(events)
    status.set_sensor(sensor)
    status.set_display_mode(video.display_mode)
    video.set_audio_duration(audio.duration_s)
    video.set_mode("IDLE")
    telemetry.start()

    # Track whether audio was playing to emit audio_end cleanly.
    state.mark_audio_playing()

    LOGGER.info("Main loop started; state=%s", state.state)
    while True:
        # Drain sensor events (from GPIO callbacks) without blocking.
        try:
            while True:
                event, ts, source = events.get_nowait()
                LOGGER.debug("Event from queue: %s %s %s", event, ts, source)
                state.handle(event)
                status.set_state(state.state)
                telemetry.event(
                    event,
                    source=source,
                    state=state.state,
                    monotonic_ts=ts,
                )
        except queue.Empty:
            pass

        # Handle keyboard input through OpenCV (main thread only).
        key = video._cv2.waitKey(1)
        if key != -1:
            key &= 0xFF
        # q and Esc always quit, whatever the sensor backend. Without this, a
        # fullscreen window driven by a hardware sensor can only be closed from
        # another machine or a virtual console.
        if key in (ord("q"), 27):
            LOGGER.info("Quit requested from keyboard")
            break
        if hasattr(sensor, "handle_key"):
            if sensor.handle_key(key) == "dump":
                LOGGER.info("Status dump: %s", status.snapshot())

        # Timer-based transitions (max-engaged timeout, audio end detection).
        now = time.monotonic()
        state.tick(now)
        status.set_state(state.state)

        # Video at-start detection.
        if state.state == "ENGAGED" and video.at_start:
            state.handle("video_at_start")

        # Periodic telemetry heartbeat.
        telemetry.heartbeat(sensor)

        # Advance video frame, paced by monotonic clock.
        video.render_next()

        # Short yield to avoid pinning a core.
        time.sleep(0.001)

    return 0


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="motion-player gallery engine")
    parser.add_argument("--verbose", action="store_true", help="Log at debug level")
    parser.add_argument("--config", default="/etc/motion-player/config.ini", help="Config path")
    parser.add_argument("--status", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit")
    args = parser.parse_args(argv)

    if args.status:
        return status_module.main()

    cfg = config.load(args.config)

    if args.check_config:
        problems = config.validate(cfg)
        print(cfg.dump())
        if problems:
            print("\nConfig problems:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("\nConfig OK")
        return 0

    logging_setup.setup(
        "debug" if args.verbose else cfg.system.log_level,
        cfg.system.log_max_mb,
        console=args.verbose,
    )

    state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "motion-player"
    lock_fd = _acquire_lock(state_dir)

    status = status_module.StatusWriter()
    status.set_last_error("")

    try:
        LOGGER.info("Starting motion-player")
        LOGGER.info("\n%s", cfg.dump())

        video = VideoEngine(cfg)
        audio = AudioEngine(cfg)
        sensor = make_sensor(cfg.sensor)
        state = StateMachine(cfg, audio, video, status)
        log_path = state_dir / "motion-player.log"
        telemetry = Telemetry(cfg, status, log_path)

        problems = _preflight(cfg, video, audio)
        for problem in problems:
            LOGGER.warning("Preflight: %s", problem)
            status.set_last_error(problem)

        return _main_loop(cfg, sensor, video, audio, state, status, telemetry, lock_fd)
    except Exception as exc:  # noqa: BLE001
        LOGGER.critical("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        status.set_last_error(str(exc))
        return 1
    finally:
        try:
            sensor.stop()  # type: ignore[has-type]
        except NameError:
            pass
        try:
            video.release()  # type: ignore[has-type]
        except NameError:
            pass
        try:
            telemetry.stop()  # type: ignore[has-type]
        except NameError:
            pass
        _release_lock(lock_fd)


def _signal_handler(signum: int, frame: Any) -> None:
    LOGGER.info("Received signal %s; exiting cleanly.", signum)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    sys.exit(run())
