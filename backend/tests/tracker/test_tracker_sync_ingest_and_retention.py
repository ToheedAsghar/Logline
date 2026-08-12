"""
Regression tests for tracker sync ingest and cleanup.

These tests check two things:
- ingest_sessions accepts good sessions (closed and valid), rejects bad
    ones (open, too long, in the future, or otherwise invalid), and handles
    duplicate resends correctly.
- cleanup_synced_sessions deletes only old sessions that match approved
    entries for the same user.

They use the real test Postgres database because the id conflict rules,
update behavior, and per-user cleanup rules need an actual DB to verify.
The tests call ingest_sessions directly and do not use any transport code.
"""

import time
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pydantic
import pytest
from sqlalchemy import text

from app.auth.models import User
from app.db.session import SessionLocal
from app.entries.models import Entry, EntryFormat, EntryStatus
from app.tracker_sync import retention, service
from app.tracker_sync.constants import (
    CLOCK_SKEW_TOLERANCE_MINUTES, KNOWN_END_REASONS, MAX_SESSION_DURATION_HOURS, RETENTION_WINDOW_DAYS,
)
from app.tracker_sync.models import LocalSession
from app.tracker_sync.schemas import LocalSessionIn
from app.tracker_sync.service import IngestStatus

USER_A_EMAIL = "tracker-sync-test-user-a@example.com"
USER_B_EMAIL = "tracker-sync-test-user-b@example.com"


def _get_or_create_user(db, email: str) -> int:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password="not-a-real-hash")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user.id


def _wipe_owned_rows(db, user_ids: list[int]) -> None:
    db.query(LocalSession).filter(LocalSession.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def users():
    db = SessionLocal()
    try:
        user_a = _get_or_create_user(db, USER_A_EMAIL)
        user_b = _get_or_create_user(db, USER_B_EMAIL)
        _wipe_owned_rows(db, [user_a, user_b])
    finally:
        db.close()

    yield user_a, user_b

    db = SessionLocal()
    try:
        _wipe_owned_rows(db, [user_a, user_b])
    finally:
        db.close()


def _session_in(**overrides) -> LocalSessionIn:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        bundle_id="com.apple.Terminal",
        app_name="Terminal",
        window_title="zsh",
        started_at=now - timedelta(minutes=10),
        ended_at=now - timedelta(minutes=5),
        end_reason="switch",
        is_idle=False,
    )
    defaults.update(overrides)
    return LocalSessionIn(**defaults)


def _by_id(result: service.IngestResult, session_id):
    return next(r for r in result.results if r.id == session_id)


class TestIngestSessionsValidBatch:
    def test_valid_batch_inserts_scoped_to_right_user(self, users):
        user_a, user_b = users
        db = SessionLocal()
        try:
            sessions = [_session_in(), _session_in(bundle_id="org.mozilla.firefox", app_name="Firefox")]
            result = service.ingest_sessions(db, user_a, sessions)

            assert result.accepted == 2
            assert result.duplicate == 0
            assert result.invalid == 0
            assert all(r.status is IngestStatus.accepted for r in result.results)

            rows = db.query(LocalSession).filter(LocalSession.user_id == user_a).all()
            assert len(rows) == 2
            assert all(row.user_id == user_a for row in rows)
            assert db.query(LocalSession).filter(LocalSession.user_id == user_b).count() == 0
        finally:
            db.close()


class TestIngestSessionsDuplicates:
    def test_duplicate_uuid_is_safe_noop_on_reingest(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            session = _session_in()

            first = service.ingest_sessions(db, user_a, [session])
            assert first.accepted == 1
            assert first.duplicate == 0
            assert _by_id(first, session.id).status is IngestStatus.accepted

            second = service.ingest_sessions(db, user_a, [session])
            assert second.accepted == 0
            assert second.duplicate == 1
            assert second.invalid == 0
            assert _by_id(second, session.id).status is IngestStatus.duplicate

            assert db.query(LocalSession).filter(LocalSession.id == session.id).count() == 1
        finally:
            db.close()

    def test_duplicate_within_same_batch_only_inserts_once(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            session = _session_in()
            result = service.ingest_sessions(db, user_a, [session, session])

            assert result.accepted == 1
            assert result.duplicate == 1
            assert result.invalid == 0
            assert db.query(LocalSession).filter(LocalSession.id == session.id).count() == 1
        finally:
            db.close()

    def test_same_session_id_across_different_users_does_not_conflict(self, users):
        """The conflict/idempotency key is (user_id, id), not id alone -- a
        UUID collision across two different users' data should never happen
        in practice, but if it ever did, each user's row must be independent
        rather than one silently shadowing the other."""
        user_a, user_b = users
        db = SessionLocal()
        try:
            shared_id = uuid4()
            result_a = service.ingest_sessions(db, user_a, [_session_in(id=shared_id)])
            result_b = service.ingest_sessions(db, user_b, [_session_in(id=shared_id)])

            assert result_a.accepted == 1
            assert result_b.accepted == 1
            assert result_b.duplicate == 0

            rows = db.query(LocalSession).filter(LocalSession.id == shared_id).all()
            assert len(rows) == 2
            assert {row.user_id for row in rows} == {user_a, user_b}
        finally:
            db.close()

    def test_resync_of_closed_session_updates_mutable_fields_not_silently_dropped(self, users):
        """The critical fix: a crash-recovered session synced with
        provisional/wrong mutable fields, then re-synced once the tracker
        finalizes it correctly, must have its DB row UPDATED -- not
        silently left stale under ON CONFLICT DO NOTHING."""
        user_a, _ = users
        db = SessionLocal()
        try:
            session_id = uuid4()
            now = datetime.now(timezone.utc)
            started_at = now - timedelta(minutes=30)

            provisional = _session_in(
                id=session_id,
                started_at=started_at,
                ended_at=now - timedelta(minutes=20),
                end_reason="lock",
                is_idle=False,
            )
            first = service.ingest_sessions(db, user_a, [provisional])
            assert first.accepted == 1

            finalized = _session_in(
                id=session_id,
                started_at=started_at,
                ended_at=now - timedelta(minutes=1),
                end_reason="switch",
                is_idle=True,
            )
            second = service.ingest_sessions(db, user_a, [finalized])
            assert second.duplicate == 1
            assert _by_id(second, session_id).status is IngestStatus.duplicate

            row = db.query(LocalSession).filter(LocalSession.id == session_id).one()
            assert row.ended_at == finalized.ended_at
            assert row.end_reason == "switch"
            assert row.is_idle is True
            assert db.query(LocalSession).filter(LocalSession.id == session_id).count() == 1
        finally:
            db.close()

    def test_resync_updates_every_mutable_field_not_just_the_previously_covered_ones(self, users):
        """UPSERT_FIELDS previously only updated ended_at/end_reason/is_idle on
        conflict, silently dropping a corrected bundle_id/app_name/window_title/
        started_at re-sent by the tracker -- the ingest docstring's promise that
        the DB "holds the latest version" must hold for every mutable field."""
        user_a, _ = users
        db = SessionLocal()
        try:
            session_id = uuid4()
            now = datetime.now(timezone.utc)

            provisional = _session_in(
                id=session_id,
                bundle_id="com.apple.Terminal",
                app_name="Terminal",
                window_title="zsh",
                started_at=now - timedelta(minutes=30),
                ended_at=now - timedelta(minutes=20),
            )
            first = service.ingest_sessions(db, user_a, [provisional])
            assert first.accepted == 1

            corrected_started_at = now - timedelta(minutes=25)
            corrected = _session_in(
                id=session_id,
                bundle_id="com.apple.Safari",
                app_name="Safari",
                window_title="Example Domain",
                started_at=corrected_started_at,
                ended_at=now - timedelta(minutes=20),
            )
            second = service.ingest_sessions(db, user_a, [corrected])
            assert second.duplicate == 1

            row = db.query(LocalSession).filter(LocalSession.id == session_id).one()
            assert row.bundle_id == "com.apple.Safari"
            assert row.app_name == "Safari"
            assert row.window_title == "Example Domain"
            assert row.started_at == corrected_started_at
        finally:
            db.close()


class TestUpsertConditionalWrite:
    """upsert_sessions' ON CONFLICT DO UPDATE carries a WHERE ... is_distinct_from
    guard so idempotent re-syncs skip the write entirely, avoiding needless
    WAL/vacuum churn -- while a genuine field change must still update the row
    and bump `synced_at` (which previously only had a value from the initial
    insert's server_default and never moved again)."""

    @staticmethod
    def _xmin(db, user_id, session_id) -> str:
        return db.execute(
            text("SELECT xmin::text FROM local_sessions WHERE user_id = :user_id AND id = :id"),
            {"user_id": user_id, "id": str(session_id)},
        ).scalar_one()

    def test_resync_with_real_field_change_updates_and_bumps_synced_at(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            session_id = uuid4()
            now = datetime.now(timezone.utc)
            started_at = now - timedelta(minutes=30)

            original = _session_in(
                id=session_id,
                started_at=started_at,
                ended_at=now - timedelta(minutes=20),
                end_reason="lock",
            )
            service.ingest_sessions(db, user_a, [original])
            first_synced_at = db.query(LocalSession).filter(LocalSession.id == session_id).one().synced_at

            time.sleep(0.01)

            changed = _session_in(
                id=session_id,
                started_at=started_at,
                ended_at=now - timedelta(minutes=10),
                end_reason="switch",
            )
            result = service.ingest_sessions(db, user_a, [changed])
            assert _by_id(result, session_id).status is IngestStatus.duplicate

            row = db.query(LocalSession).filter(LocalSession.id == session_id).one()
            assert row.ended_at == changed.ended_at
            assert row.end_reason == "switch"
            assert row.synced_at > first_synced_at
        finally:
            db.close()

    def test_identical_resync_skips_the_write_entirely(self, users):
        """The critical fix: re-sending byte-identical mutable fields must not
        perform an actual UPDATE at the storage layer. Verified via Postgres's
        `xmin` system column (the row version stamped by whichever transaction
        last wrote it) rather than end-state values -- an unconditional
        ON CONFLICT DO UPDATE would leave the same values in place but still
        bump xmin on every idempotent re-sync, which is exactly the
        WAL/vacuum churn this fix exists to avoid."""
        user_a, _ = users
        db = SessionLocal()
        try:
            session = _session_in()
            service.ingest_sessions(db, user_a, [session])
            xmin_before = self._xmin(db, user_a, session.id)

            time.sleep(0.01)

            result = service.ingest_sessions(db, user_a, [session])
            assert _by_id(result, session.id).status is IngestStatus.duplicate

            xmin_after = self._xmin(db, user_a, session.id)
            assert xmin_after == xmin_before
        finally:
            db.close()


class TestIngestSessionsValidation:
    def test_duration_of_18_hours_or_more_is_invalid(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            bad = _session_in(
                started_at=now - timedelta(hours=MAX_SESSION_DURATION_HOURS, minutes=1),
                ended_at=now - timedelta(minutes=1),
            )
            good = _session_in()

            result = service.ingest_sessions(db, user_a, [bad, good])

            assert result.accepted == 1
            assert result.invalid == 1
            bad_result = _by_id(result, bad.id)
            assert bad_result.status is IngestStatus.invalid
            assert "18h" in bad_result.reason
            assert db.query(LocalSession).filter(LocalSession.id == bad.id).count() == 0
            assert db.query(LocalSession).filter(LocalSession.id == good.id).count() == 1
        finally:
            db.close()

    def test_ended_at_far_in_the_future_is_invalid(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            bad = _session_in(started_at=now + timedelta(minutes=30), ended_at=now + timedelta(minutes=40))
            good = _session_in()

            result = service.ingest_sessions(db, user_a, [bad, good])

            assert result.accepted == 1
            assert result.invalid == 1
            bad_result = _by_id(result, bad.id)
            assert bad_result.status is IngestStatus.invalid
            assert "future" in bad_result.reason
        finally:
            db.close()

    def test_ended_at_within_clock_skew_tolerance_is_accepted(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            assert CLOCK_SKEW_TOLERANCE_MINUTES == 5
            within_tolerance = _session_in(
                started_at=now - timedelta(minutes=10),
                ended_at=now + timedelta(minutes=2),
            )

            result = service.ingest_sessions(db, user_a, [within_tolerance])

            assert result.accepted == 1
            assert result.invalid == 0
        finally:
            db.close()

    def test_zero_duration_session_is_accepted(self, users):
        """started_at <= ended_at, not strictly less-than -- an
        instantaneous session (e.g. a rapid title change) is real data, not
        an error."""
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            same_instant = now - timedelta(minutes=5)
            zero_duration = _session_in(started_at=same_instant, ended_at=same_instant)

            result = service.ingest_sessions(db, user_a, [zero_duration])

            assert result.accepted == 1
            assert result.invalid == 0
        finally:
            db.close()

    def test_ended_at_before_started_at_is_invalid(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            bad = _session_in(started_at=now - timedelta(minutes=5), ended_at=now - timedelta(minutes=10))
            good = _session_in()

            result = service.ingest_sessions(db, user_a, [bad, good])

            assert result.accepted == 1
            assert result.invalid == 1
            bad_result = _by_id(result, bad.id)
            assert bad_result.status is IngestStatus.invalid
            assert "before" in bad_result.reason
        finally:
            db.close()

    def test_still_open_session_is_rejected(self, users):
        """Only genuinely-closed sessions (ended_at and end_reason both
        present) are eligible for ingest -- a still-open or
        not-yet-finalized session must be re-synced later."""
        user_a, _ = users
        db = SessionLocal()
        try:
            still_open = _session_in(ended_at=None, end_reason=None)

            result = service.ingest_sessions(db, user_a, [still_open])

            assert result.accepted == 0
            assert result.invalid == 1
            row_result = _by_id(result, still_open.id)
            assert row_result.status is IngestStatus.invalid
            assert "not yet closed" in row_result.reason
            assert db.query(LocalSession).filter(LocalSession.id == still_open.id).count() == 0
        finally:
            db.close()

    def test_blank_end_reason_is_invalid(self, users):
        """An empty-string end_reason must not pass the closed-session gate --
        only `is None` was checked before, so "" slipped through as if the
        session were genuinely closed."""
        user_a, _ = users
        db = SessionLocal()
        try:
            blank = _session_in(end_reason="")

            result = service.ingest_sessions(db, user_a, [blank])

            assert result.invalid == 1
            bad_result = _by_id(result, blank.id)
            assert bad_result.status is IngestStatus.invalid
            assert "blank" in bad_result.reason
            assert db.query(LocalSession).filter(LocalSession.id == blank.id).count() == 0
        finally:
            db.close()

    def test_whitespace_only_end_reason_is_invalid(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            whitespace_only = _session_in(end_reason="   ")

            result = service.ingest_sessions(db, user_a, [whitespace_only])

            assert result.invalid == 1
            bad_result = _by_id(result, whitespace_only.id)
            assert bad_result.status is IngestStatus.invalid
            assert "blank" in bad_result.reason
            assert db.query(LocalSession).filter(LocalSession.id == whitespace_only.id).count() == 0
        finally:
            db.close()

    def test_naive_datetime_is_rejected_as_invalid(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            naive_now = datetime.now()
            bad = _session_in(started_at=naive_now - timedelta(minutes=10), ended_at=naive_now - timedelta(minutes=5))

            result = service.ingest_sessions(db, user_a, [bad])

            assert result.invalid == 1
            bad_result = _by_id(result, bad.id)
            assert bad_result.status is IngestStatus.invalid
            assert "timezone" in bad_result.reason
            assert db.query(LocalSession).filter(LocalSession.id == bad.id).count() == 0
        finally:
            db.close()

    def test_non_utc_timezone_is_normalized_and_accepted(self, users):
        """Comparisons happen in UTC -- an equivalent instant expressed in a
        different timezone must not be penalized."""
        user_a, _ = users
        db = SessionLocal()
        try:
            plus_five = timezone(timedelta(hours=5))
            now_local = datetime.now(plus_five)
            session = _session_in(
                started_at=now_local - timedelta(minutes=10),
                ended_at=now_local - timedelta(minutes=5),
            )

            result = service.ingest_sessions(db, user_a, [session])

            assert result.accepted == 1
            assert result.invalid == 0

            row = db.query(LocalSession).filter(LocalSession.id == session.id).one()
            assert row.started_at.astimezone(timezone.utc) == session.started_at.astimezone(timezone.utc)
            assert row.ended_at.astimezone(timezone.utc) == session.ended_at.astimezone(timezone.utc)
        finally:
            db.close()

    def test_unknown_end_reason_is_accepted_and_stored(self, users, caplog):
        """Reversed from the old behavior: an end_reason outside
        KNOWN_END_REASONS is accepted and stored as free text (with a
        warning logged), never rejected -- a future tracker release adding
        a new end_reason must not cause silent, permanent data loss."""
        user_a, _ = users
        db = SessionLocal()
        try:
            assert "reboot" not in KNOWN_END_REASONS
            unknown_reason = _session_in(end_reason="reboot")

            with caplog.at_level("WARNING"):
                result = service.ingest_sessions(db, user_a, [unknown_reason])

            assert result.accepted == 1
            assert result.invalid == 0
            assert _by_id(result, unknown_reason.id).status is IngestStatus.accepted
            assert any(getattr(record, "end_reason", None) == "reboot" for record in caplog.records)

            row = db.query(LocalSession).filter(LocalSession.id == unknown_reason.id).one()
            assert row.end_reason == "reboot"
        finally:
            db.close()

    def test_all_known_end_reasons_are_accepted(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            sessions = [_session_in(end_reason=reason) for reason in KNOWN_END_REASONS]
            result = service.ingest_sessions(db, user_a, sessions)

            assert result.accepted == len(KNOWN_END_REASONS)
            assert result.invalid == 0
        finally:
            db.close()

    def test_is_idle_true_is_not_rejected(self, users):
        """is_idle=True rows are real evidence the later aggregation step
        needs -- they must never be rejected outright."""
        user_a, _ = users
        db = SessionLocal()
        try:
            idle_session = _session_in(end_reason="idle", is_idle=True)

            result = service.ingest_sessions(db, user_a, [idle_session])

            assert result.accepted == 1
            assert result.invalid == 0
            row = db.query(LocalSession).filter(LocalSession.id == idle_session.id).one()
            assert row.is_idle is True
        finally:
            db.close()

    def test_invalid_rows_do_not_fail_the_whole_batch(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            all_bad = [
                _session_in(started_at=now - timedelta(minutes=5), ended_at=now - timedelta(minutes=10)),
                _session_in(started_at=now + timedelta(hours=1), ended_at=now + timedelta(hours=2)),
                _session_in(
                    started_at=now - timedelta(hours=MAX_SESSION_DURATION_HOURS + 1),
                    ended_at=now - timedelta(minutes=1),
                ),
            ]
            good = [_session_in(), _session_in()]

            result = service.ingest_sessions(db, user_a, all_bad + good)

            assert result.accepted == 2
            assert result.invalid == 3
        finally:
            db.close()

    def test_malformed_uuid_is_rejected_at_schema_construction(self):
        with pytest.raises(pydantic.ValidationError):
            LocalSessionIn(
                id="not-a-uuid",
                bundle_id="com.apple.Terminal",
                app_name="Terminal",
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
                end_reason="switch",
                is_idle=False,
            )


class TestIngestResponseContract:
    def test_three_distinct_statuses_returned_for_one_batch(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            existing = _session_in()
            service.ingest_sessions(db, user_a, [existing])

            fresh = _session_in()
            invalid = _session_in(ended_at=None, end_reason=None)

            result = service.ingest_sessions(db, user_a, [existing, fresh, invalid])

            assert _by_id(result, existing.id).status is IngestStatus.duplicate
            assert _by_id(result, fresh.id).status is IngestStatus.accepted
            assert _by_id(result, invalid.id).status is IngestStatus.invalid
            assert {r.status for r in result.results} == {
                IngestStatus.duplicate,
                IngestStatus.accepted,
                IngestStatus.invalid,
            }
        finally:
            db.close()

    def test_db_level_duplicate_has_an_explicit_reason(self, users):
        """A DB-level duplicate (already existing from a prior call) must carry
        a reason string, matching the in-batch duplicate case which already
        has one ("duplicate id within batch") -- not leave `reason` as None."""
        user_a, _ = users
        db = SessionLocal()
        try:
            session = _session_in()
            service.ingest_sessions(db, user_a, [session])

            result = service.ingest_sessions(db, user_a, [session])

            db_duplicate = _by_id(result, session.id)
            assert db_duplicate.status is IngestStatus.duplicate
            assert db_duplicate.reason == "session updated in database"
        finally:
            db.close()

    def test_schema_version_is_accepted_and_logged_but_not_enforced(self, users, caplog):
        user_a, _ = users
        db = SessionLocal()
        try:
            session = _session_in()
            with caplog.at_level("INFO"):
                result = service.ingest_sessions(db, user_a, [session], schema_version="tracker-1.2.0")

            assert result.accepted == 1
            assert any(getattr(record, "schema_version", None) == "tracker-1.2.0" for record in caplog.records)
        finally:
            db.close()


class TestCleanupIsolatedFromIngest:
    def test_cleanup_is_not_reachable_from_the_ingest_module(self):
        assert not hasattr(service, "cleanup_synced_sessions")
        assert hasattr(retention, "cleanup_synced_sessions")

    def test_ingest_never_invokes_cleanup(self, users, monkeypatch):
        user_a, _ = users
        db = SessionLocal()
        try:
            def _fail(*args, **kwargs):
                raise AssertionError("cleanup_synced_sessions must never be invoked from the ingest path")

            monkeypatch.setattr(retention, "cleanup_synced_sessions", _fail)
            service.ingest_sessions(db, user_a, [_session_in(), _session_in()])
        finally:
            db.close()


class TestCleanupSyncedSessions:
    @staticmethod
    def _insert_session(db, user_id, *, started_at, synced_at):
        row = LocalSession(
            id=uuid4(),
            user_id=user_id,
            bundle_id="com.apple.Terminal",
            app_name="Terminal",
            window_title=None,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=5),
            end_reason="switch",
            is_idle=False,
            synced_at=synced_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _add_entry(db, user_id, *, created_at, status, work_date=None):
        entry = Entry(
            user_id=user_id,
            format=EntryFormat.project_log,
            content={"text": "test"},
            status=status,
            created_at=created_at,
            work_date=work_date if work_date is not None else created_at.date(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    def test_deletes_old_and_reconciled_session(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            old_day = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            self._add_entry(db, user_a, created_at=old_day, status=EntryStatus.approved)
            row = self._insert_session(db, user_a, started_at=old_day, synced_at=old_day)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 1
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 0
        finally:
            db.close()

    def test_keeps_old_but_unreconciled_session(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            old_day = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            row = self._insert_session(db, user_a, started_at=old_day, synced_at=old_day)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 1
        finally:
            db.close()

    def test_non_approved_entry_does_not_reconcile(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            old_day = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            self._add_entry(db, user_a, created_at=old_day, status=EntryStatus.pending)
            row = self._insert_session(db, user_a, started_at=old_day, synced_at=old_day)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 1
        finally:
            db.close()

    def test_keeps_reconciled_but_recent_session(self, users):
        user_a, _ = users
        db = SessionLocal()
        try:
            recent_day = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS - 5)
            self._add_entry(db, user_a, created_at=recent_day, status=EntryStatus.approved)
            row = self._insert_session(db, user_a, started_at=recent_day, synced_at=recent_day)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 1
        finally:
            db.close()

    def test_never_deletes_a_different_users_session_from_this_users_approval(self, users):
        user_a, user_b = users
        db = SessionLocal()
        try:
            old_day = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            # user_a has the approved entry; user_b has the old session on the
            # same calendar date. user_b's row must not be reconciled by
            # user_a's approval -- retention is scoped per user.
            self._add_entry(db, user_a, created_at=old_day, status=EntryStatus.approved)
            row_b = self._insert_session(db, user_b, started_at=old_day, synced_at=old_day)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == row_b.id).count() == 1
        finally:
            db.close()

    def test_retention_uses_the_actual_work_date_not_the_approval_date(self, users):
        """The critical fix: get_approved_entry_dates() must key off
        Entry.work_date (the day the work happened) not Entry.created_at (when
        the entry got approved) -- someone working Monday but approving Friday
        must still have Monday's raw session data correctly reconciled."""
        user_a, _ = users
        db = SessionLocal()
        try:
            monday = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            friday = monday + timedelta(days=4)
            assert friday.date() != monday.date()

            # Approved on Friday (created_at), but the entry is ABOUT Monday's work.
            self._add_entry(db, user_a, created_at=friday, status=EntryStatus.approved, work_date=monday.date())
            row = self._insert_session(db, user_a, started_at=monday, synced_at=monday)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 1
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 0
        finally:
            db.close()

    def test_retention_does_not_match_by_coincidental_approval_date(self, users):
        """Companion to the above: an unrelated old session that happens to
        fall on the entry's Friday approval date must NOT be reconciled just
        because created_at coincidentally lines up -- only a real work_date
        match should ever trigger deletion."""
        user_a, _ = users
        db = SessionLocal()
        try:
            monday = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            friday = monday + timedelta(days=4)

            # Entry approved Friday, about Monday's work.
            self._add_entry(db, user_a, created_at=friday, status=EntryStatus.approved, work_date=monday.date())
            # A different, unrelated old session that happens to fall on Friday's date.
            unrelated_row = self._insert_session(db, user_a, started_at=friday, synced_at=friday)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == unrelated_row.id).count() == 1
        finally:
            db.close()

    def test_session_near_utc_midnight_boundary_matches_correct_calendar_day(self, users):
        """A session timestamped near UTC midnight, expressed in a non-UTC
        offset, must be matched against its actual UTC calendar day -- not
        whatever day its own local offset's wall-clock time would naively
        suggest. This is the scenario the explicit `.astimezone(timezone.utc)`
        normalization in retention.py guards against, since work_date is
        computed in UTC (see the module's documented known limitation)."""
        user_a, _ = users
        db = SessionLocal()
        try:
            minus_five = timezone(timedelta(hours=-5))
            # 2026-04-01 23:55 in UTC-5 is 2026-04-02 04:55 UTC -- the session's
            # real UTC calendar day is April 2nd, not April 1st.
            local_late_night = datetime(2026, 4, 1, 23, 55, tzinfo=minus_five)
            true_utc_day = local_late_night.astimezone(timezone.utc).date()
            assert true_utc_day == date(2026, 4, 2)

            old_synced_at = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            self._add_entry(
                db, user_a, created_at=old_synced_at, status=EntryStatus.approved, work_date=true_utc_day
            )
            row = self._insert_session(db, user_a, started_at=local_late_night, synced_at=old_synced_at)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 1
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 0
        finally:
            db.close()

    def test_session_near_utc_midnight_boundary_does_not_match_the_wrong_day(self, users):
        """Companion to the above: work_date for the local-offset day (April
        1st -- what a naive, non-UTC-normalized read might produce) must NOT
        match -- only the true UTC day (April 2nd) is correct."""
        user_a, _ = users
        db = SessionLocal()
        try:
            minus_five = timezone(timedelta(hours=-5))
            local_late_night = datetime(2026, 4, 1, 23, 55, tzinfo=minus_five)
            wrong_local_day = date(2026, 4, 1)

            old_synced_at = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS + 5)
            self._add_entry(
                db, user_a, created_at=old_synced_at, status=EntryStatus.approved, work_date=wrong_local_day
            )
            row = self._insert_session(db, user_a, started_at=local_late_night, synced_at=old_synced_at)

            deleted = retention.cleanup_synced_sessions(db)

            assert deleted == 0
            assert db.query(LocalSession).filter(LocalSession.id == row.id).count() == 1
        finally:
            db.close()
