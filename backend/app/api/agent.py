from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.agent.runner import run_agent
from app.api.deps import get_current_user
from app.db.session import SessionLocal
from app.models.event import Event
from app.models.user import User
from app.schemas.agent import AgentRunRequest, AgentRunResponse

router = APIRouter(prefix="/agent", tags=["agent"])


def _describe_task(payload: AgentRunRequest) -> str:
    if payload.date_range is None:
        return payload.task
    return (
        f"{payload.task} (focus on the date range "
        f"{payload.date_range.start.isoformat()} to {payload.date_range.end.isoformat()})"
    )


@router.post("/run", response_model=AgentRunResponse)
async def run_agent_endpoint(
    payload: AgentRunRequest,
    current_user: User = Depends(get_current_user),
):
    # No Depends(get_db) here on purpose: a run can take several minutes
    # (MAX_TOOL_ROUNDS=15 rounds of LLM + MCP calls, see app/agent/runner.py),
    # and holding a pooled connection checked out and idle for that whole
    # span would starve the pool for other requests. A session is opened only
    # for the short read below, after the run itself is done. Likewise there
    # is no timeout wrapper around run_agent() -- an aggressive one would kill
    # slow-but-healthy runs mid-flight.
    run_started_at = datetime.now(timezone.utc)
    result = await run_agent(user_id=current_user.id, task=_describe_task(payload))

    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(Event.user_id == current_user.id, Event.created_at >= run_started_at)
            .order_by(Event.created_at.asc())
            .all()
        )
        return AgentRunResponse(
            response=result.response_text, events=events, created_entry_id=result.created_entry_id
        )
