#!/bin/bash
# Fashion Bot Health Check Watchdog
#
# Crontab setup (runs watchdog as a persistent process, restarts if it dies):
#   Add to crontab with: crontab -e
#
#   # Check every minute if watchdog is running, restart if not
#   * * * * * /home/stas/fashion-bot/scripts/watchdog.sh
#
# The script itself runs continuously (30s loop), so cron just ensures
# it stays alive if it crashes.

set -euo pipefail

PIDFILE="/tmp/fashion-bot-watchdog.pid"
LOGFILE="/home/stas/fashion-bot/logs/watchdog.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOGFILE")"

# Check if already running
if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
        exit 0  # Already running
    fi
    rm -f "$PIDFILE"
fi

# Source environment
cd /home/stas/fashion-bot
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# Export watchdog-specific vars (override defaults for host-level access)
export HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

# Start watchdog in background, log to file
nohup python3 scripts/watchdog.py >> "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
