# Local activity tracker

macOS-only background recorder. Polls the frontmost app, its window title, and
per-app context, and writes sessions to a local SQLite database at
`~/Library/Application Support/Logline/tracker.db`.

## Setup

The tracker runs from its own virtualenv, which is gitignored and therefore
**not** restored by `git clone` or a branch switch:

```sh
python3 -m venv tracker/.venv
tracker/.venv/bin/pip install -r tracker/requirements.txt
```

If the venv directory is deleted while the tracker is running, the process keeps
going on its open file handles and only fails on the *next* start — so a missing
`tracker/.venv` is easy to miss until a restart fails. Recreate it with the two
commands above.

## Running

```sh
tracker/.venv/bin/python -m tracker.main
```

Only one instance should run at a time. The `open_session` table holds exactly
one row, and startup seals any dangling session, so a second concurrent instance
will fight the first over that row and corrupt session boundaries.

## Accessibility permission

Window titles and per-app context come from the macOS Accessibility (AX) API.
Without the grant the tracker still runs and still records app-level sessions,
but `window_title`, `project_path`, and `context_detail` are all NULL.

macOS attributes the grant to the *responsible* process, which is the terminal
app that launched the tracker (Ghostty, Terminal.app, VS Code…) — not to the
Python binary. A tracker launched from `launchd` has no responsible app, so it
gets `kAXErrorAPIDisabled` and silently records NULL titles even though the
launching terminal is granted. Launch it from a granted terminal.

## Tests

```sh
tracker/.venv/bin/python -m pytest tracker/tests -q
```
