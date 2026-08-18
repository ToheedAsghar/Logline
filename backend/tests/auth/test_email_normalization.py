"""Regression tests for the email-normalization fix in app/auth/crud.py.

Before this fix, "User@Example.com" and "user@example.com" were treated as
distinct rows by the `users.email` unique constraint -- a real duplicate
account despite the DB-level uniqueness guarantee. create_user and
get_user_by_email now both normalize (strip + lowercase) before touching the
DB, so the constraint applies to the same canonical form regardless of the
case a user happens to type.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md)
because a mocked session can't prove the actual uq constraint on `email`
fires for what is now the same normalized value.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth import crud
from app.auth.models import User
from app.db.session import SessionLocal

CANONICAL_EMAIL = "email-normalization-test@example.com"


@pytest.fixture
def clean_test_user():
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == CANONICAL_EMAIL).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(User).filter(User.email == CANONICAL_EMAIL).delete()
        db.commit()
    finally:
        db.close()


class TestEmailNormalization:
    def test_create_user_lowercases_email(self, clean_test_user):
        db = SessionLocal()
        try:
            user = crud.create_user(
                db, email="Email-Normalization-Test@Example.com", hashed_password="not-a-real-hash", name=None
            )
            assert user.email == CANONICAL_EMAIL
        finally:
            db.close()

    def test_mixed_case_signup_collides_with_existing_lowercase_user(self, clean_test_user):
        db = SessionLocal()
        try:
            crud.create_user(db, email=CANONICAL_EMAIL, hashed_password="not-a-real-hash", name=None)

            with pytest.raises(IntegrityError):
                crud.create_user(
                    db, email="Email-Normalization-Test@Example.com", hashed_password="not-a-real-hash", name=None
                )
        finally:
            db.rollback()
            db.close()

    def test_get_user_by_email_is_case_insensitive(self, clean_test_user):
        db = SessionLocal()
        try:
            created = crud.create_user(db, email=CANONICAL_EMAIL, hashed_password="not-a-real-hash", name=None)

            found = crud.get_user_by_email(db, "Email-Normalization-Test@Example.com")

            assert found is not None
            assert found.id == created.id
        finally:
            db.close()

    def test_get_user_by_email_strips_whitespace(self, clean_test_user):
        db = SessionLocal()
        try:
            created = crud.create_user(db, email=CANONICAL_EMAIL, hashed_password="not-a-real-hash", name=None)

            found = crud.get_user_by_email(db, f"  {CANONICAL_EMAIL}  ")

            assert found is not None
            assert found.id == created.id
        finally:
            db.close()
