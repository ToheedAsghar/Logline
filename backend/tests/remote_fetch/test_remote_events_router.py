"""Tests for GET /remote-events -- keyset pagination, scoping, and filters, against the real Postgres database."""

from datetime import datetime as dt
from datetime import timedelta, timezone

from fastapi.testclient import TestClient

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import SessionLocal
from app.main import app
from app.matching.models import RemoteEvent

TEST_EMAIL = "remote-events-test@example.com"
OTHER_EMAIL = "remote-events-other@example.com"
BASE = dt(2026, 8, 1, tzinfo=timezone.utc)


def _make_user(db, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password="not-a-real-hash")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _make_events(db, user_id: int, n: int, *, offset_days: int = 0, base: dt = BASE) -> None:
    for i in range(n):
        db.add(
            RemoteEvent(
                user_id=user_id,
                source="github",
                event_type="pull_request",
                external_id=f"ext-{offset_days}-{i}",
                occurred_at=base - timedelta(days=offset_days, minutes=i),
                summary=f"event {i}",
                description=f"desc {i}",
                raw_data={"raw": i},
            )
        )
    db.commit()


class _Client:
    def __init__(self):
        self.db = SessionLocal()
        self.user = _make_user(self.db, TEST_EMAIL)
        self.owner = self.user.id
        self.db.query(RemoteEvent).filter(RemoteEvent.user_id == self.owner).delete()
        self.db.commit()

        other = _make_user(self.db, OTHER_EMAIL)
        self.other = other.id
        self.db.query(RemoteEvent).filter(RemoteEvent.user_id == self.other).delete()
        self.db.commit()
        _make_events(self.db, self.other, 3)

        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def close(self):
        self.db.query(RemoteEvent).filter(RemoteEvent.user_id == self.owner).delete()
        self.db.query(RemoteEvent).filter(RemoteEvent.user_id == self.other).delete()
        self.db.commit()
        app.dependency_overrides.pop(get_current_user, None)
        self.db.close()


def test_pages_do_not_overlap_and_walk_every_row():
    c = _Client()
    try:
        _make_events(c.db, c.owner, 7)
        seen = []
        cursor = None
        while True:
            params = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = c.client.get("/remote-events", params=params)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            seen.extend(ev["id"] for ev in body["events"])
            if not body["has_more"]:
                assert body["next_cursor"] is None
                break
            assert body["next_cursor"] is not None
            cursor = body["next_cursor"]
        assert len(seen) == 7
        assert len(set(seen)) == 7
    finally:
        c.close()


def test_events_scoped_to_current_user_and_raw_data_excluded():
    c = _Client()
    try:
        _make_events(c.db, c.owner, 2)
        resp = c.client.get("/remote-events", params={"limit": 50})
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is False
        assert len(body["events"]) == 2
        assert "raw_data" not in body["events"][0]
    finally:
        c.close()


def test_ordering_is_occurred_at_desc_then_id_desc():
    c = _Client()
    try:
        # Two events at the exact same occurred_at: the later insert gets a higher
        # auto-increment id, which must sort first under (occurred_at DESC, id DESC).
        t = BASE
        for i in range(2):
            c.db.add(
                RemoteEvent(
                    user_id=c.owner,
                    source="github",
                    event_type="pull_request",
                    external_id=f"tie-i{i}",
                    occurred_at=t,
                    summary=f"tie {i}",
                    description=None,
                    raw_data={},
                )
            )
        c.db.flush()
        rows = (
            c.db.query(RemoteEvent)
            .filter(RemoteEvent.external_id.like("tie-%"))
            .order_by(RemoteEvent.id.desc())
            .all()
        )
        higher_id = rows[0].id
        lower_id = rows[1].id
        c.db.commit()

        resp = c.client.get("/remote-events", params={"limit": 50})
        events = resp.json()["events"]
        # external_id is not in the response; identify tie events by summary prefix.
        tie_events = [ev for ev in events if ev["summary"] and ev["summary"].startswith("tie ")]
        assert len(tie_events) == 2
        assert tie_events[0]["id"] == higher_id
        assert tie_events[1]["id"] == lower_id
    finally:
        c.close()


def test_source_filter_and_empty_page_for_no_match():
    c = _Client()
    try:
        _make_events(c.db, c.owner, 2)
        resp = c.client.get("/remote-events", params={"source": "slack", "limit": 50})
        assert resp.status_code == 200
        assert resp.json() == {"events": [], "next_cursor": None, "has_more": False}
    finally:
        c.close()


def test_date_range_filters_occurred_at_half_open():
    c = _Client()
    try:
        # t0 is the newest event, t1 is one minute older.
        # Range [t1, t0) should include only t1 (exclusive end).
        t0 = BASE
        t1 = t0 - timedelta(minutes=1)
        c.db.add(
            RemoteEvent(
                user_id=c.owner, source="github", event_type="push",
                external_id="range-a", occurred_at=t0, summary="at t0", raw_data={},
            )
        )
        c.db.add(
            RemoteEvent(
                user_id=c.owner, source="github", event_type="push",
                external_id="range-b", occurred_at=t1, summary="at t1", raw_data={},
            )
        )
        c.db.commit()

        start = t1.isoformat()
        end = t0.isoformat()
        resp = c.client.get("/remote-events", params={"date_range_start": start, "date_range_end": end})
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 1
        assert events[0]["summary"] == "at t1"
    finally:
        c.close()


def test_invalid_cursor_returns_422_and_unauth_returns_401():
    c = _Client()
    try:
        resp = c.client.get("/remote-events", params={"cursor": "garbage"})
        assert resp.status_code == 422
    finally:
        c.close()

    # Unauthenticated request.
    resp = TestClient(app).get("/remote-events")
    assert resp.status_code == 401
