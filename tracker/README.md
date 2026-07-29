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

Logs: `~/Library/Logs/Logline/tracker.log` and `tracker.error.log`. Status and uninstall:

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

## Tests

```sh
tracker/.venv/bin/python -m pytest tracker/tests -q
```
