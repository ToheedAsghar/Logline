"""The session state machine: holds exactly one open session in memory at a time.
Any boundary event closes the open session and may open a new one."""

import uuid
from datetime import datetime
from typing import Optional

from Foundation import NSTimer

from tracker.constants import HEARTBEAT_INTERVAL_SECONDS
from tracker.session.models import Session
from tracker.storage import db


def _iso(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now().astimezone()).isoformat(timespec="seconds")


class SessionManager:
    def __init__(self, conn):
        self._conn = conn
        self._open: Optional[Session] = None
        self._timer = None

        sealed = db.seal_dangling_session(self._conn)
        if sealed is not None:
            print(f"sealed dangling session from previous run: {sealed.app_name} ({sealed.bundle_id})")

    def _open_session(
        self,
        bundle_id: str,
        app_name: str,
        window_title: Optional[str] = None,
        started_at: Optional[str] = None,
        is_idle: bool = False,
    ) -> None:
        when = started_at or _iso()
        self._open = Session(
            id=str(uuid.uuid4()),
            bundle_id=bundle_id,
            app_name=app_name,
            window_title=window_title,
            started_at=when,
            ended_at=when,
            is_idle=is_idle,
        )
        db.insert_open_session(self._conn, self._open)

    def _close_open(self, end_reason: str, ended_at: Optional[str] = None) -> None:
        if self._open is None:
            return
        self._open.ended_at = ended_at or _iso()
        self._open.end_reason = end_reason
        db.close_open_session(self._conn, self._open)
        self._open = None

    def on_app_activated(self, bundle_id: str, app_name: str) -> None:
        self._close_open(end_reason="switch")
        self._open_session(bundle_id=bundle_id, app_name=app_name)

    def on_title_changed(self, bundle_id: str, app_name: str, window_title: Optional[str]) -> None:
        was_idle = self._open.is_idle if self._open else False
        self._close_open(end_reason="title_change")
        self._open_session(bundle_id=bundle_id, app_name=app_name, window_title=window_title, is_idle=was_idle)

    def on_idle_start(self, stopped_at: datetime) -> None:
        """Closes the active session backdated to when input actually stopped, then
        opens an idle session starting at that same moment. Reuses the just-closed
        session's identity: nothing else could have become frontmost during a span
        with no keyboard/mouse input to trigger a switch."""
        if self._open is None:
            return
        opened_at = datetime.fromisoformat(self._open.started_at)
        if stopped_at <= opened_at:
            self._open.is_idle = True
            return
        bundle_id, app_name, window_title = self._open.bundle_id, self._open.app_name, self._open.window_title
        backdated = _iso(stopped_at)
        self._close_open(end_reason="idle", ended_at=backdated)
        self._open_session(
            bundle_id=bundle_id, app_name=app_name, window_title=window_title, started_at=backdated, is_idle=True
        )

    def on_sleep(self) -> None:
        """The system is about to sleep — close whatever's open immediately. Wake does
        nothing; the next real event naturally opens the next session."""
        self._close_open(end_reason="sleep")

    def on_lock(self) -> None:
        """The screen locked (independent of sleep — e.g. a manual lock or
        screensaver) — close whatever's open immediately. Unlock does nothing, same
        reasoning as wake."""
        self._close_open(end_reason="lock")

    def on_idle_end(self) -> None:
        """Closes the idle session and immediately resumes normal tracking under the
        same identity — the next switch/title-change event will correct it if the
        user actually acted on a different app."""
        if self._open is None:
            return
        bundle_id, app_name, window_title = self._open.bundle_id, self._open.app_name, self._open.window_title
        self._close_open(end_reason="idle")
        self._open_session(bundle_id=bundle_id, app_name=app_name, window_title=window_title)

    def _on_heartbeat(self) -> None:
        """Keeps the open_session mirror's ended_at current so a crash seals a
        realistic duration instead of started_at. Never closes or opens a session —
        that's only ever triggered by watcher callbacks."""
        if self._open is None:
            return
        now = _iso()
        self._open.ended_at = now
        db.update_open_session_ended_at(self._conn, self._open.id, now)

    def start_heartbeat(self) -> None:
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            HEARTBEAT_INTERVAL_SECONDS, True, lambda timer: self._on_heartbeat()
        )

    def stop_heartbeat(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
