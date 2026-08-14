from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.tools.write_event import write_event
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.self_captures import crud
from app.self_captures.schemas import SelfCaptureCreate, SelfCaptureResponse
from app.timeline.models import ConfidenceLevel

router = APIRouter(prefix="/self_captures", tags=["self_captures"])

LINKED_GAP_NOT_FOUND_ERROR = "linked_gap_id does not reference an existing event"


@router.post("", response_model=SelfCaptureResponse, status_code=status.HTTP_201_CREATED)
def create_self_capture(
    payload: SelfCaptureCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a self-capture and also write an Event row so the covered time range doesn't look empty to
    anything else reading the `events` table.
    """
    try:
        self_capture = crud.create_self_capture(
            db,
            user_id=current_user.id,
            text=payload.text,
            timestamp=payload.timestamp,
            linked_gap_id=payload.linked_gap_id,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=LINKED_GAP_NOT_FOUND_ERROR)

    write_event(
        user_id=current_user.id,
        source="self_capture",
        type="self_capture",
        timestamp=self_capture.timestamp,
        metadata={
            "self_capture_id": self_capture.id,
            "text": self_capture.text,
            "linked_gap_id": self_capture.linked_gap_id,
        },
        confidence=ConfidenceLevel.proven,
    )

    return self_capture
