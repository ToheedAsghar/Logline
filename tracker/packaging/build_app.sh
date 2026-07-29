#!/bin/bash
# Builds LoglineTracker.app — a minimal wrapper bundle that exists purely to give the
# tracker a stable identity for macOS's Accessibility (TCC) grant.
#
# Why a bundle at all: macOS pins an Accessibility grant to the *responsible* process.
# Launched from a terminal, that's the terminal app; launched straight from launchd,
# there is none, and the AX API returns kAXErrorAPIDisabled with every window title
# recording as NULL. A bundle with its own permanent identifier is something the grant
# can attach to and stay attached to.
#
# The bundle contains no machine-specific paths and no Python — only the launcher
# script. Upgrading Python, rebuilding the venv, or moving the repo therefore does not
# change the signed bytes, and the grant survives. Those paths live in the config file
# written below, outside the bundle.
#
#     ./tracker/packaging/build_app.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO_ROOT/tracker/packaging"
APP="$HOME/Applications/LoglineTracker.app"
CONFIG_DIR="$HOME/Library/Application Support/Logline"
CONFIG="$CONFIG_DIR/tracker.env"

mkdir -p "$HOME/Applications"

# Rebuild the bundle from scratch so a stale executable can never survive a rename.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cp "$SRC/Info.plist" "$APP/Contents/Info.plist"

# The main executable must be a compiled Mach-O, not a shell script. With a script,
# codesign reports "app bundle with generic", the launched process is /bin/bash, and
# TCC has no identity of ours to attach the Accessibility grant to — every AX call
# returns kAXErrorAPIDisabled. Verified empirically on this bundle.
clang -O2 -Wall -Wextra -o "$APP/Contents/MacOS/logline-tracker" "$SRC/launcher.c"

# Ad-hoc signature. TCC needs a code identity to pin the grant to; without one it falls
# back to weaker path-based matching that a rebuild can invalidate.
codesign --force --sign - "$APP" >/dev/null 2>&1

mkdir -p "$CONFIG_DIR"
printf 'REPO_ROOT=%s\n' "$REPO_ROOT" > "$CONFIG"

echo "built:      $APP"
echo "bundle id:  $(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist")"
echo "config:     $CONFIG (REPO_ROOT=$REPO_ROOT)"
echo "signature:  $(codesign -dv "$APP" 2>&1 | grep -E '^Identifier|^CDHash' | tr '\n' ' ')"
echo
echo "Grant Accessibility to this bundle:"
echo "  System Settings > Privacy & Security > Accessibility > + > $APP"
