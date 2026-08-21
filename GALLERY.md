# memory-machine — gallery card

## Normal operation

1. Plug in the Raspberry Pi power.
2. Wait about 30 seconds. The sound begins on its own and plays continuously.
   The screen shows a still frame from the piece.
3. Touch and hold the pad. The image plays in reverse for as long as contact is
   held.
4. Let go. The image returns to the still frame. The sound keeps playing.

Staying in contact all the way through the reverse is the point: when it
reaches the beginning, the piece turns and plays forward.

## Start and stop from the desktop

If the Pi is on the desktop instead of auto-starting, double-click the
**memory-machine** icon to start the piece. Click it again to stop.

You can also right-click the icon and choose **Start** or **Stop**.

## Update the video and audio files

1. Right-click the **memory-machine** icon and choose **Stop**.
2. Open the **memory-machine-media** shortcut on the desktop (or right-click the
   **memory-machine** icon and choose **Open media folder**). If neither is
   there, the folder itself is `memory-machine-media` in the home folder.
3. Replace `piece.mp4` and `piece.wav` by dragging in the new files.
4. **Ask a technician to rebuild the reverse clip.** The piece plays a
   pre-rendered reversed copy of the video, and new footage needs a new one.
   Until that is done the image goes black when someone touches the pad.
5. Right-click the **memory-machine** icon and choose **Start**.

If the files have different names, a technician will need to edit
`/etc/motion-player/config.ini`.

## If the image loops on its own

If the video plays over and over with nobody touching the pad, the sensor is
not being detected. The piece keeps running deliberately so the wall is never
blank — but tell a technician, because touching the pad will do nothing until
it is fixed.

## If the screen is black

1. Wait 30 seconds after plugging in — the Pi needs time to boot.
2. If it is still black, unplug the power, wait 5 seconds, and plug it back in.
3. If it stays black, check that the touch pad's cable is connected and that
   nothing is resting on the pad.

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

- After swapping media, run `motion-player-prepare` (or `motion-player-reverse`)
  and restart the service.
- A black image only while the pad is held means the reverse clip is missing
  or stale.
- `motion-player-sensor --report` answers the rest: what the sensor is
  configured as, whether it answers, how long a visitor must hold on, and
  whether a touch and a reverse have ever actually been recorded. Fill the two
  lines below from it.
- Sensor type wired: **\*\*\*\***\_\_\_**\*\*\*\***
- GPIO pin / I2C address: **\*\*\*\***\_\_\_**\*\*\*\***
- The touch pad is the only hardware to check if contact is not detected.
