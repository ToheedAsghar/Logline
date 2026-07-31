"""
Basic CRUD-level tests for the ProjectMapping model (app/matching/models.py),
against the real Postgres database (same DB the app runs against).
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.db.session import SessionLocal
from app.matching.models import ProjectMapping

TEST_EMAIL = "project-mappings-crud-test@example.com"


@pytest.fixture
def real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(ProjectMapping).filter(ProjectMapping.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(ProjectMapping).filter(ProjectMapping.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestCreateAndRead:
    def test_insert_and_read_back(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                ProjectMapping(
                    user_id=real_db_user,
                    local_project="/Users/dev/logline",
                    source="jira",
                    remote_project_id="LOG",
                )
            )
            db.commit()

            row = db.query(ProjectMapping).filter(ProjectMapping.user_id == real_db_user).first()
            assert row.local_project == "/Users/dev/logline"
            assert row.source == "jira"
            assert row.remote_project_id == "LOG"
            assert row.created_at is not None
        finally:
            db.close()


class TestUpdate:
    def test_update_remote_project_id(self, real_db_user):
        db = SessionLocal()
        try:
            mapping = ProjectMapping(
                user_id=real_db_user, local_project="/Users/dev/logline", source="slack", remote_project_id="C111"
            )
            db.add(mapping)
            db.commit()

            mapping.remote_project_id = "C222"
            db.commit()

            row = db.query(ProjectMapping).filter(ProjectMapping.user_id == real_db_user).first()
            assert row.remote_project_id == "C222"
        finally:
            db.close()


class TestDelete:
    def test_delete_removes_row(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                ProjectMapping(
                    user_id=real_db_user, local_project="/Users/dev/logline", source="jira", remote_project_id="LOG"
                )
            )
            db.commit()

            db.query(ProjectMapping).filter(ProjectMapping.user_id == real_db_user).delete()
            db.commit()

            rows = db.query(ProjectMapping).filter(ProjectMapping.user_id == real_db_user).all()
            assert rows == []
        finally:
            db.close()


class TestUniqueConstraint:
    def test_duplicate_user_local_project_source_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                ProjectMapping(
                    user_id=real_db_user, local_project="/Users/dev/logline", source="jira", remote_project_id="LOG"
                )
            )
            db.commit()

            db.add(
                ProjectMapping(
                    user_id=real_db_user,
                    local_project="/Users/dev/logline",
                    source="jira",
                    remote_project_id="DIFFERENT",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_same_local_project_different_source_is_allowed(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                ProjectMapping(
                    user_id=real_db_user, local_project="/Users/dev/logline", source="jira", remote_project_id="LOG"
                )
            )
            db.add(
                ProjectMapping(
                    user_id=real_db_user, local_project="/Users/dev/logline", source="slack", remote_project_id="C1"
                )
            )
            db.commit()

            rows = db.query(ProjectMapping).filter(ProjectMapping.user_id == real_db_user).all()
            assert len(rows) == 2
        finally:
            db.close()
