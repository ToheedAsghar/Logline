"""Tests for the manual remote-fetch trigger endpoint."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.auth.models import User
from app.auth.security import create_access_token
from app.db.session import SessionLocal
from app.integrations.models import IntegrationSource
from app.main import app
from app.remote_fetch.constants import TRIGGER_COOLDOWN_SECONDS
from app.remote_fetch.models import RemoteFetchState

USER_EMAIL = "remote-fetch-trigger-test@example.com"
OTHER_EMAIL = "remote-fetch-trigger-other@example.com"


def _auth_headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _get_or_create_user(db, email: str) -> int:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password="not-a-real-hash", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user.id


@pytest.fixture
def trigger_env():
    db = SessionLocal()
    try:
        user_id = _get_or_create_user(db, USER_EMAIL)
        other_id = _get_or_create_user(db, OTHER_EMAIL)
    finally:
        db.close()

    yield user_id, other_id

    db = SessionLocal()
    try:
        db.query(RemoteFetchState).filter(RemoteFetchState.user_id.in_([user_id, other_id])).delete()
        db.query(User).filter(User.id.in_([user_id, other_id])).delete()
        db.commit()
    finally:
        db.close()


def _seed_attempt(db, user_id: int, attempted_at: datetime) -> None:
    db.add(RemoteFetchState(user_id=user_id, source=IntegrationSource.github, last_attempted_at=attempted_at))
    db.commit()


def test_trigger_requires_authentication(trigger_env):
    user_id, _ = trigger_env
    resp = TestClient(app).post("/remote-fetch/trigger")
    assert resp.status_code == 401


def test_trigger_runs_fetch_for_current_user(trigger_env, monkeypatch):
    user_id, other_id = trigger_env
    calls = []

    async def fake_fetch_all_sources(called_user_id):
        calls.append(called_user_id)

    monkeypatch.setattr("app.remote_fetch.routers.fetch_all_sources", fake_fetch_all_sources)

    client = TestClient(app)
    resp = client.post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "triggered"}
    assert calls == [user_id]

    db = SessionLocal()
    try:
        last_attempted_at = (
            db.query(func.max(RemoteFetchState.last_attempted_at))
            .filter(RemoteFetchState.user_id == user_id)
            .scalar()
        )
        assert last_attempted_at is not None
        assert datetime.now(timezone.utc) - last_attempted_at < timedelta(seconds=TRIGGER_COOLDOWN_SECONDS)
    finally:
        db.close()


def test_back_to_back_triggers_are_rejected(trigger_env, monkeypatch):
    user_id, _ = trigger_env

    async def fake_fetch_all_sources(called_user_id):
        pass

    monkeypatch.setattr("app.remote_fetch.routers.fetch_all_sources", fake_fetch_all_sources)

    client = TestClient(app)
    first = client.post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert first.status_code == 200

    second = client.post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert second.status_code == 429
    assert "already ran within the last" in second.json()["detail"]


def test_trigger_rejects_recent_attempt(trigger_env):
    user_id, _ = trigger_env
    db = SessionLocal()
    try:
        _seed_attempt(db, user_id, datetime.now(timezone.utc))
    finally:
        db.close()

    resp = TestClient(app).post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert resp.status_code == 429
    assert "already ran within the last" in resp.json()["detail"]


def test_trigger_allows_attempt_older_than_cooldown(trigger_env):
    user_id, _ = trigger_env
    db = SessionLocal()
    try:
        _seed_attempt(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=61))
    finally:
        db.close()

    resp = TestClient(app).post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert resp.status_code == 200


def test_rate_limit_is_scoped_per_user(trigger_env):
    user_id, other_id = trigger_env
    db = SessionLocal()
    try:
        _seed_attempt(db, other_id, datetime.now(timezone.utc))
    finally:
        db.close()

    resp = TestClient(app).post("/remote-fetch/trigger", headers=_auth_headers(user_id))
    assert resp.status_code == 200
