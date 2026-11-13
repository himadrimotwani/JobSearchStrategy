#!/usr/bin/env bash
# Stop Outreach Dispatch Daemon

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$WORKSPACE/outputs/outreach/dispatcher.pid"

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "Stopping outreach daemon (PID: $PID)..."
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "Daemon stopped."
  else
    rm -f "$PIDFILE"
    echo "Stale PID file removed. Daemon was not running."
  fi
else
  echo "No active PID file found. Cleaning up any lingering processes..."
fi

pkill -9 -f "run_outreach_dispatcher.js" 2>/dev/null || true
pkill -9 -f "caffeinate -dimsu" 2>/dev/null || true
echo "Outreach daemon and caffeinate processes terminated."
