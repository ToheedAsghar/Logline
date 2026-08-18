"""Test that reconciliation reads day boundaries in the user's timezone rather than UTC."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.agent.reconciliation.routers import ReconciliationDateRange
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import SessionLocal
from app.main import app

USER_EMAIL = "reconciliation-timezone-test@example.com"
KARACHI = ZoneInfo("Asia/Karachi")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user_factory():
    """Yield a factory creating the test user with a given timezone, removed afterwards."""
    created_ids: list[int] = []

    def make(tz_name):
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == USER_EMAIL).delete()
            db.commit()
            user = User(email=USER_EMAIL, hashed_password="not-a-real-hash", timezone=tz_name)
            db.add(user)
            db.commit()
            db.refresh(user)
            created_ids.append(user.id)
            app.dependency_overrides[get_current_user] = lambda: user
            return user
        finally:
            db.close()

    yield make

    app.dependency_overrides.pop(get_current_user, None)
    db = SessionLocal()
    try:
        db.query(User).filter(User.id.in_(created_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


class TestLocalDayBounds:
    def test_bounds_start_at_local_midnight_expressed_in_utc(self):
        """Karachi is UTC+5, so local midnight on Aug 5 is 19:00 UTC on Aug 4."""
        start, _ = ReconciliationDateRange(
            date_range_start=date(2026, 8, 5), date_range_end=date(2026, 8, 5)
        ).as_utc_bounds(KARACHI)

        assert start == datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)

    def test_bounds_end_at_the_next_local_midnight_exclusive(self):
        _, end = ReconciliationDateRange(
            date_range_start=date(2026, 8, 5), date_range_end=date(2026, 8, 5)
        ).as_utc_bounds(KARACHI)

        assert end == datetime(2026, 8, 5, 19, 0, tzinfo=timezone.utc)

    def test_a_single_day_spans_exactly_twenty_four_hours(self):
        start, end = ReconciliationDateRange(
            date_range_start=date(2026, 8, 5), date_range_end=date(2026, 8, 5)
        ).as_utc_bounds(KARACHI)

        assert (end - start).total_seconds() == 24 * 60 * 60

    def test_a_multi_day_range_covers_every_day_inclusively(self):
        start, end = ReconciliationDateRange(
            date_range_start=date(2026, 8, 4), date_range_end=date(2026, 8, 6)
        ).as_utc_bounds(KARACHI)

        assert (end - start).total_seconds() == 3 * 24 * 60 * 60

    def test_utc_bounds_differ_from_local_bounds_for_an_offset_timezone(self):
        """The regression itself: the same nominal day is a different span of real time in each zone."""
        payload = ReconciliationDateRange(date_range_start=date(2026, 8, 5), date_range_end=date(2026, 8, 5))

        assert payload.as_utc_bounds(KARACHI) != payload.as_utc_bounds(timezone.utc)

    def test_a_utc_user_still_gets_plain_utc_day_bounds(self):
        start, end = ReconciliationDateRange(
            date_range_start=date(2026, 8, 5), date_range_end=date(2026, 8, 5)
        ).as_utc_bounds(timezone.utc)

        assert start == datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc)


class TestTimezoneIsRequired:
    def test_generate_rejects_a_user_without_a_timezone(self, client, user_factory):
        """Falling back to UTC is exactly the misattribution this fix removes, so it must fail loudly instead."""
        user_factory(None)

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": "2026-08-05", "date_range_end": "2026-08-05"},
        )

        assert response.status_code == 400

    def test_the_missing_timezone_error_says_how_to_fix_it(self, client, user_factory):
        user_factory(None)

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": "2026-08-05", "date_range_end": "2026-08-05"},
        )

        assert "IANA" in response.json()["detail"]

    def test_generate_rejects_an_unrecognised_timezone_name(self, client, user_factory):
        user_factory("Mars/Olympus_Mons")

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": "2026-08-05", "date_range_end": "2026-08-05"},
        )

        assert response.status_code == 400

    def test_generate_rejects_a_timezone_name_that_escapes_the_zone_database(self, client, user_factory):
        user_factory("../../etc/passwd")

        response = client.post(
            "/reconciliation/generate",
            json={"date_range_start": "2026-08-05", "date_range_end": "2026-08-05"},
        )

        assert response.status_code == 400

    def test_approve_also_rejects_a_user_without_a_timezone(self, client, user_factory):
        user_factory(None)

        response = client.post(
            "/reconciliation/approve",
            json={
                "date_range_start": "2026-08-05",
                "date_range_end": "2026-08-05",
                "draft_id": 1,
                "draft": {"entries": [], "reminders": [], "residual_unassigned_minutes": []},
            },
        )

        assert response.status_code == 400
