#!/bin/bash

# Navigate to script directory to ensure relative paths work
cd "$(dirname "$0")" || exit

# Zero Buffering: ensure all python logs are streamed immediately
export PYTHONUNBUFFERED=1

# Log directory
LOG_DIR="$(pwd)/logs"
mkdir -p "$LOG_DIR"
API_LOG="$LOG_DIR/api.log"
SDR_LOG="$LOG_DIR/sdr.log"
IMSI_LOG="$LOG_DIR/imsi.log"
LOCK_FILE="$LOG_DIR/skytracker.pid"

# Truncate logs on fresh start
> "$API_LOG"
> "$LOG_DIR/scan_livemon.log"
> "$LOG_DIR/imsi_catcher.log"
> "$LOG_DIR/gsm_node.log"

# Kill any process on port 8000 (no sudo needed if we own it)
fuser -k 8000/tcp 2>/dev/null || true
bash reset_sdr.sh > /dev/null 2>&1

# Setup cleanup trap
cleanup() {
    echo ""
    echo "[*] Shutting down SkyTracker..."
    # Kill processes tracked by PID file if it exists
    if [ -f "$LOCK_FILE" ]; then
        xargs kill < "$LOCK_FILE" 2>/dev/null
        rm "$LOCK_FILE"
    fi
    # Forcefully kill remaining radio processes (no sudo; we own them)
    pkill -9 -f grgsm_scanner 2>/dev/null
    pkill -9 -f grgsm_livemon_headless 2>/dev/null
    pkill -9 -f scan-and-livemon.py 2>/dev/null
    pkill -9 -f simple_IMSI-catcher.py 2>/dev/null

    fuser -k 8000/tcp 2>/dev/null || true
    stty sane
    echo "[*] SkyTracker shutdown complete."
    exit 0
}
trap cleanup SIGINT SIGTERM

# Activate the python virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start FastAPI server
venv/bin/python3 api.py >> "$API_LOG" 2>&1 &
echo $! > "$LOCK_FILE"
API_PID=$!

# Wait for the API to be ready
printf "[*] Starting API server"
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        break
    fi
    printf "."
    sleep 1
done
echo " Ready!"

# Boot SDR processes via the API
echo "[*] Booting SDR processes..."
curl -sf -X POST http://localhost:8000/api/start > /dev/null

echo ""
echo "========================================================"
echo "    SkyTracker is now running!"
echo "    Dashboard:  http://$(hostname -I | awk '{print $1}'):8000/"
echo "========================================================"
echo ""
echo "[*] Live output below — scan_livemon.log:"
echo "--------"

# Tail the scanner log (cleanest signal of what's happening on air)
tail -f "$LOG_DIR/scan_livemon.log" &
TAIL_PID=$!

# Keep script alive
wait "$API_PID"
