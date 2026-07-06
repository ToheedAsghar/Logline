from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.event import EventResponse

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("", response_model=list[EventResponse])
def get_timeline(
    start: datetime = Query(...),
    end: datetime = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Event)
        .filter(Event.user_id == current_user.id, Event.timestamp >= start, Event.timestamp <= end)
        .order_by(Event.timestamp.asc())
        .all()
    )
