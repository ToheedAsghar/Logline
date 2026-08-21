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

# Copy Fonts
mkdir -p "$RESOURCES_DIR/Fonts"
cp Fonts/*.ttf "$RESOURCES_DIR/Fonts/"

# Copy Icon
cp Images/AppIcon.icns "$RESOURCES_DIR/AppIcon.icns" || true

# Copy PyInstaller binary if it exists
if [ -f "../tracker/dist/logline_tracker" ]; then
    echo "Copying logline_tracker to Resources..."
    cp "../tracker/dist/logline_tracker" "$RESOURCES_DIR/"
fi

# Set swift optimization flag
SWIFT_OPT="-Onone"
if [ "${RELEASE:-0}" = "1" ]; then
    SWIFT_OPT="-O"
    echo "Building in Release mode (-O)"
fi

# Set swift optimization flag
SWIFT_OPT="-Onone"
if [ "${RELEASE:-0}" = "1" ]; then
    SWIFT_OPT="-O"
    echo "Building in Release mode (-O)"
fi

# Compile Swift files
swiftc \
    TrackerApp.swift \
    ProcessManager.swift \
    KeychainManager.swift \
    UI/MainView.swift \
    UI/Tokens.swift \
    DatabaseReader.swift \
    UI/LiveEventsViewModel.swift \
    UI/LiveEventsView.swift \
    UI/EnrollmentViewModel.swift \
    UI/EnrollmentView.swift \
    Constants.swift \
    -lsqlite3 \
    $SWIFT_OPT \
    -o "$MACOS_DIR/tracker-app"

# Ad-hoc sign the app
codesign --force --sign - "$APP_DIR"

echo "Done! Built $APP_DIR"
