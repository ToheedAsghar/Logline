"""Accessibility diagnostic. Prints, as JSON, whether this process can actually read window titles — the one thing the
tracker silently degrades on.

Run it the same way the tracker itself is launched (terminal, .app bundle, launchd) to find out how macOS attributes the
Accessibility grant for that launch path. `trusted` false or `ax_error` -25211 (kAXErrorAPIDisabled) both mean titles
will record as NULL.

    python -m tracker.ax_probe
"""

import json

import ApplicationServices as AS
from AppKit import NSWorkspace

AX_ERROR_NAMES = {
    0: "kAXErrorSuccess",
    -25200: "kAXErrorFailure",
    -25201: "kAXErrorIllegalArgument",
    -25202: "kAXErrorInvalidUIElement",
    -25204: "kAXErrorCannotComplete",
    -25205: "kAXErrorAttributeUnsupported",
    -25211: "kAXErrorAPIDisabled",
    -25212: "kAXErrorNoValue",
}


def probe() -> dict:
    """Mirrors tracker.watchers.title_watcher's trust check and title read so the result reflects the tracker's real
    behaviour, not a more permissive approximation."""
    result = {
        "trusted": bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: False})),
        "frontmost_app": None,
        "frontmost_bundle_id": None,
        "frontmost_pid": None,
        "ax_error": None,
        "ax_error_name": None,
        "window_title": None,
    }

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return result
    result["frontmost_app"] = str(app.localizedName() or "")
    result["frontmost_bundle_id"] = str(app.bundleIdentifier() or "")
    result["frontmost_pid"] = int(app.processIdentifier())

    element = AS.AXUIElementCreateApplication(result["frontmost_pid"])
    err, window = AS.AXUIElementCopyAttributeValue(element, AS.kAXFocusedWindowAttribute, None)
    result["ax_error"] = int(err)
    result["ax_error_name"] = AX_ERROR_NAMES.get(int(err), str(err))
    if err != AS.kAXErrorSuccess or window is None:
        return result

    err, title = AS.AXUIElementCopyAttributeValue(window, AS.kAXTitleAttribute, None)
    result["ax_error"] = int(err)
    result["ax_error_name"] = AX_ERROR_NAMES.get(int(err), str(err))
    if err == AS.kAXErrorSuccess and title is not None:
        result["window_title"] = str(title)
    return result


def main() -> int:
    result = probe()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["trusted"] and result["window_title"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
