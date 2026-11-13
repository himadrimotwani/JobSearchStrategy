#!/usr/bin/env bash
set -e

# Dynamically resolve root directory of repository
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

NODE_BIN=$(command -v node || echo "/opt/homebrew/bin/node")

echo "Checking for running dispatcher processes..."
pkill -f "run_outreach_dispatcher.js" 2>/dev/null || true
pkill -f "caffeinate -dimsu" 2>/dev/null || true
sleep 1

mkdir -p outputs/outreach

echo "Launching autonomous outreach dispatcher with dynamic caffeinate sleep prevention..."
nohup "$NODE_BIN" scripts/run_outreach_dispatcher.js >> outputs/outreach/dispatcher.log 2>&1 &
DISPATCHER_PID=$!
echo $DISPATCHER_PID > outputs/outreach/dispatcher.pid

echo "Dispatcher successfully launched in background with PID: $DISPATCHER_PID"
echo "Log file: outputs/outreach/dispatcher.log"
