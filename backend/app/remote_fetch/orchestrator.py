"""Orchestrates concurrent fetching across remote sources and persists results.

Executes fetchers independently, upserts events idempotently, and advances source
high-water marks upon successful fetches.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.integrations.config import load_remote_fetch_config
from app.matching.models import RemoteEvent
from app.remote_fetch.base import FetchedEvent, SourceFetcher, SourceUnavailable
from app.remote_fetch.constants import DEFAULT_SOURCE_TIMEOUT_SECONDS, FIRST_FETCH_LOOKBACK_DAYS, SOURCE_TIMEOUT_SECONDS
from app.remote_fetch.mcp.calendar import CalendarFetcher
from app.remote_fetch.mcp.github import GitHubFetcher
from app.remote_fetch.mcp.jira import JiraFetcher
from app.remote_fetch.models import RemoteFetchState

logger = logging.getLogger(__name__)

ALL_FETCHERS: list[type[SourceFetcher]] = [
    GitHubFetcher,
    JiraFetcher,
    CalendarFetcher,
]

FETCHERS: dict[str, type[SourceFetcher]] = {cls.source: cls for cls in ALL_FETCHERS}


@dataclass
class SourceResult:
    """Represents the execution outcome and event counts for a single source fetch."""

    source: str
    ok: bool
    fetched: int = 0
    written: int = 0
    error: Optional[str] = None
    fetched_through: Optional[datetime] = None


def resolve_since(state: Optional[RemoteFetchState], now: datetime) -> Optional[datetime]:
    """Calculate the start timestamp for a source fetch window."""

    if state is not None and state.last_fetched_through is not None:
        return state.last_fetched_through
    return now - timedelta(days=FIRST_FETCH_LOOKBACK_DAYS)


def _timeout_for(source: str) -> float:
    return SOURCE_TIMEOUT_SECONDS.get(source, DEFAULT_SOURCE_TIMEOUT_SECONDS)


def _load_state(db: Session, user_id: int, source: str) -> Optional[RemoteFetchState]:
    return (
        db.query(RemoteFetchState)
        .filter(RemoteFetchState.user_id == user_id, RemoteFetchState.source == source)
        .first()
    )


def upsert_remote_events(db: Session, user_id: int, events: list[FetchedEvent]) -> int:
    """Upsert fetched events into remote_events database table.

    Returns the number of rows inserted or updated.
    """

    if not events:
        return 0

    rows = [
        {
            "user_id": user_id,
            "source": event.source,
            "event_type": event.event_type,
            "external_id": event.external_id,
            "occurred_at": event.occurred_at,
            "summary": event.summary,
            "description": event.description,
            "match_keys": event.match_keys,
            "raw_data": event.raw_data,
            "remote_project_id": event.remote_project_id,
            "fetched_at": datetime.now(timezone.utc),
        }
        for event in events
    ]

    statement = pg_insert(RemoteEvent).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_remote_events_user_source_external_id",
        set_={
            "event_type": statement.excluded.event_type,
            "occurred_at": statement.excluded.occurred_at,
            "summary": statement.excluded.summary,
            "description": statement.excluded.description,
            "match_keys": statement.excluded.match_keys,
            "raw_data": statement.excluded.raw_data,
            "remote_project_id": statement.excluded.remote_project_id,
            "fetched_at": statement.excluded.fetched_at,
        },
    )
    result = db.execute(statement)
    return result.rowcount or 0


def record_fetch_state(
    db: Session,
    user_id: int,
    source: str,
    attempted_at: datetime,
    fetched_through: Optional[datetime],
    error: Optional[str],
) -> None:
    """Write back this source's fetch bookkeeping.

    `last_attempted_at` always moves, so a source failing every run is
    visible rather than looking idle. `last_fetched_through` moves only when
    `fetched_through` is not None, which the caller passes only on success.
    """

    statement = pg_insert(RemoteFetchState).values(
        user_id=user_id,
        source=source,
        last_attempted_at=attempted_at,
        last_fetched_through=fetched_through,
        last_error=error,
    )
    existing = RemoteFetchState.__table__.c
    excluded = statement.excluded
    latest_attempt = or_(
        existing.last_attempted_at.is_(None),
        excluded.last_attempted_at >= existing.last_attempted_at,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_remote_fetch_state_user_source",
        set_={
            "last_attempted_at": case(
                (latest_attempt, excluded.last_attempted_at),
                else_=existing.last_attempted_at,
            ),
            "last_error": case(
                (latest_attempt, excluded.last_error),
                else_=existing.last_error,
            ),
            "last_fetched_through": case(
                (excluded.last_fetched_through.is_(None), existing.last_fetched_through),
                (existing.last_fetched_through.is_(None), excluded.last_fetched_through),
                else_=func.greatest(existing.last_fetched_through, excluded.last_fetched_through),
            ),
        },
    )
    db.execute(statement)


async def _run_one_source(
    fetcher: SourceFetcher, user_id: int, since: Optional[datetime], now: datetime
) -> tuple[SourceResult, list[FetchedEvent]]:
    """Fetch one source, converting every failure mode into a SourceResult.

    Nothing raises out of here: `gather` is called with
    `return_exceptions=True` as a backstop, but a source that fails should
    still produce a *described* failure (which source, what went wrong)
    rather than a bare exception object the caller has to interpret.

    The fetched events ride alongside the result rather than on it --
    `SourceResult` is the caller-facing summary and shouldn't carry hundreds
    of raw payloads.
    """

    source = fetcher.source
    try:
        data = await asyncio.wait_for(fetcher.fetch(user_id, since), timeout=_timeout_for(source))
    except asyncio.TimeoutError:
        message = f"timed out after {_timeout_for(source)}s"
        logger.warning("remote_fetch_source_timeout", extra={"source": source, "timeout_message": message})
        return SourceResult(source=source, ok=False, error=message), []
    except SourceUnavailable as exc:
        logger.warning("remote_fetch_source_unavailable", extra={"source": source, "error": str(exc)})
        return SourceResult(source=source, ok=False, error=str(exc)), []
    except Exception as exc:  # noqa: BLE001 - one source's bug must not abort the other three
        logger.exception("remote_fetch_source_raised", extra={"source": source})
        return SourceResult(source=source, ok=False, error=f"{type(exc).__name__}: {exc}"), []

    fetched_through = now
    if data.fetched_through_override is not None:
        fetched_through = min(now, data.fetched_through_override)

    result = SourceResult(
        source=source,
        ok=True,
        fetched=len(data.events),
        fetched_through=fetched_through,
    )
    return result, data.events


async def fetch_all_sources(user_id: int, sources: Optional[list[str]] = None) -> dict[str, SourceResult]:
    """Fetch every source for one user, concurrently, and persist the results.

    Returns one `SourceResult` per source, keyed by source name. Sources are
    never dropped from the result: a source that failed is present with
    `ok=False` and a reason, because "GitHub returned nothing" and "GitHub
    was never reached" are different facts and the caller needs to tell them
    apart.
    """

    selected = sources or list(FETCHERS)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        since_by_source = {
            source: resolve_since(_load_state(db, user_id, source), now) for source in selected
        }
        remote_fetch_config = load_remote_fetch_config(db, user_id)

    outcomes = await asyncio.gather(
        *(
            _run_one_source(
                _configured_fetcher(FETCHERS[source], remote_fetch_config),
                user_id,
                since_by_source[source],
                now,
            )
            for source in selected
        ),
        return_exceptions=True,
    )

    results: dict[str, SourceResult] = {}
    events_by_source: dict[str, list[FetchedEvent]] = {}

    for source, outcome in zip(selected, outcomes):
        if isinstance(outcome, BaseException):
            # Defensive: _run_one_source already converts its own failures,
            # so reaching here means something escaped it entirely.
            logger.error(
                "remote_fetch_source_escaped_handler",
                extra={"source": source, "outcome": repr(outcome)},
                exc_info=outcome,
            )
            results[source] = SourceResult(
                source=source, ok=False, error=f"{type(outcome).__name__}: {outcome}"
            )
            events_by_source[source] = []
        else:
            result, events = outcome
            results[source] = result
            events_by_source[source] = events

    for source in selected:
        _persist_source(user_id, source, results[source], events_by_source[source], now)

    return results


def _configured_fetcher(
    fetcher_type: type[SourceFetcher], remote_fetch_config
) -> SourceFetcher:
    """Attach one run's immutable database configuration to a fetcher."""

    fetcher = fetcher_type()
    fetcher.remote_fetch_config = remote_fetch_config
    return fetcher


def _persist_source(
    user_id: int, source: str, result: SourceResult, events: list[FetchedEvent], now: datetime
) -> None:
    """Write one source's events and state in its own transaction.

    Per-source rather than one transaction covering all working sources, so a database
    error while writing one source's events can't roll back another's
    already-successful work -- the same isolation the fetch side guarantees.
    """

    try:
        with SessionLocal() as db:
            if result.ok and events:
                result.written = upsert_remote_events(db, user_id, events)
            record_fetch_state(
                db,
                user_id=user_id,
                source=source,
                attempted_at=now,
                fetched_through=result.fetched_through if result.ok else None,
                error=None if result.ok else result.error,
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - a write failure for one source is that source's failure
        logger.exception("remote_fetch_persist_failed", extra={"source": source})
        result.ok = False
        result.written = 0
        result.fetched_through = None
        result.error = f"persist failed: {type(exc).__name__}: {exc}"

        # The transaction above rolled back along with the exception, so the
        # failure was never written -- the row would otherwise look idle
        # rather than broken. Recorded in a fresh session, since the one
        # above is now in whatever state the exception left it in.
        try:
            with SessionLocal() as recovery_db:
                record_fetch_state(
                    recovery_db,
                    user_id=user_id,
                    source=source,
                    attempted_at=now,
                    fetched_through=None,
                    error=result.error,
                )
                recovery_db.commit()
        except Exception:  # noqa: BLE001 - the recovery write itself must not take other sources down
            logger.exception("remote_fetch_persist_failure_recording_failed", extra={"source": source})
