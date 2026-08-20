# Handoff — memory-machine

_Last updated 2026-08-19, end of a long shore-up session. Everything below is
current as of main @ e0864de (PR #50)._

## What this is

A gallery installation: lift the headphones and the video plays in reverse
while the audio plays forward; stay through the whole rewind and the piece
turns and plays forward (the reward). Runs on a Raspberry Pi named `rhubarb`
(user `binarylady`, Debian trixie) for a month-long show. Several screens
mounted on iridescent acrylic with LED edge lighting; audio through one jack
via USB adapter into a headphone splitter feeding two headphones on one
cradle with one switch.

Repo builds the `motion-player` Debian package. `COMMANDS.md` is the operator
reference (rendered as a live page via `make manual`; published copy also on
Notion, which drifts).

## Where things stand

**Working, verified on the Pi:**
- Playback engine: pre-rendered reverse clips (never seeks per frame), idle
  costs ~0ms/frame, fullscreen recovers from unmapped windows.
- Sensor backend starts clean (lgpio; the fix was the working directory —
  lgpio writes FIFOs to cwd).
- `motion-player-update`: pull, build, install, restart, rollback; survives
  interrupted dpkg; visible sudo prompts.
- Telemetry, status.json (atomic, change-only writes), heartbeat LCD driver.

**Merged but NEVER verified on hardware (the important list):**
1. A physical lift. No switch has ever been wired and probed; the piece has
   only ever been triggered by spacebar. Probe: stop the service, run the
   gpiozero Button snippet in COMMANDS.md troubleshooting from `~`.
2. A `Playback REVERSE` timing line. The rewind — the point of the piece —
   has never been measured end to end.
3. Any physical screen. All viewing so far was Pi Connect's virtual desktop.
   TekGroAml 4" (720x720, micro-HDMI, needs 5V USB power) lacked a cable;
   VSDISPLAY 10.1" (1280x800 HDMI) was arriving; two DSI panels (LUCKFOX 8"
   800x1280 portrait, Hosyond 5" 800x480) need dtoverlay lines — COMMANDS.md
   deliberately carries none (the overlay depends on the panel; use the line
   the vendor specifies).
4. Audio through the USB adapter + splitter + headphones. `audio_sink` is
   still `auto` on the Pi; pin it (wizard step ③b does this).
5. Sleep/wake, the LCD panel (never wired; it's a 20x4 I2C at 0x27), the
   forward-reward turn, the setup wizard itself, any soak run.

**The Pi's config lags the new defaults**: `/etc/motion-player/config.ini`
says `on_rewind_end = hold` explicitly (conffile refreshed during an update),
so the forward reward needs one edit or a wizard run. `[schedule]` is absent
from the Pi's /etc file (it exists in the shipped defaults with
`enabled = false`, so scheduling is off either way — fine).

## The next session, in order

1. `motion-player-update` on the Pi, then `motion-player-setup` — the wizard
   walks every choice (screen shape, sensor, audio sink, reward, LCD, sleep,
   telemetry, mode). Enter-through-everything should leave the config
   byte-identical — compare content, not mtime: the wizard rewrites the file
   and drops a timestamped `.bak-` copy on every run. That's the smoke test.
2. The switch probe (COMMANDS.md troubleshooting) — until it passes, the
   sensor is decorative.
3. One real screen + `motion-player-prepare` at its exact resolution + the
   `Playback REVERSE` grep. This is the original question of the whole
   project and it is still unanswered.
4. Audio by ear: lift, fade on replace, and the turn into forward with sound
   uninterrupted (PR #44/#45 seam).
5. A soak: `system.exit_after_s=14400`, four hours, then read `throttled` in
   motion-player-status — heat is the show's only real tax.

## Open questions / deferred

- **Multi-screen with different content**: one Pi per screen shape, one
  switch wired in parallel to GPIO 4 on all Pis (common ground) — decided,
  not built. Audio should be optional on follower Pis (config requires an
  audio file today; small fix when needed).
- **LED edge lighting reacting to state** (brighten on lift?) — natural fit
  for the state machine, offered, not requested yet.
- **Lian Li 8.8" USB screen (1920x480)**: driveable only via
  sgtaziz/lian-li-linux + evdi, x86-only docs, software H.264 encode. Gate:
  does evdi-dkms build on the Pi kernel. Experiment, not a show screen.
  `--mode tile` exists for its shape (square repeated 4x).
- **20x4 LCD #2 and #3** (she has 3): second panel as audio timecode / lift
  tally was floated.
- GALLERY.md technician blanks (sensor type, GPIO pin) still unfilled.

## Hard-won lessons (also in memory files)

- **Get the Pi's log line before writing a fix.** Every guessed fix this
  session was wrong (codecs, XAUTHORITY, sys.path); every pasted log line
  solved it immediately. `grep -a` — the logs can contain control bytes.
- **lgpio writes FIFOs to the working directory.** Anything running the
  engine must cwd somewhere writable (launcher does; direct runs from ~).
- **Sonia's PR style: substantial, steady, never stacked.** Batch a feature
  area (code+tests+docs) per PR; she merges in minutes; stacked PRs stranded
  work twice (#27, #49). Memory file: memmac-big-prs.
- **Defaults must not change behaviour under an untouched conffile** — but
  note her /etc config has explicit values, so new defaults don't reach the
  Pi without an edit or wizard run.
- **`--verbose` must lead the args** for console output; `--check-config`,
  `--log`, `--help` are exempt (launcher fast-path).
- The mechanical docs audit (installed commands × README × COMMANDS.md ×
  config keys) catches real drift; run it after feature work.

## Artifacts

- Field Manual (live render of COMMANDS.md):
  https://claude.ai/code/artifact/f8d8aee9-9b65-4bb7-b40d-513dffc0fc58
  Regenerate: `make manual`, republish to that URL. Keep the 🎧 favicon.
- Notion copy of the old command reference — stale, superseded by the above.
