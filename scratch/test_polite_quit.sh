#!/bin/bash
rm -f scratch/app.log
echo "Starting tracker-app..."
./tracker-app/LoglineSync.app/Contents/MacOS/tracker-app > scratch/app.log 2>&1 &
APP_PID=$!
sleep 3

echo ""
echo "=== PS Output: Mid-flight sync ==="
ps aux | grep -E "tracker.main|tracker.sync.agent|tracker-app" | grep -v grep

echo ""
echo "Sending polite quit to com.logline.tracker..."
osascript -e 'tell application id "com.logline.tracker" to quit'
sleep 3

echo ""
echo "=== PS Output: After App Terminated ==="
ps aux | grep -E "tracker.main|tracker.sync.agent|tracker-app" | grep -v grep
echo "Done."
