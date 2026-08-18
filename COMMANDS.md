# memory-machine command reference

Everything you need to run, inspect, and change the installation. Commands run
on the Pi unless marked **(laptop)**.

---

## Getting started

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

The piece needs three files in `~/memory-machine-media/`:

If no sensor is fitted at all, set `sensor_type = none` in the config. The piece
then loops forward continuously and never rewinds — no sensor, no audio, no
reverse, just the footage playing.

| File | What it is |
| --- | --- |
| `piece.mp4` | the footage, played forward |
| `piece.reverse.mp4` | pre-rendered reverse of the above, played during the rewind |
| `piece.wav` | the audio, played forward on lift |

Open the folder in the desktop file manager:

```bash
motion-player-media
```

Build the reversed companion clip after any change to the footage:

```bash
motion-player-reverse
```

Point it at other files, or tune the encode:

```bash
motion-player-reverse ~/memory-machine-media/other.mp4 ~/memory-machine-media/other.reverse.mp4
```

```bash
CRF=20 PRESET=veryfast SEGMENT_SECONDS=5 motion-player-reverse
```

Encoding is CPU-heavy. Running it on a laptop and copying the result over is
usually much faster than encoding on the Pi.

`.mp3` works anywhere `.wav` does — set `audio_file` in the config and the
engine loads it unchanged.

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

Then encode `piece.mp4` at exactly the forced mode, so the Pi does no scaling at
all. Do not master at 4K to serve a 4K screen: the splitter emits one mode
regardless, and 4K decode is what the Pi cannot sustain.

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

Unattended runs still need to install a package, which needs root. The command
prints the one-line `sudoers` rule to allow that without a password — it grants
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

**No audio.** Confirm the mixer opened and which sink it picked:

```bash
grep -E "Audio mixer|Audio loaded|sink" ~/.local/state/motion-player/motion-player.log | tail -5
```

Pin a specific device by setting `audio_sink` in the config to a name from:

```bash
python3 -c "import pygame; pygame.mixer.init(); from pygame._sdl2.audio import get_audio_device_names as n; print(n(False))"
```
