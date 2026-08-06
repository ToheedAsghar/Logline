# Local activity tracker

macOS-only background recorder. Polls the frontmost app, its window title, and
per-app context, and writes sessions to a local SQLite database at
`~/Library/Application Support/Logline/tracker.db`.

## Setup (supervised, recommended)

Runs the tracker as a launchd-supervised background agent — the way it's meant to run
day to day. One script does everything that can be automated:

```sh
./tracker/setup.sh
```

This creates `tracker/.venv`, builds `LoglineTracker.app` into `~/Applications`, and
installs+loads the launchd agent at `~/Library/LaunchAgents/com.logline.tracker.plist`.
It's safe to re-run any time — on a fresh machine, after a partial failure, or just to
pick up code changes, since each step rebuilds or replaces its own output.

The one thing it cannot do is grant Accessibility permission — macOS requires that as a
manual click, per machine, for any app that reads window titles:

1. Open **System Settings > Privacy & Security > Accessibility**.
2. Click **+**, navigate to `~/Applications/LoglineTracker.app`, and add it.
3. Toggle it on.

The grant is pinned to the app bundle's code signature, not to a path or to Python, so
rebuilding the bundle (via `setup.sh` or `build_app.sh` directly) does not cost it.

Verify the grant took effect:

```sh
tracker/.venv/bin/python -m tracker.ax_probe
```

`trusted: true` and a non-null `window_title` mean the tracker will record real window
titles and per-app context. Until then it still runs and records app-level sessions, but
`window_title`, `project_path`, and `context_detail` all stay NULL.

Logs: `~/Library/Logs/Logline/tracker.log` (diagnostics), `tracker.error.log` (warnings/errors), and `activity.log` / `activity.error.log` (stdout/stderr from launchd). Status and uninstall:

```sh
launchctl print gui/$(id -u)/com.logline.tracker
./tracker/packaging/install_agent.sh --uninstall
```

Signing is ad-hoc (`codesign --sign -`), which is why the app must be added to
Accessibility explicitly rather than being pre-trusted. Apple Developer ID signing and
notarization are out of scope here and tracked separately as a future decision.

## Setup (manual, foreground)

For development, or to run the tracker in a terminal instead of under launchd:

```sh
python3 -m venv tracker/.venv
tracker/.venv/bin/pip install -r tracker/requirements.txt
tracker/.venv/bin/python -m tracker.main
```

If the venv directory is deleted while the tracker is running, the process keeps
going on its open file handles and only fails on the *next* start — so a missing
`tracker/.venv` is easy to miss until a restart fails. Recreate it with the two
`venv`/`pip install` commands above, or just run `./tracker/setup.sh`.

Only one instance should run at a time. The `open_session` table holds exactly
one row, and startup seals any dangling session, so a second concurrent instance
will fight the first over that row and corrupt session boundaries.

Accessibility works differently here: macOS attributes the grant to the
*responsible* process, which for a terminal-launched tracker is the terminal app
itself (Ghostty, Terminal.app, VS Code…), not the Python binary or the tracker.
Grant Accessibility to that terminal app to get real window titles this way.

## Backend sync

A second launchd agent (`com.logline.sync`) uploads closed sessions to the Logline backend
every 5 minutes. It is a separate, periodic job rather than part of the capture daemon:
capture has to keep recording through a backend outage, and a failing upload must not be
able to take window tracking down with it. It opens `tracker.db` read-only, so it cannot
damage what the capture daemon writes.

Enrollment is manual and one-time. Get a device token from the backend as the logged-in
user:

```sh
curl -X POST http://localhost:8000/tracker/devices \
     -H "Authorization: Bearer $LOGLINE_JWT" \
     -H 'Content-Type: application/json' \
     -d '{"name": "'"$(hostname -s)"'"}'
```

The `token` in that response is shown **once** and is not recoverable — the backend stores
only a hash of it. `./tracker/setup.sh` prompts for it and writes it to
`~/Library/Application Support/Logline/device_token` with mode 600. Until a token exists the
sync agent runs and exits cleanly, doing nothing.

Optional config at `~/Library/Application Support/Logline/sync.json`:

```json
{"base_url": "https://api.example.com", "batch_size": 300, "interval_seconds": 300}
```

`base_url` must be `https://`, or `http://` to localhost — anything else is rejected at load
rather than uploading window titles in plaintext. Changing `interval_seconds` needs a re-run
of `install_sync_agent.sh`, since launchd owns the schedule.

Sync is stateless: there is no local cursor file. Every run asks the backend where it left
off (`GET /tracker/sync/checkpoint`), so a crash mid-backlog, an offline laptop, or a
restored backup all resume correctly.

```sh
launchctl kickstart -p gui/$(id -u)/com.logline.sync   # run one sync now
tracker/.venv/bin/python -m tracker.sync.agent         # or run it in the foreground
./tracker/packaging/install_sync_agent.sh --uninstall  # stop syncing
```

Logs: `~/Library/Logs/Logline/sync.log` and `sync.error.log`. A silent failure is also
visible in the app's Settings page, which shows when the account last synced.

To retire a machine, revoke its device (`DELETE /tracker/devices/{device_id}` as the logged-in
user). The token stops working immediately; the sync checkpoint is kept, so re-enrolling the
same machine does not re-upload its whole history.

## Tests

```sh
tracker/.venv/bin/python -m pytest tracker/tests -q
```
