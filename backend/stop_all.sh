#!/usr/bin/env bash
# stop_all.sh
# ===========
# Stops both backend services started by run_all.sh, by reading the PIDs
# it wrote to .run_all.pids. Use this from a separate terminal when Ctrl+C
# in the run_all.sh terminal isn't available — e.g. that terminal was
# closed, or you're driving this from a script/CI step — leaving
# chatagent/voiceagent running as orphaned processes with nothing left to
# catch Ctrl+C for them.
#
# Usage:
#   ./stop_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.run_all.pids"

if [ ! -f "$PID_FILE" ]; then
    echo "No $PID_FILE found — nothing to stop (run_all.sh may not have been started from here, or was already stopped)."
    exit 0
fi

while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    if command -v taskkill >/dev/null 2>&1; then
        if taskkill //F //T //PID "$pid" >/dev/null 2>&1; then
            echo "Stopped PID $pid"
        else
            echo "PID $pid was not running"
        fi
    else
        if kill "$pid" 2>/dev/null; then
            echo "Stopped PID $pid"
        else
            echo "PID $pid was not running"
        fi
    fi
done < "$PID_FILE"

rm -f "$PID_FILE"
echo "Done."
