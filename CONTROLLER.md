# The controller

The piece is played with an NES-style USB controller — beige, two buttons,
four arrows, a 1.4m cable. Everything it can do is here; nothing it can do
breaks the piece.

```text
   ┌──────────────────────────────────────────────────────────┐
   │                     memory-machine                       │
   │      ┌───┐                                               │
   │      │ ▲ │                                               │
   │   ┌──┘   └──┐      ╔══════╗  ╔══════╗       ╭───╮ ╭───╮  │
   │   │ ◀     ▶ │      ║SELECT║  ║START ║       │ B │ │ A │  │
   │   └──┐   ┌──┘      ╚══════╝  ╚══════╝       ╰───╯ ╰───╯  │
   │      │ ▼ │                                               │
   │      └───┘                                               │
   └──────────────────────────────────────────────────────────┘
        arrows            hold either one         either one:
     change the sound       to rewind            kaleidoscope
```

## Hold — Start or Select

**Hold the button down and the piece plays in reverse.** This is the whole
interaction. Keep holding and the image winds further and further back; let go
and it returns to its resting frame. The sound never stops either way.

Stay all the way through the rewind — hold on until the image reaches its very
beginning — and the piece turns and plays forward. That is the reward for
staying present. It cannot be reached by tapping; only by holding on.

## Kaleidoscope — A or B

**One press turns the picture into a kaleidoscope. Another turns it back.**
The piece keeps its place: if it was three quarters of the way through the
rewind, it stays three quarters of the way through, in the other picture.
Works while resting, while rewinding, any time.

## Sound — the arrows

**The arrows turn through her sounds.** Right or down moves to the next one,
left or up to the one before; the piece keeps playing under the new
accompaniment — same picture, same place, new sound — and the deck wraps round
at either end. Every sound in the media folder is in the deck. (With only one
sound there, the arrows do nothing.)

## Nothing to get wrong

- Press anything in any order — no combination stops the piece.
- Buttons only do things while the piece is awake; asleep overnight it
  ignores the controller entirely.
- If the controller is unplugged mid-hold, the piece simply lets go — plug it
  back in and it works again straight away, no restart.

## For the technician

| Control | Job | Config |
| --- | --- | --- |
| Start, Select | hold to rewind | `[gamepad] hold = start+select` |
| A, B | kaleidoscope on/off | `[gamepad] kaleidoscope = a+b` |
| ▶ ▼ / ◀ ▲ | next sound / previous sound | `[gamepad] audio_next = right+down`, `audio_prev = left+up` |

The pad reports buttons as numbers and pads disagree about which is which.
The shipped numbers are `a = 1`, `b = 0`, `select = 2`, `start = 3`. To check
this pad, stop-and-watch it live:

```bash
motion-player-sensor --probe
```

It prints the name, number and job of everything pressed. If the names are
wrong, correct the four numbers in `[gamepad]` — every job follows the name,
so fixing the numbers once fixes everything. Full detail in COMMANDS.md.
