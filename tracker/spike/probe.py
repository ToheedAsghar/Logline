import ApplicationServices as AS
import Cocoa

def main():
    options = {AS.kAXTrustedCheckOptionPrompt: False}
    trusted = AS.AXIsProcessTrustedWithOptions(options)
    print(f"Is trusted (bool): {trusted}")
    if trusted:
        system_wide = AS.AXUIElementCreateSystemWide()
        error, focused_app = AS.AXUIElementCopyAttributeValue(system_wide, "AXFocusedApplication", None)
        print(f"Focused app error code: {error}")
        if error == 0 and focused_app is not None:
            print("Successfully exercised Accessibility API.")
        else:
            print("Failed to exercise Accessibility API despite being 'trusted'.")
    else:
        print("Not trusted.")

if __name__ == "__main__":
    main()
