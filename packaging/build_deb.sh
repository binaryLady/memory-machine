#!/usr/bin/env bash
# Build the motion-player Debian package.
#
# Usage:
#   packaging/build_deb.sh              # development build (Recommends Pi libs)
#   STRICT_DEPS=1 packaging/build_deb.sh # release build (Depends on Pi libs)
set -euo pipefail

PKG="motion-player"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-$(cat "$REPO_ROOT/VERSION" | tr -d '[:space:]')}"
MAINTAINER="${MAINTAINER:-TheTechMargin <sonia@thetechmargin.com>}"
BUILD_ROOT="$(mktemp -d)"
STAGE="$BUILD_ROOT/$PKG"
OUTDIR="$REPO_ROOT"
trap 'rm -rf "$BUILD_ROOT"' EXIT

# Append git sha for untagged builds.
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if ! git -C "$REPO_ROOT" describe --exact-match --tags "$GIT_SHA" >/dev/null 2>&1; then
    VERSION="${VERSION}~git${GIT_SHA}"
fi

echo "=== Building ${PKG}_${VERSION}_all.deb ==="

command -v dpkg-deb >/dev/null || { echo "!! dpkg-deb not found (install dpkg-dev)"; exit 1; }
ROOT_FLAG="--root-owner-group"
dpkg-deb --help 2>&1 | grep -q -- --root-owner-group || ROOT_FLAG=""

# ---------------------------------------------------------------------------
# 1. Directory skeleton and Python source
# ---------------------------------------------------------------------------
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/motion-player" \
         "$STAGE/opt/motion-player/sensors" \
         "$STAGE/etc/motion-player" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/lib/systemd/user" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/doc/$PKG" \
         "$STAGE/usr/share/icons/hicolor"

cp -a "$REPO_ROOT/src/"*.py "$STAGE/opt/motion-player/"
cp -a "$REPO_ROOT/src/sensors/"*.py "$STAGE/opt/motion-player/sensors/"
cp "$REPO_ROOT/config/config.default.ini" "$STAGE/opt/motion-player/config.default.ini"
find "$STAGE/opt/motion-player" -name '*.py' -exec python3 -m py_compile {} + 2>/dev/null || true
find "$STAGE/opt/motion-player" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. BUILD_INFO
# ---------------------------------------------------------------------------
REPO_URL="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo unknown)"
cat > "$STAGE/opt/motion-player/BUILD_INFO" <<EOF
package=${PKG}
version=${VERSION}
commit=${GIT_SHA}
repo=${REPO_URL}
build_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
chmod 0644 "$STAGE/opt/motion-player/BUILD_INFO"

# ---------------------------------------------------------------------------
# 3. Icons
# ---------------------------------------------------------------------------
for sz in 16 22 24 32 48 64 128 256; do
    src="$REPO_ROOT/packaging/icons/motion-player-${sz}.png"
    if [[ -f "$src" ]]; then
        mkdir -p "$STAGE/usr/share/icons/hicolor/${sz}x${sz}/apps"
        cp "$src" "$STAGE/usr/share/icons/hicolor/${sz}x${sz}/apps/motion-player.png"
    fi
done

# ---------------------------------------------------------------------------
# 4. Launcher
# ---------------------------------------------------------------------------
cat > "$STAGE/usr/bin/motion-player" <<'LAUNCHER'
#!/usr/bin/env bash
# Silent launcher for motion-player. No crash dialogs, no terminal.
set -uo pipefail

APP_DIR=/opt/motion-player
PY_SCRIPT="$APP_DIR/motion_test.py"
APP_NAME="memory-machine"

VERBOSE=0
case "${1:-}" in
    --verbose|-v) VERBOSE=1 ;;
    --log) exec xdg-open "${XDG_STATE_HOME:-$HOME/.local/state}/motion-player/motion-player.log" 2>/dev/null || exec cat "${XDG_STATE_HOME:-$HOME/.local/state}/motion-player/motion-player.log" ;;
esac

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/motion-player"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/motion-player.log"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:0
fi
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export PYGAME_HIDE_SUPPORT_PROMPT=1

cd "$APP_DIR" || exit 1

# Single instance: file-descriptor flock.
LOCK="$STATE_DIR/instance.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$APP_NAME is already running." >&2
    exit 0
fi

# Hide cursor; ignore if unclutter is not installed.
if command -v unclutter >/dev/null 2>&1; then
    unclutter -idle 0 -root >/dev/null 2>&1 &
    UNCLUTTER_PID=$!
fi

# Disable screen blanking under XWayland.
if command -v xset >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    xset s off -dpms >/dev/null 2>&1 || true
fi

{
    echo "=============================================="
    echo " $APP_NAME"
    echo " Started : $(date '+%Y-%m-%d %H:%M:%S')"
    echo " Script  : $PY_SCRIPT"
    echo "=============================================="
} >> "$LOG"

if [ "$VERBOSE" = "1" ]; then
    python3 -u "$PY_SCRIPT" "$@" 2>&1 | tee -a "$LOG"
    STATUS=${PIPESTATUS[0]}
else
    python3 -u "$PY_SCRIPT" "$@" >> "$LOG" 2>&1
    STATUS=$?
fi

echo "---- exited with status $STATUS at $(date '+%Y-%m-%d %H:%M:%S') ----" >> "$LOG"

[ -n "${UNCLUTTER_PID:-}" ] && kill "$UNCLUTTER_PID" >/dev/null 2>&1 || true

exit "$STATUS"
LAUNCHER
chmod 0755 "$STAGE/usr/bin/motion-player"

# ---------------------------------------------------------------------------
# 5. Status / update helpers
# ---------------------------------------------------------------------------
cat > "$STAGE/usr/bin/motion-player-status" <<'STATUS'
#!/usr/bin/env bash
exec python3 /opt/motion-player/status.py "$@"
STATUS
chmod 0755 "$STAGE/usr/bin/motion-player-status"

cat > "$STAGE/usr/bin/motion-player-update" <<'UPDATE'
#!/usr/bin/env bash
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
sudo apt install --reinstall ./motion-player_*.deb

systemctl --user daemon-reload
systemctl --user enable motion-player.service
systemctl --user start motion-player.service

echo "Updated and restarted."
UPDATE
chmod 0755 "$STAGE/usr/bin/motion-player-update"

cp "$REPO_ROOT/packaging/motion-player-toggle" "$STAGE/usr/bin/motion-player-toggle"
chmod 0755 "$STAGE/usr/bin/motion-player-toggle"

# ---------------------------------------------------------------------------
# 6. systemd user service
# ---------------------------------------------------------------------------
cp "$REPO_ROOT/packaging/motion-player.service" "$STAGE/usr/lib/systemd/user/motion-player.service"
chmod 0644 "$STAGE/usr/lib/systemd/user/motion-player.service"

# ---------------------------------------------------------------------------
# 7. Desktop entry
# ---------------------------------------------------------------------------
cp "$REPO_ROOT/packaging/motion-player.desktop" "$STAGE/usr/share/applications/motion-player.desktop"
chmod 0644 "$STAGE/usr/share/applications/motion-player.desktop"

# ---------------------------------------------------------------------------
# 8. Config as conffile
# ---------------------------------------------------------------------------
if [ ! -f "$STAGE/etc/motion-player/config.ini" ]; then
    cp "$REPO_ROOT/config/config.default.ini" "$STAGE/etc/motion-player/config.ini"
fi
chmod 0644 "$STAGE/etc/motion-player/config.ini"

cat > "$STAGE/DEBIAN/conffiles" <<EOF
/etc/motion-player/config.ini
EOF
chmod 0644 "$STAGE/DEBIAN/conffiles"

# ---------------------------------------------------------------------------
# 9. Package metadata
# ---------------------------------------------------------------------------
if [[ "${STRICT_DEPS:-0}" == "1" ]]; then
    DEPENDS="python3, python3-opencv, python3-gpiozero, python3-lgpio, python3-pygame, zenity, xdg-utils, unclutter"
    RECOMMENDS=""
else
    DEPENDS="python3, zenity, xdg-utils, unclutter"
    RECOMMENDS="python3-opencv, python3-gpiozero, python3-lgpio, python3-pygame"
fi

INSTALLED_SIZE=$(du -sk "$STAGE" | cut -f1)

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: video
Priority: optional
Architecture: all
Depends: $DEPENDS
Recommends: $RECOMMENDS
Installed-Size: $INSTALLED_SIZE
Maintainer: $MAINTAINER
Description: TheTechMargin memory-machine gallery installation
 Plays a video in reverse through headphones when a viewer lifts them
 from a sensor-equipped stand. Runs unattended on a Raspberry Pi.
EOF

cat > "$STAGE/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: motion-player

Files: *
Copyright: 2026 TheTechMargin
License: MIT
 See /usr/share/doc/motion-player/LICENSE on systems where it is installed.
EOF
chmod 0644 "$STAGE/usr/share/doc/$PKG/copyright"

printf '%s (%s) unstable; urgency=low\n\n  * Packaged build of memory-machine.\n\n -- %s  %s\n' \
    "$PKG" "$VERSION" "$MAINTAINER" "$(date -R)" \
    | gzip -9n > "$STAGE/usr/share/doc/$PKG/changelog.Debian.gz"
chmod 0644 "$STAGE/usr/share/doc/$PKG/changelog.Debian.gz"

# ---------------------------------------------------------------------------
# 10. postinst / postrm
# ---------------------------------------------------------------------------
cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
    fi
    if command -v systemd >/dev/null 2>&1; then
        systemctl --system daemon-reload >/dev/null 2>&1 || true
    fi

    SRC=/usr/share/applications/motion-player.desktop
    getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1":"$6}' | while IFS=: read -r U H; do
        # Create a simple A/V directory in the user's home, Desktop or not.
        MEDIA_DIR="$H/memory-machine-media"
        mkdir -p "$MEDIA_DIR"
        chown "$U:$U" "$MEDIA_DIR" 2>/dev/null || true
        chmod 0755 "$MEDIA_DIR"

        [ -d "$H/Desktop" ] || continue

        ln -sfn "$MEDIA_DIR" "$H/Desktop/memory-machine-media" 2>/dev/null || true
        chown -h "$U" "$H/Desktop/memory-machine-media" 2>/dev/null || true

        cp -f "$SRC" "$H/Desktop/motion-player.desktop" || continue
        chmod 0755 "$H/Desktop/motion-player.desktop"
        chown "$U" "$H/Desktop/motion-player.desktop" 2>/dev/null || true
        if command -v gio >/dev/null 2>&1; then
            runuser -u "$U" -- gio set -t string \
                "$H/Desktop/motion-player.desktop" metadata::trusted true \
                >/dev/null 2>&1 || true
        fi
    done
fi
exit 0
POSTINST

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $6}' | while read -r H; do
        rm -f "$H/Desktop/motion-player.desktop" || true
        rm -f "$H/Desktop/memory-machine-media" || true
    done
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
    fi
    if command -v systemd >/dev/null 2>&1; then
        systemctl --system daemon-reload >/dev/null 2>&1 || true
    fi
fi
exit 0
POSTRM

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# 11. md5sums + build
# ---------------------------------------------------------------------------
( cd "$STAGE" && find . -path ./DEBIAN -prune -o -type f -print0 \
    | xargs -0 md5sum 2>/dev/null | sed 's|\.\/||' > DEBIAN/md5sums ) || true
chmod 0644 "$STAGE/DEBIAN/md5sums"

DEB="$OUTDIR/${PKG}_${VERSION}_all.deb"
dpkg-deb $ROOT_FLAG --build "$STAGE" "$DEB" >/dev/null

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$STAGE/usr/share/applications/motion-player.desktop" \
        && echo ">> .desktop validates clean" || echo ">> .desktop warnings (usually harmless)"
fi

echo
echo "Built: $DEB ($(du -h "$DEB" | cut -f1))"
echo "Install with: sudo apt install $DEB"
echo
