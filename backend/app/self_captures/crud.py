from datetime import datetime

from sqlalchemy.orm import Session

from app.self_captures.models import SelfCapture


def create_self_capture(
    db: Session, *, user_id: int, text: str, timestamp: datetime, linked_gap_id: int | None
) -> SelfCapture:
    self_capture = SelfCapture(
        user_id=user_id,
        text=text,
        timestamp=timestamp,
        linked_gap_id=linked_gap_id,
    )
    db.add(self_capture)
    db.commit()
    db.refresh(self_capture)
    return self_capture
