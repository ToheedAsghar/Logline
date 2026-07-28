from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.agent.runner import run_agent
from app.agent.schemas import AgentRunRequest, AgentRunResponse
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import SessionLocal
from app.timeline.models import Event

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
