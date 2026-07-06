from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.self_capture import SelfCapture
from app.models.user import User
from app.schemas.self_capture import SelfCaptureCreate, SelfCaptureResponse

router = APIRouter(prefix="/self_captures", tags=["self_captures"])


@router.post("", response_model=SelfCaptureResponse, status_code=status.HTTP_201_CREATED)
def create_self_capture(
    payload: SelfCaptureCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    self_capture = SelfCapture(
        user_id=current_user.id,
        text=payload.text,
        timestamp=payload.timestamp,
        linked_gap_id=payload.linked_gap_id,
    )
    db.add(self_capture)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="linked_gap_id does not reference an existing event")
    db.refresh(self_capture)
    return self_capture
