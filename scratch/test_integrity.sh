#!/bin/bash
set -e

echo "Building app..."
cd tracker-app && ./build.sh && cd ..

# Get the real DB path
DB_PATH=$(PYTHONPATH=. tracker/.venv/bin/python -c 'from tracker.constants import DB_PATH; print(DB_PATH)')
echo "Using DB path: $DB_PATH"

rm -f scratch/app.log
echo "Starting tracker-app..."
./tracker-app/LoglineSync.app/Contents/MacOS/tracker-app > scratch/app.log 2>&1 &
APP_PID=$!
sleep 3

# Verify app launched successfully
if ! kill -0 $APP_PID 2>/dev/null; then
    echo "ERROR: tracker-app failed to launch!"
    exit 1
fi
echo "App is running (PID: $APP_PID)"

echo "Starting heavy active-write load via rapid app switching..."
# Create a much heavier stream of UI events by rapidly cycling through 4 apps with 0.05s delay
osascript -e '
repeat 20 times
    tell application "Finder" to activate
    delay 0.05
    tell application "System Settings" to activate
    delay 0.05
    tell application "Terminal" to activate
    delay 0.05
    tell application "Calculator" to activate
    delay 0.05
end repeat' &
LOAD_PID=$!

sleep 2
echo "Sending polite quit to com.logline.tracker mid-write..."
osascript -e 'tell application id "com.logline.tracker" to quit'
sleep 3

wait $LOAD_PID 2>/dev/null || true

echo "=== Checking logs for crash traces ==="
# We do not use grep -e because set -e would fail if not found.
if grep -q "OC_PythonException" scratch/app.log; then
    echo "ERROR: Found PyObjC crash trace in app.log!"
    cat scratch/app.log
    exit 1
else
    echo "No crash traces found (clean exit)."
fi

echo "=== Checking DB Integrity ==="
sqlite3 "$DB_PATH" "PRAGMA integrity_check;"
