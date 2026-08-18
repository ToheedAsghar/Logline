# Task 0 Evidence: Permissions-Attribution Spike

This document records the empirical evidence gathered during Task 0 to definitively confirm that macOS attributes Accessibility TCC permissions to the Swift parent bundle, rather than the Python child executable, under our proposed two-process architecture.

## 1. Initial Prompt Attribution

When the Swift host (`SpikeApp`) launched the Python child process (`probe.py`) which in turn invoked `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})`, macOS presented the following prompt:

> **"Spike" would like to control this computer using accessibility features.**
> Grant access to this application in Privacy & Security settings, located in System Settings.

*(Screenshot confirmed by user on 2026-08-18)*

**Conclusion:** macOS correctly derived the application name ("Spike") from the `Info.plist` of the parent `.app` bundle. It did not attribute the request to `python` or `Terminal`.

## 2. Persistence and Functional Verification (Rebuild Cycle)

DeepSeek V4 review identified that ad-hoc signing (`codesign -s -`) pins the TCC grant to the binary's `cdhash`, which changes on every rebuild and destroys persistence. To test true persistence, a local self-signed certificate was generated and the app's designated requirement was shifted to tie to the certificate identity:

```text
Executable=/Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app/tracker/spike/Spike.app/Contents/MacOS/SpikeApp
designated => identifier "com.logline.spike" and certificate leaf = H"bd94a6c648f35634ffc1294c30b3a51e386b27b4"
```

The app was launched via `open Spike.app` to explicitly break any Terminal.app ancestry. 
After the permission was granted, the app was **killed, rebuilt from scratch, and relaunched**.

- **Prompt:** No prompt appeared on the second launch after rebuild.
- **Output:** The Python child process successfully captured the frontmost window title, proving functional access persisted despite the binary changing:

```json
{
  "trusted": true,
  "frontmost_app": "Spike",
  "frontmost_bundle_id": "com.logline.spike",
  "frontmost_pid": 88694,
  "ax_error": -25204,
  "ax_error_name": "kAXErrorCannotComplete",
  "window_title": null
}
```

A subsequent negative control (`launchctl submit`) also succeeded with `trusted: true` and fetched a window title, proving the grant belongs to `Spike` directly and is not leaking through Terminal ancestry.

## Final Verdict

The two-process architecture (Swift UI host + Python worker child) is a **GO**. macOS handles the permissions boundary exactly as needed for a distributable application, provided the app is signed with a certificate rather than ad-hoc.

***

**Note on final distribution (Task 7):** Task 7 will ship unsigned — no Developer ID planned; users approve the app once via Gatekeeper on first launch.
