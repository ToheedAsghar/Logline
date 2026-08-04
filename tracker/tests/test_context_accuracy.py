"""Capture-accuracy regressions found reviewing the rich-context work.

Each class documents one way the resolvers recorded something they had not actually observed.
"""

import pytest

from tracker.context import resolve_context
from tracker.context.meet import parse_meet_title
from tracker.context.resolvers import ANTIGRAVITY_BUNDLE_ID, VSCODE_BUNDLE_ID
from tracker.tests.constants import UNKNOWN_BROWSER_BUNDLE_ID


def _active_file(title):
    return resolve_context(ANTIGRAVITY_BUNDLE_ID, "Antigravity IDE", title, document_url=None).detail.get(
        "active_file"
    )


class TestActiveFileIsNotProse:
    """The bug: `^[^/\\\\]*\\.[A-Za-z0-9_+-]{1,12}$` matched any string with a dot near the end, so chat and
    task names sharing the file slot were recorded as `active_file` — exactly the guess `_clean_active_file`
    exists to prevent."""

    @pytest.mark.parametrize(
        "title",
        [
            "logline — Chat about auth.py",
            "logline — Refactor the db.py",
            "logline — Fix bug in main.py and models.py",
            "logline — TODO: rename manager.py",
            "logline — Release notes v1.2",
            "logline — Meeting 2026.07",
            "logline — 3.14",
        ],
    )
    def test_prose_is_not_an_active_file(self, title):
        assert _active_file(title) is None

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("logline — db.py", "db.py"),
            ("logline — .env", ".env"),
            ("logline — SessionContext.tsx", "SessionContext.tsx"),
            ("logline — package-lock.json", "package-lock.json"),
            ("logline — main.test.ts", "main.test.ts"),
            ("logline — archive.7z", "archive.7z"),
        ],
    )
    def test_real_file_names_still_captured(self, title, expected):
        assert _active_file(title) == expected


class TestMeetingsAreNotDetectedInEditors:
    """The bug: `_apply_meet` ran inside `resolve_generic`, so every resolver inherited it and an editor
    window could be tagged as a meeting."""

    @pytest.mark.parametrize(
        "title",
        ["meet.google.com-notes.md — logline", "Meet - Daily Standup — logline"],
    )
    def test_editor_titles_are_never_meetings(self, title):
        result = resolve_context(VSCODE_BUNDLE_ID, "Code", title, document_url=None)
        assert "is_meeting" not in result.detail
        assert "meeting_name" not in result.detail

    def test_unknown_app_still_detects_meetings(self):
        """Decision #6 stands: an unrecognized app may be a browser, so detection stays on by default."""
        result = resolve_context(UNKNOWN_BROWSER_BUNDLE_ID, "NewBrowser", "Meet - Sprint Review", document_url=None)
        assert result.detail["is_meeting"] is True


class TestMeetHostMustBeTheWholeTitle:
    """The bug: a bare `meet.google.com` substring check tagged any title mentioning the host as a meeting,
    and short-circuited before segment parsing so a real meeting name was thrown away."""

    @pytest.mark.parametrize(
        "title",
        [
            "How to use meet.google.com for standups - Google Chrome",
            "meet.google.com-notes.md",
            "Why meet.google.com beats Zoom - Blog",
        ],
    )
    def test_mentioning_the_host_is_not_a_meeting(self, title):
        assert parse_meet_title(title) == (False, None)

    @pytest.mark.parametrize(
        "title", ["meet.google.com", "https://meet.google.com/abc-defg", "meet.google.com/abc-defg"]
    )
    def test_the_url_alone_is_a_lobby_tab(self, title):
        assert parse_meet_title(title) == (True, None)

    def test_meeting_name_survives_a_trailing_host_segment(self):
        """Previously returned (True, None) — the name was lost."""
        assert parse_meet_title("Meet - Daily Standup - meet.google.com") == (True, "Daily Standup")
