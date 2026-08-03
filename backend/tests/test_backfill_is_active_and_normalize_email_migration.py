"""Tests for the user-data fixup in migration 6aff4d503b81 (add password
reset and email verification support).

That migration adds email verification, which means: every user now needs
is_active=true to log in, and every email is now stored lowercase. Existing
users predate both rules, so the migration also updates their rows directly:
marks them all active (they signed up before verification existed, so
there's nothing for them to verify) and lowercases their emails.

These tests insert rows via raw SQL to look like a user from before the
migration (is_active=false, one with a mixed-case email), then call the
migration's own update function directly -- not a rewritten copy of it -- and
check the users can still log in and be found by email afterward.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import importlib

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text

from app.auth.crud import get_user_by_email
from app.auth.models import EmailVerificationToken, User
from app.auth.routers import login, signup
from app.auth.schemas import UserLogin, UserSignup
from app.auth.security import hash_password
from app.db.session import SessionLocal, engine

MIGRATION_MODULE = "app.db.migrations.versions.6aff4d503b81_add_password_reset_and_email_"

PRE_EXISTING_PASSWORD = "grandfathered-user-password"
PRE_EXISTING_EMAIL = "pre-existing-migration-backfill-test@example.com"
PRE_EXISTING_MIXED_CASE_EMAIL = "Pre-Existing-Mixed-Case-Migration-Test@Example.com"
PRE_EXISTING_MIXED_CASE_NORMALIZED = "pre-existing-mixed-case-migration-test@example.com"

NEW_SIGNUP_EMAIL = "new-signup-after-migration-test@example.com"
NEW_SIGNUP_PASSWORD = "a-brand-new-correct-horse"


def _run_backfill():
    migration = importlib.import_module(MIGRATION_MODULE)
    with engine.begin() as conn:
        migration.backfill_is_active_and_normalize_email(conn)


def _insert_pre_migration_row(db, email, password_hash):
    db.execute(
        text(
            "INSERT INTO users (email, hashed_password, is_active, is_sso_user) "
            "VALUES (:email, :hashed_password, false, false)"
        ),
        {"email": email, "hashed_password": password_hash},
    )
    db.commit()


@pytest.fixture
def pre_existing_users():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM users WHERE lower(email) = lower(:email)"), {"email": PRE_EXISTING_EMAIL})
        db.execute(
            text("DELETE FROM users WHERE lower(email) = lower(:email)"),
            {"email": PRE_EXISTING_MIXED_CASE_EMAIL},
        )
        db.commit()

        _insert_pre_migration_row(db, PRE_EXISTING_EMAIL, hash_password(PRE_EXISTING_PASSWORD))
        _insert_pre_migration_row(db, PRE_EXISTING_MIXED_CASE_EMAIL, hash_password(PRE_EXISTING_PASSWORD))
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM users WHERE lower(email) = lower(:email)"), {"email": PRE_EXISTING_EMAIL})
        db.execute(
            text("DELETE FROM users WHERE lower(email) = lower(:email)"),
            {"email": PRE_EXISTING_MIXED_CASE_EMAIL},
        )
        db.commit()
    finally:
        db.close()


class TestMigrationBackfillsExistingUsers:
    def test_pre_existing_user_can_log_in_without_any_verification_step(self, pre_existing_users):
        _run_backfill()

        db = SessionLocal()
        try:
            response = login(UserLogin(email=PRE_EXISTING_EMAIL, password=PRE_EXISTING_PASSWORD), db=db)
            assert response.access_token
        finally:
            db.close()

    def test_pre_existing_mixed_case_email_is_still_findable_after_normalization(self, pre_existing_users):
        _run_backfill()

        db = SessionLocal()
        try:
            user = get_user_by_email(db, PRE_EXISTING_MIXED_CASE_EMAIL)
            assert user is not None
            assert user.email == PRE_EXISTING_MIXED_CASE_NORMALIZED
            assert user.is_active is True
        finally:
            db.close()


class TestNewSignupsStillRequireVerification:
    def test_new_signup_after_migration_defaults_inactive_and_login_is_rejected(self):
        db = SessionLocal()
        try:
            existing = db.query(User).filter(User.email == NEW_SIGNUP_EMAIL).first()
            if existing is not None:
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == existing.id).delete()
                db.query(User).filter(User.id == existing.id).delete()
                db.commit()

            signup(
                UserSignup(email=NEW_SIGNUP_EMAIL, password=NEW_SIGNUP_PASSWORD, name=None),
                BackgroundTasks(),
                db=db,
            )

            created = db.query(User).filter(User.email == NEW_SIGNUP_EMAIL).first()
            assert created.is_active is False

            with pytest.raises(HTTPException) as exc_info:
                login(UserLogin(email=NEW_SIGNUP_EMAIL, password=NEW_SIGNUP_PASSWORD), db=db)
            assert exc_info.value.status_code == 403
        finally:
            created = db.query(User).filter(User.email == NEW_SIGNUP_EMAIL).first()
            if created is not None:
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == created.id).delete()
                db.query(User).filter(User.id == created.id).delete()
                db.commit()
            db.close()
