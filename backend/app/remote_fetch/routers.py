"""Manual trigger for a full remote-fetch run, scoped to the authenticated user.

No scheduler here by design -- this is the human-facing button path only. The
fetch runs synchronously inside the request: FastAPI's BackgroundTasks are
cancelled when the HTTP client disconnects after the response, so an immediate
"triggered" ack would silently drop the run for real clients.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.integrations.models import IntegrationSource
from app.matching.models import RemoteEvent
from app.remote_fetch.constants import TRIGGER_COOLDOWN_SECONDS, TRIGGER_RATE_LIMIT_ERROR_MSG
from app.remote_fetch.models import RemoteFetchState
from app.remote_fetch.orchestrator import fetch_all_sources, record_fetch_state
from app.remote_fetch.registry import FETCHERS
from app.remote_fetch.schemas import RemoteEventListResponse, decode_cursor, encode_cursor

router = APIRouter(prefix="/remote-fetch", tags=["remote-fetch"])
events_router = APIRouter(prefix="/remote-events", tags=["remote-events"])


class RemoteFetchTriggerResult(BaseModel):
    """Acknowledgment that a remote-fetch run was accepted for the current user."""

    status: str


@router.post("/trigger", response_model=RemoteFetchTriggerResult, status_code=status.HTTP_200_OK)
async def trigger_remote_fetch(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> RemoteFetchTriggerResult:
    """Run a full remote-fetch for the current user and persist its results.

    Only `current_user`'s own sources are fetched -- the orchestrator is called with the authenticated user's id, never
    anyone else's. The endpoint stamps each source's `last_attempted_at` before fetching so the cooldown is effective
    from the moment a trigger is accepted, closing the window in which a double-click or retry storm could stack
    concurrent runs against each source's upstream rate limits.
    """
    last_attempt = (
        db.query(func.max(RemoteFetchState.last_attempted_at))
        .filter(RemoteFetchState.user_id == current_user.id)
        .scalar()
    )
    if last_attempt is not None and datetime.now(timezone.utc) - last_attempt < timedelta(
        seconds=TRIGGER_COOLDOWN_SECONDS
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TRIGGER_RATE_LIMIT_ERROR_MSG,
        )
    now = datetime.now(timezone.utc)
    for source in FETCHERS:
        record_fetch_state(
            db, user_id=current_user.id, source=source, attempted_at=now, fetched_through=None, error=None
        )
    db.commit()
    await fetch_all_sources(current_user.id)
    return RemoteFetchTriggerResult(status="triggered")


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@events_router.get("", response_model=RemoteEventListResponse)
def list_remote_events(
    source: IntegrationSource | None = Query(default=None),
    date_range_start: datetime | None = Query(default=None),
    date_range_end: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one page of the user's remote events, newest first.

    Pagination is keyset over (occurred_at DESC, id DESC): `cursor` is opaque and encodes the last seen row's
    key pair, so pages keep their relative order even as new events land between fetches. `date_range` is a
    half-open [start, end) window on `occurred_at`. A user without events in scope gets an empty page, not a 404.
    """
    query = db.query(RemoteEvent).filter(RemoteEvent.user_id == current_user.id)
    if source is not None:
        query = query.filter(RemoteEvent.source == source)
    if date_range_start is not None:
        query = query.filter(RemoteEvent.occurred_at >= date_range_start)
    if date_range_end is not None:
        query = query.filter(RemoteEvent.occurred_at < date_range_end)
    if cursor is not None:
        try:
            cursor_occurred_at, cursor_id = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        query = query.filter(
            tuple_(RemoteEvent.occurred_at, RemoteEvent.id)
            < (cursor_occurred_at, cursor_id)
        )

    rows = (
        query.order_by(RemoteEvent.occurred_at.desc(), RemoteEvent.id.desc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1].occurred_at, page[-1].id) if has_more else None
    )
    return RemoteEventListResponse(events=page, next_cursor=next_cursor, has_more=has_more)
