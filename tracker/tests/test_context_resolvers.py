"""Resolver tests. Every title string here is real — sampled from the live tracker database, not invented."""

import pytest

from tracker.context import resolve_context
from tracker.context.ide_extension import find_ide_extension_tool
from tracker.context.meet import parse_meet_title
from tracker.context.models import TerminalToolContext
from tracker.context.resolvers import (
    ANTIGRAVITY_BUNDLE_ID, CHROME_BUNDLE_ID, CURSOR_BUNDLE_ID, FIREFOX_BUNDLE_ID, VSCODE_BUNDLE_ID, resolve_generic,
    resolver_for,
)
from tracker.tests.constants import UNKNOWN_BROWSER_BUNDLE_ID


@pytest.fixture(autouse=True)
def _no_extensions(monkeypatch):
    find_ide_extension_tool.cache_clear()
    monkeypatch.setattr("tracker.context.ide_extension.find_ide_extension_tool", lambda pid: None)


def _resolve(bundle_id, app_name, title, document_url=None, pid=None):
    return resolve_context(bundle_id, app_name, window_title=title, document_url=document_url, pid=pid)


class TestVSCode:
    """VS Code puts the project last: `<file> — <project>`."""

    def test_extracts_project_and_file(self):
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "manager.py — logline")
        assert result.detail["project_name"] == "logline"
        assert result.detail["active_file"] == "manager.py"

    def test_project_only_title(self):
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "logline")
        assert result.detail["project_name"] == "logline"
        assert "active_file" not in result.detail

    def test_working_tree_decoration_stripped(self):
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "env.py (Working Tree) (env.py) — logline")
        assert result.detail["active_file"] == "env.py"

    @pytest.mark.parametrize(
        "title",
        [
            "Claude Code — logline",
            "Build local activity tra… — logline",
            "/model — logline",
            "Task: stage, commit, and… — logline",
        ],
    )
    def test_non_file_titles_do_not_become_active_file(self, title):
        """Chat/task/terminal names share the file slot — recording them as active_file would be a guess."""
        result = _resolve(VSCODE_BUNDLE_ID, "Code", title)
        assert result.detail["project_name"] == "logline"
        assert "active_file" not in result.detail

    def test_claude_panel_sets_tool_when_no_file(self, monkeypatch):
        monkeypatch.setattr("tracker.context.terminal.resolve_terminal_tool", lambda pid: None)
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "Claude — logline", document_url="")
        assert result.detail["project_name"] == "logline"
        assert result.detail["tool"] == "claude-code"

    def test_claude_panel_ignored_when_file_is_active(self, monkeypatch):
        monkeypatch.setattr("tracker.context.terminal.resolve_terminal_tool", lambda pid: None)
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "main.py — logline",
                          document_url="file:///Users/dev/project/main.py")
        assert result.detail["active_file"] == "main.py"
        assert "tool" not in result.detail

    def test_integrated_terminal_detects_tool_and_project(self, monkeypatch):
        monkeypatch.setattr(
            "tracker.context.terminal.resolve_terminal_tool",
            lambda pid: TerminalToolContext(tool="codex", cwd="/Users/dev/project", branch="main"),
        )
        monkeypatch.setattr("tracker.context.terminal.project_root_for", lambda cwd: cwd)
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "Terminal — logline", pid=42, document_url="")
        assert result.project_path == "/Users/dev/project"
        assert result.detail["tool"] == "codex"
        assert result.detail["cwd"] == "/Users/dev/project"
        assert result.detail["branch"] == "main"
        assert result.detail["project_name"] == "logline"

    def test_integrated_terminal_falls_back_to_shell_project(self, monkeypatch):
        monkeypatch.setattr(
            "tracker.context.terminal.resolve_terminal_tool",
            lambda pid: TerminalToolContext(tool=None, cwd="/Users/dev/project", branch="main"),
        )
        monkeypatch.setattr("tracker.context.terminal.project_root_for", lambda cwd: cwd)
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "Terminal — logline", pid=42, document_url="")
        assert result.project_path == "/Users/dev/project"
        assert result.detail["cwd"] == "/Users/dev/project"
        assert result.detail["branch"] == "main"
        assert result.detail["project_name"] == "logline"
        assert "tool" not in result.detail

    def test_active_file_wins_over_integrated_terminal(self, monkeypatch):
        monkeypatch.setattr(
            "tracker.context.terminal.resolve_terminal_tool",
            lambda pid: TerminalToolContext(tool="codex", cwd="/Users/dev/project", branch="main"),
        )
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "db.py — logline",
                          document_url="file:///Users/dev/project/db.py")
        assert result.detail["active_file"] == "db.py"
        assert result.detail["project_name"] == "logline"
        assert "tool" not in result.detail

    def test_extension_panel_title_uses_extension_tool_not_terminal(self, monkeypatch):
        """When the title indicates the extension panel is focused, extension tool wins over terminal."""
        monkeypatch.setattr(
            "tracker.context.terminal.resolve_terminal_tool",
            lambda pid: TerminalToolContext(tool="codex", cwd="/Users/dev/project", branch="main"),
        )
        monkeypatch.setattr("tracker.context.terminal.project_root_for", lambda cwd: cwd)
        monkeypatch.setattr(
            "tracker.context.ide_extension.find_ide_extension_tool",
            lambda pid: "claude-code",
        )
        result = _resolve(VSCODE_BUNDLE_ID, "Code", "Claude — logline", document_url="", pid=42)
        assert result.detail["tool"] == "claude-code"


class TestCursor:
    """Cursor is a VSCode fork and uses the same title convention (project last)."""

    def test_extracts_project_and_file(self):
        result = _resolve(CURSOR_BUNDLE_ID, "Cursor", "manager.py — logline")
        assert result.detail["project_name"] == "logline"
        assert result.detail["active_file"] == "manager.py"

    def test_project_only_title(self):
        result = _resolve(CURSOR_BUNDLE_ID, "Cursor", "logline")
        assert result.detail["project_name"] == "logline"
        assert "active_file" not in result.detail

    def test_claude_panel_sets_tool_when_no_file(self, monkeypatch):
        monkeypatch.setattr("tracker.context.terminal.resolve_terminal_tool", lambda pid: None)
        result = _resolve(CURSOR_BUNDLE_ID, "Cursor", "Claude — logline", document_url="")
        assert result.detail["project_name"] == "logline"
        assert result.detail["tool"] == "claude-code"


class TestAntigravity:
    """Antigravity puts the project first — the reverse of VS Code."""

    def test_extracts_project_and_file(self):
        result = _resolve(ANTIGRAVITY_BUNDLE_ID, "Antigravity IDE", "logline — SessionContext.tsx")
        assert result.detail["project_name"] == "logline"
        assert result.detail["active_file"] == "SessionContext.tsx"

    def test_working_tree_decoration_stripped(self):
        result = _resolve(ANTIGRAVITY_BUNDLE_ID, "Antigravity IDE", "logline — db.py (Working Tree) (db.py)")
        assert result.detail["active_file"] == "db.py"

    def test_dotfile_is_a_file(self):
        result = _resolve(ANTIGRAVITY_BUNDLE_ID, "Antigravity IDE", "logline — .env")
        assert result.detail["active_file"] == ".env"

    def test_opposite_order_from_vscode(self):
        """The same string parses to different projects per editor — the regression this guards against."""
        title = "logline — main.py"
        assert resolve_context(ANTIGRAVITY_BUNDLE_ID, "A", title, document_url=None).detail["project_name"] == "logline"
        assert resolve_context(VSCODE_BUNDLE_ID, "C", title, document_url=None).detail["project_name"] == "main.py"


class TestMeetTitles:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Meet - Daily Standup - Camera and microphone recording - Google Chrome - Toheed (arbisoft.com)",
             "Daily Standup"),
            ("Meet - Daily Standup - Microphone recording - Google Chrome - Toheed (arbisoft.com)", "Daily Standup"),
            ("Meet - Daily Standup - Toheed (arbisoft.com)", "Daily Standup"),
            ("Meet - Genesis - OKR Progress Tracking - Camera and microphone recording - Google Chrome - "
             "Toheed (arbisoft.com)", "Genesis - OKR Progress Tracking"),
            ("Meet - Baithak - Microphone recording - Google Chrome - Toheed (arbisoft.com)", "Baithak"),
            ("Meet – Inline AI - IV", "Inline AI - IV"),
        ],
    )
    def test_extracts_meeting_name(self, title, expected):
        is_meeting, name = parse_meet_title(title)
        assert is_meeting is True
        assert name == expected

    def test_memory_usage_noise_stripped(self):
        """Chrome splits 'High memory usage - 801 MB' across two segments; both are noise."""
        title = ("Meet - Daily Standup - Microphone recording - High memory usage - 801 MB - "
                 "Google Chrome - Toheed (arbisoft.com)")
        assert parse_meet_title(title) == (True, "Daily Standup")

    @pytest.mark.parametrize("title", ["Meet", "Meet - Google Chrome - Toheed (arbisoft.com)", "meet.google.com"])
    def test_unnamed_meeting_detected_without_name(self, title):
        is_meeting, name = parse_meet_title(title)
        assert is_meeting is True
        assert name is None

    @pytest.mark.parametrize(
        "title",
        ["Logline-2 - Claude", "Pull requests · ToheedAsghar/Logline", "Zoom Meeting", "", None],
    )
    def test_non_meet_titles_rejected(self, title):
        assert parse_meet_title(title) == (False, None)

    def test_meeting_detected_regardless_of_browser(self):
        for bundle_id in (CHROME_BUNDLE_ID, FIREFOX_BUNDLE_ID, UNKNOWN_BROWSER_BUNDLE_ID):
            result = _resolve(bundle_id, "Browser", "Meet - Daily Standup - Toheed (arbisoft.com)")
            assert result.detail["is_meeting"] is True
            assert result.detail["meeting_name"] == "Daily Standup"


class TestBrowsers:
    def test_chrome_captures_url(self):
        result = _resolve(CHROME_BUNDLE_ID, "Google Chrome", "Meet", document_url="https://meet.google.com/abc-defg")
        assert result.detail["url"] == "https://meet.google.com/abc-defg"

    def test_firefox_records_no_url(self):
        """Firefox advertises AXDocument but returns no value; nothing should be invented."""
        result = _resolve(FIREFOX_BUNDLE_ID, "Firefox", "Logline-2 - Claude", document_url=None)
        assert "url" not in result.detail
        assert result.detail["browser"] == "Firefox"


class TestUnknownApps:
    def test_unrecognized_app_uses_generic_resolver(self):
        assert resolver_for(UNKNOWN_BROWSER_BUNDLE_ID) is resolve_generic
        assert resolver_for("com.tinyspeck.slackmacgap") is resolve_generic

    def test_unrecognized_browser_still_captured_not_skipped(self):
        """Decision #6: an unknown browser must still get title-based capture, never be special-cased away."""
        result = _resolve(UNKNOWN_BROWSER_BUNDLE_ID, "NewBrowser", "Meet - Sprint Review - NewBrowser Nightly")
        assert result.detail["is_meeting"] is True
        assert result.detail["meeting_name"] is not None
        assert result.detail["meeting_name"].startswith("Sprint Review")

    def test_unknown_app_never_raises(self):
        result = _resolve("com.apple.Notes", "Notes", "Notes – 30 notes")
        assert result.project_path is None

    def test_none_title_is_safe(self):
        result = _resolve(VSCODE_BUNDLE_ID, "Code", None)
        assert result.project_path is None
        assert result.detail == {}


class TestResolverIsolation:
    def test_resolver_exception_degrades_to_empty(self, monkeypatch):
        """Expected environmental failures (e.g. OSError / AX bridge) degrade to empty context."""
        import tracker.context as context_pkg

        def boom(ctx):
            raise OSError("AX read failed")

        monkeypatch.setattr(context_pkg, "resolver_for", lambda bundle_id: boom)
        result = resolve_context("com.any.App", "App", "title", document_url=None)
        assert result.project_path is None
        assert result.detail == {}

    def test_programming_error_in_resolver_surfaces(self, monkeypatch):
        """Programming errors in resolvers (KeyError, TypeError, etc.) must surface."""
        import tracker.context as context_pkg

        def boom(ctx):
            raise KeyError("missing_key")

        monkeypatch.setattr(context_pkg, "resolver_for", lambda bundle_id: boom)
        with pytest.raises(KeyError):
            resolve_context("com.any.App", "App", "title", document_url=None)
