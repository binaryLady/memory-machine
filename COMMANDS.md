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
`--allow-downgrades` covers builds whose version string sorts below what is
already installed.

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

- **`--verbose` has to come first.** `motion-player --check-config` prints
  nothing, because the launcher redirects output to the log unless `--verbose`
  leads. Either put it first or call
  `python3 /opt/motion-player/motion_test.py` directly.
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
- **`motion-player-update` needs `~/memory-machine/.git`.** See Getting started
  above if it reports "Not running from a git checkout".
- **Never install with a bare `motion-player_*.deb` glob.** Stale builds in the
  repo root make apt pick between candidates and silently do nothing —
  `Installing: 0, Upgrading: 0`. Run `make clean` before `make release`.

---

## Media

The piece needs three files in `~/memory-machine-media/`:

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

See what mode the splitter is currently advertising. Mixed-resolution sinks make
splitters report either the lowest common mode or whatever they detected first,
which can quietly drop the whole install to 720p:

```bash
cat /sys/class/drm/card*-HDMI-A-1/modes | head -20
```

Don't trust that negotiation. Force the mode on the single existing line in
`/boot/firmware/cmdline.txt`:

```
video=HDMI-A-1:1920x1080@60D
```

Use `HDMI-A-2` if the splitter is in the Pi's second port. The trailing `D`
forces the mode even when EDID disagrees and keeps the connector alive when a
screen is powered off — without it, switching a monitor off can blank or resize
the piece mid-show.

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

```bash
motion-player-toggle
```

```bash
motion-player-toggle --start
```

```bash
motion-player-toggle --stop
```

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

Validate it and print every resolved value. `--verbose` must come **first** —
the launcher only shows you output when it leads:

```bash
motion-player --verbose --check-config
```

Or bypass the launcher entirely:

```bash
python3 /opt/motion-player/motion_test.py --check-config
```

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

Click the video window to focus it, then:

| Key | Effect |
| --- | --- |
| `space` | toggle lift / replace |
| `d` | dump the status snapshot to the log |
| `q` | quit |

Keys are read through the OpenCV window, not the terminal — a focused terminal
swallows them. Run it from the Pi's own desktop session; over SSH the window
has nowhere to draw.

Restore normal operation:

```bash
motion-player-toggle --start
```

---

## Updating

```bash
motion-player-update
```

```bash
motion-player-update --check
```

```bash
motion-player-update --force
```

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

**A command appears to do nothing.** The launcher redirects output to the log
unless `--verbose` is the first argument. Read the log, or call
`python3 /opt/motion-player/motion_test.py` directly.

**No audio.** Confirm the mixer opened and which sink it picked:

```bash
grep -E "Audio mixer|Audio loaded|sink" ~/.local/state/motion-player/motion-player.log | tail -5
```

Pin a specific device by setting `audio_sink` in the config to a name from:

```bash
python3 -c "import pygame; pygame.mixer.init(); from pygame._sdl2.audio import get_audio_device_names as n; print(n(False))"
```
