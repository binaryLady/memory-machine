# memory-machine

A Raspberry Pi gallery installation: lift the headphones from their stand and a
video plays in reverse while the audio plays forward. Replace them and the piece
returns to its idle state.

This repository builds the `motion-player` Debian package. The package name is
`motion-player`; the repo is `memory-machine`.

## Quick start (on your laptop)

```bash
make lint        # syntax-check everything
make check       # run pytest
make deb         # build motion-player_*.deb
make install     # install it locally (requires sudo)
```

Use `make release` to build a `.deb` with hard dependencies on the Pi Python
libraries (`python3-opencv`, `python3-gpiozero`, `python3-lgpio`,
`python3-pygame`).

## Repo layout

```
src/                       Python engine
  motion_test.py           entry point
  config.py                config loading / validation
  logging_setup.py         size-capped rotating log
  state.py                 state machine
  video.py                 OpenCV playback
  audio.py                 pygame.mixer playback/fade
  status.py                runtime status file + CLI
  sensors/                 pluggable sensor backends
config/
  config.default.ini       shipped defaults
packaging/
  build_deb.sh             Debian package builder
  motion-player.desktop    menu / desktop entry
  motion-player.service    systemd user unit
  icons/                   16px … 256px PNGs
  make_icon.py             regenerate icons
scripts/
  bootstrap_pi.sh          one-time Pi setup
  update.sh                source for /usr/bin/motion-player-update
  status.sh                source for /usr/bin/motion-player-status
VERSION                    package version
Makefile
README.md                  this file
GALLERY.md                 laminated card for gallery staff
```

## Install on the Pi

1. Generate a deploy key on the Pi and add it to this GitHub repo under
   **Settings → Deploy keys** (write access only if you will push from the Pi).
2. `ssh -T git@github.com` should succeed before continuing.
3. Clone this repo and run the bootstrap:

```bash
git clone git@github.com:binaryLady/memory-machine.git ~/memory-machine
cd ~/memory-machine
./scripts/bootstrap_pi.sh
```

The bootstrap installs dependencies, builds the release `.deb`, installs it,
enables linger for your user, and starts the systemd user service.

## Media

Place the real video and audio files in `~/memory-machine-media`, which the
desktop shortcut **memory-machine-media** points to:

```
~/memory-machine-media/piece.mp4                    always
~/memory-machine-media/piece.wav                    always
~/memory-machine-media/piece.reverse.mp4            always
~/memory-machine-media/piece_portrait.mp4           one per panel shape
~/memory-machine-media/piece_portrait.reverse.mp4   with each cut
```

Every video cut needs its own pre-rendered reverse, because the rewind plays
that copy forward — a cut without one goes black the moment the headphones are
lifted. Build them once, whenever the footage changes, one call per cut:

```bash
motion-player-reverse
```

```bash
motion-player-reverse ~/memory-machine-media/piece_portrait.mp4
```

For a show, render each cut at the resolution it will actually be displayed at
instead, which builds the reverse at the same time and removes per-frame scaling
entirely:

```bash
motion-player-prepare
```

```bash
motion-player-prepare ~/memory-machine-media/piece_portrait.mp4 --size 1080x1920
```

The rewind plays that file forward, so playback stays sequential and never
seeks. Seeking per frame forces the H.264 decoder back to the preceding
keyframe every time, which is what limited the old engine to small clips; with
the pre-reversed file, 1080p runs comfortably on a Pi. Encoding is CPU-heavy —
run it on a laptop and copy the result over if the Pi is slow.

The installer creates that folder and a desktop shortcut, so you can drag and
drop files without using a terminal. You can also right-click the
**memory-machine** icon and choose **Open media folder**.

Driving several screens from an HDMI splitter needs no configuration in the
app — it mirrors one signal, so the resolutions may differ as long as the aspect
ratios match. Pin the output mode so the splitter cannot renegotiate it
mid-show; see **Multiple screens** in [COMMANDS.md](COMMANDS.md).

If you use different file names, edit `/etc/motion-player/config.ini` to point
elsewhere. The package does not ship media; the app logs a clear "media missing"
reason and shows a black screen if the files are absent.

## Commands

| Command | What it does |
| --- | --- |
| `motion-player-toggle` | start/stop the piece (`--start`, `--stop`) |
| `motion-player-status` | runtime state and resolved config (`--json`) |
| `motion-player-update` | fetch, rebuild, reinstall, restart, roll back on failure |
| `motion-player-prepare` | render the piece at the screen's resolution, plus its reverse |
| `motion-player-reverse` | build the pre-rendered reverse clip |
| `motion-player-display` | pin the HDMI output mode, stop screen blanking |
| `motion-player-media` | open the media folder |
| `motion-player` | the engine itself (`--check-config`, `--verbose`, `--log`) |

`motion-player-install-deb` is an internal helper for unattended updates and
is not run by hand.

[COMMANDS.md](COMMANDS.md) is the full operator reference: getting started,
media, multiple screens, testing without the sensor, and troubleshooting.

## Update from the Pi

```bash
motion-player-update                 # fetch, rebuild, reinstall, restart
motion-player-update --check         # is anything waiting?
motion-player-update --force         # discard local changes, if any
motion-player-update --enable-auto   # nightly, outside gallery hours
```

The checkout is cloned automatically if there isn't one, so this works on a Pi
installed straight from a `.deb`. If the service fails to stay up after an
update, the previous package is reinstalled and the piece keeps running. See
**Updating** in [COMMANDS.md](COMMANDS.md) for the automatic-update tradeoffs.

## Status over SSH

```bash
/usr/bin/motion-player-status        # human-readable
/usr/bin/motion-player-status --json # machine-readable
```

This shows uptime, systemd restart count, current state, sensor reading, lift
and accepted/rejected transition counts, resolved audio sink, and the last
error.

## Config reference

All configuration lives in `/etc/motion-player/config.ini`, root-owned `0644`.
It is marked as a Debian `conffile`, so edits survive package upgrades. Unknown
keys are warned and ignored; missing keys fall back to the default below.

```ini
[media]
video_file          = piece.mp4        ; absolute or relative to ~/memory-machine-media/
audio_file          = piece.wav
reverse_file        = piece.reverse.mp4 ; built by motion-player-reverse
cuts                  =                ; alternative cuts, comma separated;
                                       ; the closest in shape to the screen wins

[playback]
idle_mode           = hold_first_frame ; hold_first_frame | loop_forward | black
reverse_rate        = native           ; native | fit_to_audio | <float>
on_rewind_end       = hold             ; hold | loop_reverse | resume_forward
scaling             = fit              ; fit | fill | stretch
fullscreen          = true
display             = auto             ; auto | HDMI-A-1 | HDMI-A-2
display_mode        = auto             ; auto | 1920x1080@60, re-pinned each start

[audio]
audio_sink          = auto             ; ALSA/PipeWire device NAME
volume              = 0.8              ; fixed 0.0–1.0
fade_out_ms         = 400
on_audio_end        = silence          ; silence | loop

[sensor]
sensor_type         = switch           ; switch | reed | beam | reflective |
                                       ; capacitive | distance | hall | pir |
                                       ; mmwave | gpio_raw | keyboard | none
                                       ; or fused: switch+beam
sensor_combine      = any              ; any | all
engaged_when        = open             ; open | closed

gpio_pin            = 4
pull_up             = true

; distance backends
trigger_pin         = 23
echo_pin            = 24
threshold_cm        = 15
i2c_address         = 0x29             ; set to use VL53L0X ToF instead of HC-SR04

; capacitive
touch_channel       = 0

; timing
bounce_time_ms      = 50
min_lift_ms         = 250
min_replace_ms      = 250
max_engaged_minutes = 30

[telemetry]
enabled             = false            ; true | false
endpoint_url        =                  ; http:// or https://
interval_s          = 60               ; heartbeat interval
batch_size          = 10               ; events per POST
timeout_s           = 5                ; HTTP timeout

[system]
log_level           = info             ; debug | info | warning | error
log_max_mb          = 20               ; cap across all rotated files
restart_on_crash    = true
```

### Key config choices to make on site

- `engaged_when`: with the headphones resting on a microswitch, lifting them
  usually opens the contact, so `open` is the default. Verify with a multimeter.
- `reverse_rate`: use `fit_to_audio` if the audio is longer than the footage;
  it slows the rewind so frame 0 is reached exactly when the sound ends.

## Sensor wiring

| sensor_type  | Hardware                       | Notes                                                |
| ------------ | ------------------------------ | ---------------------------------------------------- |
| `switch`     | Lever microswitch under stand  | Default; headphone weight closes it.                 |
| `reed`       | Reed switch + magnet in earcup | Same logic as `switch`.                              |
| `beam`       | IR beam-break across cradle    | Shield from gallery lighting.                        |
| `reflective` | TCRT5000 reflective proximity  | Drifts with ambient IR and earcup colour.            |
| `capacitive` | MPR121 over I²C                | Senses hand, not headphone.                          |
| `distance`   | HC-SR04 or VL53L0X             | Set `i2c_address` for ToF; otherwise HC-SR04.        |
| `hall`       | Analog Hall + magnet           | Threshold-based.                                     |
| `pir`        | Room PIR                       | Legacy; not recommended for headphone lift.          |
| `mmwave`     | Presence module                | Uses the same `gpio_pin` as a digital presence line. |
| `gpio_raw`   | Bare digital pin               | Escape hatch.                                        |
| `keyboard`   | Spacebar                       | Laptop dev/test only.                                |
| `none`       | Nothing fitted                 | The piece loops forward and never rewinds.           |

Fuse sensors with `sensor_type = switch+beam` and `sensor_combine = any` (OR,
survives one dying) or `all` (AND, kills false triggers).

If the configured hardware cannot be initialised, the engine logs the error and
falls back to `keyboard` so the piece keeps running.

## Tuning debounce from the logs

Every raw edge and accepted transition is logged to the `motion-player.transitions`
logger. Greppable lines look like:

```
transition sensor=switch event=lift raw=engaged engaged_when=open accepted=true ts=12345.678
```

Tune `bounce_time_ms`, `min_lift_ms`, and `min_replace_ms` in
`/etc/motion-player/config.ini`, then restart:

```bash
systemctl --user restart motion-player.service
```

## Logs

Runtime logs go to:

```
~/.local/state/motion-player/motion-player.log
```

and are rotated so the total size stays near `log_max_mb`. The package never
shows a traceback or dialog on screen.

## Remote telemetry

Set `enabled = true` in the `[telemetry]` section. The default endpoint is:

```
https://lab.thetechmargin.com/memorymachine/api/telemetry
```

The engine POSTs JSON batches containing:

- **Events:** every accepted `lift` and `replace`, with timestamp, source sensor,
  and current state.
- **Heartbeats:** every `interval_s` with uptime, current state, raw sensor
  reading, lift/accepted/rejected counts, resolved audio sink,
  last error, and a tail of the local log (`log_tail_lines`).

Telemetry runs on a background thread and never blocks the main loop. Invalid
or unreachable endpoints are logged but do not stop the piece.

A prompt for building the receiving UI route is in `docs/ui-prompt.md`.

## Development on a laptop

Use `sensor_type = keyboard` and run:

```bash
python3 src/motion_test.py --verbose --config config/config.default.ini
```

Keys in the OpenCV window:

- `Space`: toggle lift/replace
- `d`: dump current status to log
- `q`: quit

## License

MIT License — Copyright 2026 TheTechMargin
