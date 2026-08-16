"""Tests for the reconciliation endpoints (app/agent/reconciliation/routers.py) against real Postgres.

The behaviour worth pinning here is the approval path, not the model call: `/approve` re-derives the
evidence server-side and re-runs verification, so a caller cannot approve a draft that charges more
minutes than were measured, and every entry it writes must carry a `human_approved` version snapshot.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import get_llm_provider
from app.agent.llm.base import LLMProvider
from app.agent.reconciliation.schemas import WorkLogDraft
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import SessionLocal
from app.entries.models import Entry, EntryStatus, EntryVersion, EntryVersionSource
from app.main import app
from app.tracker_sync.models import LocalSession

USER_EMAIL = "reconciliation-router-test@example.com"
PROJECT_PATH = "/Users/test/projects/logline"

DAY = datetime(2026, 7, 30, tzinfo=timezone.utc)
SESSION_START = DAY.replace(hour=9)
SESSION_END = DAY.replace(hour=11)
BLOCK_MINUTES = 120
WORK_DATE = "2026-07-30"


class _ScriptedProvider(LLMProvider):
    """Returns a fixed draft, so `/generate` can be exercised without a live model."""

    def __init__(self, draft: WorkLogDraft):
        self._draft = draft

    async def run_structured(self, messages, response_model):
        return self._draft


def _draft(minutes: int = BLOCK_MINUTES, *, description: str = "Worked on the reconciliation endpoints.") -> dict:
    return {
        "entries": [
            {
                "date": WORK_DATE,
                "project": PROJECT_PATH,
                "allocations": [{"block_id": 1, "minutes": minutes}],
                "tag": "Coding",
                "description": description,
                "source_remote_event_ids": [],
                "review_reason": None,
            }
        ],
        "reminders": [],
        "residual_unassigned_minutes": [],
    }


def _cleanup(db, user_id: int) -> None:
    entry_ids = [row.id for row in db.query(Entry.id).filter(Entry.user_id == user_id).all()]
    if entry_ids:
        db.query(EntryVersion).filter(EntryVersion.entry_id.in_(entry_ids)).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id == user_id).delete()
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


@pytest.fixture
def recon_user():
    """A user with exactly one 120-minute tracked session, cleaned up afterwards."""
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

        db.add(
            LocalSession(
                id=uuid4(),
                user_id=user_id,
                bundle_id="com.microsoft.VSCode",
                app_name="Code",
                window_title="routers.py - logline",
                project_path=PROJECT_PATH,
                started_at=SESSION_START,
                ended_at=SESSION_END,
                end_reason="app_switch",
                is_idle=False,
            )
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        app.dependency_overrides[get_current_user] = lambda: user
        yield user_id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_llm_provider, None)
        db.close()

    db = SessionLocal()
    try:
        _cleanup(db, user_id)
    finally:
        db.close()


def _cleanup_sessions_and_entries(db, user_id: int) -> None:
    entry_ids = [row.id for row in db.query(Entry.id).filter(Entry.user_id == user_id).all()]
    if entry_ids:
        db.query(EntryVersion).filter(EntryVersion.entry_id.in_(entry_ids)).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id == user_id).delete()
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.commit()


@pytest.fixture
def client():
    return TestClient(app)


class TestEndpointsAreRegistered:
    def test_generate_and_approve_are_not_404(self, client):
        """Guards the actual bug this branch fixes: the router existing but never being included."""
        paths = client.app.openapi()["paths"]
        assert "/reconciliation/generate" in paths
        assert "/reconciliation/approve" in paths


class TestDateRangeValidation:
    def test_reversed_range_is_rejected(self, client, recon_user):
        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": "2026-07-31", "date_range_end": "2026-07-01", "draft": _draft()},
        )
        assert response.status_code == 422

    def test_range_longer_than_31_days_is_rejected(self, client, recon_user):
        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": "2026-01-01", "date_range_end": "2026-06-01", "draft": _draft()},
        )
        assert response.status_code == 422


class TestApproveRunsVerificationServerSide:
    def test_draft_overcharging_a_block_is_rejected_with_issues(self, client, recon_user):
        """The block is worth 120 measured minutes; charging 480 must not be persisted on the caller's say-so."""
        response = client.post(
            "/reconciliation/approve",
            json={
                "date_range_start": WORK_DATE,
                "date_range_end": WORK_DATE,
                "draft": _draft(minutes=480),
            },
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "issues" in detail
        assert any(issue["check"] == "conservation" for issue in detail["issues"])

        db = SessionLocal()
        try:
            assert db.query(Entry).filter(Entry.user_id == recon_user).count() == 0
        finally:
            db.close()

    def test_draft_citing_an_unknown_block_is_rejected(self, client, recon_user):
        draft = _draft()
        draft["entries"][0]["allocations"] = [{"block_id": 99, "minutes": 30}]

        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE, "draft": draft},
        )

        assert response.status_code == 422
        checks = {issue["check"] for issue in response.json()["detail"]["issues"]}
        assert "unknown_id" in checks


class TestApproveWritesThroughTheSharedApprovalPath:
    def test_approved_entry_gets_a_human_approved_version_snapshot(self, client, recon_user):
        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE, "draft": _draft()},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == EntryStatus.approved.value
        assert body[0]["approved_at"] is not None

        db = SessionLocal()
        try:
            entry = db.query(Entry).filter(Entry.user_id == recon_user).one()
            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).all()
            assert [v.source for v in versions] == [EntryVersionSource.human_approved]
            assert versions[0].content["text"] == "Worked on the reconciliation endpoints."
        finally:
            db.close()

    def test_full_draft_provenance_is_persisted_not_just_the_description(self, client, recon_user):
        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE, "draft": _draft()},
        )

        assert response.status_code == 201, response.text
        content = response.json()[0]["content"]
        assert content["text"] == "Worked on the reconciliation endpoints."
        assert content["project"] == PROJECT_PATH
        assert content["tag"] == "Coding"
        assert content["allocations"] == [{"block_id": 1, "minutes": BLOCK_MINUTES}]

    def test_reminders_and_residual_minutes_are_not_persisted_as_entries(self, client, recon_user):
        draft = _draft(minutes=60)
        draft["residual_unassigned_minutes"] = [{"block_id": 1, "minutes": 60}]
        draft["reminders"] = [
            {
                "note": "Which ticket does this belong to?",
                "source": "jira",
                "day": WORK_DATE,
                "source_remote_event_ids": [],
            }
        ]

        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE, "draft": draft},
        )

        assert response.status_code == 201, response.text
        assert len(response.json()) == 1

        db = SessionLocal()
        try:
            assert db.query(Entry).filter(Entry.user_id == recon_user).count() == 1
        finally:
            db.close()


class TestGenerate:
    def test_generate_returns_draft_and_verification_without_writing(self, client, recon_user):
        scripted = WorkLogDraft.model_validate(_draft())

        import app.agent.reconciliation.routers as routers_module

        original = routers_module.get_llm_provider
        routers_module.get_llm_provider = lambda: _ScriptedProvider(scripted)
        try:
            response = client.post(
                "/reconciliation/generate",
                json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
            )
        finally:
            routers_module.get_llm_provider = original

        assert response.status_code == 200, response.text
        body = response.json()
        assert "draft" in body and "verification" in body
        assert body["verification"]["passed"] is True

        db = SessionLocal()
        try:
            assert db.query(Entry).filter(Entry.user_id == recon_user).count() == 0
        finally:
            db.close()


class TestAuthenticationRequired:
    def test_generate_requires_auth(self, client):
        app.dependency_overrides.pop(get_current_user, None)
        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE},
        )
        assert response.status_code == 401

    def test_approve_requires_auth(self, client):
        app.dependency_overrides.pop(get_current_user, None)
        response = client.post(
            "/reconciliation/approve",
            json={"date_range_start": WORK_DATE, "date_range_end": WORK_DATE, "draft": _draft()},
        )
        assert response.status_code == 401
