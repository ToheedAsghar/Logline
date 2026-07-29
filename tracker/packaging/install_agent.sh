#!/bin/bash
# Installs (or removes) the launchd agent that keeps the tracker running.
#
#     ./tracker/packaging/install_agent.sh              # install and start
#     ./tracker/packaging/install_agent.sh --uninstall  # stop and remove
#
# Requires build_app.sh to have been run first, and LoglineTracker.app to hold an
# Accessibility grant — without it the tracker runs but records NULL window titles.
# Verify with:  tracker/.venv/bin/python -m tracker.ax_probe

set -euo pipefail

LABEL="com.logline.tracker"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$HOME/Applications/LoglineTracker.app"
APP_EXECUTABLE="$APP/Contents/MacOS/logline-tracker"
LOG_DIR="$HOME/Library/Logs/Logline"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    exit 0
fi

if [ ! -x "$APP_EXECUTABLE" ]; then
    echo "install_agent: no app bundle at $APP" >&2
    echo "               run ./tracker/packaging/build_app.sh first" >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

sed -e "s|__APP_EXECUTABLE__|$APP_EXECUTABLE|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$REPO_ROOT/tracker/packaging/$LABEL.plist" > "$PLIST"

plutil -lint "$PLIST" >/dev/null

# Replace any previous instance rather than layering a second one on top. bootout is
# asynchronous: bootstrapping while the old job is still tearing down fails with
# "Bootstrap failed: 5: Input/output error", so wait for it to actually disappear.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for _ in $(seq 1 50); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 0.2
done

if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "install_agent: bootstrap failed — is the job still loaded?" >&2
    echo "               launchctl print $DOMAIN/$LABEL" >&2
    exit 1
fi

echo "installed:  $PLIST"
echo "logs:       $LOG_DIR/tracker.log"
echo "status:     launchctl print $DOMAIN/$LABEL"
echo "stop:       ./tracker/packaging/install_agent.sh --uninstall"
