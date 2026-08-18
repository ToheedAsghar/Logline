"""Test the endpoint that sets the current user's IANA timezone."""

import pytest
from fastapi.testclient import TestClient

from app.auth.models import User
from app.auth.security import create_access_token
from app.db.session import SessionLocal
from app.main import app

USER_EMAIL = "auth-timezone-test@example.com"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user():
    """Create an active user with no timezone set and authenticate as them with a real bearer token.

    A real token is used rather than a `get_current_user` override so the endpoint receives a `User` attached to the
    request's own session, exactly as it does in production.
    """
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == USER_EMAIL).delete()
        db.commit()
        row = User(email=USER_EMAIL, hashed_password="not-a-real-hash", is_active=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        user_id = row.id
    finally:
        db.close()

    yield user_id, {"Authorization": f"Bearer {create_access_token(user_id)}"}

    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestSettingATimezone:
    def test_a_valid_iana_name_is_accepted(self, client, user):
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"}, headers=headers)

        assert response.status_code == 200

    def test_the_new_timezone_is_returned_in_the_response(self, client, user):
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"}, headers=headers)

        assert response.json()["timezone"] == "Asia/Karachi"

    def test_the_new_timezone_is_persisted(self, client, user):
        user_id, headers = user
        client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"}, headers=headers)

        db = SessionLocal()
        try:
            assert db.query(User).filter(User.id == user_id).first().timezone == "Asia/Karachi"
        finally:
            db.close()

    def test_the_timezone_can_be_changed_again(self, client, user):
        _, headers = user
        client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"}, headers=headers)
        response = client.patch("/auth/me/timezone", json={"timezone": "Europe/London"}, headers=headers)

        assert response.json()["timezone"] == "Europe/London"

    def test_me_reports_the_saved_timezone(self, client, user):
        _, headers = user
        client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"}, headers=headers)

        assert client.get("/auth/me", headers=headers).json()["timezone"] == "Asia/Karachi"

    def test_me_reports_null_before_any_timezone_is_set(self, client, user):
        _, headers = user

        assert client.get("/auth/me", headers=headers).json()["timezone"] is None


class TestRejectingInvalidTimezones:
    def test_an_unknown_zone_name_is_rejected(self, client, user):
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": "Mars/Olympus_Mons"}, headers=headers)

        assert response.status_code == 422

    def test_a_path_traversal_style_name_is_rejected(self, client, user):
        """`ZoneInfo` treats its key as a path into the zone database, so a traversal attempt must not reach it."""
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": "../../etc/passwd"}, headers=headers)

        assert response.status_code == 422

    def test_an_empty_name_is_rejected(self, client, user):
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": ""}, headers=headers)

        assert response.status_code == 422

    def test_an_over_long_name_is_rejected(self, client, user):
        _, headers = user
        response = client.patch("/auth/me/timezone", json={"timezone": "A" * 100}, headers=headers)

        assert response.status_code == 422

    def test_a_rejected_timezone_is_not_persisted(self, client, user):
        user_id, headers = user
        client.patch("/auth/me/timezone", json={"timezone": "Mars/Olympus_Mons"}, headers=headers)

        db = SessionLocal()
        try:
            assert db.query(User).filter(User.id == user_id).first().timezone is None
        finally:
            db.close()


class TestAuthenticationIsRequired:
    def test_setting_a_timezone_without_auth_is_rejected(self, client):
        response = client.patch("/auth/me/timezone", json={"timezone": "Asia/Karachi"})

        assert response.status_code == 401
