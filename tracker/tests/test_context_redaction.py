"""Redacted apps must yield no context, not just no title.

The bug this guards against: `redact_title` nulled a terminal's window title, but the AXDocument read that
backs context resolution was not gated the same way — so a terminal still recorded the project path and git
branch that redacting the title was meant to withhold. Confirmed live: Ghostty reports its shell's working
directory as `AXDocument`.
"""

import pytest

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS
from tracker.context import resolve_context
from tracker.redaction import is_redacted, redact_title

A_REAL_REPO_FILE = "file:///Users/toheed.asghar/Documents/projects/logline/tracker/storage/db.py"


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_redacted_app_resolves_no_context_even_with_a_document_url(bundle_id):
    result = resolve_context(bundle_id, "Terminal", window_title=None, document_url=A_REAL_REPO_FILE)
    assert result.project_path is None
    assert result.detail == {}


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_redacted_app_never_reaches_the_accessibility_read(bundle_id, monkeypatch):
    """The gate has to short-circuit before the AX call, not just discard its result."""
    import tracker.context.ax as ax_module

    def fail(pid):
        raise AssertionError("AXDocument was read for a redacted app")

    monkeypatch.setattr(ax_module, "focused_document_url", fail)
    result = resolve_context(bundle_id, "Terminal", window_title=None, pid=1234)
    assert result.detail == {}


def test_ghostty_is_a_known_terminal():
    """Ghostty exposes its working directory via AXDocument and was the 5th most-recorded app in the live
    database while still being tracked unredacted."""
    assert "com.mitchellh.ghostty" in KNOWN_TERMINAL_BUNDLE_IDS
    assert is_redacted("com.mitchellh.ghostty")
    assert redact_title("com.mitchellh.ghostty", "zsh — export TOKEN=secret") is None


def test_non_redacted_app_still_resolves_context():
    """Regression guard: the gate must not suppress context for ordinary apps."""
    result = resolve_context("com.microsoft.VSCode", "Code", "db.py — logline", document_url=A_REAL_REPO_FILE)
    assert result.project_path is not None
