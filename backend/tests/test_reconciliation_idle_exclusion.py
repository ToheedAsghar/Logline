"""Test that classified idle and screen-lock time is excluded before reconciliation evidence generation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.agent.reconciliation.routers as routers_module
from app.agent.llm.base import LLMProvider
from app.agent.reconciliation.schemas import EntryDescriptionProposal
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
    """Records the per-entry evidence text each description call was made with and returns a clean proposal for it."""

    def __init__(self):
        self.last_user_content: str | None = None

    async def run_turn(self, messages, tools):
        raise NotImplementedError

    async def run_structured(self, messages, response_model):
        self.last_user_content = messages[-1].content
        return EntryDescriptionProposal(description="Worked on this entry.")


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
    """One real 30-minute coding session and one 45-minute loginwindow session, both is_idle=False -- reproducing the
    real gap where the tracker's idle watcher never fires on a locked screen."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == USER_EMAIL).first()
        if user is None:
            user = User(email=USER_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
        user.timezone = "UTC"
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
        """30 real minutes, not 75 -- the 45 idle minutes must not inflate what gets charged."""
        _, provider = idle_and_real_sessions_user

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )

        assert "30 min measured" in provider.last_user_content
        allocations = [a for e in response.json()["draft"]["entries"] for a in e["allocations"]]
        assert sum(a["minutes"] for a in allocations) == 30

    def test_the_generated_drafts_verification_still_passes_with_idle_time_excluded(
        self, client, idle_and_real_sessions_user
    ):
        """Excluding idle blocks from evidence must not itself break conservation/completeness.

        Entry formation is deterministic and accounts for every real (non-idle) block by construction, so the idle-
        excluded loginwindow session correctly never needs accounting for at all -- verification passes clean, not
        because the idle block was charged somewhere, but because it was never evidence in the first place.
        """
        _, provider = idle_and_real_sessions_user

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )

        body = response.json()
        assert body["verification"]["passed"] is True
        assert body["verification"]["issues"] == []
