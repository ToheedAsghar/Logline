#!/bin/bash
echo "Starting tracker-app..."
./tracker-app/LoglineSync.app/Contents/MacOS/tracker-app > scratch/app.log 2>&1 &
APP_PID=$!

sleep 3
echo ""
echo "=== PS Output: Mid-flight sync ==="
ps aux | grep -E "tracker.main|tracker.sync.agent|tracker-app" | grep -v grep

echo ""
echo "Sending SIGTERM to tracker-app ($APP_PID)..."
kill -15 $APP_PID
sleep 3

echo ""
echo "=== PS Output: After App Terminated ==="
ps aux | grep -E "tracker.main|tracker.sync.agent|tracker-app" | grep -v grep
echo "Done."
