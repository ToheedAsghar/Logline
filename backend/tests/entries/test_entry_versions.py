"""Tests for the entry_versions append-only history table (app/entries/models.py) and its write
points: approve_entry (human_approved) and update_entry on an already-approved entry
(human_revision) -- against the real Postgres database.
"""

import pytest

from app.auth.models import User
from app.db.session import SessionLocal
from app.entries import crud
from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource

TEST_EMAIL = "entry-versions-test@example.com"


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
        db.query(Entry).filter(Entry.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(Entry).filter(Entry.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


def _make_draft_entry(db, user_id, text="original ai draft") -> Entry:
    entry = Entry(
        user_id=user_id,
        format=EntryFormat.project_log,
        content={"text": text},
        work_date="2026-07-31",
        status=EntryStatus.draft,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


class TestApproveEntryCreatesHumanApprovedVersion:
    def test_approve_appends_human_approved_version_with_current_content(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)
            entry = crud.approve_entry(db, entry, approved_at=entry.created_at)

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).all()
            assert len(versions) == 1
            assert versions[0].source == EntryVersionSource.human_approved
            assert versions[0].content == {"text": "original ai draft"}
        finally:
            db.close()

    def test_approve_after_a_pre_approval_edit_captures_the_edited_content(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)
            crud.update_entry(db, entry, content={"text": "edited before approval"}, status=None, approved_at=None)
            entry = crud.approve_entry(db, entry, approved_at=entry.created_at)

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).all()
            # No version is appended for a pre-approval edit -- only generation and approval are
            # tracked moments -- so approval's version is the only row, holding the edited content.
            assert len(versions) == 1
            assert versions[0].source == EntryVersionSource.human_approved
            assert versions[0].content == {"text": "edited before approval"}
        finally:
            db.close()


class TestPostApprovalEditCreatesHumanRevisionVersion:
    def test_content_edit_after_approval_appends_human_revision_version(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)
            entry = crud.approve_entry(db, entry, approved_at=entry.created_at)

            entry = crud.update_entry(
                db, entry, content={"text": "corrected after approval"}, status=None, approved_at=None
            )

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).order_by(
                EntryVersion.created_at
            ).all()
            assert [v.source for v in versions] == [
                EntryVersionSource.human_approved,
                EntryVersionSource.human_revision,
            ]
            assert versions[-1].content == {"text": "corrected after approval"}
        finally:
            db.close()

    def test_content_edit_before_approval_does_not_append_a_version(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)

            crud.update_entry(db, entry, content={"text": "edited while still draft"}, status=None, approved_at=None)

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).all()
            assert versions == []
        finally:
            db.close()

    def test_non_content_update_after_approval_does_not_append_a_version(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)
            entry = crud.approve_entry(db, entry, approved_at=entry.created_at)

            crud.update_entry(db, entry, content=None, status=EntryStatus.approved, approved_at=entry.approved_at)

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry.id).all()
            assert len(versions) == 1
            assert versions[0].source == EntryVersionSource.human_approved
        finally:
            db.close()


class TestEntryVersionsCascadeDeleteWithEntry:
    def test_deleting_entry_deletes_its_versions(self, real_db_user):
        db = SessionLocal()
        try:
            entry = _make_draft_entry(db, real_db_user)
            crud.approve_entry(db, entry, approved_at=entry.created_at)
            entry_id = entry.id

            db.delete(entry)
            db.commit()

            versions = db.query(EntryVersion).filter(EntryVersion.entry_id == entry_id).all()
            assert versions == []
        finally:
            db.close()
