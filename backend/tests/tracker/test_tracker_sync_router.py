"""Unit and integration tests for tracker sync endpoints and device authentication."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.models import User
from app.db.session import SessionLocal
from app.main import app
from app.tracker_sync.models import LocalSession, TrackerDevice, TrackerSyncState
from app.tracker_sync.security import hash_device_token

USER_EMAIL = "tracker-router-test@example.com"

DEV_1_TOKEN = "secret-token-1"
DEV_2_TOKEN = "secret-token-2"


def _auth(token: str) -> dict:
    """Device tokens are opaque bearer tokens -- the device is found by the hash of the token itself, so nothing
    identifying the device travels in the header."""
    return {"Authorization": f"Bearer {token}"}


def _get_or_create_user_and_device(db):
    user = db.query(User).filter(User.email == USER_EMAIL).first()
    if user is None:
        user = User(email=USER_EMAIL, hashed_password="not-a-real-hash")
        db.add(user)
        db.commit()
        db.refresh(user)

    dev_1 = TrackerDevice(
        user_id=user.id,
        device_id=uuid4(),
        name="Device 1",
        token_hash=hash_device_token(DEV_1_TOKEN),
    )

    dev_2 = TrackerDevice(
        user_id=user.id,
        device_id=uuid4(),
        name="Device 2",
        token_hash=hash_device_token(DEV_2_TOKEN),
    )
    db.add_all([dev_1, dev_2])
    db.commit()
    db.refresh(dev_1)
    db.refresh(dev_2)
    return user, dev_1, dev_2


def _cleanup(db, user_id):
    db.query(TrackerSyncState).filter(TrackerSyncState.user_id == user_id).delete()
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.query(TrackerDevice).filter(TrackerDevice.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


@pytest.fixture
def sync_env():
    db = SessionLocal()
    try:
        user, dev_1, dev_2 = _get_or_create_user_and_device(db)
        user_id = user.id
    finally:
        db.close()

    yield user_id, dev_1, dev_2

    db = SessionLocal()
    try:
        _cleanup(db, user_id)
    finally:
        db.close()


def test_checkpoint_scoped_to_authenticated_device(sync_env):
    user_id, dev_1, dev_2 = sync_env
    db = SessionLocal()
    try:
        # Pre-populate checkpoint for dev_1
        now = datetime.now(timezone.utc)
        state_1 = TrackerSyncState(
            user_id=user_id,
            device_id=dev_1.device_id,
            last_synced_at=now,
        )
        db.add(state_1)
        db.commit()

        client = TestClient(app)
        headers = _auth(DEV_1_TOKEN)

        resp = client.get("/tracker/sync/checkpoint", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_synced_at"] is not None

        # Device 2 has no checkpoint
        headers_2 = _auth(DEV_2_TOKEN)
        resp_2 = client.get("/tracker/sync/checkpoint", headers=headers_2)
        assert resp_2.status_code == 200
        assert resp_2.json()["last_synced_at"] is None
    finally:
        db.close()


def test_sync_rejects_mismatched_device_id(sync_env):
    user_id, dev_1, dev_2 = sync_env
    client = TestClient(app)
    headers = _auth(DEV_1_TOKEN)

    payload = {
        "device_id": str(dev_2.device_id),
        "sessions": [],
    }
    resp = client.post("/tracker/sync", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "does not match" in resp.json()["detail"]


def test_checkpoint_advances_only_for_accepted_or_duplicate_sessions(sync_env):
    user_id, dev_1, dev_2 = sync_env
    now = datetime.now(timezone.utc)

    valid_ended_at = now - timedelta(minutes=10)
    invalid_ended_at = now + timedelta(days=1)  # Future date -> rejected as invalid

    valid_session = {
        "id": str(uuid4()),
        "bundle_id": "com.apple.Terminal",
        "app_name": "Terminal",
        "started_at": (valid_ended_at - timedelta(minutes=5)).isoformat(),
        "ended_at": valid_ended_at.isoformat(),
        "end_reason": "switch",
        "is_idle": False,
    }

    invalid_session = {
        "id": str(uuid4()),
        "bundle_id": "com.apple.Terminal",
        "app_name": "Terminal",
        "started_at": now.isoformat(),
        "ended_at": invalid_ended_at.isoformat(),
        "end_reason": "switch",
        "is_idle": False,
    }

    client = TestClient(app)
    headers = _auth(DEV_1_TOKEN)

    payload = {
        "device_id": str(dev_1.device_id),
        "sessions": [valid_session, invalid_session],
    }

    resp = client.post("/tracker/sync", json=payload, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["accepted"] == 1
    assert res_data["invalid"] == 1

    # Check checkpoint: should be valid_ended_at, NOT invalid_ended_at
    db = SessionLocal()
    try:
        state = db.query(TrackerSyncState).filter(
            TrackerSyncState.user_id == user_id,
            TrackerSyncState.device_id == dev_1.device_id,
        ).first()
        assert state is not None
        assert abs((state.last_synced_at - valid_ended_at).total_seconds()) < 1.0
    finally:
        db.close()
