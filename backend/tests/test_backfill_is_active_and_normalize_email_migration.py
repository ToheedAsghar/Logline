"""Tests for the ee68bb2ed4fb migration (backfill is_active for existing
users, normalize existing emails). Proves the actual migration module's
upgrade() -- not a reimplementation of its SQL -- against rows inserted via
raw SQL to mimic the pre-migration state: is_active=false and (for one row)
mixed-case email, exactly what every user looked like before the email
verification flow and normalize_email (app/auth/crud.py) existed.

alembic.op only resolves inside an active MigrationContext, so
_run_migration_upgrade binds one to the real test connection and calls the
module's upgrade() directly -- see _run_migration_upgrade. downgrade() is
intentionally a no-op (see the migration file's docstring: backfilling
is_active and normalizing casing are one-way, there's no reliable prior
state to restore), so round-trip verification here means "upgrade() is safe
to run again," which every case below exercises implicitly.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text

from app.auth.crud import get_user_by_email
from app.auth.models import EmailVerificationToken, User
from app.auth.routers import login, signup
from app.auth.schemas import UserLogin, UserSignup
from app.auth.security import hash_password
from app.db.session import SessionLocal, engine

MIGRATION_MODULE = "app.db.migrations.versions.ee68bb2ed4fb_backfill_is_active_for_existing_users_"

PRE_EXISTING_PASSWORD = "grandfathered-user-password"
PRE_EXISTING_EMAIL = "pre-existing-migration-backfill-test@example.com"
PRE_EXISTING_MIXED_CASE_EMAIL = "Pre-Existing-Mixed-Case-Migration-Test@Example.com"
PRE_EXISTING_MIXED_CASE_NORMALIZED = "pre-existing-mixed-case-migration-test@example.com"

NEW_SIGNUP_EMAIL = "new-signup-after-migration-test@example.com"
NEW_SIGNUP_PASSWORD = "a-brand-new-correct-horse"


def _run_migration_upgrade():
    migration = importlib.import_module(MIGRATION_MODULE)
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        migration.op = Operations(context)
        migration.upgrade()


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
        _run_migration_upgrade()

        db = SessionLocal()
        try:
            response = login(UserLogin(email=PRE_EXISTING_EMAIL, password=PRE_EXISTING_PASSWORD), db=db)
            assert response.access_token
        finally:
            db.close()

    def test_pre_existing_mixed_case_email_is_still_findable_after_normalization(self, pre_existing_users):
        _run_migration_upgrade()

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
