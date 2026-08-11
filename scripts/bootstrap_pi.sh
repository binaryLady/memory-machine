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
sudo apt update
sudo apt install -y dpkg-dev python3 python3-pip zenity xdg-utils unclutter git
sudo apt install -y python3-opencv python3-gpiozero python3-lgpio python3-pygame || true

# Build and install the package.
make release
DEB="$(ls -t ./motion-player_*.deb | head -n1)"
sudo apt install -y "$DEB"

# Enable linger so the user service can start before login.
loginctl enable-linger "$USER"

# Enable and start the user service.
systemctl --user daemon-reload
systemctl --user enable motion-player.service
systemctl --user start motion-player.service

echo "Bootstrap complete."
echo "Place your media in $MEDIA_DIR/ (there is a desktop shortcut called memory-machine-media)."
echo "Restart the service if needed: systemctl --user restart motion-player.service"
