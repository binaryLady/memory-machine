#!/usr/bin/env bash
# motion-player-update: fetch, rebuild, reinstall, restart — with rollback.
#
# Safe to run unattended: it clones the checkout if one is missing, refuses to
# interrupt a visitor mid-piece, keeps the last known-good package so a bad
# build can be reverted, and leaves the service running whatever version
# actually came up.
set -euo pipefail

REPO="${MOTION_PLAYER_REPO:-$HOME/memory-machine}"
GIT_URL="${MOTION_PLAYER_GIT_URL:-https://github.com/binaryLady/memory-machine.git}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/motion-player"
LOG="$STATE_DIR/update.log"
KEEP="$STATE_DIR/motion-player_last-good.deb"
SERVICE="motion-player.service"
TIMER="motion-player-update.timer"
SETTLE_SECONDS="${SETTLE_SECONDS:-8}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

FORCE=0
CHECK=0
AUTO=0
ACTION="update"

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --check) CHECK=1 ;;
        --auto) AUTO=1 ;;
        --enable-auto) ACTION="enable-auto" ;;
        --disable-auto) ACTION="disable-auto" ;;
        -h|--help) ACTION="help" ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

mkdir -p "$STATE_DIR"

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"
}

install_deb() {
    local deb="$1"
    if sudo -n true 2>/dev/null || [ -t 0 ]; then
        sudo apt install --reinstall -y --allow-downgrades "$deb" >>"$LOG" 2>&1
        return
    fi
    # The helper takes no arguments so it can hold a single fixed sudoers rule;
    # it installs the newest package in the repo, so make this one the newest.
    if [ "$deb" != "$REPO/$(basename "$deb")" ]; then
        cp -f "$deb" "$REPO/$(basename "$deb")"
    else
        touch "$deb"
    fi
    sudo -n /usr/bin/motion-player-install-deb >>"$LOG" 2>&1
}

report_failure() {
    {
        echo "--- systemctl --user status $SERVICE ---"
        systemctl --user status "$SERVICE" --no-pager -l 2>&1 | tail -20
        echo "--- last 30 lines of motion-player.log ---"
        tail -30 "$STATE_DIR/motion-player.log" 2>/dev/null || echo "(no engine log yet)"
    } | tee -a "$LOG"
}

usage() {
    cat <<'USAGE'
motion-player-update — update the installation and restart it.

  motion-player-update                 update now
  motion-player-update --check         report whether an update is available
  motion-player-update --force         discard local changes, update anyway
  motion-player-update --auto          unattended mode: skip while engaged
  motion-player-update --enable-auto   run nightly on a timer
  motion-player-update --disable-auto  stop running on a timer

Clones the checkout automatically if it is missing. Rolls back to the last
known-good package if the new one fails to come up.
USAGE
}

installed_version() {
    dpkg-query -W -f='${Version}' motion-player 2>/dev/null || echo "none"
}

is_engaged() {
    local status="$STATE_DIR/status.json"
    [ -f "$status" ] && grep -q '"state"[[:space:]]*:[[:space:]]*"ENGAGED"' "$status"
}

ensure_checkout() {
    if [ -d "$REPO/.git" ]; then
        return
    fi
    if [ -e "$REPO" ] && [ -n "$(ls -A "$REPO" 2>/dev/null)" ]; then
        log "ERROR: $REPO exists but is not a git checkout. Move it aside and rerun."
        exit 1
    fi
    log "No checkout at $REPO; cloning $GIT_URL"
    git clone --quiet "$GIT_URL" "$REPO"
}

case "$ACTION" in
    help)
        usage
        exit 0
        ;;
    enable-auto)
        systemctl --user enable --now "$TIMER"
        log "Automatic updates enabled: $(systemctl --user list-timers --no-pager "$TIMER" | sed -n 2p)"
        if ! sudo -n true 2>/dev/null; then
            echo
            echo "Note: installing a package needs root. Unattended runs will fail"
            echo "until this account can run the install helper without a password:"
            echo
            echo "  echo \"$USER ALL=(root) NOPASSWD: /usr/bin/motion-player-install-deb\" \\"
            echo "    | sudo tee /etc/sudoers.d/motion-player-update"
            echo "  sudo chmod 0440 /etc/sudoers.d/motion-player-update"
            echo
            echo "That lets this account install packages as root without prompting,"
            echo "which is effectively root access. Skip it and use the menu's"
            echo "Update action instead if you would rather approve each upgrade."
        fi
        exit 0
        ;;
    disable-auto)
        systemctl --user disable --now "$TIMER"
        log "Automatic updates disabled"
        exit 0
        ;;
esac

ensure_checkout
cd "$REPO"

git fetch --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse '@{u}')"

if [ "$CHECK" = "1" ]; then
    if [ "$LOCAL" = "$REMOTE" ]; then
        echo "Already up to date ($(installed_version))."
    else
        echo "Update available: $(git log --oneline -1 "$REMOTE")"
    fi
    exit 0
fi

# A fresh clone can already match the remote while nothing is installed yet,
# so an up-to-date checkout alone is not reason enough to stop.
if [ "$LOCAL" = "$REMOTE" ] && [ "$FORCE" = "0" ] && [ "$(installed_version)" != "none" ]; then
    log "Already up to date ($(installed_version)); nothing to do"
    exit 0
fi

if [ "$AUTO" = "1" ] && is_engaged; then
    log "Piece is engaged; deferring update to the next run"
    exit 0
fi

if [ "$FORCE" = "0" ] && ! git diff-index --quiet HEAD; then
    log "Checkout has local changes. Use --force to discard, or commit them."
    exit 1
fi

BEFORE="$(installed_version)"
log "Updating from $BEFORE"

systemctl --user stop "$SERVICE" >/dev/null 2>&1 || true

if [ "$FORCE" = "1" ]; then
    git reset --quiet --hard "$REMOTE"
else
    git pull --quiet --ff-only
fi

if [ ! -f "$KEEP" ]; then
    EXISTING="$(ls -t ./motion-player_*.deb 2>/dev/null | head -n1 || true)"
    if [ -n "$EXISTING" ]; then
        cp -f "$EXISTING" "$KEEP"
        log "Kept $(basename "$EXISTING") as the fallback package"
    else
        log "No existing package to keep as a fallback; a failed update cannot be rolled back this time"
    fi
fi

make clean >/dev/null
make release >>"$LOG" 2>&1
DEB="$(ls -t ./motion-player_*.deb | head -n1)"
log "Built $(basename "$DEB")"

install_deb "$DEB"

systemctl --user daemon-reload
systemctl --user enable "$SERVICE" >/dev/null 2>&1 || true
systemctl --user start "$SERVICE"

sleep "$SETTLE_SECONDS"

SERVICE_STATE="$(systemctl --user is-active "$SERVICE" 2>/dev/null || true)"
if [ "$SERVICE_STATE" = "active" ]; then
    cp -f "$DEB" "$KEEP"
    log "Updated to $(installed_version) and running"
    exit 0
fi

log "ERROR: $SERVICE is '$SERVICE_STATE' after updating to $(installed_version)"
if [ "$SERVICE_STATE" = "activating" ]; then
    log "That state means it is restarting in a loop, so it exited straight after starting"
fi
report_failure

if [ -f "$KEEP" ]; then
    log "Rolling back to $(basename "$KEEP")"
    install_deb "$KEEP"
    systemctl --user daemon-reload
    systemctl --user start "$SERVICE" || true
    sleep "$SETTLE_SECONDS"
    if systemctl --user is-active --quiet "$SERVICE"; then
        log "Rolled back to $(installed_version) and running"
    else
        log "ERROR: rollback did not come up either"
        report_failure
    fi
else
    log "No known-good package kept yet; cannot roll back automatically"
fi
exit 1
