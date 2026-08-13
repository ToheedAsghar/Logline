"""Device enrollment, revocation, and the sync-status endpoint.

The properties under test are the ones that make a stolen database useless and a lost laptop recoverable: the
token exists in plaintext for exactly one response, the stored form cannot be reversed, and revocation takes
effect immediately without destroying the device's sync checkpoint.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.models import User
from app.auth.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.tracker_sync.models import LocalSession, TrackerDevice, TrackerSyncState
from app.tracker_sync.security import hash_device_token

USER_EMAIL = "tracker-enroll-test@example.com"
OTHER_USER_EMAIL = "tracker-enroll-other@example.com"


def _create_user(db, email):
    """`is_active` must be set explicitly: it defaults to False pending email verification, and get_current_user
    rejects inactive users."""
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password="not-a-real-hash", is_active=True)
        db.add(user)
    else:
        user.is_active = True
    db.commit()
    db.refresh(user)
    return user


def _cleanup(db, user_id):
    device_ids = [row[0] for row in db.query(TrackerDevice.device_id).filter(TrackerDevice.user_id == user_id)]
    if device_ids:
        db.query(TrackerSyncState).filter(TrackerSyncState.device_id.in_(device_ids)).delete(
            synchronize_session=False
        )
    db.query(TrackerSyncState).filter(TrackerSyncState.user_id == user_id).delete()
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.query(TrackerDevice).filter(TrackerDevice.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


@pytest.fixture
def enroll_env():
    """Yields (client, user_headers, user_id, other_user_headers, other_user_id)."""
    db = SessionLocal()
    try:
        user = _create_user(db, USER_EMAIL)
        other = _create_user(db, OTHER_USER_EMAIL)
        user_id, other_id = user.id, other.id
    finally:
        db.close()

    yield (
        TestClient(app),
        {"Authorization": f"Bearer {create_access_token(user_id)}"},
        user_id,
        {"Authorization": f"Bearer {create_access_token(other_id)}"},
        other_id,
    )

    db = SessionLocal()
    try:
        _cleanup(db, user_id)
        _cleanup(db, other_id)
    finally:
        db.close()


def _enroll(client, headers, name="Test MacBook"):
    resp = client.post("/tracker/devices", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestEnrollment:
    def test_enrollment_returns_a_device_id_and_token(self, enroll_env):
        client, headers, _, _, _ = enroll_env

        body = _enroll(client, headers)

        assert body["device_id"]
        assert body["token"]
        assert body["name"] == "Test MacBook"

    def test_token_is_stored_only_as_a_hash(self, enroll_env):
        """A database dump must not yield a usable token."""
        client, headers, user_id, _, _ = enroll_env
        body = _enroll(client, headers)

        db = SessionLocal()
        try:
            device = db.query(TrackerDevice).filter(TrackerDevice.device_id == body["device_id"]).first()
            assert device.token_hash == hash_device_token(body["token"])
            assert body["token"] not in device.token_hash
            assert not hasattr(device, "token")
        finally:
            db.close()

    def test_the_token_is_never_returned_again(self, enroll_env):
        """There is no read endpoint that can surface it, so the enrollment response is genuinely the only copy."""
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)

        for path in (f"/tracker/devices/{body['device_id']}", "/tracker/sync/status"):
            resp = client.get(path, headers=headers)
            assert body["token"] not in resp.text

    def test_each_enrollment_issues_a_distinct_token(self, enroll_env):
        client, headers, _, _, _ = enroll_env

        first, second = _enroll(client, headers, "One"), _enroll(client, headers, "Two")

        assert first["token"] != second["token"]
        assert first["device_id"] != second["device_id"]

    def test_blank_name_falls_back_to_a_default(self, enroll_env):
        client, headers, _, _, _ = enroll_env

        resp = client.post("/tracker/devices", json={"name": "   "}, headers=headers)

        assert resp.status_code == 201
        assert resp.json()["name"] == "Tracker device"

    def test_enrollment_requires_a_logged_in_user(self, enroll_env):
        client, _, _, _, _ = enroll_env

        assert client.post("/tracker/devices", json={"name": "x"}).status_code == 401
        assert client.post(
            "/tracker/devices", json={"name": "x"}, headers={"Authorization": "Bearer not-a-jwt"}
        ).status_code == 401

    def test_a_device_token_cannot_enroll_another_device(self, enroll_env):
        """Enrollment is a user action. A leaked device token must not be able to mint more device tokens."""
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)

        resp = client.post(
            "/tracker/devices", json={"name": "escalated"}, headers={"Authorization": f"Bearer {body['token']}"}
        )

        assert resp.status_code == 401


class TestIssuedTokenAuthenticates:
    def test_the_issued_token_works_on_the_sync_endpoints(self, enroll_env):
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)
        device_headers = {"Authorization": f"Bearer {body['token']}"}

        resp = client.get("/tracker/sync/checkpoint", headers=device_headers)

        assert resp.status_code == 200
        assert resp.json()["last_synced_at"] is None
        assert resp.json()["device_id"] == body["device_id"]

    def test_an_unknown_token_is_rejected(self, enroll_env):
        client, _, _, _, _ = enroll_env

        resp = client.get("/tracker/sync/checkpoint", headers={"Authorization": "Bearer not-a-real-token"})

        assert resp.status_code == 401

    def test_the_device_id_mismatch_check_still_holds_after_enrollment(self, enroll_env):
        """Regression guard: the new opaque-token flow must not weaken the existing 403 on a payload naming a
        different device."""
        client, headers, _, _, _ = enroll_env
        first, second = _enroll(client, headers, "One"), _enroll(client, headers, "Two")

        resp = client.post(
            "/tracker/sync",
            json={"device_id": second["device_id"], "sessions": []},
            headers={"Authorization": f"Bearer {first['token']}"},
        )

        assert resp.status_code == 403

    def test_a_device_token_cannot_read_user_scoped_sync_status(self, enroll_env):
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)

        resp = client.get("/tracker/sync/status", headers={"Authorization": f"Bearer {body['token']}"})

        assert resp.status_code == 401


class TestRevocation:
    def test_revoking_stops_the_token_working_immediately(self, enroll_env):
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)
        device_headers = {"Authorization": f"Bearer {body['token']}"}
        assert client.get("/tracker/sync/checkpoint", headers=device_headers).status_code == 200

        assert client.delete(f"/tracker/devices/{body['device_id']}", headers=headers).status_code == 200

        assert client.get("/tracker/sync/checkpoint", headers=device_headers).status_code == 401
        assert client.post(
            "/tracker/sync", json={"device_id": body["device_id"], "sessions": []}, headers=device_headers
        ).status_code == 401

    def test_revocation_is_idempotent_and_keeps_the_original_timestamp(self, enroll_env):
        client, headers, _, _, _ = enroll_env
        body = _enroll(client, headers)

        first = client.delete(f"/tracker/devices/{body['device_id']}", headers=headers).json()
        second = client.delete(f"/tracker/devices/{body['device_id']}", headers=headers).json()

        assert first["revoked_at"] == second["revoked_at"]

    def test_revocation_keeps_the_sync_checkpoint(self, enroll_env):
        """Re-enrolling the same machine must not replay its whole local history, so the checkpoint row survives."""
        client, headers, user_id, _, _ = enroll_env
        body = _enroll(client, headers)
        synced_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db = SessionLocal()
        try:
            db.add(TrackerSyncState(user_id=user_id, device_id=UUID(body["device_id"]), last_synced_at=synced_at))
            db.commit()
        finally:
            db.close()

        client.delete(f"/tracker/devices/{body['device_id']}", headers=headers)

        db = SessionLocal()
        try:
            state = (
                db.query(TrackerSyncState).filter(TrackerSyncState.device_id == body["device_id"]).first()
            )
            assert state is not None
            assert abs((state.last_synced_at - synced_at).total_seconds()) < 1.0
        finally:
            db.close()

    def test_another_users_device_cannot_be_revoked(self, enroll_env):
        client, headers, _, other_headers, _ = enroll_env
        body = _enroll(client, headers)

        resp = client.delete(f"/tracker/devices/{body['device_id']}", headers=other_headers)

        assert resp.status_code == 404
        assert client.get(
            "/tracker/sync/checkpoint", headers={"Authorization": f"Bearer {body['token']}"}
        ).status_code == 200

    def test_revoking_an_unknown_device_is_404(self, enroll_env):
        client, headers, _, _, _ = enroll_env

        assert client.delete(f"/tracker/devices/{uuid4()}", headers=headers).status_code == 404


class TestSyncStatus:
    def test_reports_no_devices_before_enrollment(self, enroll_env):
        client, headers, _, _, _ = enroll_env

        body = client.get("/tracker/sync/status", headers=headers).json()

        assert body == {"last_synced_at": None, "device_count": 0}

    def test_reports_the_newest_checkpoint_across_devices(self, enroll_env):
        client, headers, user_id, _, _ = enroll_env
        older, newer = _enroll(client, headers, "Older"), _enroll(client, headers, "Newer")
        newest = datetime.now(timezone.utc) - timedelta(minutes=3)
        db = SessionLocal()
        try:
            db.add(
                TrackerSyncState(
                    user_id=user_id, device_id=UUID(older["device_id"]), last_synced_at=newest - timedelta(days=2)
                )
            )
            db.add(TrackerSyncState(user_id=user_id, device_id=UUID(newer["device_id"]), last_synced_at=newest))
            db.commit()
        finally:
            db.close()

        body = client.get("/tracker/sync/status", headers=headers).json()

        assert body["device_count"] == 2
        assert abs((datetime.fromisoformat(body["last_synced_at"]) - newest).total_seconds()) < 1.0

    def test_revoked_devices_do_not_keep_an_account_looking_fresh(self, enroll_env):
        client, headers, user_id, _, _ = enroll_env
        body = _enroll(client, headers)
        db = SessionLocal()
        try:
            db.add(
                TrackerSyncState(
                    user_id=user_id, device_id=UUID(body["device_id"]), last_synced_at=datetime.now(timezone.utc)
                )
            )
            db.commit()
        finally:
            db.close()

        client.delete(f"/tracker/devices/{body['device_id']}", headers=headers)

        status = client.get("/tracker/sync/status", headers=headers).json()
        assert status == {"last_synced_at": None, "device_count": 0}

    def test_status_is_scoped_to_the_logged_in_user(self, enroll_env):
        client, headers, _, other_headers, _ = enroll_env
        _enroll(client, headers)

        assert client.get("/tracker/sync/status", headers=other_headers).json()["device_count"] == 0

    def test_status_requires_authentication(self, enroll_env):
        client, _, _, _, _ = enroll_env

        assert client.get("/tracker/sync/status").status_code == 401
