# memory-machine — gallery card

## Normal operation

1. Plug in the Raspberry Pi power.
2. Wait about 30 seconds. The screen should show a still frame from the piece.
3. Lift the headphones from the stand. Sound begins in the headphones and the
   image on the wall plays in reverse.
4. Put the headphones back. The sound fades, then stops, and the image returns
   to the still frame.

## Start and stop from the desktop

If the Pi is on the desktop instead of auto-starting, double-click the
**memory-machine** icon to start the piece. Click it again to stop.

You can also right-click the icon and choose **Start** or **Stop**.

## Update the video and audio files

1. Right-click the **memory-machine** icon and choose **Stop**.
2. Open the **memory-machine-media** shortcut on the desktop (or right-click the
   **memory-machine** icon and choose **Open media folder**).
3. Replace `piece.mp4` and `piece.wav` by dragging in the new files.
4. Right-click the **memory-machine** icon and choose **Start**.

If the files have different names, a technician will need to edit
`/etc/motion-player/config.ini`.

## If the screen is black

1. Wait 30 seconds after plugging in — the Pi needs time to boot.
2. If it is still black, unplug the power, wait 5 seconds, and plug it back in.
3. If it stays black, check that the small sensor under the headphone stand
   is connected and nothing is pressing on it.

## Do not

- Change any files, settings, or cables except the power cable.
- Open a terminal or move the mouse/keyboard.
- Turn off the monitor; only remove power from the Pi.

## Contact

If the piece is not responding after a power cycle, contact:

**TheTechMargin**
Sonia Cook-Broen — sonia@thetechmargin.com

---

## Technician's appendix

- Sensor type wired: **\*\*\*\***\_\_\_**\*\*\*\***
- GPIO pin: **\*\*\*\***\_\_\_**\*\*\*\***
- The sensor at the headphone stand is the only hardware to check if lifts are
  not detected.
