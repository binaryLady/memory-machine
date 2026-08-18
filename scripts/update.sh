#!/usr/bin/env bash
# motion-player-update: pull, rebuild, and reinstall.
set -euo pipefail

REPO="${MOTION_PLAYER_REPO:-$HOME/memory-machine}"
FORCE=0
CHECK=0

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --check) CHECK=1 ;;
    esac
done

if [ ! -d "$REPO/.git" ]; then
    echo "Not running from a git checkout. Install a newer .deb release instead."
    exit 0
fi

cd "$REPO"

if [ "$CHECK" = "1" ]; then
    git fetch --quiet
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse @{u})
    if [ "$LOCAL" = "$REMOTE" ]; then
        echo "Already up to date."
    else
        echo "Update available: $REMOTE"
    fi
    exit 0
fi

if [ "$FORCE" = "0" ] && ! git diff-index --quiet HEAD; then
    echo "Checkout has local changes. Use --force to discard, or commit them."
    exit 1
fi

systemctl --user stop motion-player.service >/dev/null 2>&1 || true

git pull --ff-only

make release
DEB="$(ls -t ./motion-player_*.deb | head -n1)"
sudo apt install --reinstall -y "$DEB"

systemctl --user daemon-reload
systemctl --user enable motion-player.service
systemctl --user start motion-player.service

echo "Updated and restarted."
