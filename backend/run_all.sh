set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATAGENT_DIR="$SCRIPT_DIR/chatagent"
VOICEAGENT_DIR="$SCRIPT_DIR/voiceagent"
PID_FILE="$SCRIPT_DIR/.run_all.pids"

# Resolves the real Windows PID of whatever process is LISTENING on a
# given local port, via netstat. Git Bash's own $! for a backgrounded
# native Windows executable (python.exe) is an MSYS-internal handle, not
# the real Windows PID netstat/taskkill/Get-Process use — confirmed by
# testing, where $! and the actual listening process's PID were two
# different, unrelated numbers. Cleanup has to target the real PID by
# port instead of trusting $!.
resolve_pid_by_port() {
    netstat -ano 2>/dev/null | grep -E ":$1[[:space:]]" | grep LISTENING | awk '{print $NF}' | head -1
}

# Git Bash's `kill` sends signals through MSYS's POSIX emulation layer,
# which does not reliably reach native Windows child processes (python.exe
# started via `python main.py` keeps running even after `kill $pid`).
# taskkill talks to the real Windows process tree instead. //F //T //PID
# uses double slashes so MSYS doesn't rewrite "/F" into a filesystem path.
kill_pid() {
    local pid="$1"
    [ -z "$pid" ] && return 0
    if command -v taskkill >/dev/null 2>&1; then
        taskkill //F //T //PID "$pid" >/dev/null 2>&1
    else
        kill "$pid" 2>/dev/null
    fi
}

cleanup() {
    echo ""
    echo "Stopping services..."
    if [ -f "$PID_FILE" ]; then
        while IFS= read -r pid; do
            kill_pid "$pid"
        done < "$PID_FILE"
    fi
    rm -f "$PID_FILE"
    echo "Both services stopped."
}
trap cleanup SIGINT SIGTERM

echo "Starting chatagent (port 8001)..."
(cd "$CHATAGENT_DIR" && python main.py) &

echo "Starting voiceagent (port 8002)..."
(cd "$VOICEAGENT_DIR" && python main.py) &

# chatagent's Google ADK + LiteLLM imports are slow, so poll for each port
# to actually start LISTENING rather than trusting a flat sleep — this
# doubles as how we learn each service's real Windows PID (see
# resolve_pid_by_port above), which is what cleanup actually needs.
CHATAGENT_PID=""
VOICEAGENT_PID=""
for _ in $(seq 1 20); do
    [ -z "$CHATAGENT_PID" ] && CHATAGENT_PID="$(resolve_pid_by_port 8001)"
    [ -z "$VOICEAGENT_PID" ] && VOICEAGENT_PID="$(resolve_pid_by_port 8002)"
    [ -n "$CHATAGENT_PID" ] && [ -n "$VOICEAGENT_PID" ] && break
    sleep 1
done

if [ -z "$CHATAGENT_PID" ]; then
    echo "ERROR: chatagent never started listening on :8001 — see its output above for why (missing GROQ_API_KEY, missing dependency, or the port already in use)." >&2
    kill_pid "$VOICEAGENT_PID"
    exit 1
fi

if [ -z "$VOICEAGENT_PID" ]; then
    echo "ERROR: voiceagent never started listening on :8002 — see its output above for why (missing RETELL_API_KEY/RETELL_AGENT_ID, missing dependency, or the port already in use)." >&2
    kill_pid "$CHATAGENT_PID"
    exit 1
fi

printf '%s\n' "$CHATAGENT_PID" "$VOICEAGENT_PID" > "$PID_FILE"

echo ""
echo "Both services running — chatagent on :8001 (pid $CHATAGENT_PID), voiceagent on :8002 (pid $VOICEAGENT_PID)."
echo "PIDs written to $PID_FILE"
echo "Ctrl+C may not reliably stop both on Windows/Git Bash (untested/inconsistent"
echo "in this setup) — the tested, reliable way to stop both is:"
echo "    ./stop_all.sh"
echo "from another terminal."
echo ""

# Git Bash's `wait` does not reliably block on native Windows child
# processes — confirmed by testing, where the script exited on its own
# with both services still running, never giving Ctrl+C a chance to fire.
# Polling in a plain sleep loop instead avoids depending on `wait`'s
# behavior for those children. NOTE: even with this loop in place, a
# direct SIGINT to this script's own process was tested and did NOT
# reliably trigger the trap below on Windows/Git Bash — cause unconfirmed.
# `./stop_all.sh` is the verified way to stop both; treat Ctrl+C as
# best-effort, not guaranteed.
while true; do
    sleep 2
done
