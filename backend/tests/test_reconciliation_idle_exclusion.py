"""Tests that idle/screen-lock time never reaches Stage 5 evidence, against real Postgres.

Companion to `test_reconciliation_router.py` -- same fixture shape, scoped to its own user so it does not
disturb that file's shared `recon_user` fixture. Proves the fix for the real 2026-08-06 production bug:
`com.apple.loginwindow` sessions survive the `is_idle=false` filter (the tracker's IdleWatcher does not fire
on a locked screen) and must be excluded by category instead, entirely before the model ever sees them --
never folded into `residual_unassigned_minutes`, since idle is proven non-work, not genuine ambiguity.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.agent.reconciliation.routers as routers_module
from app.agent.llm.base import LLMProvider
from app.agent.reconciliation.schemas import WorkLogDraft
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import SessionLocal
from app.entries.models import Entry, EntryVersion
from app.main import app
from app.tracker_sync.models import LocalSession

USER_EMAIL = "reconciliation-idle-exclusion-test@example.com"
PROJECT_PATH = "/Users/test/projects/logline"

DAY = datetime(2026, 7, 30, tzinfo=timezone.utc)
WORK_DATE = "2026-07-30"


class _CapturingProvider(LLMProvider):
    """Records the evidence text it was called with and returns an empty draft."""

    def __init__(self):
        self.last_user_content: str | None = None

    async def run_turn(self, messages, tools):  # pragma: no cover
        raise NotImplementedError

    async def run_structured(self, messages, response_model):
        self.last_user_content = messages[-1].content
        return WorkLogDraft(entries=[], reminders=[], residual_unassigned_minutes=[])


def _cleanup_sessions_and_entries(db, user_id: int) -> None:
    entry_ids = [row.id for row in db.query(Entry.id).filter(Entry.user_id == user_id).all()]
    if entry_ids:
        db.query(EntryVersion).filter(EntryVersion.entry_id.in_(entry_ids)).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id == user_id).delete()
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.commit()


def _cleanup(db, user_id: int) -> None:
    _cleanup_sessions_and_entries(db, user_id)
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


@pytest.fixture
def idle_and_real_sessions_user():
    """One real 30-minute coding session and one 45-minute loginwindow session, both is_idle=False --
    reproducing the real gap where the tracker's idle watcher never fires on a locked screen."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == USER_EMAIL).first()
        if user is None:
            user = User(email=USER_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        _cleanup_sessions_and_entries(db, user_id)

        db.add_all(
            [
                LocalSession(
                    id=uuid4(),
                    user_id=user_id,
                    bundle_id="com.microsoft.VSCode",
                    app_name="Code",
                    window_title="routers.py - logline",
                    project_path=PROJECT_PATH,
                    started_at=DAY.replace(hour=9),
                    ended_at=DAY.replace(hour=9, minute=30),
                    end_reason="app_switch",
                    is_idle=False,
                ),
                LocalSession(
                    id=uuid4(),
                    user_id=user_id,
                    bundle_id="com.apple.loginwindow",
                    app_name="loginwindow",
                    window_title=None,
                    project_path=None,
                    started_at=DAY.replace(hour=10),
                    ended_at=DAY.replace(hour=10, minute=45),
                    end_reason="lock",
                    is_idle=False,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        app.dependency_overrides[get_current_user] = lambda: user
        provider = _CapturingProvider()
        original_get_llm_provider = routers_module.get_llm_provider
        routers_module.get_llm_provider = lambda: provider
        yield user_id, provider
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        routers_module.get_llm_provider = original_get_llm_provider
        db.close()

    db = SessionLocal()
    try:
        _cleanup(db, user_id)
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


class TestIdleTimeNeverReachesEvidence:
    def test_loginwindow_session_never_appears_in_the_evidence_sent_to_the_model(
        self, client, idle_and_real_sessions_user
    ):
        _, provider = idle_and_real_sessions_user

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )

        assert response.status_code == 200
        assert provider.last_user_content is not None
        assert "loginwindow" not in provider.last_user_content
        assert "category: Idle" not in provider.last_user_content

    def test_only_the_real_sessions_measured_minutes_are_in_the_evidence_total(
        self, client, idle_and_real_sessions_user
    ):
        """30 real minutes, not 75 -- the 45 idle minutes must not inflate the tracked total."""
        _, provider = idle_and_real_sessions_user

        client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )

        assert "Total measured time across all blocks: 30 min." in provider.last_user_content

    def test_the_generated_drafts_verification_still_passes_with_idle_time_excluded(
        self, client, idle_and_real_sessions_user
    ):
        """Excluding idle blocks from evidence must not itself break conservation/completeness -- an empty
        draft with nothing charged should still fail completeness on the one real block, proving the idle
        block was never counted as needing to be accounted for in the first place."""
        _, provider = idle_and_real_sessions_user

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )

        body = response.json()
        assert body["verification"]["passed"] is False
        completeness_issues = [issue for issue in body["verification"]["issues"] if issue["check"] == "completeness"]
        assert len(completeness_issues) == 1
        assert completeness_issues[0]["block_id"] == 1
