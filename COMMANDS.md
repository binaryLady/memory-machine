# memory-machine command reference

Everything you need to run, inspect, and change the installation. Commands run
on the Pi unless marked **(laptop)**.

---

## Every command at a glance

| Command | Flags | What it does |
| --- | --- | --- |
| `motion-player-toggle` | `--start` `--stop` | start or stop the piece; bare call toggles |
| `motion-player-setup` | `--set section.key=value` | guided configuration: screen shape, sensor, audio output, forward reward, heartbeat panel, sleep, telemetry, run mode; `--set` writes values directly, no questions |
| `motion-player-status` | `--json` `--watch` | state, sensor, health figures, last error, resolved config |
| `motion-player-update` | `--check` `--force` `--auto` `--enable-auto` `--disable-auto` | fetch, rebuild, reinstall, restart; rolls back if the service does not stay up |
| `motion-player-prepare` | `[SRC]` `--size WxH` `--mode fit\|fill\|tile` `--force` `--apply` `--no-apply` | render a cut at the screen's resolution, build its reverse, and offer to point the config at it; run per cut |
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
It shows what screen is attached, then walks through the shape, the sensor, the
audio output, the forward reward, the heartbeat panel, the sleep hours,
telemetry and gallery-vs-test mode — writing the config and offering a restart
at the end:

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
forward, so a cut without one goes black the moment the headphones are lifted.
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

Those three are mechanical. Anything compositional — a different framing, a
deliberate arrangement, motion that responds to the shape — belongs in an editor.
Prepare the file however you like and hand the result to `motion-player-reverse`,
which builds the reversed copy from whatever you give it.

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

**A rotated screen must use the `video_file` flow, not `cuts`.** Cut selection sizes
the screen from the pinned `display_mode`, which is the physical mode — a
landscape panel mounted portrait behind a compositor transform still reads as
landscape, so the chooser would score the portrait cut as the wrong shape.
`video_file` names the clip outright and nothing second-guesses it. The setup
wizard's printed prepare hint has the same blind spot: it uses the detected
physical mode, so on a rotated panel ignore that one line and pass `--size`
with the rotated (logical) resolution yourself.

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
installation's health. The heart beats slowly at rest and quickens while the
headphones are lifted, so the panel reports the state of the piece rather than
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

The heart beats at `idle_bpm` at rest and `engaged_bpm` while someone listens;
overnight it slows to `sleep_bpm` — 0 holds it still — while the backlight goes
dark and the panel says goodnight. It says hello for a few seconds at wake, and
goodbye when the piece shuts down.

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

---

## Testing without the headphone sensor

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

**Is the switch itself wired and working?** Probe the physical switch directly,
with no engine in the way. Stop the service first (the engine holds the GPIO),
then run this from your home directory — lgpio writes its FIFOs to the working
directory, so a read-only one fails:

```bash
motion-player-toggle --stop
```

```bash
cd ~ && python3 - <<'EOF'
from gpiozero import Button
from signal import pause
b = Button(4, pull_up=True, bounce_time=0.05)
print("watching GPIO 4 — flip the switch; Ctrl+C to stop")
print("now:", "pressed (headphones down)" if b.is_pressed else "released (headphones lifted)")
b.when_pressed = lambda: print("pressed  (headphones down)")
b.when_released = lambda: print("released (headphones lifted)")
pause()
EOF
```

`pull_up=True` and the 50ms bounce match what the engine's `switch` backend
uses, so a switch that prints cleanly here will work in the piece. No output on
flips means the wiring, the pin number, or the switch itself. Restore with
`motion-player-toggle --start`.

**Lifting the headphones does nothing, and the log mentions `.lgd-nfy`.**
lgpio creates its notification FIFOs in the process's working directory, so a
read-only one makes every GPIO backend fail — reported as a bare
`[Errno 2] No such file or directory: '.lgd-nfy-3'`, or as `BadPinFactory` if
the underlying error is swallowed. The engine now runs from its state directory
for exactly this reason. If you invoke it by hand, do so from somewhere
writable:

```bash
cd ~ && python3 /opt/motion-player/motion_test.py --verbose
```

**Lifting the headphones does nothing, and the log says `BadPinFactory`.**
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
