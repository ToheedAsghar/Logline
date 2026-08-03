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


def test_context_detail_rejects_unapproved_keys():
    from tracker.context.models import ContextResult

    result = ContextResult(detail={"tool": "codex", "window_title": "SECRET", "args": "SECRET"})
    assert result.detail == {"tool": "codex"}


def test_storage_boundary_strips_unapproved_detail_keys(conn):
    from tracker.session.models import Session
    from tracker.storage import db

    session = Session(
        id="s1", bundle_id="com.apple.Terminal", app_name="Terminal", window_title=None,
        started_at="2026-08-03T10:00:00", ended_at="2026-08-03T10:01:00", end_reason="title_change",
        context_detail={"tool": "codex", "window_title": "SECRET"},
    )
    db.close_open_session(conn, session)
    row = conn.execute("SELECT context_detail FROM sessions").fetchone()
    assert "SECRET" not in row[0]
    assert db._decode_context(row[0]) == {"tool": "codex"}
