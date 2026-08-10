"""Tuning values for turning raw local tracker sessions into readable blocks.

Centralized here so the merge threshold below isn't a magic number buried in
aggregation logic -- anyone tuning it later should be able to find and reason
about it in one place.

`KNOWN_IDE_BUNDLE_IDS` and `KNOWN_TERMINAL_BUNDLE_IDS` are duplicated from tracker/constants.py rather than
imported: the tracker is a separate top-level desktop-app project (see backend/CLAUDE.md), and the backend
has no dependency on it. Keep both lists in sync by hand if the tracker adds a new IDE or terminal.
"""

MERGE_GAP_THRESHOLD_MINUTES = 15

MICRO_IDLE_ABSORB_SECONDS = 5

KNOWN_IDE_BUNDLE_IDS = frozenset(
    {
        "com.microsoft.VSCode",
        "com.todesktop.1500222257.65536",
        "com.google.antigravity-ide",
    }
)

KNOWN_TERMINAL_BUNDLE_IDS = frozenset(
    {
        "com.apple.Terminal",
        "com.googlecode.iterm2",
        "com.mitchellh.ghostty",
        "dev.warp.Warp-Stable",
        "net.kovidgoyal.kitty",
        "org.alacritty",
        "com.github.wez.wezterm",
        "co.zeit.hyper",
    }
)

IDLE_BUNDLE_IDS = frozenset(
    {
        "com.apple.loginwindow",
        "com.apple.SecurityAgent",
    }
)

KNOWN_COMMS_BUNDLE_IDS = frozenset(
    {
        "com.tinyspeck.slackmacgap",
        "com.hnc.Discord",
        "net.whatsapp.WhatsApp",
        "com.microsoft.Outlook",
    }
)

KNOWN_MEETING_BUNDLE_IDS = frozenset(
    {
        "us.zoom.xos",
        "com.microsoft.teams",
        "com.microsoft.teams2",
    }
)

CONTEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("branch", "branches"),
    ("project_name", "project_names"),
    ("active_file", "active_files"),
    ("tool", "tools"),
    ("url", "urls"),
    ("cwd", "cwds"),
    ("browser", "browsers"),
    ("end_reason", "end_reasons"),
    ("bundle_id", "bundle_ids"),
)
