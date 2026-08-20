## Phase 0: De-risk the core assumption
- [x] **Task 0: Permissions-attribution spike.** Build the smallest possible throwaway harness. (Completed)

## Phase 1: Foundation
- [x] **Task 1: Swift-side Keychain storage.** Native Keychain read/write in Swift.
- [x] **Task 1a: Design tokens.** Pull real color/type-scale/spacing/radius values from the web frontend's design system into `tracker-app/UI/Tokens.swift`.
- [x] **Task 1b: Python token-read mechanism.** Update the Python tracker's token-loading code to read from the standard input stream (`stdin`).

## Phase 2: Swift App Shell
- [x] **Task 2: App shell — menu-bar icon + window lifecycle.** `LSUIElement` in Info.plist; `NSStatusItem` with Start/Stop/Quit menu items.

## Phase 3: Enrollment & Status
- [x] **Task 3: Enrollment logic.** Token field → validate against `GET /tracker/sync/status` → store via Task 1's Keychain wrapper on success → UI shows "Connected as [user]".
- [x] **Task 3a: Disconnect action.** Clears the stored token, reverts to "Not connected".
- [x] **Task 4: Sync status polling.** Timer-driven poll (30–60s) of `GET /tracker/sync/status`, updates status label/menu-bar icon.

## Phase 4: Events View
- [x] **Task 5: Live events view.** Swift reads `tracker.db` directly, read-only (`mode=ro`), single bounded query (`LIMIT 500`, most recent), native `NSTableView` with cell reuse.

## Phase 5: Process Integration
- [x] **Task 6: Wire the real Python child process.** `ProcessManager.swift` launches the PyInstaller-built Python executable on Start, terminates it on Stop/Quit.

## Phase 6: Packaging & DMG
- [x] **Task 7: Packaging & DMG.** Ship a `.dmg` with the Swift app wrapping the PyInstaller-bundled tracker.

## Phase 7: UI Redesign
- [x] **Task 8: UI Redesign.** Implement native AppKit UI to match the Logline Tracker web mockup.
  - [x] Bundle `Space Grotesk` and `JetBrains Mono` fonts natively.
  - [x] Overhaul `Tokens.swift` with exact OKLCH values and custom font modifiers.
  - [x] Update `MainView.swift`, `EnrollmentView.swift`, and `LiveEventsView.swift`.
  - [x] **Observation from 2026-08-20**: Orphaned PIDs from earlier Gateway tests were found concurrently writing to `tracker.db` alongside the active tracker instance. This caused overlapping and duplicate rows in the database. Orphan-detection/cleanup is currently deferred to future work, but this observation elevates its priority.

---

## Known Gaps / Future Enhancements
- `SingleInstanceLock` currently can't distinguish a genuinely orphaned process (parent gone) from a still-supervised one, so a force-quit followed by relaunch requires manual cleanup. (Crash-safe session cleanup follow-up).
- `tracker.sync.agent` currently has no graceful shutdown handling on SIGTERM. It exits immediately with no cleanup.

## Future item: replace manual token-paste enrollment with real sign-in

**Not started. Propose-first required before implementation — new auth surface, same rigor
as Phase 1's Keychain work.**

Idea: replace the current "paste a token" enrollment flow entirely with a real sign-in —
click "Sign in" in the tracker app, authenticate with the same Logline web account (via
`ASWebAuthenticationSession`, Apple's secure system browser sheet — not the app's own
WebView, doesn't conflict with the no-WebView UI decision), get redirected back to the app via
a custom URL scheme (e.g. `logline://auth-callback`), and have the app exchange that for a
real device token automatically, storing it in Keychain the same way as today.

**Full replacement, not a fallback** — the existing token-paste UI, its validation logic, and
the Disconnect flow's local-token-clear step all need to be reworked against this new flow
once built, not kept alongside it.

**New backend requirement**, not just tracker-app work: an endpoint that issues a device token
as the automated last step of the web login redirect (today this token is generated and
copy-pasted manually; this flow needs it issued automatically after a successful login).

**Real security surface, needs the same treatment as Task 0/Phase 1**: OAuth-style redirect
handling has well-known attack surface (state-parameter CSRF, redirect URI validation, custom
URL scheme hijacking on macOS). Needs propose-first, then adversarial security review before
merging — do not treat this as routine UI work.

**Open question to resolve during the propose step**: what does losing access look like once
there's no token field to paste back into — i.e. what's the re-authentication UX when a
session expires or Disconnect is used, given there's no more manual fallback path.

**Sequencing**: this is separate from the current tracker-desktop-app branch (Task 6/7) and
should not be pulled into it — scope as its own task once the current branch is fully merged.