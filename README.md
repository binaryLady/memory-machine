# Memory<>Machine

*A self-portrait that unmakes itself when observed.*

**[the-tech-margin.com/memory-machine](https://the-tech-margin.com/memory-machine)**

Memory<>Machine is an interactive installation by [Sonia Cook-Broen
(TheTechMargin)](https://the-tech-margin.com), shown at SynthTember 2026. The
portrait comes from a GAN trained exclusively on the artist's hand-painted
works — no external datasets, a machine whose only memory is her painting.
Snapshots saved during training capture its progression from noise to a
recognizable face; played in reverse, they become a timeline of forgetting.

At rest, the portrait plays forward. Observe it — lift the headphones, touch
and hold — and it degrades backward through the machine's training history,
un-learning itself toward noise. Let go and it recovers. Hold all the way to
its beginning and it surrenders, re-forming from nothing. A measurement event,
in the sense Jung and Pauli meant it: observation alters the observed, the way
remembering rewrites a memory.

This repository is the engine that runs the piece: a Raspberry Pi video/audio
player driven by a physical sensor, shipped as the `motion-player` Debian
package. The package name is `motion-player`; the repo is `memory-machine`.

## The gallery build

The installed piece, as it runs in the show:

- The portrait floats in a layered acrylic light box, edge-lit neon pink,
  mounted portrait with pre-rendered portrait cuts (no compositor rotation).
- Below it a Raspberry Pi 5 runs exposed at the center of an LED-edged
  dichroic diamond.
- Two blue 20x4 character LCDs murmur the machine's inner monologue — one is
  its heartbeat (60 bpm at rest, 100 bpm while a visitor holds on, still
  overnight), the other a rotating instruction card for the visitor.
- Two pairs of headphones hang on hooks either side — lifting one is the act
  of observation that collapses the portrait — and a dichroic-wrapped USB
  gamepad offers a second touch.
- The soundscape, *explore*, is built on the Moog TheraMini, threaded with
  loops of generative sitar prompted from free-verse writing.
- The system runs autonomously: one power outlet, no network. It sleeps
  overnight on a schedule and wakes itself for gallery hours.

The engine is not tied to that build: any of a dozen sensor backends can be
the "observation", any video/audio pair can be the piece, and everything is
driven from one config file.

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
  state.py                 state machine
  video.py                 OpenCV playback
  audio.py                 pygame.mixer playback/fade
  lcd.py                   heartbeat + instruction-card LCD panels
  schedule.py              overnight sleep window
  telemetry.py             optional remote monitoring
  setup_wizard.py          motion-player-setup
  status.py                runtime status file + CLI
  sensors/                 pluggable sensor backends
config/
  config.default.ini       shipped defaults (single source for the docs)
packaging/
  build_deb.sh             Debian package builder
  motion-player-*          installed command wrappers
  motion-player.service    systemd user unit
  motion-player.desktop    menu / desktop entry
  icons/                   16px … 1024px PNGs
scripts/
  bootstrap_pi.sh          one-time Pi setup
  update.sh                source for /usr/bin/motion-player-update
  status.sh                source for /usr/bin/motion-player-status
  check_docs.py            audits COMMANDS.md against the code
tests/                     377 tests; run anywhere, no Pi hardware needed
COMMANDS.md                full operator reference
GALLERY.md                 laminated card for gallery staff
CONTROLLER.md              visitor-facing instruction card
VERSION                    package version
```

## Install on a Pi

```bash
git clone https://github.com/binaryLady/memory-machine.git ~/memory-machine
cd ~/memory-machine
./scripts/bootstrap_pi.sh
```

The bootstrap installs apt dependencies, enables I2C, installs the MPR121
touch-pad library system-wide (`pip --break-system-packages`, deliberately —
the engine runs under the OS Python), builds the release `.deb`, installs it,
enables linger for your user, and starts the systemd user service. Use
`git@github.com:binaryLady/memory-machine.git` instead if the Pi has a deploy
key and will push.

Then run the guided setup — screen shape, sensor, sleep hours, test mode:

```bash
motion-player-setup
```

## Media

The package ships no media: bring your own video and audio. Place the files in
`~/memory-machine-media`, which the desktop shortcut **memory-machine-media**
points to:

```
~/memory-machine-media/piece.mp4                    always
~/memory-machine-media/piece.wav                    always
~/memory-machine-media/piece.reverse.mp4            always
~/memory-machine-media/piece_portrait.mp4           one per panel shape
~/memory-machine-media/piece_portrait.reverse.mp4   with each cut
```

Every video cut needs its own pre-rendered reverse, because the rewind plays
that copy forward — a cut without one goes black the moment the visitor lets
go. Build them once, whenever the footage changes, one call per cut:

```bash
motion-player-reverse
```

```bash
motion-player-reverse ~/memory-machine-media/piece_portrait.mp4
```

For a show, render each cut at the resolution it will actually be displayed at
instead, which builds the reverse at the same time and removes per-frame
scaling entirely:

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

The installer creates the media folder and a desktop shortcut, so you can drag
and drop files without using a terminal. You can also right-click the
**memory-machine** icon and choose **Open media folder**.

Driving several screens from an HDMI splitter needs no configuration in the
app — it mirrors one signal, so the resolutions may differ as long as the
aspect ratios match. Pin the output mode so the splitter cannot renegotiate it
mid-show; see **Multiple screens** in [COMMANDS.md](COMMANDS.md).

If you use different file names, edit `/etc/motion-player/config.ini` to point
elsewhere. The app logs a clear "media missing" reason and shows a black
screen if the files are absent.

## Commands

| Command | What it does |
| --- | --- |
| `motion-player-setup` | guided configuration: screen shape, sensor, sleep hours, test mode |
| `motion-player-toggle` | start/stop the piece (`--start`, `--stop`) |
| `motion-player-status` | runtime state and resolved config (`--json`) |
| `motion-player-update` | fetch, rebuild, reinstall, restart, roll back on failure |
| `motion-player-prepare` | render the piece at the screen's resolution, plus its reverse |
| `motion-player-reverse` | build the pre-rendered reverse clip |
| `motion-player-display` | pin the HDMI output mode, stop screen blanking |
| `motion-player-sensor` | probe and fit the sensor (`--probe`, `--fit`) |
| `motion-player-media` | open the media folder |
| `motion-player` | the engine itself (`--check-config`, `--verbose`, `--log`) |

`motion-player-install-deb` is an internal helper for unattended updates and
is not run by hand.

[COMMANDS.md](COMMANDS.md) is the full operator reference: getting started,
media, multiple screens, testing without the sensor, every config key, and
troubleshooting.

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
motion-player-status        # human-readable
motion-player-status --json # machine-readable
```

This shows uptime, systemd restart count, current state, sensor reading, lift
and accepted/rejected transition counts, resolved audio sink, and the last
error.

## Configuration

All configuration lives in `/etc/motion-player/config.ini`, root-owned `0644`.
It is a Debian `conffile`, so edits survive package upgrades. Unknown keys are
warned and ignored; missing keys fall back to the shipped defaults in
[config/config.default.ini](config/config.default.ini).

The full key-by-key reference lives in
[COMMANDS.md](COMMANDS.md) and is generated from `config.default.ini` by
`make docs-sync`, so it cannot drift. The short version of what's in there:

- `[media]` — the video/audio pair, alternative cuts per screen shape, and an
  optional kaleidoscope twin the gamepad can switch to.
- `[playback]` — idle behaviour, rewind rate (`fit_to_audio` slows the rewind
  so frame 0 lands exactly when the sound ends), scaling, display pinning.
- `[audio]` — sink selection by name, volume, fades, whether sound is tied to
  the sensor at all.
- `[lcd]` / `[lcd2]` — the heartbeat panel and the rotating instruction card.
- `[sensor]` / `[gamepad]` — which observation hardware drives the piece, and
  its debounce timing.
- `[schedule]` — overnight sleep: black, silent, dark LCD.
- `[telemetry]` — optional remote monitoring, off by default.
- `[system]` — production/test mode, log level and size cap.

Key choices to make on site:

- `engaged_when`: a touch pad is engaged when its contact **closes**, which is
  why `closed` is the default. A cradle microswitch is the other way round —
  the headphones' weight holds it closed and lifting them opens it, so that
  wants `open`. Change this whenever `sensor_type` changes;
  `motion-player-setup` does it for you.
- `reverse_rate`: use `fit_to_audio` if the audio is longer than the footage.

## Sensors

The shipped default sensor is a USB game controller. Hold **Start or Select**
and the piece rewinds; **A or B** switches the picture to its kaleidoscope
twin; the **arrows** turn through every sound in the media folder.
`motion-player-sensor --fit` finds the pad and writes the config for it, and
`--probe` prints the name and number of whatever you press, which is how a pad
that numbers its buttons differently gets corrected. See COMMANDS.md for the
whole control map and the touch pad's header pins, and CONTROLLER.md for the
visitor-facing instruction card.

| sensor_type  | Hardware                       | Notes                                                |
| ------------ | ------------------------------ | ---------------------------------------------------- |
| `gamepad`    | Any USB game controller        | Default; a held button closes it, so `engaged_when=closed`. |
| `capacitive` | MPR121 touch pad over I²C      | Contact closes it, so `engaged_when=closed`.         |
| `switch`     | Lever microswitch under stand  | Headphone weight closes it; wants `engaged_when=open`. |
| `reed`       | Reed switch + magnet in earcup | Same logic as `switch`.                              |
| `beam`       | IR beam-break across cradle    | Shield from gallery lighting.                        |
| `reflective` | TCRT5000 reflective proximity  | Drifts with ambient IR and earcup colour.            |
| `distance`   | HC-SR04 or VL53L0X             | Set `i2c_address` for ToF; otherwise HC-SR04.        |
| `hall`       | Analog Hall + magnet           | Threshold-based.                                     |
| `pir`        | Room PIR                       | Legacy; presence, not a deliberate act.              |
| `mmwave`     | Presence module                | Uses the same `gpio_pin` as a digital presence line. |
| `gpio_raw`   | Bare digital pin               | Escape hatch.                                        |
| `keyboard`   | Spacebar                       | Laptop dev/test only.                                |
| `none`       | Nothing fitted                 | The piece loops forward and never rewinds.           |

Fuse sensors with `sensor_type = switch+beam` and `sensor_combine = any` (OR,
survives one dying) or `all` (AND, kills false triggers).

If the configured hardware cannot be initialised, the engine logs the error and
falls back to `keyboard` so the piece keeps running.

## Tuning debounce from the logs

Every raw edge and accepted transition is logged to the
`motion-player.transitions` logger. Greppable lines look like:

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

and are rotated so the total size stays near `log_max_mb`. The piece never
shows a traceback or dialog on screen.

## Remote telemetry

Off by default, and the endpoint ships empty — nothing is sent anywhere unless
you set `endpoint_url` to your own server and flip `enabled = true` in the
`[telemetry]` section.

The engine then POSTs JSON batches containing:

- **Events:** every accepted `lift` and `replace`, with timestamp, source
  sensor, and current state.
- **Heartbeats:** every `interval_s` with uptime, current state, raw sensor
  reading, lift/accepted/rejected counts, CPU temperature and throttle flags,
  playback fps, resolved audio sink, and the last error. A tail of the local
  log is attached only when `mode = test`; production runs keep their logs
  local.

No file paths or identifiers beyond the above are sent. Telemetry runs on a
background thread and never blocks the main loop. Invalid or unreachable
endpoints are logged but do not stop the piece.

A wire-format spec for building a receiving dashboard is in
[docs/ui-prompt.md](docs/ui-prompt.md).

## Development on a laptop

Use `sensor_type = keyboard` and run:

```bash
python3 src/motion_test.py --verbose --config config/config.default.ini
```

Keys in the OpenCV window:

- `Space`: toggle lift/replace
- `d`: dump current status to log
- `q`: quit

The whole suite runs without Pi hardware — every native library is imported
lazily and mocked in tests:

```bash
make lint && make check
```

## The artist

**Sonia Cook-Broen** — [@thetechmargin](https://github.com/binaryLady) — is an artist-technologist working at
the intersection of painting, generative systems, and interactive
installation. Memory<>Machine belongs to a larger body of work of paintings,
generative pieces, and installations; she is currently accepting commissions.

- Piece: [the-tech-margin.com/memory-machine](https://the-tech-margin.com/memory-machine)
- Studio: [the-tech-margin.com](https://the-tech-margin.com)
- Contact: [sonia@thetechmargin.com](mailto:sonia@thetechmargin.com)

## License

[MIT](LICENSE) — Copyright 2026 TheTechMargin

Author: [@thetechmargin](https://the-tech-margin.com) — sonia@thetechmargin.com

The engine is open source; the piece's media — the GAN portrait, the training
snapshots, the soundscape — is the artist's own work and is not part of this
repository.
