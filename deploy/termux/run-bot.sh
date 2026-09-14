#!/data/data/com.termux/files/usr/bin/bash
# Keeps the bot running on Termux — the Android equivalent of the systemd unit.
#
# Android has no systemd, and it aggressively kills background processes. This
# script does what it can about that:
#   - takes a wake lock so the CPU isn't suspended
#   - restarts the bot if it exits, with backoff
#   - releases the wake lock on a clean exit
#
# It is NOT a guarantee of 24/7 uptime: Android (15 especially) can still kill
# the process. Also set Termux to "Unrestricted" under Android's battery
# settings, and see deploy/termux/README.md.
#
# Usage:  bash deploy/termux/run-bot.sh

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/bot.log"
MIN_BACKOFF=5
MAX_BACKOFF=300

mkdir -p "$LOG_DIR"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG_FILE"; }

cleanup() {
    log "Shutting down; releasing wake lock."
    command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
    exit 0
}
trap cleanup INT TERM

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    log "Wake lock acquired."
else
    log "termux-wake-lock not found (install with: pkg install termux-api)."
    log "Without it Android will suspend the bot when the screen is off."
fi

if [ ! -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    log "No virtualenv found. Run: bash deploy/termux/install.sh"
    exit 1
fi
# shellcheck disable=SC1091
source "$PROJECT_DIR/.venv/bin/activate"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log "No .env found. Run: python -m portfolio_agent.cli setup"
    exit 1
fi

backoff=$MIN_BACKOFF
log "Starting bot supervisor."

while true; do
    started_at=$(date +%s)
    python -m portfolio_agent.cli bot 2>&1 | tee -a "$LOG_FILE"
    ran_for=$(( $(date +%s) - started_at ))

    # Ran a decent while before dying? Treat it as a fresh failure, not a loop.
    if [ "$ran_for" -gt 120 ]; then
        backoff=$MIN_BACKOFF
    fi

    log "Bot exited after ${ran_for}s. Restarting in ${backoff}s."
    sleep "$backoff"
    backoff=$(( backoff * 2 ))
    [ "$backoff" -gt "$MAX_BACKOFF" ] && backoff=$MAX_BACKOFF
done
