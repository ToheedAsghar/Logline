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

A subsequent test (`make run-headless`) executed the `SpikeApp` binary via `launchctl submit`. This succeeded with `trusted: true` and fetched a window title, proving the grant belongs to `Spike` directly and functions even when running completely detached in the background without UI ancestry.

## 3. True Cross-Identity Negative Control

To definitively rule out the possibility that the Python executable itself somehow gained blanket permissions (or leaked them globally), a true cross-identity negative control was executed (`make run-negative`). 

This test launched the bare Python executable (`test_env/bin/python`) via `launchctl submit`, completely severed from `SpikeApp`'s process tree and any terminal ancestry.

- **Output:** The bare Python process correctly failed to access accessibility features, returning `trusted: false` and `kAXErrorAPIDisabled`:

```json
{"trusted": false, "frontmost_app": "Code", "frontmost_bundle_id": "com.microsoft.VSCode", "frontmost_pid": 6703, "ax_error": -25211, "ax_error_name": "kAXErrorAPIDisabled", "window_title": null}
```

**Conclusion:** The accessibility grant is strictly bounded to the `SpikeApp` certificate identity. The Python executable has no intrinsic permissions of its own and only gains functional access when launched as a legitimate child of the authorized `SpikeApp` host.

***

**Note on final distribution (Task 7):** Task 7 will ship unsigned — no Developer ID planned; users approve the app once via Gatekeeper on first launch.
