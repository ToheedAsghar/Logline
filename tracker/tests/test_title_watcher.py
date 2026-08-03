"""Regression tests for TitleWatcher's exception isolation, nullable-field guards,
and the bundle-identity-aware dedup fix."""

import tracker.watchers.title_watcher as title_watcher_module
from tracker.context.models import ContextResult
from tracker.session.manager import SessionManager
from tracker.tests.conftest import all_sessions
from tracker.watchers.title_watcher import TitleWatcher


class _FakeFrontmost:
    def __init__(self, bundle_id, name, pid=1):
        self.bundle_id = bundle_id
        self.name = name
        self.pid = pid

    def bundleIdentifier(self):
        return self.bundle_id

    def localizedName(self):
        return self.name

    def processIdentifier(self):
        return self.pid


class _StubWorkspace:
    def __init__(self, frontmost):
        self.frontmost = frontmost

    def frontmostApplication(self):
        return self.frontmost


class _StubNSWorkspace:
    """Stands in for AppKit.NSWorkspace — production code only ever calls
    .sharedWorkspace().frontmostApplication() on it."""

    def __init__(self, frontmost):
        self.instance = _StubWorkspace(frontmost)

    def sharedWorkspace(self):
        return self.instance


class TestExceptionIsolation:
    """One bad callback invocation must not crash the whole process — a
    subsequent poll has to still get through."""

    def test_callback_exception_is_swallowed_and_watcher_keeps_polling(self, monkeypatch):
        calls = []

        def flaky(bundle_id, app_name, window_title, context=None):
            calls.append((bundle_id, window_title))
            if len(calls) == 1:
                raise RuntimeError("boom")

        watcher = TitleWatcher(callback=flaky)
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: False)

        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.A", "App A"))
        )
        watcher._poll()  # raises inside the callback — must not propagate

        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.B", "App B"))
        )
        watcher._poll()  # proves polling continues afterward

        assert len(calls) == 2


class TestCoalescesNullableFields:
    """bundle_id/app_name must never reach the callback as None — SessionManager
    and storage both assume real strings."""

    def test_none_bundle_id_and_app_name_coalesce_to_placeholders(self, monkeypatch):
        calls = []
        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: False)
        monkeypatch.setattr(title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost(None, None)))

        watcher._poll()

        assert len(calls) == 1
        assert calls[0]["bundle_id"] == "unknown"
        assert calls[0]["app_name"] == "Unknown"
        assert calls[0]["window_title"] is None
        assert calls[0]["context"].project_path is None

    def test_coalesced_values_dont_crash_on_session_close(self, monkeypatch, conn):
        """The bug this guards against: a None bundle_id/app_name flows through
        fine while a session is only *open*, then blows up with
        sqlite3.IntegrityError the moment it's closed into `sessions`, which
        requires NOT NULL bundle_id/app_name."""
        manager = SessionManager(conn)
        watcher = TitleWatcher(callback=manager.on_title_changed)
        manager._open_session(bundle_id="com.example.Foo", app_name="Foo", window_title="a.txt")

        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: False)
        monkeypatch.setattr(title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost(None, None)))
        watcher._poll()  # opens a coalesced-identity session ("unknown"/"Unknown")

        assert manager._open.bundle_id == "unknown"

        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: True)
        monkeypatch.setattr(title_watcher_module, "_focused_window_title", lambda pid: "now with a title")
        watcher._poll()  # closes the coalesced session into `sessions` — must not raise

        closed = all_sessions(conn)
        assert any(row["bundle_id"] == "unknown" for row in closed)


class TestTitleDedupIncludesAppIdentity:
    """The bug: comparing only the title string meant switching to a different
    app with an identical window title (e.g. two blank "Untitled" documents)
    silently suppressed a real title_change event."""

    def test_same_title_different_app_still_fires_title_change(self, monkeypatch):
        calls = []
        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: True)
        monkeypatch.setattr(title_watcher_module, "_focused_window_title", lambda pid: "Untitled")

        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.A", "App A"))
        )
        watcher._poll()

        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.B", "App B"))
        )
        watcher._poll()

        assert len(calls) == 2
        assert calls[0]["bundle_id"] == "com.example.A"
        assert calls[1]["bundle_id"] == "com.example.B"
        assert calls[0]["window_title"] == calls[1]["window_title"] == "Untitled"

    def test_reset_forces_the_next_poll_to_re_emit(self, monkeypatch):
        """The bug: an app switch opens a session with no context, and only a title_change carries context
        in. Switching away and back inside one poll interval left the title unchanged, so dedup suppressed
        the event and that session kept NULL context for its whole lifetime."""
        calls = []
        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: True)
        monkeypatch.setattr(title_watcher_module, "_focused_window_title", lambda pid: "manager.py — logline")
        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.microsoft.VSCode", "Code"))
        )

        watcher._poll()
        watcher._poll()  # unchanged — still suppressed
        assert len(calls) == 1

        watcher.reset()  # what on_app_activated does after a switch back
        watcher._poll()

        assert len(calls) == 2
        assert calls[1]["window_title"] == "manager.py — logline"
        assert calls[1]["context"].detail["project_name"] == "logline"

    def test_identical_polls_of_the_same_app_still_suppress_duplicates(self, monkeypatch):
        """Regression guard: the fix must not turn every poll into an event —
        the same app reporting the same title twice in a row is still a no-op."""
        calls = []
        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: True)
        monkeypatch.setattr(title_watcher_module, "_focused_window_title", lambda pid: "Untitled")
        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.A", "App A"))
        )

        watcher._poll()
        watcher._poll()

        assert len(calls) == 1


class TestTerminalDetectionPolling:
    def test_redacted_terminal_rechecks_detection_each_poll(self, monkeypatch):
        calls = []
        resolver_calls = []
        state = [{"tool": "codex", "cwd": "/one"}, {"tool": "codex", "cwd": "/two"}]

        def fake_resolve(**kwargs):
            resolver_calls.append(kwargs["pid"])
            detail = state[min(len(resolver_calls) - 1, len(state) - 1)]
            result = ContextResult()
            for key, value in detail.items():
                result.set(key, value)
            return result

        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: False)
        monkeypatch.setattr(title_watcher_module, "resolve_context", fake_resolve)
        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.apple.Terminal", "Terminal"))
        )

        watcher._poll()
        watcher._poll()

        assert resolver_calls == [1, 1]
        assert len(calls) == 2
        assert calls[0]["context"].detail["cwd"] == "/one"
        assert calls[1]["context"].detail["cwd"] == "/two"

    def test_unexpected_context_error_does_not_escape_poll(self, monkeypatch):
        calls = []
        watcher = TitleWatcher(callback=lambda **kwargs: calls.append(kwargs))
        monkeypatch.setattr(title_watcher_module, "_is_trusted", lambda prompt: False)

        def fail(**kwargs):
            raise RuntimeError()

        monkeypatch.setattr(title_watcher_module, "resolve_context", fail)
        monkeypatch.setattr(
            title_watcher_module, "NSWorkspace", _StubNSWorkspace(_FakeFrontmost("com.example.App", "App"))
        )

        watcher._poll()

        assert len(calls) == 1
        assert calls[0]["context"].detail == {}
