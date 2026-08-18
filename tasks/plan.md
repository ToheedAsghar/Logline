# Implementation Plan: Packaged Tracker App (Swift Shell + Python Child Process)

## Overview
Implements `tasks/spec.md`. Swift native app owns UI/lifecycle/Keychain/backend calls; the
existing, unchanged Python tracker runs as a child process the Swift app starts and stops.
Revised from an earlier single-process Python/PyObjC draft after deciding Swift is the right
stack for the app shell (native memory/tooling/permissions), while keeping the already-tested
Python capture logic as-is rather than risking a rewrite.

## Architecture Decisions
- **Two processes**: Swift app (main, signed, visible) + Python tracker (child, existing
  logic unchanged, packaged standalone via PyInstaller with its own bundled interpreter).
- **Swift owns the lifecycle**: starts the Python process on Start, kills it on Stop or Quit.
  No independent always-on Python daemon.
- **IPC kept minimal**: Swift → Python is just process spawn/terminate. Python → Swift status
  comes from polling `GET /tracker/sync/status` + reading `tracker.db` directly — no custom
  message channel unless the permissions spike or later testing shows it's actually needed.
- **Token storage**: Keychain, written by Swift. Python reads the same Keychain item — exact
  mechanism is an open question resolved in Task 1b below, not assumed upfront.
- **Three lifecycle states**: Running / Paused / Quit, each visually distinct on the menu-bar
  icon.
- **UI**: native AppKit (Swift), no WebView. Design tokens ported from the web frontend.
- **The riskiest unknown in this whole design is permissions attribution** — whether macOS
  correctly attributes Accessibility/Screen Recording prompts to the Swift app when Python is
  a child process. This is deliberately sequenced as Task 0, before any other real work,
  because if it doesn't hold, the process-boundary design needs to be revisited before
  building on top of it.

## Task List

### Phase 0: De-risk the core assumption
- [ ] **Task 0: Permissions-attribution spike.** Build the smallest possible throwaway
  harness — a minimal Swift app that launches a minimal Python child process which requests
  one TCC-gated permission (e.g. Accessibility). Confirm empirically which app identity the
  system permission prompt shows, and confirm the grant persists correctly across relaunches
  of the child process (not just first-run). **This is a go/no-go gate for the two-process
  design as specced** — if attribution doesn't work as expected, architecture needs
  revisiting (e.g. XPC service, or a signing/entitlements adjustment) before Phase 1 starts.
  - Acceptance: documented, empirical (screenshots/logs) confirmation of what the permission
    prompt shows and that it persists correctly — not a theoretical read of Apple docs.

### Checkpoint: De-risk
- [ ] Task 0 passed cleanly, OR a revised process/permissions approach is documented and
  approved before continuing.

### Phase 1: Foundation
- [ ] **Task 1: Swift-side Keychain storage.** Native Keychain read/write in Swift
  (`Security` framework or a thin Swift wrapper) for the sync token — `storeToken()`,
  `getToken()`, `clearToken()`.
- [ ] **Task 1a: Design tokens.** Pull real color/type-scale/spacing/radius values from the
  web frontend's design system into `tracker-app/UI/Tokens.swift`. Independent of Task 1, can
  run in parallel.
- [ ] **Task 1b: Python token-read mechanism.** Update the Python tracker's token-loading code
  to read from the standard input stream (`stdin`) instead of its current file-based mechanism. The Swift `ProcessManager` will pipe the token securely to the agent on launch. **This is the only planned change to the
  Python codebase in this entire project** — everything else in `tracker/` stays as-is.

### Checkpoint: Foundation
- [ ] Swift can store/retrieve/clear a token via Keychain, verified in Keychain Access.
- [ ] `Tokens.swift` contains real ported values, reviewed against the web frontend.
- [ ] Python (built via PyInstaller) can read a token Swift wrote to Keychain — real
  cross-process verification, not assumed.

### Phase 2: Swift App Shell
- [ ] **Task 2: App shell — menu-bar icon + window lifecycle.** `LSUIElement` in Info.plist;
  `NSStatusItem` with Start/Stop/Quit menu items; main window hides (not terminates) on close.
  Window contains placeholders for the three surfaces, styled per `Tokens.swift`. Establishes
  the Running/Paused/Quit state model and icon representation (state can be stubbed here,
  wired to the real Python process in Task 6).
  - Acceptance: no Dock icon; menu-bar icon present; closing window leaves process running
    (verify in Activity Monitor); Quit terminates; icon visibly differs across the three
    states.

### Phase 3: Enrollment & Status
- [ ] **Task 3: Enrollment logic.** Token field → validate against
  `GET /tracker/sync/status` → store via Task 1's Keychain wrapper on success → UI shows
  "Connected as [user]". Failure shows an explicit error, stores nothing.
- [ ] **Task 3a: Disconnect action.** Clears the stored token, reverts to "Not connected".
  (Open question carried from spec: local-clear-only vs. also calling
  `DELETE /tracker/devices/{id}` server-side — confirm before or during this task.)
- [ ] **Task 4: Sync status polling.** Timer-driven poll (30–60s) of
  `GET /tracker/sync/status`, updates status label/menu-bar icon.

### Checkpoint: Enrollment & Status
- [ ] End-to-end: paste valid token → validates → Keychain write → UI shows Connected →
  polling reflects real backend state. Invalid token errors cleanly. Disconnect works.

### Phase 4: Events View
- [ ] **Task 5: Live events view.** Swift reads `tracker.db` directly, read-only (`mode=ro`),
  single bounded query (`LIMIT 500`, most recent), native `NSTableView` with cell reuse.
  Refreshes only while window is visible/foreground.

### Checkpoint: Events View
- [ ] Real events (from a manually-run Python tracker instance) appear correctly; confirmed no
  refresh/query activity while window is hidden (verify via logging, not assumption).

### Phase 5: Process Integration
- [ ] **Task 6: Wire the real Python child process.** `ProcessManager.swift` launches the
  PyInstaller-built Python executable on Start, terminates it on Stop/Quit. Wires the
  Task 2 stub state model to real process state. Python reads its token per Task 1b.
  - Acceptance: Stop actually halts the Python process (verify via `tracker.db` — no new rows
    while Paused, and verify the OS process is actually gone, not just unresponsive); Start
    relaunches cleanly; Quit terminates both the Swift app and the Python process with zero
    orphaned processes left (verify via `ps`/Activity Monitor after Quit, every time —
    this is a common failure mode for parent/child process teardown and deserves explicit,
    repeated verification, not a single spot-check).

### Checkpoint: Process Integration
- [ ] Full real flow: launch app → enroll → Start → real activity captured and synced →
  visible in both events view and backend → Stop halts capture → Quit leaves no orphan
  process.

### Task 7: Packaging & DMG (Phase 4)
- **Goal**: Ship a `.dmg` with the Swift app wrapping the PyInstaller-bundled tracker.
- **Steps**:
  - Add `pyinstaller` to a new `Makefile` target. Build the Python app into a single executable.
  - Update Swift `ProcessManager` to point to the bundled executable (`Bundle.main.url(forResource:...)`) in production, retaining the `.venv` path for dev.
  - Create `Release` build scheme for Swift.
  - Generate an unsigned `.dmg` (e.g., using `create-dmg`). 
  - **Note:** Task 7 will ship unsigned — no Developer ID planned; users approve the app once via Gatekeeper on first launch, and will grant Keychain access once per app update (accepted trade-off). (right-click -> Open).
  - Acceptance: double-click launches with no Dock icon, menu-bar icon present, Start/Stop/
    Quit and all prior-phase behavior intact in the fully packaged build.

### Checkpoint: Complete
- [ ] All acceptance criteria in spec.md met.
- [ ] Ready for review.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Permissions don't attribute to the Swift app as expected | High | Task 0 spikes this first, before any other work — go/no-go gate. |
| Orphaned Python process survives Quit | Med-High | Explicit, repeated `ps`/Activity Monitor verification in Task 6 and Task 7 checkpoints, not a single spot-check. |
| PyInstaller-bundled executable can't read Keychain the same way `python main.py` can in dev | Med | Task 1b explicitly verifies against the bundled executable, not just dev-mode script. |
| Unsigned child executable blocked by Gatekeeper inside a signed parent app | Med | Task 7 explicitly signs and verifies both binaries, not just the Swift app. |
| Menu-bar icon states (Running/Paused/Quit) ambiguous | Low-Med | Explicit distinct-icon acceptance criteria in Task 2 and Task 6. |
| Events view polling while hidden (memory/CPU regression) | Med | Explicit verification requirement in Task 5 checkpoint. |

## Open Questions (carried from spec.md — resolve before or during relevant task)
- Whether Python → Swift needs a live status signal beyond DB-polling + backend status
  (affects Task 6's IPC scope).
- Minimum macOS version (affects Task 2's login-item API choice).
- DMG hosting location (affects distribution, not development).
- Disconnect (Task 3a): local-clear-only vs. also server-side revoke.

## Future work (explicitly not part of this plan)
Full Swift migration of the tracking logic itself — piece-by-piece conversion, each piece
verified against real data against its Python original before the Python version is retired.
See spec.md "Future: full Swift migration." Not scheduled, not scoped here.