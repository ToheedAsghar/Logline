"""Manual trigger for a full remote-fetch run, scoped to the authenticated user.

No scheduler here by design -- this is the human-facing button path only. The
fetch runs synchronously inside the request: FastAPI's BackgroundTasks are
cancelled when the HTTP client disconnects after the response, so an immediate
"triggered" ack would silently drop the run for real clients.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.remote_fetch.constants import TRIGGER_COOLDOWN_SECONDS, TRIGGER_RATE_LIMIT_ERROR_MSG
from app.remote_fetch.models import RemoteFetchState
from app.remote_fetch.orchestrator import fetch_all_sources, record_fetch_state
from app.remote_fetch.registry import FETCHERS

router = APIRouter(prefix="/remote-fetch", tags=["remote-fetch"])


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
