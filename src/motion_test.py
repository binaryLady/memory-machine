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
import sysinfo
from lcd import Heartbeat
from schedule import SleepScheduler
from sensors import NullSensor, make_sensor, start_sensor
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


def _apply_schedule_transition(transition: str | None, state: StateMachine, video: VideoEngine,
                               audio: AudioEngine, telemetry: Telemetry, cfg: config.Config) -> None:
    """Put the piece to bed or wake it, from a scheduler flip."""
    if transition == "sleep":
        if state.state == "ENGAGED":
            # The existing replace transition fades the audio and clears the
            # engagement bookkeeping; going black mid-listen without the fade
            # would be a jolt.
            state.handle("replace")
        else:
            audio.fade_out(cfg.audio.fade_out_ms)
        video.set_mode("BLACK")
        telemetry.event("sleep_start")
        LOGGER.info("Going to sleep for the night")
    elif transition == "wake":
        video.set_mode("IDLE")
        state.mark_audio_playing()
        telemetry.event("sleep_end")
        LOGGER.info("Waking up")


def _main_loop(cfg: config.Config, sensor, video: VideoEngine, audio: AudioEngine, state: StateMachine,
               status: status_module.StatusWriter, telemetry: Telemetry, lock_fd: int,
               heartbeat: Heartbeat) -> int:
    events: queue.Queue = queue.Queue()
    started = start_sensor(sensor, events)
    degraded = started is not sensor
    if degraded:
        status.set_last_error(
            f"Sensor {sensor.name} could not start; running on the keyboard backend"
        )
    sensor = started
    status.set_sensor(sensor)
    status.set_audio_sink(audio.resolved_sink)

    # With no working sensor the lift never comes, and a held first frame reads
    # as a broken installation. Loop the piece forward instead; the rewind is
    # what needs the sensor, not the video.
    if degraded or isinstance(sensor, NullSensor):
        video.set_idle_mode("loop_forward")
    status.set_display_mode(video.display_mode)
    video.set_audio_duration(audio.duration_s)
    # The cap only applies when the picture stops with the rewind: under hold
    # the screen goes black at the rewind's end, so the audio must end there
    # too, with fade-room so the hold-fade is not clipped into a click. Under
    # resume_forward or loop_reverse the picture keeps going and the audio
    # plays its natural length; on_audio_end governs from there.
    if cfg.playback.on_rewind_end == "hold":
        audio.set_max_duration(video.rewind_duration_s + cfg.audio.fade_out_ms / 1000.0)
    video.set_mode("IDLE")
    telemetry.start()

    # Track whether audio was playing to emit audio_end cleanly.
    state.mark_audio_playing()

    scheduler = SleepScheduler(cfg.schedule)
    status.set_extra("version", sysinfo.read_version())
    loop_started = time.monotonic()
    next_housekeeping = 0.0
    cpu_previous: tuple[int, int] | None = None

    LOGGER.info("Main loop started; state=%s", state.state)
    while True:
        # Drain sensor events (from GPIO callbacks) without blocking.
        try:
            while True:
                event, ts, source = events.get_nowait()
                if scheduler.asleep:
                    LOGGER.debug("Asleep; discarding sensor event %s", event)
                    continue
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

        _apply_schedule_transition(scheduler.poll(now), state, video, audio, telemetry, cfg)
        display_state = "SLEEP" if scheduler.asleep else state.state
        status.set_state(display_state)
        # The panel narrates the drama, not just the sensor: staying through
        # the whole rewind turns the piece forward, and the panel should mark
        # that moment with its own words.
        panel_state = display_state
        if display_state == "ENGAGED" and video.mode == "FORWARD":
            panel_state = "REWARD"
        heartbeat.set_state(panel_state)

        # Video at-start detection.
        if not scheduler.asleep and state.state == "ENGAGED" and video.at_start:
            state.handle("video_at_start")

        # Once a second: host health into the status file, whence the LCD, the
        # status CLI, and the telemetry heartbeat all read it.
        if now >= next_housekeeping:
            next_housekeeping = now + 1.0
            cpu, cpu_previous = sysinfo.read_cpu_percent(cpu_previous)
            status.set_extra("cpu_percent", round(cpu, 1))
            status.set_extra("temperature_c", round(sysinfo.read_temperature_c(), 1))
            status.set_extra("mem_available_mb", round(sysinfo.read_mem_available_mb(), 1))
            status.set_extra("load_1m", sysinfo.read_load_1m())
            status.set_extra("throttled", sysinfo.read_throttled())
            status.set_extra("disk_free_mb", round(sysinfo.disk_free_mb(Path.home()), 1))
            status.set_extra("asleep", scheduler.asleep)
            timing = video.last_timing
            if timing is not None:
                status.set_extra("playback", timing)
            status.write()

        # A configured soak run stops itself instead of relying on someone
        # remembering to; 0 means run forever, which is the gallery setting.
        if cfg.system.exit_after_s > 0 and now - loop_started >= cfg.system.exit_after_s:
            LOGGER.info("exit_after_s=%d reached; stopping", cfg.system.exit_after_s)
            break

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

    # Test runs are for troubleshooting, so they log everything; production
    # keeps the configured level and the queue keeps writes off this thread.
    level = "debug" if (args.verbose or cfg.system.mode == "test") else cfg.system.log_level
    logging_setup.setup(
        level,
        cfg.system.log_max_mb,
        console=args.verbose,
    )

    state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "motion-player"
    lock_fd = _acquire_lock(state_dir)

    # lgpio writes its notification FIFOs into the working directory, so a
    # read-only one makes every GPIO backend fail with a bare ENOENT. The
    # launcher already starts us somewhere writable; this covers being run
    # directly from somewhere that is not.
    if not os.access(os.getcwd(), os.W_OK):
        LOGGER.info("Working directory %s is not writable; using %s", os.getcwd(), state_dir)
        os.chdir(state_dir)

    status = status_module.StatusWriter()
    status.set_last_error("")

    try:
        LOGGER.info("Starting motion-player")
        LOGGER.info("\n%s", cfg.dump())

        video = VideoEngine(cfg)
        audio = AudioEngine(cfg)
        sensor = make_sensor(cfg.sensor)
        state = StateMachine(cfg, audio, video, status)
        heartbeat = Heartbeat(cfg, status)
        heartbeat.start()
        log_path = state_dir / "motion-player.log"
        telemetry = Telemetry(cfg, status, log_path)

        problems = _preflight(cfg, video, audio)
        for problem in problems:
            LOGGER.warning("Preflight: %s", problem)
            status.set_last_error(problem)

        result = _main_loop(cfg, sensor, video, audio, state, status, telemetry, lock_fd, heartbeat)
        # A clean stop is news too: remote monitoring cannot otherwise tell a
        # deliberate quit from the start of a crash loop.
        telemetry.event("shutdown", reason="requested", exit_code=result)
        return result
    except Exception as exc:  # noqa: BLE001
        LOGGER.critical("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        try:
            telemetry.event("shutdown", reason="exception", error=str(exc))  # type: ignore[has-type]
        except NameError:
            pass
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
        try:
            heartbeat.stop()  # type: ignore[has-type]
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
