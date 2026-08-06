#!/bin/bash
# Installs (or removes) the launchd agent that syncs recorded sessions to the backend.
#
#     ./tracker/packaging/install_sync_agent.sh              # install and start
#     ./tracker/packaging/install_sync_agent.sh --uninstall  # stop and remove
#
# com.logline.sync.plist is a template: this script substitutes its __PLACEHOLDERS__ and
# installs the result to ~/Library/LaunchAgents — never load that file directly. Interval
# and log paths come from tracker/constants.py so the schedule has one source of truth.
#
# Separate job from the capture agent (com.logline.tracker): capture must keep recording
# through a backend outage, and this one is periodic rather than persistent. Requires
# tracker/.venv; enrollment (the device token) is handled by setup.sh, and its absence is
# a clean no-op run rather than an install-time failure.

set -euo pipefail

LABEL="com.logline.sync"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PYTHON="$REPO_ROOT/tracker/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    exit 0
fi

if [ ! -x "$VENV_PYTHON" ]; then
    echo "install_sync_agent: no virtualenv at $VENV_PYTHON" >&2
    echo "                    run ./tracker/setup.sh first" >&2
    exit 1
fi

if ! CONFIG="$(
    cd "$REPO_ROOT"
    "$VENV_PYTHON" -c 'from tracker.constants import LOG_DIR, SYNC_INTERVAL_SECONDS; print(f"{LOG_DIR}|{SYNC_INTERVAL_SECONDS}")'
)"; then
    echo "install_sync_agent: could not read config from tracker.constants — is tracker/.venv intact?" >&2
    exit 1
fi
LOG_DIR="${CONFIG%|*}"
INTERVAL_SECONDS="${CONFIG##*|}"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

sed -e "s|__PYTHON__|$VENV_PYTHON|g" \
    -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
    -e "s|__INTERVAL_SECONDS__|$INTERVAL_SECONDS|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$REPO_ROOT/tracker/packaging/$LABEL.plist" > "$PLIST"

plutil -lint "$PLIST" >/dev/null

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for _ in $(seq 1 50); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 0.2
done

if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "install_sync_agent: bootstrap failed — is the job still loaded?" >&2
    echo "                    launchctl print $DOMAIN/$LABEL" >&2
    exit 1
fi

echo "installed:  $PLIST"
echo "interval:   ${INTERVAL_SECONDS}s"
echo "logs:       $LOG_DIR/sync.log, $LOG_DIR/sync.error.log"
echo "run now:    launchctl kickstart -p $DOMAIN/$LABEL"
echo "stop:       ./tracker/packaging/install_sync_agent.sh --uninstall"
