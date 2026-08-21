#!/usr/bin/env bash
# One-time setup on the Raspberry Pi for memory-machine.
set -euo pipefail

REPO_DIR="${1:-$HOME/memory-machine}"
MEDIA_DIR="$HOME/memory-machine-media"

echo "Bootstrapping memory-machine in $REPO_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning repository..."
    git clone git@github.com:binaryLady/memory-machine.git "$REPO_DIR"
fi

cd "$REPO_DIR"

# Optional: locate an existing flat motion_test.py and archive it, but never
# overwrite the refactored engine shipped by the repo.
LEGACY=$(find ~/Desktop ~ ~/Documents ~/Videos /home/pi -maxdepth 3 -name 'motion_test.py' -not -path '*/.*' -print -quit 2>/dev/null || true)
if [ -n "$LEGACY" ] && [ "$LEGACY" != "$REPO_DIR/src/motion_test.py" ]; then
    echo "Found legacy $LEGACY; archiving to $REPO_DIR/legacy_motion_test.py"
    cp "$LEGACY" "$REPO_DIR/legacy_motion_test.py"
fi

# Create a simple A/V directory in the user's home for drag-and-drop media swaps.
mkdir -p "$MEDIA_DIR"

# Install build and runtime dependencies.
sudo apt-get update
sudo apt-get install -y dpkg-dev python3 python3-pip ffmpeg zenity xdg-utils unclutter libnotify-bin i2c-tools git
# One at a time: a single unavailable package must not skip the rest, and a
# missing GPIO backend is worth saying out loud rather than swallowing.
for pkg in python3-opencv python3-gpiozero python3-lgpio python3-pygame; do
    sudo apt-get install -y "$pkg" || echo "WARNING: could not install $pkg"
done

# The shipped sensor is a capacitive pad on I2C, so the bus has to be on and
# the MPR121 driver present. Neither Blinka nor the driver is packaged for apt,
# which is why this is pip and not a dependency of the deb — and without them a
# correctly wired pad still does nothing: the backend cannot start and the
# engine falls back to the keyboard. --break-system-packages is what Debian
# trixie needs; the plain form is the fallback for an older pip.
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_i2c 0 || echo "WARNING: could not enable I2C"
fi
sudo pip3 install --break-system-packages adafruit-circuitpython-mpr121 \
    || sudo pip3 install adafruit-circuitpython-mpr121 \
    || echo "WARNING: no MPR121 driver; run motion-player-sensor --fit"

# Build and install the package.
make release
DEB="$(ls -t ./motion-player_*.deb | head -n1)"
sudo apt-get install -y "$DEB"

# Enable linger so the user service can start before login.
loginctl enable-linger "$USER"

# Enable and start the user service.
systemctl --user daemon-reload
systemctl --user enable motion-player.service
systemctl --user start motion-player.service

echo "Bootstrap complete."
echo "Place your media in $MEDIA_DIR/ (there is a desktop shortcut called memory-machine-media)."
echo "Restart the service if needed: systemctl --user restart motion-player.service"
