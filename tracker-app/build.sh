#!/bin/bash
set -euo pipefail

APP_NAME="LoglineSync"
APP_DIR="$APP_NAME.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RESOURCES_DIR="$APP_DIR/Contents/Resources"

echo "Building $APP_NAME..."

# Clean old build
rm -rf "$APP_DIR"

# Create bundle structure
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Copy Info.plist
cp Info.plist "$APP_DIR/Contents/Info.plist"

# Compile Swift files
swiftc \
    TrackerApp.swift \
    ProcessManager.swift \
    KeychainManager.swift \
    UI/MainView.swift \
    UI/Tokens.swift \
    -o "$MACOS_DIR/tracker-app"

# Ad-hoc sign the app
codesign --force --sign - "$APP_DIR"

echo "Done! Built $APP_DIR"
