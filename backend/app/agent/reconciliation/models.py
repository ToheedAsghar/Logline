import enum

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ReconciliationDraftState(str, enum.Enum):
    active = "active"
    superseded = "superseded"
    approved = "approved"
    discarded = "discarded"


class ReconciliationDraft(Base):
    """Persist one generated reconciliation scope and its non-entry draft envelope."""

    __tablename__ = "reconciliation_drafts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date_range_start = Column(Date, nullable=False)
    date_range_end = Column(Date, nullable=False)
    state = Column(
        Enum(ReconciliationDraftState, name="reconciliation_draft_state"),
        nullable=False,
        default=ReconciliationDraftState.active,
    )
    draft = Column(JSONB, nullable=False)
    verification = Column(JSONB, nullable=False)
    supersedes_id = Column(Integer, ForeignKey("reconciliation_drafts.id"), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)

    entries = relationship("Entry", back_populates="reconciliation_draft", order_by="Entry.draft_position")
