"""Tests for the remote fetch orchestrator and event persistence."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.db.session import SessionLocal
from app.matching.models import RemoteEvent
from app.remote_fetch import orchestrator as orchestrator_module
from app.remote_fetch.base import FetchedEvent, SourceFetchData, SourceFetcher, SourceUnavailable
from app.remote_fetch.models import RemoteFetchState
from app.remote_fetch.orchestrator import fetch_all_sources, record_fetch_state, resolve_since, upsert_remote_events

TEST_EMAIL = "remote-fetch-orchestrator-test@example.com"
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


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
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.query(RemoteFetchState).filter(RemoteFetchState.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.query(RemoteFetchState).filter(RemoteFetchState.user_id == user_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


def _event(source="github", external_id="sha-1", summary="Did a thing", description=None):
    return FetchedEvent(
        source=source,
        event_type="commit",
        external_id=external_id,
        occurred_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
        summary=summary,
        description=description,
        remote_project_id="Toheed/logline",
        match_keys={"repo": "Toheed/logline"},
        raw_data={"sha": external_id},
    )


class _FakeFetcher(SourceFetcher):
    """Stands in for a real fetcher: no MCP connection, scripted outcome.

    Overrides `fetch` rather than `fetch_with_session` precisely because
    `fetch` is the layer that would open a real MCP connection -- replacing it
    is what keeps these tests offline.
    """

    def __init__(self, source, events=None, raises=None, hang=False):
        self.source = source
        self._events = events or []
        self._raises = raises
        self._hang = hang

    async def fetch(self, user_id, since):
        if self._hang:
            await asyncio.sleep(3600)
        if self._raises is not None:
            raise self._raises
        return SourceFetchData(events=self._events)

    async def fetch_with_session(self, session, user_id, since):  # pragma: no cover - never reached
        raise AssertionError("fetch() is overridden; fetch_with_session must not be called")


def _install(monkeypatch, fetchers: dict):
    monkeypatch.setattr(
        orchestrator_module, "FETCHERS", {source: (lambda f=f: f) for source, f in fetchers.items()}
    )


class TestFailureIsolation:
    def test_one_source_raising_does_not_stop_the_others(self, monkeypatch, real_db_user):
        _install(
            monkeypatch,
            {
                "github": _FakeFetcher("github", raises=RuntimeError("GitHub API 500")),
                "jira": _FakeFetcher("jira", events=[_event("jira", "LOG-1@x")]),
                "slack": _FakeFetcher("slack", events=[_event("slack", "C1:1.0")]),
                "calendar": _FakeFetcher("calendar", events=[_event("calendar", "evt-1")]),
            },
        )

        results = asyncio.run(fetch_all_sources(real_db_user))

        assert results["github"].ok is False
        assert "GitHub API 500" in results["github"].error
        # The other three completed, independently and successfully.
        for source in ("jira", "slack", "calendar"):
            assert results[source].ok is True, results[source].error
            assert results[source].fetched == 1
            assert results[source].written == 1

    def test_an_unreachable_source_is_reported_not_raised(self, monkeypatch, real_db_user):
        _install(
            monkeypatch,
            {
                "github": _FakeFetcher("github", raises=SourceUnavailable("could not connect")),
                "jira": _FakeFetcher("jira", events=[_event("jira", "LOG-2@x")]),
            },
        )

        results = asyncio.run(fetch_all_sources(real_db_user, sources=["github", "jira"]))

        assert results["github"].ok is False
        assert "could not connect" in results["github"].error
        assert results["jira"].ok is True

    def test_a_hanging_source_times_out_without_blocking_the_others(self, monkeypatch, real_db_user):
        monkeypatch.setattr(orchestrator_module, "SOURCE_TIMEOUT_SECONDS", {"github": 0.05})
        monkeypatch.setattr(orchestrator_module, "DEFAULT_SOURCE_TIMEOUT_SECONDS", 30.0)
        _install(
            monkeypatch,
            {
                "github": _FakeFetcher("github", hang=True),
                "jira": _FakeFetcher("jira", events=[_event("jira", "LOG-3@x")]),
            },
        )

        results = asyncio.run(fetch_all_sources(real_db_user, sources=["github", "jira"]))

        assert results["github"].ok is False
        assert "timed out" in results["github"].error
        assert results["jira"].ok is True
        assert results["jira"].written == 1

    def test_every_requested_source_is_present_in_the_result(self, monkeypatch, real_db_user):
        """A failed source must not silently vanish -- "returned nothing" and
        "was never reached" are different facts the caller has to distinguish.
        """

        _install(
            monkeypatch,
            {
                "github": _FakeFetcher("github", raises=RuntimeError("boom")),
                "jira": _FakeFetcher("jira", events=[]),
                "slack": _FakeFetcher("slack", raises=RuntimeError("boom")),
                "calendar": _FakeFetcher("calendar", events=[]),
            },
        )

        results = asyncio.run(fetch_all_sources(real_db_user))

        assert set(results) == {"github", "jira", "slack", "calendar"}
        # jira reached the source and found nothing; github never reached it.
        assert results["jira"].ok is True and results["jira"].fetched == 0
        assert results["github"].ok is False


class TestIdempotentUpsert:
    def test_fetching_the_same_event_twice_creates_one_row(self, real_db_user):
        events = [_event(external_id="sha-dup")]

        with SessionLocal() as db:
            upsert_remote_events(db, real_db_user, events)
            db.commit()
        with SessionLocal() as db:
            upsert_remote_events(db, real_db_user, events)
            db.commit()

        with SessionLocal() as db:
            rows = db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).all()
        assert len(rows) == 1

    def test_refetching_updates_changed_fields_in_place(self, real_db_user):
        with SessionLocal() as db:
            upsert_remote_events(db, real_db_user, [_event(external_id="sha-upd", summary="Old summary")])
            db.commit()
        with SessionLocal() as db:
            upsert_remote_events(
                db,
                real_db_user,
                [_event(external_id="sha-upd", summary="New summary", description="Now with a why")],
            )
            db.commit()

        with SessionLocal() as db:
            rows = db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).all()
        assert len(rows) == 1
        assert rows[0].summary == "New summary"
        assert rows[0].description == "Now with a why"

    def test_a_full_run_repeated_does_not_duplicate(self, monkeypatch, real_db_user):
        _install(
            monkeypatch,
            {"github": _FakeFetcher("github", events=[_event(external_id="sha-run"), _event(external_id="sha-run-2")])},
        )

        first = asyncio.run(fetch_all_sources(real_db_user, sources=["github"]))
        second = asyncio.run(fetch_all_sources(real_db_user, sources=["github"]))

        assert first["github"].written == 2
        assert second["github"].written == 2  # both rows touched again...
        with SessionLocal() as db:
            rows = db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).all()
        assert len(rows) == 2  # ...but no new rows created

    def test_the_same_external_id_for_two_users_does_not_collide(self, real_db_user):
        other_email = "remote-fetch-orchestrator-other@example.com"
        with SessionLocal() as db:
            other = db.query(User).filter(User.email == other_email).first()
            if other is None:
                other = User(email=other_email, hashed_password="not-a-real-hash")
                db.add(other)
                db.commit()
                db.refresh(other)
            other_id = other.id
            db.query(RemoteEvent).filter(RemoteEvent.user_id == other_id).delete()
            db.commit()

        try:
            with SessionLocal() as db:
                upsert_remote_events(db, real_db_user, [_event(external_id="shared-sha")])
                upsert_remote_events(db, other_id, [_event(external_id="shared-sha")])
                db.commit()

            with SessionLocal() as db:
                assert db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).count() == 1
                assert db.query(RemoteEvent).filter(RemoteEvent.user_id == other_id).count() == 1
        finally:
            with SessionLocal() as db:
                db.query(RemoteEvent).filter(RemoteEvent.user_id == other_id).delete()
                db.query(User).filter(User.id == other_id).delete()
                db.commit()


class TestHighWaterMark:
    def test_first_fetch_is_bounded_to_the_lookback_window(self):
        since = resolve_since(None, NOW)

        assert since == NOW - timedelta(days=90)

    def test_an_existing_mark_is_used_verbatim(self):
        state = RemoteFetchState(user_id=1, source="github", last_fetched_through=NOW - timedelta(days=2))

        assert resolve_since(state, NOW) == NOW - timedelta(days=2)

    def test_a_state_row_that_never_succeeded_still_uses_the_lookback(self):
        state = RemoteFetchState(user_id=1, source="github", last_attempted_at=NOW, last_error="boom")

        assert resolve_since(state, NOW) == NOW - timedelta(days=90)

    def test_success_advances_the_mark_and_clears_the_error(self, monkeypatch, real_db_user):
        _install(monkeypatch, {"github": _FakeFetcher("github", events=[_event(external_id="sha-hw")])})

        asyncio.run(fetch_all_sources(real_db_user, sources=["github"]))

        with SessionLocal() as db:
            state = (
                db.query(RemoteFetchState)
                .filter(RemoteFetchState.user_id == real_db_user, RemoteFetchState.source == "github")
                .one()
            )
            assert state.last_fetched_through is not None
            assert state.last_error is None
            assert state.last_attempted_at is not None

    def test_failure_leaves_the_mark_untouched_but_records_the_attempt(self, monkeypatch, real_db_user):
        previous = NOW - timedelta(days=3)
        with SessionLocal() as db:
            record_fetch_state(
                db, real_db_user, "github", attempted_at=previous, fetched_through=previous, error=None
            )
            db.commit()

        _install(monkeypatch, {"github": _FakeFetcher("github", raises=RuntimeError("nope"))})
        asyncio.run(fetch_all_sources(real_db_user, sources=["github"]))

        with SessionLocal() as db:
            state = (
                db.query(RemoteFetchState)
                .filter(RemoteFetchState.user_id == real_db_user, RemoteFetchState.source == "github")
                .one()
            )
        # The mark did NOT move -- the next run re-covers this window.
        assert state.last_fetched_through == previous
        # But the failure is visible rather than looking like an idle source.
        assert "nope" in state.last_error
        assert state.last_attempted_at > previous

    def test_an_older_state_update_cannot_move_the_mark_backward(self, real_db_user):
        newer = NOW
        older = NOW - timedelta(hours=1)
        with SessionLocal() as db:
            record_fetch_state(db, real_db_user, "github", newer, newer, None)
            db.commit()
        with SessionLocal() as db:
            record_fetch_state(db, real_db_user, "github", older, older, "stale failure")
            db.commit()

        with SessionLocal() as db:
            state = (
                db.query(RemoteFetchState)
                .filter(RemoteFetchState.user_id == real_db_user, RemoteFetchState.source == "github")
                .one()
            )

        assert state.last_attempted_at == newer
        assert state.last_fetched_through == newer
        assert state.last_error is None

    def test_a_fetcher_may_hold_the_mark_back_but_never_push_it_forward(
        self, monkeypatch, real_db_user
    ):
        """Slack does this when a full page means older messages are unreachable."""

        held_back = NOW - timedelta(hours=6)

        class _HoldingFetcher(_FakeFetcher):
            async def fetch(self, user_id, since):
                return SourceFetchData(events=[], fetched_through_override=held_back)

        class _OverreachingFetcher(_FakeFetcher):
            async def fetch(self, user_id, since):
                return SourceFetchData(
                    events=[], fetched_through_override=NOW + timedelta(days=365)
                )

        _install(monkeypatch, {"slack": _HoldingFetcher("slack"), "calendar": _OverreachingFetcher("calendar")})

        results = asyncio.run(fetch_all_sources(real_db_user, sources=["slack", "calendar"]))

        assert results["slack"].fetched_through == held_back
        # An override past "now" is clamped -- we can't have fetched the future.
        assert results["calendar"].fetched_through <= datetime.now(timezone.utc)
