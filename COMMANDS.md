# memory-machine command reference

Everything you need to run, inspect, and change the installation. Commands run
on the Pi unless marked **(laptop)**.

---

## Every command at a glance

| Command | Flags | What it does |
| --- | --- | --- |
| `motion-player-toggle` | `--start` `--stop` | start or stop the piece; bare call toggles |
| `motion-player-setup` | `--set section.key=value` `--save-setup NAME` `--load-setup NAME` `--list-setups` | guided configuration: setups menu (save/load/duplicate a named configuration), screen shape, which render plays, sensor, audio output, forward reward, heartbeat panel, sleep, telemetry, run mode; `--set` writes values directly, no questions |
| `motion-player-status` | `--json` `--watch` | state, sensor, health figures, last error, resolved config |
| `motion-player-sensor` | `--report` `--probe` `--fit` | what the sensor is configured as, whether it answers, how long a visitor must hold on, and whether a lift and a rewind have ever actually happened; `--fit` finds the sensor and points the config at it |
| `motion-player-update` | `--check` `--force` `--auto` `--enable-auto` `--disable-auto` | fetch, rebuild, reinstall, restart; rolls back if the service does not stay up |
| `motion-player-prepare` | `[SRC]` `--size WxH` `--mode fit\|fill\|tile` `--crop auto\|W:H:X:Y` `--rotate cw\|ccw` `--fx double-h\|mirror-h\|mirror-v\|kaleidoscope` `--force` `--apply` `--no-apply` | render a cut at the screen's resolution (optionally turned 90° and/or with a baked symmetry), build its reverse, and offer to point the config at it; run per cut |
| `motion-player-prepare-all` | `[PROFILE …]` `--force` `--report` | build the whole render library — every screen profile from both masters — or report every clip's true dimensions and reverse status |
| `motion-player-reverse` | `[SRC] [DST]` `--force` | build the pre-rendered reverse clip; run once per cut |
| `motion-player-display` | `--show` `--set CONN MODE` `--revert` `--no-blank` | pin the HDMI output mode at boot, stop screen blanking |
| `motion-player-media` | — | open the media folder in the file manager |
| `motion-player` | `--check-config` `--verbose` `--log` `--config PATH` | the engine itself |

`motion-player-install-deb` also exists but is not meant to be run by hand: it
installs the newest built package and exists so unattended updates can hold one
fixed `sudoers` rule.

Both render commands skip work whose output is already newer than its source;
`--force` rebuilds regardless.

Two things worth committing to memory:

- **`--verbose` must come first** when running the piece, or output goes to the
  log instead of your terminal. `--check-config`, `--log` and `--help` are
  exempt.
- **`q` or `Esc` quits** from any sensor backend — the way out of fullscreen
  without another machine.

---

## Getting started

The quickest route on a Pi that already has the package: run the guided setup.
It shows what screen is attached, then walks through the shape, which of the
finished renders in the media folder plays (pick one outright, or several as a
shape-matched set), the sensor, the audio output, the forward reward, the
heartbeat panel, the sleep hours, telemetry and gallery-vs-test mode — writing
the config and offering a restart at the end:

```bash
motion-player-setup
```

Every answer can be skipped with Enter, and the previous config is backed up
beside itself before anything is written.

First install on a fresh Pi. The bootstrap installs dependencies, builds and
installs the `.deb`, enables linger, and starts the service:

```bash
git clone git@github.com:binaryLady/memory-machine.git ~/memory-machine
```

```bash
cd ~/memory-machine && ./scripts/bootstrap_pi.sh
```

Use `https://github.com/binaryLady/memory-machine.git` if this Pi has no deploy
key set up.

If the app was installed straight from a `.deb` there is no checkout, which is
what makes `motion-player-update` refuse to run. Clone it, then build and
install over the top — your `/etc/motion-player/config.ini` is a Debian
conffile and survives:

```bash
git clone git@github.com:binaryLady/memory-machine.git ~/memory-machine
```

```bash
cd ~/memory-machine && sudo apt install -y dpkg-dev ffmpeg && make clean && make release
```

```bash
sudo apt install -y --allow-downgrades ./motion-player_*.deb
```

`make clean` matters: old `.deb` files accumulate in the repo root, and the glob
hands apt several candidates at once, which it resolves to "nothing to do".
`--allow-downgrades` is only needed once, when coming from a build older than
1.0.1 — those were versioned by bare commit sha, which dpkg orders essentially
at random, so a newer build could look like a downgrade.

Either way, finish by putting the media in place and building the reversed
clip — the engine treats it as required media and will report
`Reverse clip missing` without it:

```bash
motion-player-reverse
```

```bash
motion-player --verbose --check-config
```

Expect `Config OK`, then start it:

```bash
motion-player-toggle --start
```

---

## Quick tips

- **`q` or `Esc` always quits**, whatever the sensor is set to — that is the way
  out of a fullscreen window without another machine or a virtual console.
- **`--verbose` has to come first** when running the piece itself, otherwise the
  launcher sends output to the log. `--check-config`, `--help` and `--log` are
  exempt and print straight to the terminal.
- **The log is the real output channel.** The engine writes almost nothing to a
  terminal on its own: `tail -f ~/.local/state/motion-player/motion-player.log`.
- **Stop the service before any foreground run.** The engine takes a
  single-instance lock, so a second copy exits immediately.
- **Keys go to the video window, not the terminal.** During a keyboard-sensor
  test, click the window first or `space` does nothing.
- **Rebuild `piece.reverse.mp4` whenever the footage changes.** A stale reverse
  clip is logged as a frame-count mismatch at startup, and the rewind will be
  the wrong length.
- **Config lives at `/etc/motion-player/config.ini`**, root-owned — not under
  `~/.config`.
- **`motion-player-update` clones its own checkout** if one is missing, so it
  works on a Pi installed from a bare `.deb`.
- **Never install with a bare `motion-player_*.deb` glob.** Stale builds in the
  repo root make apt pick between candidates and silently do nothing —
  `Installing: 0, Upgrading: 0`. Run `make clean` before `make release`.

---

## Media

The piece needs these files in `~/memory-machine-media/`:

| File | What it is | Needed |
| --- | --- | --- |
| `piece.mp4` | the footage, played forward | always |
| `piece.reverse.mp4` | pre-rendered reverse of it, played during the rewind | always |
| `piece.wav` | the audio, played forward on lift | always |
| `piece_<shape>.mp4` | a cut framed for another screen shape | one per panel shape |
| `piece_<shape>.reverse.mp4` | pre-rendered reverse of that cut | with each cut |

**Every video file needs its own reversed copy.** The rewind plays that copy
forward, so a cut without one goes black the moment a visitor engages the piece.
That applies to the portrait cut and to anything produced by
`motion-player-prepare` as much as to `piece.mp4`.

Open the folder in the desktop file manager:

```bash
motion-player-media
```

`.mp3` works anywhere `.wav` does — set `audio_file` in the config and the
engine loads it unchanged.

### Building the reversed copies

After any change to the footage, rebuild the reverse of **each** cut. With no
arguments it does `piece.mp4`:

```bash
motion-player-reverse
```

Name the file to do any other cut. The output defaults to the same name with
`.reverse` before the extension:

```bash
motion-player-reverse ~/memory-machine-media/piece_portrait.mp4
```

Both paths can be given explicitly, and the encode can be tuned:

```bash
motion-player-reverse ~/memory-machine-media/other.mp4 ~/memory-machine-media/other.reverse.mp4
```

```bash
CRF=20 PRESET=veryfast SEGMENT_SECONDS=5 motion-player-reverse
```

Encoding is CPU-heavy. Running it on a laptop and copying the result over is
usually much faster than encoding on the Pi.

### Preparing media for a show

For an installation that loops all day, render the piece at the screen's own
resolution once rather than scaling every frame on the Pi. This writes both the
sized clip and its reversed copy, then offers to point the config at them — it
knows the exact names it just rendered, so nothing is retyped. `--apply` says
yes up front, `--no-apply` prints the config lines instead:

```bash
motion-player-prepare
```

With no arguments it takes `piece.mp4` at the screen's reported mode and writes
`piece.<WxH>.mp4` and `piece.<WxH>.reverse.mp4`. Be explicit about either:

```bash
motion-player-prepare ~/memory-machine-media/piece.mp4 --size 1920x1080 --mode fill
```

`--mode fit` pads with black, `--mode fill` covers the screen and crops the
overflow, and `--mode tile` repeats the frame across the screen instead of
cropping — for a screen far wider than the piece, where a crop would leave a
narrow slice of it. A 1280x1280 square onto a 1920x480 strip becomes four
480x480 repeats.

Both commands skip work that is already done: an output newer than its source
is left alone, so re-running them while working through a set of cuts costs
nothing. Editing a source makes its outputs stale again and they rebuild. Pass
`--force` to rebuild regardless.

Those three are mechanical, and one family of compositional moves is built in
because it must be pixel-exact against the output to be seamless — the
symmetries:

```bash
motion-player-prepare ~/memory-machine-media/piece.mp4 --size 1280x800 --fx kaleidoscope
```

`mirror-h` reflects the left half across a vertical center line, `mirror-v`
reflects the top half downward, and `kaleidoscope` mirrors the top-left
quadrant four ways — those three are applied after sizing (and after
`--rotate`), so the seam lands exactly on the center of the finished frame.
`double-h` is different: it sets the **whole** frame beside its own
reflection, losing nothing — a ~1:2 portrait doubled becomes a square — and
is applied before sizing, since it changes the frame's shape. The effect
joins the filename — `piece.kaleidoscope.1280x800.mp4` — so variants live
side by side and the config names the one that plays. A non-default `--mode`
joins it the same way — `piece.1280x800.fill.mp4` — because the mode decides
the framing, and a render named only for its size would be ambiguous between a
padded one and a cropped one. None combine with `--mode tile`.

Anything else compositional — a different framing, a deliberate arrangement,
motion that responds to the shape — belongs in an editor. Prepare the file
however you like and hand the result to `motion-player-reverse`, which builds
the reversed copy from whatever you give it.

### The whole library in one command

Build every screen's render from both masters at once — nothing is chosen,
everything becomes available to the setup wizard's picker:

```bash
motion-player-prepare-all
```

Profiles cover the show's screens (the VSDISPLAY 1280x800 standing portrait,
the Hosyond 800x480 the same way, the 720x720 square panel, the 1920x480
strip) plus the square variants cut from the portrait master (`double-h`
mirrored pair, `kaleidoscope`). Name profiles to build just those; renders
already newer than their master are skipped, `--force` rebuilds. The portrait
master is expected **pre-flipped** — its turn is baked in at export, so the
rotated rectangles are pure scales.

The VSDISPLAY profile renders `--mode fill`. The pre-flipped master is a wider
shape than that panel, so the default `fit` pads it, and on a screen standing
on its long edge those bars run down both sides of the piece. `fill` covers the
panel and crops the overflow instead: from a 16:9 master that is about 5% off
each end of the long axis, which is the top and bottom of the standing screen.
Any profile whose master is not the panel's shape has the same choice to make —
pad and show bars, crop and lose the edges, or re-export the master at the
panel's shape and lose neither.

Audit the shelf without rendering — every clip's true pixel dimensions,
frame count, and whether its reverse exists (names can lie; this is what the
engine will actually see):

```bash
motion-player-prepare-all --report
```

A `1920x1080` verdict flags a likely editor-canvas export: the piece may be
letterboxed inside it with the bars baked into the pixels — re-export that
master at the art's own frame before trusting its renders.

**Preparing the portrait cut needs an explicit `--size`**, because the default
comes from the screen this Pi is attached to, which is the wrong shape for it:

```bash
motion-player-prepare ~/memory-machine-media/piece_portrait.mp4 --size 1080x1920
```

Once the media matches the output exactly the engine skips scaling entirely, and
playback becomes decode and upload with nothing in between. That is the single
biggest thing you can do for smooth continuous playback on a Pi.

Check what playback is actually achieving:

```bash
grep Playback ~/.local/state/motion-player/motion-player.log | tail -5
```

Each line reports achieved frame rate against target, mean and worst frame time,
and how many frames missed their deadline. The same figures appear in
`motion-player-status` under `playback`, alongside CPU, temperature, memory,
load, disk free, and the firmware throttle flags — and the compact subset rides
every telemetry heartbeat, so a remote monitor sees them too. Late frames in any number mean the Pi
is not keeping up: prepare the media at the output size first, and if it still
cannot, the source resolution is too high for software decode.

### Cuts for different screens

A piece framed for a square panel does not suit a portrait one. List alternative
cuts and the engine uses whichever is closest in **shape** to the attached
screen, so one media folder and one config serve a whole set of panels:

```ini
[media]
video_file = piece.mp4
cuts       = piece_square.mp4, piece_portrait.mp4, piece_wide.mp4
```

`video_file` competes as a candidate too, so it is the natural home for the
default framing rather than a special case.

Shape is what matters, not resolution — a 720x720 cut is an equally good match
for any square panel. Given cuts at 720x720, 800x1280, 1280x800 and 800x480:

| Screen | Cut chosen |
| --- | --- |
| 720x720 square panel | 720x720 |
| 800x1280 portrait panel | 800x1280 |
| 1280x800 monitor | 1280x800 |
| 800x480 touchscreen | 800x480 |
| 1920x1080 projector or TV | 800x480, nearest at 5:3 |

Every cut needs its reversed copy beside it, named the way the tooling writes it
— `piece_portrait.mp4` needs `piece_portrait.reverse.mp4`. A cut missing one is
skipped with a logged error rather than chosen, since choosing it would black
the screen on lift:

```bash
motion-player-reverse ~/memory-machine-media/piece_portrait.mp4
```

For a show, prepare each cut at the exact resolution of the panel it is for,
which builds its reverse at the same time and removes per-frame scaling:

```bash
motion-player-prepare ~/memory-machine-media/piece_portrait.mp4 --size 800x1280
```

**A master with baked-in bars poisons every render** — an editor-canvas
export carries its letterbox into the pixels, and `fill` faithfully keeps any
bar that survives its crop. `--crop auto` measures the true picture with
cropdetect and trims exactly the bars, before rotation, effects, or scaling:

```bash
motion-player-prepare ~/memory-machine-media/piece_portrait.mp4 --size 1280x800 --mode fill --crop auto --force
```

Explicit `--crop W:H:X:Y` (ffmpeg's crop order) takes framing into your own
hands. The clean long-term fix is still an export at the art's true frame.

**Preparing renames the file, and the config must follow.** That command writes
`piece_portrait.800x1280.mp4` (and its reverse) — it does not touch
`piece_portrait.mp4`. The engine only plays files the config names; nothing
scans the media folder, so a prepared clip the config doesn't mention is never
used and the engine keeps scaling the unprepared original every frame.

On a Pi that drives one screen, let prepare do it: when it finishes it offers
to write the config itself (`--apply` skips the question). That sets
`video_file` to the prepared clip, which also bypasses cut selection entirely.

On a Pi whose media folder serves several screen shapes, the prepared name goes
into the cut list instead, replacing the unprepared one:

```ini
[media]
cuts = piece_square.mp4, piece_portrait.800x1280.mp4, piece_wide.mp4
```

The chooser reads real pixel dimensions from each file, not the name — the
`800x1280` in the filename is bookkeeping for humans.

**A panel mounted sideways: bake the turn into the render.** A landscape panel
standing portrait (or the reverse) wants `--rotate`:

```bash
motion-player-prepare ~/memory-machine-media/piece_portrait.mp4 --size 1280x800 --rotate cw
```

`--size` stays the panel's **native** mode — the rotation happens inside the
render, once, and the screen itself is never rotated. The engine then plays a
clip that exactly matches the output: no per-frame cost, nothing to persist
across reboots, and the cut chooser sees the true shape. `cw` when the panel's
top edge points left as you face it; if the picture comes up inverted, rerun
with `ccw` and `--force`.

Rotating the screen in the compositor instead (`wlr-randr --transform 90`) is
tempting and does rotate the desktop — but the engine renders through XWayland,
which can keep reporting the unrotated mode, leaving the piece drawing into a
letterboxed landscape window on a portrait desktop. The baked render avoids
that whole stack, and matches how everything else here works: pay at render
time, never at playback.

The screen shape is read from the pinned `display_mode`, or from what the sink
advertises, before the window is opened. `playback.scaling` still covers
whatever difference remains between the chosen cut and the screen.

---

## A DSI panel

A ribbon-connected panel (DSI) is a display like any other, but it appears as
`DSI-1` rather than `HDMI-A-1`, and it is not hot-pluggable — connect it with the
Pi powered off.

Check the Pi sees it after booting:

```bash
motion-player-display --show
```

A `DSI-1` line reading `connected` with a mode beside it means the kernel has
the panel. If it is absent, the panel needs its device tree overlay in
`/boot/firmware/config.txt` — which overlay depends on the panel, so use the
line its manufacturer specifies — followed by a reboot:

```bash
dmesg | grep -iE "dsi|panel|drm" | tail -20
```

Then point the piece at it, using the panel's own resolution:

```ini
[playback]
display             = DSI-1
display_mode        = 800x480@60
```

```bash
motion-player-prepare --size 800x480 --mode fill
```

With both HDMI and DSI connected the Pi drives two outputs, and the engine opens
one fullscreen window on whichever the compositor treats as primary. `display`
pins the mode on the named connector but does not choose which screen the window
lands on — if it opens on the wrong one, disconnect the other, or set the panel
as primary in the desktop's screen settings.

---

## The forward reward

By default, a visitor who stays through the whole rewind is rewarded: when the
picture reaches the beginning, it turns and plays forward, with the audio
continuing. Letting go at any point still fades out and returns to the held
frame.

```ini
[playback]
on_rewind_end = resume_forward   ; the default
```

To toggle the reward off, choose what the end of the rewind does instead:
`hold` fades the audio and holds a black screen; `loop_reverse` starts the
rewind over from the end. Existing configs keep whatever they say — the default
only applies where the key is absent, so enabling it on an installed Pi is one
edit to `/etc/motion-player/config.ini`.

---

## Sleeping overnight

The piece can rest outside gallery hours: screens black, audio silent, sensor
events ignored, and the LCD dark with a "goodnight". At the wake time it says
"hello" for a few seconds and the loop resumes exactly as configured — including
the sensorless loop-forward fallback.

```ini
[schedule]
enabled     = true
sleep_start = 00:00
sleep_end   = 08:00
```

Times are HH:MM local (set the Pi's timezone with `sudo raspi-config` if it is
wrong); a window may span midnight. `sleep_start == sleep_end` disables the
window, and a typo in the hours is reported by `--check-config` rather than
silently ignored. Sleep and wake each emit a telemetry event, and
`motion-player-status` shows `State: SLEEP` overnight.

For a timed soak test, `system.exit_after_s = 3600` stops the piece cleanly
after an hour and emits a `shutdown` telemetry event. Leave it at 0 for a show.

`system.mode` separates the two ways the piece runs. `test` logs everything at
debug level and ships the log tail with every telemetry heartbeat, so a remote
troubleshooter sees what happened without asking. `production` keeps the
configured log level and sends heartbeats without log tails — the health
figures travel, the log stays on disk. In both modes log writes go through a
queue to a background thread, so a slow SD card can never stall a frame. The
setup wizard sets the mode with its gallery/test presets.

---

## The heartbeat panel

An optional 20x4 character LCD on I2C, showing a beating heart above the
installation's health. The heart beats slowly at rest and quickens while a
visitor holds the pad, so the panel reports its state rather than
just the machine.

Enable I2C once, then find the panel's address — these modules are almost always
0x27 or 0x3F:

```bash
sudo raspi-config nonint do_i2c 0 && sudo i2cdetect -y 1
```

Then in `/etc/motion-player/config.ini`:

```ini
[lcd]
enabled     = true
i2c_address = 0x27
idle_bpm    = 60
engaged_bpm = 100
sleep_bpm   = 0
```

The heart beats at `idle_bpm` at rest and `engaged_bpm` while someone holds on;
overnight it slows to `sleep_bpm` — 0 holds it still — while the backlight goes
dark and the panel says goodnight. It says hello for a few seconds at wake, and
goodbye when the piece shuts down.

### The panel's voice

Every word and the icon are configurable — the wizard's heartbeat step offers
it ("Customise the panel's text and icon?"), and because they are ordinary
`[lcd]` keys, saved setups carry a panel voice per gallery:

```ini
[lcd]
title         = her memory
label_engaged = with you
icon          = ring
```

Built-in icons all beat — a full and a relaxed shape alternate so they pulse
rather than blink: `heart`, `star`, `ring`, `note`, `eye`, or `none` for a
bare column. Or draw your own 5x8 icon: 8 comma-separated row values 0–31,
top to bottom (each row is 5 bits), setting **both** shapes of the beat:

```bash
sudo motion-player-setup --set lcd.icon_full=0,10,31,31,31,14,4,0 --set lcd.icon_small=0,0,10,31,14,4,0,0
```

### Art layout — the panel as a small artwork

`layout = art` drops all text and health figures: the icon sits centered on
the panel with asterisk stars twinkling around it in counter-phase with the
beat. This is the panel not as a readout but as a piece — and the right
choice for a portrait-mounted panel, where ROM text would lie sideways (draw
the icon pre-rotated in that case, exactly like the video masters). The
wizard's customise step asks the panel style; labels can also be individually
blanked (`-` at the prompt, or an empty value in the config) if you want the
status layout with fewer words. Sleep still darkens the backlight, and the
farewell still prints at shutdown.

### Show layout — the panel as her narrator

`layout = show` wears two faces. At rest it is the background texture: the
title always up, the idle word beside a tiny beating heart, system health
beneath, stars twinkling in the corners. The moment she is interacting it
gives itself over — one big heart (your pixel-art icon, every tile) beating
at the center, the state's word beneath it, stars scattered wide. At the
flip, when a visitor has stayed through the whole rewind, the word changes
(`label_reward`, default `I see you`) and the whole sky flashes with the
beat. Glyph memory is reprogrammed only when the face changes, never per
beat, so the animation stays a handful of character writes.

### The second panel — the visitor's instruction card

A second 20x4 panel renders the controller instructions from
[CONTROLLER.md](CONTROLLER.md) as a rotating deck of pages, each led by
`Memory<>Machine` with the heart beating beside it and a star twinkling in
the far corner. It rides the Pi 5's second hardware I2C bus so both
backpacks keep their factory 0x27 address — no solder bridge. Add
`dtoverlay=i2c3-pi5,pins_22_23` to `/boot/firmware/config.txt` and reboot;
wire the second panel's SDA to GPIO 22 (physical pin 15) and SCL to GPIO 23
(pin 16), power and ground to any spare 5V/GND pins. Confirm it appears in
`i2cdetect -y 3` (the heartbeat panel stays on `i2cdetect -y 1`), then:

```bash
sudo motion-player-setup --set lcd2.enabled=true
```

Every `[lcd]` key works in `[lcd2]` — icon, bpm, labels — plus the deck's
own: `page_seconds` for how long each page stays up, and `page_1` …
`page_6` to replace the shipped words, up to four lines per page separated
by `|`, each up to 20 printable ASCII columns. The card rotates whenever the
piece is awake and goes dark overnight with everything else; unplugging it
mid-show only logs an error and never touches playback or the heartbeat
panel.

### The captain's log

Every interaction is also written locally, one JSON line per event, one file
per day, at `~/.local/state/motion-player/journal/YYYY-MM-DD.jsonl` — lift,
replace, reward (a visitor stayed through the whole rewind), sleep, wake,
startup, shutdown. Telemetry can lose the network; this cannot, and it never
interrupts the show: a failed write is a logged warning. A day of heavy
visiting is a few tens of kilobytes — the raw material for a visualization
of a month of presence:

```bash
ls ~/.local/state/motion-player/journal/
```

### Pixel-art icons, up to 10x16

The panel has no emoji and no free-form graphics — it is a character device —
but its eight programmable glyph slots compose into something better: icons up
to **2x2 character cells (10x16 pixels)**, drawn as plain text. Put a file at
`~/memory-machine-media/icons/<name>.txt` (it travels with the media folder,
like setups): `#` for a lit pixel, `.` for dark, 5 or 10 pixels wide, 8 or 16
tall — the full shape, a line of `---`, then the relaxed shape it beats
against:

```
.##..#..##.
####.#.####
###########
###########
.#########.
.#########.
..#######..
..#######..
...#####...
...#####...
....###....
....###....
.....#.....
.....#.....
...........
...........
---
(same size, drawn smaller)
```

Then set `icon = <name>` — or just rerun `motion-player-setup`: every file in
the icons folder appears in the icon menu by name. A big icon occupies the
panel's left margin (text already clears it), and both beat frames stay
resident in the chip so the pulse costs a handful of character writes, not a
redraw. 10x16 is the hard ceiling: both frames must share the chip's eight
glyph slots. A file that will not parse falls back to the heart with the
reason in the log, and `motion-player --check-config` reports it precisely.

Panel text is printable ASCII only (the HD44780's character set garbles
anything else) and up to 18 columns — the loader trims and warns rather than
letting the glass show noise.

The panel is driven from its own thread, never the render loop — an I2C write
takes milliseconds against a 33ms frame budget. If it cannot be opened, or a
write fails, the reason is logged and the piece carries on without it:

```bash
grep -a -i lcd ~/.local/state/motion-player/motion-player.log | tail -5
```

---

## Multiple screens

An HDMI splitter mirrors one signal, so the Pi renders a single framebuffer and
each screen scales that same image to its own panel. Nothing in the engine
changes for a multi-screen install.

Different **resolutions** are fine. Different **aspect ratios** are not: at the
same aspect (1280x720, 1920x1080 and 3840x2160 are all 16:9) every screen shows
the piece correctly, one downscaling and another upscaling. A 16:10, 4:3 or
portrait panel will letterbox or stretch according to its own scaler, and the Pi
cannot compensate per screen — there is only one signal.

See what is connected and what mode each sink is asking for. Mixed-resolution
sinks make splitters report either the lowest common mode or whatever they
detected first, which can quietly drop the whole install to 720p:

```bash
motion-player-display --show
```

Don't trust that negotiation — pin the mode instead. Two layers do this, and you
want both:

**At boot**, as a kernel parameter, so the very first frame after a cold boot is
already correct and a screen switched off at boot cannot change what the Pi
negotiates:

```bash
sudo motion-player-display --set HDMI-A-1 1920x1080@60
```

Use `HDMI-A-2` if the splitter is in the Pi's second port. This is idempotent,
backs up `cmdline.txt` the first time, and needs a reboot. It appends
`video=HDMI-A-1:1920x1080@60D` — the trailing `D` forces the mode even when EDID
disagrees and keeps the connector alive when a screen is powered off. Undo with
`sudo motion-player-display --revert`.

**On every start**, from the app itself, so a screen that was off at boot and
came back later cannot leave the output negotiated to something else. Set it in
`/etc/motion-player/config.ini`:

```ini
[playback]
display             = HDMI-A-1
display_mode        = 1920x1080@60
```

The engine re-pins that mode each time it starts, before opening its window. If
the mode is wrong, unavailable, or the tooling is missing, it logs the reason and
plays anyway rather than failing — check which happened with
`motion-player-status`, which reports the mode it settled on.

While you are there, stop the screen blanking:

```bash
sudo motion-player-display --no-blank
```

Confirm what is actually going out after a reboot:

```bash
wlr-randr
```

Force a mode every screen can **accept as input**, which is not the same as its
native resolution. Nearly all 720p HDMI TVs accept 1080p and downscale
internally, but some 1366x768 monitors top out at 1360x768 and will show
nothing at 1080p. Power each screen on one at a time after the change and check
that it syncs.

A splitter can only mirror, so a mix of portrait and landscape screens cannot
each get their own cut from one Pi — the portrait cut is chosen once, from the
single output mode. Mixed orientations need one Pi per orientation.

`playback.scaling` decides how a frame meets a screen of a different shape:
`fit` pads with black, `fill` crops to cover, `stretch` distorts. See the
scaling entry under Troubleshooting.

Then render the media at exactly the forced mode with `motion-player-prepare`,
so the Pi does no scaling at all. Do not master at 4K to serve a 4K screen: the
splitter emits one mode regardless, and 4K decode is what the Pi cannot sustain.

---

## Service control

The **memory-machine** desktop icon has explicit right-click actions — Start,
Stop, Status, Update, Open media folder, Run with visible log, Open log file.
Prefer those to clicking the icon itself, which toggles and is easy to misread.
Each one reports what it did as a desktop notification.

From a terminal, toggle:

```bash
motion-player-toggle
```

```bash
motion-player-toggle --start
```

```bash
motion-player-toggle --stop
```

The service waits up to 90 seconds for a display to appear before giving up, so
starting at boot before the desktop session is ready is not a failure. If no
display ever appears it says so in the log and exits, rather than running
invisibly.

The underlying systemd user unit, if you want it directly:

```bash
systemctl --user restart motion-player.service
```

```bash
systemctl --user status motion-player.service
```

---

## Status and logs

```bash
motion-player-status
```

```bash
motion-player-status --json
```

Follow the log live:

```bash
tail -f ~/.local/state/motion-player/motion-player.log
```

That is the engine's own log, and the one worth reading. The launcher keeps a
separate `motion-player-launcher.log` beside it holding start banners, exit
statuses, and raw output from the graphics and audio libraries — useful when the
engine dies before it can log anything itself.

Pass `grep -a` when searching either file. Library output can contain control
bytes, and without it grep reports "binary file matches" and stops reading:

```bash
grep -a -iE "pin factory|could not start" ~/.local/state/motion-player/motion-player.log | tail -5
```

Open it in the desktop text editor:

```bash
motion-player --log
```

The log is the primary output channel — the engine writes almost nothing to a
terminal unless you pass `--verbose`.

### Fitting the gamepad

The shipped sensor is a USB game controller: the visitor holds a button and the
piece rewinds for as long as it is held. Nothing to wire and no driver to
install — the kernel presents any USB pad as `/dev/input/js0`.

```bash
motion-player-sensor --fit
```

Finds the pad, says what it calls itself, checks this user may read it, and
writes `sensor_type = gamepad` with `engaged_when = closed` — a held button is
engaged when its contact closes, and left on `open` the piece would run
whenever nobody is holding anything.

`[sensor] gamepad_device` picks the pad: `auto` takes the first one plugged in,
or name one (`/dev/input/js1`) to pin it when there are two.

### What each control does

An NES-style pad has Select, Start, A, B and four arrows, and the `[gamepad]`
section gives each a job:

| Setting | Ships as | What it does |
| --- | --- | --- |
| `hold` | `start+select` | held to wind the piece back — the interaction itself. `any` means any button, which suits a pad that does nothing else. |
| `kaleidoscope` | `a+b` | switches the picture between the plain render and its kaleidoscope twin |
| `audio_up`, `audio_down`, `audio_left`, `audio_right` | empty | one sound per arrow, chosen live while the piece runs |

A control can only hold **or** do something else — if A toggles the
kaleidoscope, A cannot also be the rewind.

The pad reports each button as a number, and pads disagree about which is
which. The numbers ship as `a = 1`, `b = 0`, `select = 2`, `start = 3`; if this
pad says otherwise, `--probe` prints the name and number of everything you
press, and correcting the four numbers in `[gamepad]` fixes every job at once.
The arrows are usually an axis pair and need no numbers — if `--probe` shows
them as buttons on yours, give them numbers too.

### The kaleidoscope twin

The effect is baked at render time, not applied per frame, so it costs the
rewind nothing:

```bash
motion-player-prepare piece_portrait.mp4 --size 800x480 --fx kaleidoscope
```

That writes `piece_portrait.kaleidoscope.800x480.mp4` and its reverse, and
offers to set `media.kaleidoscope_file` — the twin the pad switches to, never
`video_file`, which is the piece itself. `motion-player-prepare-all` builds one
for every screen profile it can (`vsdisplay-kaleido`, `hosyond-kaleido`,
`tekgroaml-kaleido`); the Lian Li tile has none, since the kaleidoscope cannot
be combined with `--mode tile`. With several screen shapes in one media folder,
list the twins in `media.kaleidoscope_cuts` and the closest in shape to the
attached screen is used, exactly as `media.cuts` works.

Switching keeps the visitor's place: the twin is the same footage at the same
length, so a rewind three quarters of the way back carries on from three
quarters of the way back.

A pad unplugged mid-hold lets go rather than leaving the piece stuck engaged,
and is picked up again when it is plugged back in, without a restart.

### Fitting the touch pad

Wire the MPR121 breakout to the Pi first — it shares the I²C bus with the LCD,
so both sit on the same two pins:

| MPR121 | Pi header |
| ------ | ---------- |
| VIN | pin 1 (3V3) |
| GND | pin 6 (GND) |
| SDA | pin 3 (GPIO 2) |
| SCL | pin 5 (GPIO 3) |
| ADDR | leave unconnected — that is what makes it 0x5a |
| IRQ | leave unconnected — the backend polls |

The pad itself is one wire from electrode **0** to a plate or a length of
copper tape; electrode 0 is what `sensor.touch_channel = 0` means.

Then the software half, which is one command:

```bash
motion-player-sensor --fit
```

Enables the I²C bus, installs `i2c-tools` and the MPR121 driver, and writes the
pad's three settings — `sensor_type = capacitive`, `engaged_when = closed`,
`i2c_address = 0x5a`. Those move together or the piece breaks quietly: a pad
left on `open` runs whenever nobody is touching it, and `0x29` is the
range-finder's address, not the pad's. Every step is skipped when it is already
done, so running `--fit` twice is safe. If it had to turn the bus on, reboot
and run it again — `/dev/i2c-1` only appears after a restart.

The driver is `adafruit-circuitpython-mpr121`, installed with pip into the
system python because neither it nor Blinka is packaged for apt — which is also
why the `.deb` cannot depend on them. Without them a correctly wired pad still
does nothing: the backend fails to start and the engine falls back to the
keyboard.

### Is the sensor real yet?

```bash
motion-player-sensor --report
```

Reads the config and the engine's own log and answers, in one place, what has
otherwise been checked by hand: what the sensor is configured as, whether the
hardware answers (`i2cdetect` for a touch pad, a GPIO read for anything else),
how long a visitor must keep contact to reach the forward turn, and two
verdicts — whether a lift has **ever** been accepted from real hardware, and
whether the rewind has **ever** run end to end. It changes nothing and is safe
to run during the show.

The hold figure is the one to look at first. It is the rewind's length, so
under `reverse_rate = fit_to_audio` it is the length of the audio. Thirty
seconds is an invitation; three minutes is an endurance test, and the report
says so. Raising `playback.reverse_rate` above 1.0 shortens the rewind without
touching the sound.

```bash
motion-player-sensor --probe
```

Watches the sensor live with the engine stopped — it holds the GPIO while it
runs — and prints every contact and release **with the hold time**, then
restarts the engine when you quit. The hold time is the point: a pad reporting
holds of a few milliseconds is sending taps, not continuous contact, and the
piece needs contact held for the whole rewind. A TTP223-style pad must be in
direct mode, not toggle, or letting go becomes a second tap.

---

## Config

Lives at `/etc/motion-player/config.ini`, root-owned, preserved across package
upgrades.

```bash
sudo nano /etc/motion-player/config.ini
```

Validate it and print every resolved value:

```bash
motion-player --check-config
```

This needs no display and takes no lock, so it is safe to run while the piece is
playing.

Look for `Config OK`. Missing media is reported as `media.video_file not
found: …`, naming the exact path it tried.

### Setups

Each showing of the piece — a gallery, a format, a screen — is a
configuration worth keeping. A **setup** is a named snapshot of the whole
config, stored in `~/memory-machine-media/setups/<name>.ini`. Because setups
live in the media folder, they travel with the content: copy the folder to
another Pi and its setups arrive with it.

The wizard opens by asking **which run this Pi plays** — every saved setup
is its own numbered option, alongside walking the questions, saving the
current config under a name, or duplicating one. Picking a name loads it
outright. Duplication as a workflow: load the setup,
walk the questions to tweak it, and save under the new name at the end (the
wizard offers exactly that after writing). The same operations exist
non-interactively:

```bash
motion-player-setup --save-setup vsdisplay-portrait
```

```bash
motion-player-setup --load-setup vsdisplay-portrait
```

```bash
motion-player-setup --list-setups
```

Loading is the same safe write as every wizard run: the previous config is
backed up beside itself, and validation runs immediately. A setup that names
renders this Pi does not have reports each missing file by exact path — build
them with `motion-player-prepare-all` and the setup plays.

### Every key

Generated from the shipped defaults, so it cannot drift — to change a
description, edit the comments in `config/config.default.ini` and run
`make docs-sync`:

<!-- config-reference:begin — generated from config/config.default.ini by scripts/check_docs.py --sync; edit the ini comments, not this block -->

### `[media]`

| Key | Default | What it is |
| --- | --- | --- |
| `video_file` | `piece.mp4` | Paths may be absolute or relative to ~/memory-machine-media/ |
| `audio_file` | `piece.wav` | — |
| `reverse_file` | `piece.reverse.mp4` | Pre-reversed copy of video_file, built by motion-player-reverse. The rewind plays this forward so no frame is ever seeked to. |
| `cuts` | `*(empty)*` | Optional alternative cuts of the same piece, framed for different screen shapes. The one closest in shape to the attached screen is used; video_file above is the fallback. Each needs its own reversed copy, named the same way motion-player-reverse writes it (piece_portrait.mp4 -> piece_portrait.reverse.mp4). |
| `kaleidoscope_file` | `*(empty)*` | The kaleidoscope twin of the render — built by motion-player-prepare --fx kaleidoscope, or by motion-player-prepare-all's *-kaleido profiles. The gamepad switches the picture between the plain render and this one; leave it empty and that button does nothing. |
| `kaleidoscope_cuts` | `*(empty)*` | Twins of the cuts above, matched to the screen the same way. One per cut, each needing its own reversed copy. |

### `[playback]`

| Key | Default | What it is |
| --- | --- | --- |
| `idle_mode` | `hold_first_frame` | idle_mode: hold_first_frame \| loop_forward \| black |
| `reverse_rate` | `native` | reverse_rate: native \| fit_to_audio \| <float multiplier> |
| `on_rewind_end` | `resume_forward` | on_rewind_end: what happens when the rewind reaches the beginning while the visitor is still listening. resume_forward  the piece turns and plays forward — the reward for staying present (default) hold            the screen goes black and the audio fades with it loop_reverse    the rewind starts over from the end |
| `scaling` | `fit` | scaling: fit \| fill \| stretch — how the frame meets a screen of a different shape. fit keeps all of it and pads with black, fill covers the screen and crops the overflow, stretch distorts to fill. |
| `fullscreen` | `true` | — |
| `display` | `auto` | display: auto \| HDMI-A-1 \| HDMI-A-2 (which connector to drive) |
| `display_mode` | `auto` | display_mode: auto \| 1920x1080@60 — pinned on every start, so a screen that was off at boot cannot leave the output negotiated to something else. |

### `[audio]`

| Key | Default | What it is |
| --- | --- | --- |
| `audio_sink` | `USB` | ALSA/PipeWire device NAME, not index. Matched exactly first, then as a substring, so "USB" pins the USB adapter whatever its full model string is. "auto" takes the first non-HDMI output instead. Pinned rather than auto so the sound can never wander to a screen's speakers. |
| `volume` | `0.8` | Fixed volume, 0.0–1.0. Staff cannot change this at runtime. |
| `fade_out_ms` | `400` | Fade-out length when the sensor is released. Unused when audio_mode = always. |
| `on_audio_end` | `silence` | on_audio_end: silence \| loop |
| `audio_mode` | `always` | audio_mode: always \| on_lift — whether the sound is tied to the sensor. always   the sound loops continuously from boot and the sensor drives only the picture on_lift  the sound starts when the sensor engages and fades when it is released — the piece's original headphone behaviour |

### `[lcd]`

| Key | Default | What it is |
| --- | --- | --- |
| `enabled` | `false` | An optional 20x4 character LCD on I2C showing a beating heart and health figures. The heart quickens while a visitor is engaged with the piece. |
| `i2c_bus` | `1` | — |
| `i2c_address` | `0x27` | — |
| `idle_bpm` | `60` | — |
| `engaged_bpm` | `100` | — |
| `sleep_bpm` | `0` | Heart rate while asleep; 0 = a still heart. |
| `layout` | `status` | layout: status \| art \| show \| instructions. status is the readout — icon, title, state word, health figures. art is the panel as a small artwork: the icon centered with stars twinkling around it, no text at all — the choice for a portrait-mounted panel, where ROM text would lie sideways. show keeps the title always up over the centered beating icon, with stars whose energy follows the piece's state — calm at rest, lively while someone holds on, every star lit for the wake-up hello. instructions turns the panel into the visitor's rotating instruction card — see [lcd2], the second panel it was made for. |
| `title` | `Memory<>Machine` | The panel's voice — printable ASCII only, up to 18 columns each. A key left empty on purpose (title =) means blank, not the default. |
| `label_idle` | `at rest` | — |
| `label_engaged` | `holding on` | — |
| `label_reward` | `I see you` | Spoken when a visitor stays through the whole rewind and the piece turns forward — the reward for staying present. |
| `label_hello` | `hello` | — |
| `label_sleep` | `goodnight` | — |
| `label_goodbye` | `goodbye` | — |
| `icon` | `heart` | icon: heart \| star \| ring \| note \| eye \| none — the beating glyph beside the title — or the name of a pixel-art file at ~/memory-machine-media/icons/<name>.txt (up to 10x16 pixels; see COMMANDS.md). |
| `icon_full` | `*(empty)*` | Or draw your own 5x8 icon: 8 comma-separated row values 0-31, top to bottom (each row is 5 bits, e.g. 0,10,31,31,31,14,4,0 is the heart). Set both — the full shape and the relaxed one it beats against. |
| `icon_small` | `*(empty)*` | — |

### `[lcd2]`

| Key | Default | What it is |
| --- | --- | --- |
| `enabled` | `false` | A second 20x4 panel — the visitor's instruction card, distilled from CONTROLLER.md. It rides the Pi 5's second hardware I2C bus so both backpacks keep their factory 0x27 address — add dtoverlay=i2c3-pi5,pins_22_23 to /boot/firmware/config.txt (SDA on GPIO 22 / physical pin 15, SCL on GPIO 23 / pin 16) and reboot. Every [lcd] key works here too — icon, bpm, labels, layout — and it goes dark overnight with the rest of the piece. |
| `i2c_bus` | `3` | — |
| `i2c_address` | `0x27` | — |
| `layout` | `instructions` | — |
| `page_seconds` | `6` | Seconds each instruction page stays up before the deck turns. |
| `page_1` | `*(empty)*` | The pages, page_1 .. page_6. Up to four lines per page separated by \|, each up to 20 printable ASCII columns. Left empty, the shipped deck speaks: her name on every page, the controls in the operator's words — HOLD START, A or B, ARROWS — and hers underneath. |
| `page_2` | `*(empty)*` | — |
| `page_3` | `*(empty)*` | — |
| `page_4` | `*(empty)*` | — |
| `page_5` | `*(empty)*` | — |
| `page_6` | `*(empty)*` | — |

### `[sensor]`

| Key | Default | What it is |
| --- | --- | --- |
| `sensor_type` | `gamepad` | sensor_type: gamepad \| switch \| reed \| beam \| reflective \| capacitive \| distance \| hall \| pir \| mmwave \| gpio_raw \| keyboard \| none "none" means no sensor is fitted: the piece loops forward and never rewinds. May be a fused list, e.g. switch+beam. |
| `sensor_combine` | `any` | sensor_combine: any \| all  (used only when fusing multiple sensors) |
| `engaged_when` | `closed` | engaged_when: open \| closed — which raw electrical state means "lifted". A held button and a touch pad are engaged when their contact CLOSES; a cradle switch is lifted when its contact OPENS. Change this whenever sensor_type changes. |
| `gpio_pin` | `4` | --- digital backends: switch, reed, beam, reflective, hall, pir, gpio_raw --- |
| `pull_up` | `true` | — |
| `trigger_pin` | `23` | --- distance backends --- |
| `echo_pin` | `24` | — |
| `threshold_cm` | `15` | — |
| `i2c_address` | `0x5a` | --- i2c backends: capacitive (MPR121, 0x5a) and distance (VL53L0X, 0x29) --- One key, read by whichever backend sensor_type names, so it has to match the sensor in use. Leave it unset and each backend falls back to its own default. |
| `touch_channel` | `0` | --- capacitive --- |
| `gamepad_device` | `auto` | --- gamepad --- A USB game controller, read straight from the kernel's joystick device. "auto" takes the first pad plugged in; name one (/dev/input/js1) to pin it when there are two. |
| `bounce_time_ms` | `50` | --- timing, all backends --- First-level hardware/library debounce (ms). |
| `min_lift_ms` | `250` | How long a raw state must persist before it is accepted (ms). |
| `min_replace_ms` | `250` | — |
| `max_engaged_minutes` | `30` | Force back to idle if engaged this long (minutes). |

### `[gamepad]`

| Key | Default | What it is |
| --- | --- | --- |
| `a` | `1` | A USB game controller has more than one control, and each can do a job. The numbers below are what this pad reports for each button — motion-player-sensor --probe prints the number of whatever you press, and these are the usual values for NES-style USB pads. |
| `b` | `0` | — |
| `select` | `2` | — |
| `start` | `3` | — |
| `up` | `*(empty)*` | The four arrows are axes on most pads and need no numbers. If --probe shows them as buttons on yours, give their numbers here. |
| `down` | `*(empty)*` | — |
| `left` | `*(empty)*` | — |
| `right` | `*(empty)*` | — |
| `hold` | `start+select` | What the controls do. Names: a, b, select, start, up, down, left, right — joined with + for more than one, empty to switch the job off. hold          held to wind the piece back: the interaction itself. "any" means any button, which suits a pad that does nothing else. kaleidoscope  switches the picture between the plain render and its kaleidoscope twin (see media.kaleidoscope_file). |
| `kaleidoscope` | `a+b` | — |
| `audio_up` | `*(empty)*` | One sound per arrow, chosen live while the piece runs. Paths as in [media]; an empty one means that arrow changes nothing. |
| `audio_down` | `*(empty)*` | — |
| `audio_left` | `*(empty)*` | — |
| `audio_right` | `*(empty)*` | — |

### `[schedule]`

| Key | Default | What it is |
| --- | --- | --- |
| `enabled` | `false` | Sleep the piece overnight: screens black, audio silent, sensor ignored, LCD dark with a "goodnight". Times are HH:MM local; a window may span midnight (23:00 to 08:00). start == end disables the window. |
| `sleep_start` | `00:00` | — |
| `sleep_end` | `08:00` | — |

### `[system]`

| Key | Default | What it is |
| --- | --- | --- |
| `mode` | `production` | mode: production \| test. Test runs keep their logs to themselves; only production heartbeats carry log tails to the telemetry endpoint, and only while the piece is awake. |
| `log_level` | `info` | — |
| `exit_after_s` | `0` | Stop cleanly after this many seconds; 0 = run forever. Soak tests only — leave at 0 for a show. |
| `log_max_mb` | `20` | — |
| `restart_on_crash` | `true` | — |

### `[telemetry]`

| Key | Default | What it is |
| --- | --- | --- |
| `enabled` | `false` | Send HTTP POSTs to a remote endpoint for monitoring. Only http:// and https:// URLs are accepted. |
| `endpoint_url` | `https://lab.thetechmargin.com/memorymachine/api/telemetry` | — |
| `interval_s` | `60` | — |
| `batch_size` | `10` | — |
| `timeout_s` | `5` | — |
| `log_tail_lines` | `20` | — |

<!-- config-reference:end -->

---

## Testing without the sensor

Stop the service first — the engine takes a single-instance lock:

```bash
motion-player-toggle --stop
```

Make a throwaway config using the keyboard backend, windowed so the log stays
visible:

```bash
cp /etc/motion-player/config.ini /tmp/test.ini && sed -i -e 's/^sensor_type.*/sensor_type = keyboard/' -e 's/^fullscreen.*/fullscreen = false/' /tmp/test.ini
```

```bash
python3 /opt/motion-player/motion_test.py --verbose --config /tmp/test.ini
```

If no sensor is fitted at all, set `sensor_type = none` in the config. The piece
then loops forward continuously and never rewinds — no sensor, no audio, no
reverse, just the footage playing.

`q` and `Esc` quit from any sensor backend now, so you no longer depend on the
keyboard sensor to get out of fullscreen. Click the video window to focus it,
then:

| Key | Effect |
| --- | --- |
| `space` | toggle lift / replace |
| `d` | dump the status snapshot to the log |
| `q` or `Esc` | quit |

Keys are read through the OpenCV window, not the terminal — a focused terminal
swallows them. Run it from the Pi's own desktop session; over SSH the window
has nowhere to draw.

Restore normal operation:

```bash
motion-player-toggle --start
```

---

## Updating

One command does everything: fetch, rebuild, reinstall, restart. It clones the
checkout first if there isn't one, so it works on a Pi that was installed
straight from a `.deb`:

```bash
motion-player-update
```

There is also an **Update** action on the right-click menu of the
**memory-machine** desktop icon, for updating without a terminal.

Ask whether anything is waiting, without changing a thing:

```bash
motion-player-update --check
```

Discard local edits to the checkout and update regardless:

```bash
motion-player-update --force
```

If the service fails to stay up after an update, the previous package is
reinstalled automatically and the piece keeps running on it. Every run is
recorded:

```bash
tail -20 ~/.local/state/motion-player/update.log
```

### Nightly automatic updates

```bash
motion-player-update --enable-auto
```

That enables a timer that runs at 04:30 with a randomised delay, well outside
gallery hours. An update is skipped if someone is mid-piece, and retried on the
next run. To stop:

```bash
motion-player-update --disable-auto
```

Unattended runs still need to install a package, which needs root. That is done
by `motion-player-install-deb`, which takes no arguments so it can hold a single
fixed rule rather than a wildcard over `apt`. The command prints the one-line
`sudoers` rule to allow that without a password — it grants
this account passwordless root for the install helper, which is effectively root
access, so it is opt-in. Without it the timer will fetch and build but fail at
the install step; use the menu's **Update** action instead if you would rather
approve each upgrade.

---

## Development **(laptop)**

```bash
make lint
```

```bash
make check
```

```bash
make deb
```

```bash
make release
```

```bash
make install
```

```bash
make clean
```

Render this document as the published Field Manual page:

```bash
make manual
```

That writes `build/field-manual.html`. The published page is a copy of this
file rather than a rendering of it, so it drifts until someone regenerates it —
this is how.

---

## Troubleshooting

**Files on a network share don't appear.** The file manager caches directory
listings. Refresh with `Ctrl+R`, then confirm what the server is actually
offering:

```bash
smbclient //HOST/SHARE -U USER -c 'ls'
```

**Playback is slow or stuttering.** Check that the reversed clip is present and
matches the source; a mismatch is logged at startup:

```bash
grep -E "Video loaded|Reverse clip" ~/.local/state/motion-player/motion-player.log | tail -5
```

**One screen is black, or every screen dropped to a lower resolution.** The
splitter is choosing the mode. Force it in `/boot/firmware/cmdline.txt` as
above, then check what the Pi settled on:

```bash
wlr-randr
```

**`motion-player-update` says "already up to date" but the fix is not there.**
It compares the installed package against what the checkout would build, so a
checkout that pulled without installing — a previous run that failed, or a
rollback — is detected and rebuilt. If it still insists, confirm the two agree:

```bash
dpkg-query -W -f='${Version}\n' motion-player; cd ~/memory-machine && echo "$(tr -d '[:space:]' < VERSION)~git$(git rev-list --count HEAD).$(git rev-parse --short HEAD)"
```

`motion-player-update --force` rebuilds and reinstalls regardless.

**apt refuses to do anything: "dpkg was interrupted".** An install that was
killed partway leaves packages half-configured, and every later apt call refuses
until that is cleared. The updater now detects and clears it before installing,
but to do it by hand:

```bash
sudo dpkg --configure -a
```

Note the `-a` — `dpkg --configure -` is a different, invalid command.

**The service won't stay up after an update.** The updater now appends the
`systemctl` status and the tail of the engine log to `update.log`, so the reason
should be right there:

```bash
tail -40 ~/.local/state/motion-player/update.log
```

A state of `activating` means it is restarting in a loop — it exited immediately
after starting. The most common cause is a leftover copy from a foreground run
holding the instance lock:

```bash
pgrep -af motion_test.py
```

Kill it, then start the service again. After five failures in two minutes the
unit stops retrying and lands in `failed`, which is deliberate: a silent restart
loop hides the problem.

**A command appears to do nothing.** The launcher redirects output to the log
unless `--verbose` is the first argument. Read the log, or call
`python3 /opt/motion-player/motion_test.py` directly.

**Is the sensor itself wired and working?**

```bash
motion-player-sensor --probe
```

It stops the engine (which holds the GPIO), watches whichever backend the
config names, prints every contact and release with its hold time, and restarts
the engine when you quit. It also runs from your home directory for you — lgpio
writes its FIFOs to the working directory, so probing from a read-only one
fails with a bare `.lgd-nfy` error that says nothing about the real cause.

No output at all on contact means the wiring, the pin or address, or the sensor
itself. Holds of a few milliseconds mean it is sending taps rather than
continuous contact, which the piece cannot use.

**Touching the sensor does nothing, and the log mentions `.lgd-nfy`.**
lgpio creates its notification FIFOs in the process's working directory, so a
read-only one makes every GPIO backend fail — reported as a bare
`[Errno 2] No such file or directory: '.lgd-nfy-3'`, or as `BadPinFactory` if
the underlying error is swallowed. The engine now runs from its state directory
for exactly this reason. If you invoke it by hand, do so from somewhere
writable:

```bash
cd ~ && python3 /opt/motion-player/motion_test.py --verbose
```

**Touching the sensor does nothing, and the log says `BadPinFactory`.**
gpiozero could not load a GPIO backend, so there is no sensor. The piece keeps
running: it loops forward instead of holding a still frame, and `space` still
triggers a rewind by hand while you sort the hardware out. A still frame would
read as a broken installation to a visitor; a loop does not.

Reproduce the failure in the same environment the service runs in, which is not
the same as your shell:

```bash
systemd-run --user --pipe --wait python3 -c "from gpiozero import Device; Device.ensure_pin_factory(); print(Device.pin_factory)"
```

```bash
id -nG; ls -l /dev/gpiochip*
```
 Check which backend gpiozero finds:

```bash
python3 -c "from gpiozero import Device; Device.ensure_pin_factory(); print(Device.pin_factory)"
```

If that raises, install the backend and confirm this account may reach the GPIO
character devices:

```bash
sudo apt install -y python3-lgpio
```

```bash
ls -l /dev/gpiochip*; id -nG | tr ' ' '\n' | grep -qx gpio && echo "in the gpio group" || echo "NOT in the gpio group"
```

Adding yourself to the group needs a fresh login to take effect:
`sudo usermod -aG gpio "$USER"`.

**The picture looks stretched, or has black bars.** `playback.scaling` decides
how a frame meets a screen of a different shape:

| scaling | Behaviour |
| --- | --- |
| `fit` | keeps the whole frame and pads the rest with black (default) |
| `fill` | covers the screen and crops whatever overflows |
| `stretch` | distorts the frame to fill the screen |

A 1280x1280 square piece on a 1920x1080 screen shows as a 1080x1080 square with
420px black bars under `fit`, or covers the screen under `fill` by cropping the
top and bottom 280px. `stretch` was the old behaviour and makes everything 1.5x
too wide. Check what the engine is working with:

```bash
grep -E "Video loaded|Output surface" ~/.local/state/motion-player/motion-player.log | tail -2
```

**The audio keeps playing after the picture stops.** It no longer can — playback
is capped to the length of the rewind, and `on_rewind_end = hold` fades the sound
out with the picture. If the audio is much longer than the footage you are
throwing most of it away, which may not be the intent; `reverse_rate =
fit_to_audio` stretches the rewind across the whole audio instead. Compare the
two durations:

```bash
grep -E "Audio loaded|Video loaded|playback will stop" ~/.local/state/motion-player/motion-player.log | tail -3
```

**No audio.** Confirm the mixer opened and which sink it picked:

```bash
grep -E "Audio mixer|Audio loaded|sink" ~/.local/state/motion-player/motion-player.log | tail -5
```

Pin a specific device by setting `audio_sink` in the config to a name from:

```bash
python3 -c "import pygame; pygame.mixer.init(); from pygame._sdl2.audio import get_audio_device_names as n; print(n(False))"
```
