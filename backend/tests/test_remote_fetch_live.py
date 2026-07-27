"""Integration tests for remote source fetchers using live MCP servers."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.auth.models import User
from app.matching.models import RemoteEvent
from app.remote_fetch.base import SourceUnavailable
from app.remote_fetch.calendar import CalendarFetcher
from app.remote_fetch.github import GitHubFetcher
from app.remote_fetch.jira import JiraFetcher
from app.remote_fetch.models import RemoteFetchState
from app.remote_fetch.orchestrator import fetch_all_sources
from app.remote_fetch.slack import SlackFetcher

RUN_LIVE = os.environ.get("RUN_LIVE_REMOTE_FETCH_TESTS") == "1"
live_only = pytest.mark.skipif(
    not RUN_LIVE, reason="set RUN_LIVE_REMOTE_FETCH_TESTS=1 to make real MCP/API calls"
)

TEST_EMAIL = "remote-fetch-live-test@example.com"
LOOKBACK = timedelta(days=30)


def _since() -> datetime:
    return datetime.now(timezone.utc) - LOOKBACK


def _assert_schema_valid(events, source):
    """Every event must be insertable into `remote_events` as-is."""

    for event in events:
        assert event.source == source
        assert event.event_type, "event_type is NOT NULL"
        assert event.external_id, "external_id is NOT NULL and part of the unique key"
        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None, "occurred_at must be timezone-aware"
        assert isinstance(event.raw_data, dict) and event.raw_data, "raw_data is NOT NULL"
        if event.match_keys is not None:
            assert isinstance(event.match_keys, dict)


def _report(source, data):
    print(f"\n[live:{source}] fetched {len(data.events)} events")
    for event in data.events[:3]:
        print(
            f"  - {event.occurred_at.isoformat()} [{event.event_type}] "
            f"project={event.remote_project_id!r}\n"
            f"      summary={(event.summary or '')[:100]!r}\n"
            f"      description={(event.description or '')[:100]!r}"
        )


@pytest.fixture
def live_user():
    """A dedicated user row, with every artifact it creates cleaned up after."""

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
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


@live_only
class TestLiveSourceFetchers:
    """One test per source, each independently skippable if that source's
    server can't be reached -- a missing Docker daemon shouldn't look like a
    parsing bug.
    """

    def _run(self, fetcher, user_id):
        try:
            return asyncio.run(fetcher.fetch(user_id, _since()))
        except SourceUnavailable as exc:
            pytest.skip(f"{fetcher.source} MCP server unavailable: {exc}")

    def test_github_returns_schema_valid_events(self, live_user):
        data = self._run(GitHubFetcher(), live_user)
        _report("github", data)
        _assert_schema_valid(data.events, "github")

        for event in data.events:
            assert event.event_type in {"commit", "pull_request"}
            # Identity comes from the API response; without it the matcher
            # can never pair this event with local work.
            assert event.remote_project_id and "/" in event.remote_project_id

    def test_jira_returns_schema_valid_events(self, live_user):
        data = self._run(JiraFetcher(), live_user)
        _report("jira", data)
        _assert_schema_valid(data.events, "jira")

        for event in data.events:
            assert event.event_type == "issue_updated"
            assert event.summary and event.summary.split()[0].count("-") >= 1
            assert event.remote_project_id

    def test_slack_returns_schema_valid_events(self, live_user):
        data = self._run(SlackFetcher(), live_user)
        _report("slack", data)
        _assert_schema_valid(data.events, "slack")

        for event in data.events:
            assert event.event_type == "message"
            assert event.remote_project_id, "the channel id is the project identity"
            assert event.summary and event.summary.startswith("Message in ")

    def test_calendar_returns_schema_valid_events(self, live_user):
        data = self._run(CalendarFetcher(), live_user)
        _report("calendar", data)
        _assert_schema_valid(data.events, "calendar")

        for event in data.events:
            assert event.event_type == "meeting"
            # A meeting has no project identity in the calendar's own terms.
            assert event.remote_project_id is None
            assert event.raw_data.get("eventType") != "workingLocation"


@live_only
class TestLiveOrchestrator:
    def test_all_four_sources_run_and_persist(self, live_user):
        """End to end: fetch every source concurrently, write to the real
        table, and confirm the run is reported honestly per source.
        """

        results = asyncio.run(fetch_all_sources(live_user))

        assert set(results) == {"github", "jira", "slack", "calendar"}
        for source, result in sorted(results.items()):
            status = "ok" if result.ok else f"FAILED: {result.error}"
            print(f"\n[live:orchestrator] {source}: {status} fetched={result.fetched} written={result.written}")

        with SessionLocal() as db:
            rows = db.query(RemoteEvent).filter(RemoteEvent.user_id == live_user).all()
            states = db.query(RemoteFetchState).filter(RemoteFetchState.user_id == live_user).all()

        # Every source attempted must have left a state row, successful or not.
        assert {state.source.value for state in states} == {"github", "jira", "slack", "calendar"}
        for state in states:
            assert state.last_attempted_at is not None
            if state.last_error is None:
                assert state.last_fetched_through is not None
            else:
                # A failed source must not have advanced its mark.
                assert state.last_fetched_through is None

        written = sum(result.written for result in results.values())
        assert len(rows) == written
        print(f"\n[live:orchestrator] persisted {len(rows)} remote_events rows")

        assert any(result.ok for result in results.values()), (
            "no source succeeded -- check Docker is running and backend/.env credentials are set"
        )

    def test_a_second_run_does_not_duplicate_rows(self, live_user):
        """The high-water mark plus the idempotent upsert together mean a
        repeated run adds nothing new.
        """

        asyncio.run(fetch_all_sources(live_user))
        with SessionLocal() as db:
            first_count = db.query(RemoteEvent).filter(RemoteEvent.user_id == live_user).count()

        asyncio.run(fetch_all_sources(live_user))
        with SessionLocal() as db:
            second_count = db.query(RemoteEvent).filter(RemoteEvent.user_id == live_user).count()

        print(f"\n[live:orchestrator] rows after run 1={first_count}, after run 2={second_count}")
        assert second_count == first_count
