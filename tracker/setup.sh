#!/bin/bash
# Sets up everything the tracker's supervisor needs to run: the Python virtualenv, the
# LoglineTracker.app bundle, and the launchd agent that keeps it alive. Safe to re-run —
# each step rebuilds or replaces its own output rather than layering on top of it, so a
# partial failure or a later re-run both land in the same end state.
#
# One step cannot be automated: granting Accessibility permission to the app bundle.
# macOS requires that as a manual click in System Settings for any app reading window
# titles, on every machine. This script prints the exact steps at the end; do not attempt
# to script around that grant.
#
#     ./tracker/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/tracker/.venv"
APP="$HOME/Applications/LoglineTracker.app"

echo "==> Python virtualenv ($VENV)"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO_ROOT/tracker/requirements.txt"
echo "    ready"
echo

echo "==> App bundle"
"$REPO_ROOT/tracker/packaging/build_app.sh"
echo

echo "==> launchd agent"
"$REPO_ROOT/tracker/packaging/install_agent.sh"
echo

echo "==> Backend enrollment"
if security find-generic-password -a "SyncToken" -s "LoglineTracker" >/dev/null 2>&1; then
    echo "    already enrolled in Keychain — leaving it alone"
    echo "    to re-enroll: security delete-generic-password -a SyncToken -s LoglineTracker"
else
    echo "    Paste the device token from POST /tracker/devices (leave blank to skip)."
    echo "    Skipping is safe: the sync agent exits cleanly until a token exists."
    printf "    token: "
    read -r -s DEVICE_TOKEN
    echo
    if [ -n "$DEVICE_TOKEN" ]; then
        security add-generic-password -a "SyncToken" -s "LoglineTracker" -w "$DEVICE_TOKEN" -U
        echo "    stored token in Keychain securely"
    else
        echo "    skipped — no token stored"
    fi
fi
unset DEVICE_TOKEN
echo


echo "=================================================================="
echo "Setup complete. One manual step remains — grant Accessibility (see"
echo "the path printed above), then verify it took effect:"
echo
echo "  $VENV/bin/python -m tracker.ax_probe"
echo
echo "Until the grant is in place the tracker still runs and records"
echo "app-level sessions, but window_title, project_path, and"
echo "context_detail all stay NULL."
echo "=================================================================="
