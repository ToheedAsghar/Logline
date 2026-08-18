# Spec: Packaged Tracker App (Swift Shell + Python Tracker Child Process)

## Objective
Migrate the Logline tracker from a headless, launchd-managed terminal process to a
distributable, native macOS menu-bar app. Closing the window does not stop tracking; only an
explicit Quit does.

**Two-process architecture** (revised from an earlier single-process draft):
- **Main process — Swift app.** Owns the UI, the menu-bar icon, app lifecycle, Keychain
  token storage, and backend calls (enrollment validation, sync-status polling). This is what
  macOS treats as "the app" — signed, visible, holds the permission grants.
- **Child process — existing Python tracker.** Unchanged capture/redaction/classification
  logic. Launched, supervised, and stopped by the Swift app (not a separate always-on daemon,
  not a thread inside the Swift process).

Three UI surfaces, all inside the Swift app:
1. **Enrollment / Connection State** — paste sync token, validated against the backend,
   stored in macOS Keychain.
2. **Sync Status Indicator** — polls `GET /tracker/sync/status`.
3. **Live Local Events View** — read-only, last 500 rows from `tracker.db`.

Plus explicit **Start / Stop / Quit** controls, which actually start/stop the Python child
process (three real states — see Architecture).

## Why this stack (record of the decision, for anyone asking later)
Two options were considered for the app shell: Python+PyObjC, or Swift. Swift was chosen:
- **Memory**: a Python-based app must bundle a full Python interpreter to run at all; Swift
  needs none. Matters here because this app is meant to sit resident/idle in the background
  most of the time.
- **Native tooling**: Apple's own profiling/debugging tools (Xcode, Instruments) are built
  for native apps; PyObjC's bridging layer sits outside that support.
- **Permissions**: macOS TCC permission grants (Accessibility, Screen Recording) attach most
  predictably to a true native, signed app rather than a bridged one.

**The tracking/capture logic itself is deliberately staying in Python, not being rewritten
for this project.** That logic (redaction, meeting detection, terminal/VSCode resolvers) has
already been through real security review and real-data testing — rewriting it now would be
pure regression risk for no benefit. It becomes a *child process* the Swift app manages,
not code the Swift app reimplements. Converting it to Swift is an explicitly separate, later,
piece-by-piece effort (see "Future: full Swift migration" below) — not part of this spec.

## Tech Stack
- **Swift app**: Swift + AppKit (native macOS UI, no WebView — same memory-footprint
  reasoning as before: 3 simple screens don't justify a WebView's renderer overhead. Ported
  design tokens from the web frontend, applied to native views).
- **Python tracker**: unchanged existing codebase, packaged as a **standalone executable with
  its own bundled interpreter** (e.g. via `PyInstaller`) — required because macOS cannot be
  assumed to have a usable system Python available. This bundled-interpreter cost is real but
  now scoped to only the tracker process, not the whole app.
- **Token Storage**: macOS Keychain, written by the Swift app. Python reads the token from
  Keychain too (exact read mechanism — see Open Questions; this is a real, non-trivial change
  to how the Python side currently gets its token and needs its own small design pass).
- **Packaging**: Xcode build for the Swift `.app`; `PyInstaller` for the Python executable,
  bundled inside the `.app`'s Resources; DMG wrapping the whole thing after.
- **Login item**: Swift app registers via `SMAppService.mainApp.register()` (or
  `SMLoginItemSetEnabled` depending on minimum macOS version — still open, see below).

## Architecture Decisions (confirmed)

### Two processes, Swift-owned lifecycle
The Swift app launches the Python tracker executable as a child process on Start, and
terminates it on Stop or Quit — it does not run independently in the background the way the
original launchd setup did. This is a deliberate choice so the Swift app is the single point
of control and the single thing macOS attributes permissions to.

**Not yet verified, must be checked early and empirically, not assumed:** that macOS actually
attributes Accessibility/Screen Recording permission prompts to the Swift app's identity when
the Python executable is a child process it launches, rather than prompting under the Python
executable's own name. If this doesn't hold, the permission UX will look broken (wrong app
name in the system prompt, or duplicate prompts). This is the single riskiest open item in
this design and should be spiked before committing further engineering time to the rest of
the plan.

### Inter-process communication (Swift ↔ Python)
Kept intentionally simple given the scope — no message bus or IPC framework needed:
- **Swift → Python (start/stop)**: Swift starts/stops the process directly (process
  spawn/terminate) — no separate signal needed for this direction.
- **Python → Swift (status)**: Swift does not need a live channel from Python at all for
  status — it already polls `GET /tracker/sync/status` from the backend, and reads
  `tracker.db` directly (read-only) for the events view. Python writing its own local
  status file is only needed if the Swift app needs to distinguish "child process alive but
  stuck" from "child process cleanly exited" — flagged as an open question, may not be needed
  for v1.

### Three real lifecycle states, not two
- **Running** — Python child process alive and capturing.
- **Paused** — Swift app running, Python child process stopped (via Stop control).
- **Quit** — Swift app terminated (explicit Quit only); Python child process is also
  terminated as part of Quit (no orphaned Python process left running after the Swift app
  exits).
`Paused` and `Quit` must be visually distinguishable on the menu-bar icon alone.

### Process lifecycle mechanics (Swift app)
- `LSUIElement = true` in Info.plist — no Dock icon, not in ⌘-Tab, process persists with
  windows closed.
- `NSStatusItem` (menu-bar icon) is the persistent anchor — hosts Start/Stop/Quit, reachable
  even with the main window closed. Icon reflects Running/Paused/Quit state.
- Main window close (red button) hides, does not terminate the Swift app (and therefore does
  not stop the Python child process either — window-close and tracker-state are independent).
- Quit terminates the Swift app **and** ensures the Python child process is terminated too —
  no orphaned process left behind.

### Memory/performance constraints (explicit, non-negotiable)
- No WebView in the Swift UI.
- Sync-status polling and events refresh are timer-driven (30–60s range), not tight loops.
- Events view refreshes only while the window is visible/foreground.
- Events query is a single bounded fetch (`LIMIT 500`, most recent, `mode=ro`).
- The Python tracker executable's bundled-interpreter footprint is an accepted, known cost —
  scoped to only that one process, not the whole app.

## Commands
- **Run (Dev, Swift)**: build/run via Xcode, or `swift run` if using Swift Package Manager.
- **Run (Dev, Python tracker)**: unchanged — `python main.py` or equivalent, run standalone
  during development before Swift integration is wired.
- **Build (Swift)**: Xcode archive/build.
- **Build (Python)**: `pyinstaller` spec (to be defined) producing the standalone executable.
- **Test**: `make test` (Python side, unchanged); Swift unit tests via `xcodebuild test`.

## Project Structure
- `tracker-app/` -> New Swift Xcode project. Contains UI, menu-bar/window lifecycle,
  Keychain integration, backend API calls, child-process management.
  - `tracker-app/UI/` -> Views/controllers for the 3 surfaces.
  - `tracker-app/UI/Tokens.swift` -> Ported design tokens from the web frontend.
  - `tracker-app/ProcessManager.swift` -> Launches/stops/monitors the Python child process.
- `tracker/` -> Existing Python tracker codebase — **capture/redaction/resolver logic
  unchanged**. Only change needed: how it obtains the sync token (from Keychain instead of
  its current mechanism — see Open Questions).
- `tracker/packaging/pyinstaller/` -> PyInstaller spec/build scripts for the standalone
  executable.
- `tasks/` -> Planning and task management.

## Code Style
- **Swift**: standard Swift API design guidelines, native naming conventions. Docstrings/
  comments follow the same philosophy as the Python side — state WHAT plainly, WHY only when
  a design choice could otherwise look like a mistake and get "fixed" accidentally later.
- **Python** (unchanged, existing convention): wraps at 120 characters, `isort`, no inline
  comments, docstrings only.

## Testing Strategy
- **Swift**: unit-test the state/lifecycle logic (Running/Paused/Quit transitions,
  process-manager start/stop) independent of AppKit rendering where feasible.
- **Python**: existing headless capture-logic test coverage is unchanged (logic itself
  untouched). Add/verify a test for the new Keychain-based token-read path specifically.
- **Integration**: manual + scripted end-to-end check that Swift can actually start, stop,
  and cleanly terminate the Python child process, and that no orphaned process survives Quit.
- **Permissions spike** (see above): a standalone, early empirical check — not a deferred
  nice-to-have — that TCC prompts attribute correctly to the Swift app with Python as a child
  process.

## Boundaries
- **Always**: keep the Python tracker's capture/redaction/classification logic exactly as-is
  in this project — no logic changes beyond the token-read mechanism. Reflect Running/Paused/
  Quit distinctly on the menu-bar icon. Ensure Quit leaves no orphaned Python process.
- **Ask first**: any change to Python capture/redaction logic beyond the token-read change.
  Any IPC mechanism beyond simple process spawn/terminate (if status file requirement in
  "Open Questions" is unexpectedly needed).
- **Never**: store the token in plain text. Trust client-side token validation without
  calling the backend. Use a WebView. Let the Swift app assume the permissions-attribution
  question without verifying it empirically first.

## Success Criteria
- Swift `.app` launches with a menu-bar icon, no Dock icon.
- Closing the main window leaves current tracker state (Running/Paused) unchanged.
- Start launches the Python child process; Stop terminates it (verify via `tracker.db` — no
  new rows while stopped); Quit terminates both the Swift app and the Python child process,
  with no orphan left running.
- User pastes a token, it validates against the backend, is stored in Keychain, and the
  Python child process is able to read/use that same token.
- macOS permission prompts (Accessibility/Screen Recording) attribute to the Swift app's
  identity — confirmed empirically, not assumed.
- Live events view shows the most recent 500 local events, read-only, refreshing only while
  visible.
- Visual style matches the web frontend's design tokens.
- App launches at login via `SMAppService` (or fallback API).

## Future: full Swift migration (explicitly out of scope for this spec)
Once there's bandwidth: convert the Python tracker to Swift **piece by piece** (e.g. app/
window detection, meeting detection, terminal-title redaction, resolvers, DB writes handled
as separate convertible units) — never as one big rewrite. Each converted piece is verified
by running real captured data through both the old Python piece and the new Swift piece and
confirming matching output, before that piece is trusted and the Python equivalent retired.
Only once every piece is converted and verified does the Python child process — and its
bundled-interpreter cost — get removed entirely, at which point the app becomes a single
fully-native Swift process. This is a distinct future project, not a task in this plan.

## Open Questions (need answers before/at implementation start)
- **Permissions attribution** (see above) — needs an early, standalone empirical spike before
  the rest of the plan is trusted to work as designed.
- **Exact token hand-off mechanism**: Swift writes to Keychain; how exactly does the Python
  child process read it? (Keychain access from Python via `keyring`, reading the same
  Keychain item Swift wrote, is the likely answer, but needs confirming — Keychain access
  scoping/entitlements can differ between a GUI app and a bundled command-line executable.)
- **Does Swift need a live status signal from Python**, or is polling `tracker.db` +
  `GET /tracker/sync/status` sufficient to know the child process is healthy? (Affects
  whether the "Python → Swift" IPC line in Architecture stays this simple or needs a status
  file added.)
- Minimum macOS version to target (`SMAppService` vs. `SMLoginItemSetEnabled`).
- Apple Developer ID / signing status — and whether **both** the Swift app and the bundled
  Python executable need signing (likely yes, for the child process to run under Gatekeeper
  inside a distributed DMG).
- DMG hosting location.
- Exact design tokens to port from the web frontend (real values, not placeholders).