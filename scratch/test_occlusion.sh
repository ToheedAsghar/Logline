#!/bin/bash
set -e

echo "Starting app..."
./tracker-app/LoglineSync.app/Contents/MacOS/tracker-app > scratch/app_occlusion.log 2>&1 &
APP_PID=$!

sleep 2 # Let it start

echo "Making app active and frontmost..."
osascript -e 'tell application "System Events" to set frontmost of the first process whose unix id is '"$APP_PID"' to true'
sleep 2

echo "Window should be visible. Waiting 18 seconds for first refresh to hit (timer is 15s)..."
sleep 18

echo "Hiding app..."
osascript -e 'tell application "System Events" to set visible of the first process whose unix id is '"$APP_PID"' to false'

echo "App hidden. Waiting 20 seconds..."
sleep 20

echo "Killing app..."
kill $APP_PID

echo "Log output:"
cat scratch/app_occlusion.log
