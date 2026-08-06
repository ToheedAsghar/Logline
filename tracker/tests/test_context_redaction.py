"""Redacted apps must yield no context, not just no title.

The bug this guards against: `redact_title` nulled a terminal's window title, but the AXDocument read that
backs context resolution was not gated the same way — so a terminal still recorded the project path and git
branch that redacting the title was meant to withhold. Confirmed live: Ghostty reports its shell's working
directory as `AXDocument`.

The current invariant: redacted apps do not read AX in the common single-session case. When foreground processes
span multiple TTYs, one scoped AX read (the focused tab's cwd via AXDocument) is permitted to disambiguate. The
recorded cwd always comes from process facts, never from AX.
"""

import pytest

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS, VSCODE_BUNDLE_ID
from tracker.context import resolve_context
from tracker.redaction import is_redacted, redact_title
from tracker.tests.constants import A_REAL_REPO_FILE, AX_READ_FOR_REDACTED_APP_MSG


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_redacted_app_resolves_no_context_even_with_a_document_url(bundle_id):
    result = resolve_context(bundle_id, "Terminal", window_title=None, document_url=A_REAL_REPO_FILE)
    assert result.project_path is None
    assert result.detail == {}


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_redacted_app_skips_ax_when_walk_is_not_ambiguous(bundle_id, monkeypatch):
    """pid=1234 yields no hits, so the provider is never invoked — AX is untouched."""
    import tracker.context.ax as ax_module

    def fail(pid):
        raise AssertionError(AX_READ_FOR_REDACTED_APP_MSG)

    monkeypatch.setattr(ax_module, "focused_document_url", fail)
    result = resolve_context(bundle_id, "Terminal", window_title=None, pid=1234)
    assert result.detail == {}


class _FakeInfo:
    def __init__(self, pid, tty, foreground, cwd):
        self.pbi_pgid = pid
        self.e_tdev = tty
        self.e_tpgid = pid if foreground else 0


def _build_tree(monkeypatch, processes):
    table = {p[0]: p for p in processes}

    def fake_bsd_info(pid):
        p = table.get(pid)
        if p is None:
            return None
        return _FakeInfo(pid, p[2], p[3], p[4])

    def fake_child_pids(pid):
        p = table.get(pid)
        return list(p[5]) if p else []

    def fake_exec_path_and_argv(pid):
        p = table.get(pid)
        return (p[0], p[1]) if p else (None, [])

    def fake_working_directory(pid):
        p = table.get(pid)
        return p[4] if p else None

    def fake_is_tty_foreground(info):
        return info.e_tdev != 0xFFFFFFFF and info.pbi_pgid == info.e_tpgid

    monkeypatch.setattr("tracker.context.terminal.bsd_info", fake_bsd_info)
    monkeypatch.setattr("tracker.context.terminal.child_pids", fake_child_pids)
    monkeypatch.setattr("tracker.context.terminal.exec_path_and_argv", fake_exec_path_and_argv)
    monkeypatch.setattr("tracker.context.terminal.working_directory", fake_working_directory)
    monkeypatch.setattr("tracker.context.terminal.is_tty_foreground", fake_is_tty_foreground)
    monkeypatch.setattr("tracker.context.ide_extension.bsd_info", lambda pid: None)
    monkeypatch.setattr("tracker.context.ide_extension.child_pids", lambda pid: [])
    monkeypatch.setattr("tracker.context.ide_extension.exec_path_and_argv", lambda pid: (None, []))


class TestRedactionAxBoundary:
    def test_ax_called_only_when_walk_ambiguous(self, monkeypatch):
        """Two TTYs with tools — the focused-cwd provider must be called to disambiguate."""
        calls = []
        _build_tree(monkeypatch, [
            (None, [], 0xFFFFFFFF, False, None, [101, 200]),
            ("/usr/bin/zsh", ["zsh"], 0x11, True, "/Users/dev/project-a", []),
            ("/opt/homebrew/bin/codex", ["codex"], 0x22, True, "/Users/dev/project-b", []),
        ])

        def fake_ax(pid):
            calls.append(pid)
            return "file:///Users/dev/project-a"

        monkeypatch.setattr("tracker.context.ax.focused_document_url", fake_ax)
        result = resolve_context("com.apple.Terminal", "Terminal", window_title=None, pid=100)
        assert calls == [100]
        assert result.detail["tool"] is None
        assert result.detail["cwd"] == "/Users/dev/project-a"

    def test_ax_skipped_when_single_tty(self, monkeypatch):
        """One TTY — the focused-cwd provider must never be invoked."""
        calls = []
        _build_tree(monkeypatch, [
            (None, [], 0xFFFFFFFF, False, None, [101]),
            ("/opt/homebrew/bin/codex", ["codex"], 0x11, True, "/Users/dev/project", []),
        ])

        def fake_ax(pid):
            calls.append(pid)
            return "file:///Users/dev/project"

        monkeypatch.setattr("tracker.context.ax.focused_document_url", fake_ax)
        result = resolve_context("com.apple.Terminal", "Terminal", window_title=None, pid=100)
        assert calls == []
        assert result.detail["tool"] == "codex"
        assert result.detail["cwd"] == "/Users/dev/project"

    def test_ax_value_never_becomes_recorded_cwd(self, monkeypatch):
        """A symlink-focused cwd must not leak into the record — recorded cwd is always the process cwd."""
        _build_tree(monkeypatch, [
            (None, [], 0xFFFFFFFF, False, None, [101, 200]),
            ("/usr/bin/zsh", ["zsh"], 0x11, True, "/private/tmp/real-project", []),
            ("/opt/homebrew/bin/codex", ["codex"], 0x22, True, "/Users/dev/other", []),
        ])
        monkeypatch.setattr("tracker.context.ax.focused_document_url", lambda pid: "file:///tmp/link-to-project")
        result = resolve_context("com.apple.Terminal", "Terminal", window_title=None, pid=100)
        assert result.detail["cwd"] == "/private/tmp/real-project"
        assert "link" not in result.detail["cwd"]


def test_ghostty_is_a_known_terminal():
    """Ghostty exposes its working directory via AXDocument and was the 5th most-recorded app in the live
    database while still being tracked unredacted."""
    assert "com.mitchellh.ghostty" in KNOWN_TERMINAL_BUNDLE_IDS
    assert is_redacted("com.mitchellh.ghostty")
    assert redact_title("com.mitchellh.ghostty", "zsh — export TOKEN=secret") is None


def test_non_redacted_app_still_resolves_context():
    """Regression guard: the gate must not suppress context for ordinary apps."""
    result = resolve_context(VSCODE_BUNDLE_ID, "Code", "db.py — logline", document_url=A_REAL_REPO_FILE)
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
