#!/data/data/com.termux/files/usr/bin/bash
# Keeps the bot running on Termux — the Android equivalent of the systemd unit.
#
# Android has no systemd, and it aggressively kills background processes. This
# script does what it can about that:
#   - takes a wake lock so the CPU isn't suspended
#   - restarts the bot if it exits, with backoff
#   - releases the wake lock on a clean exit
#   - refuses to start if another bot is already running (Telegram allows only
#     one process per token; a second one just gets 409 Conflict forever)
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
STATE_DIR="$PROJECT_DIR/state"
PID_FILE="$STATE_DIR/bot.pid"
MIN_BACKOFF=5
MAX_BACKOFF=300

mkdir -p "$LOG_DIR" "$STATE_DIR"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG_FILE"; }

# --- Only one bot per token -------------------------------------------------
# Telegram hands 409 Conflict to every process after the first, so a second
# supervisor is never useful. Refuse early and say how to stop the other one,
# rather than letting the bot loop on conflicts.

if [ -f "$PID_FILE" ]; then
    existing="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$existing" ] && kill -0 "$existing" 2>/dev/null; then
        log "Another supervisor is already running (pid $existing) — not starting a second."
        log "Telegram allows one process per bot token; a second gets 409 Conflict."
        log "Stop the running one first:  kill $existing"
        exit 2
    fi
    log "Clearing stale pid file (pid ${existing:-unknown} is no longer running)."
fi

if command -v pgrep >/dev/null 2>&1; then
    stray="$(pgrep -f 'portfolio_agent\.cli bot' 2>/dev/null | grep -v "^$$\$" || true)"
    if [ -n "$stray" ]; then
        log "A bot process is already running outside this supervisor (pid(s): $(echo $stray))."
        log "Telegram allows one process per bot token; starting another gets 409 Conflict."
        log "Stop it first:  pkill -f 'portfolio_agent.cli bot'"
        exit 2
    fi
fi

printf '%s\n' "$$" > "$PID_FILE"
# Only claim the trap once the pid file is ours, so the guard above can never
# delete another instance's claim on its way out.
trap 'rm -f "$PID_FILE"' EXIT

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
