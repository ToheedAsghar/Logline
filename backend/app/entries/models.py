import enum

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class EntryFormat(str, enum.Enum):
    project_log = "project_log"
    standup = "standup"


class EntryStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    discarded = "discarded"


class EntryVersionSource(str, enum.Enum):
    ai_draft = "ai_draft"
    human_approved = "human_approved"
    human_revision = "human_revision"


class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    format = Column(Enum(EntryFormat, name="entry_format"), nullable=False)
    content = Column(JSONB, nullable=False)
    status = Column(Enum(EntryStatus, name="entry_status"), nullable=False, default=EntryStatus.draft)
    work_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    reconciliation_draft_id = Column(
        Integer, ForeignKey("reconciliation_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    draft_position = Column(Integer, nullable=True)

    user = relationship("User", back_populates="entries")
    reconciliation_draft = relationship("ReconciliationDraft", back_populates="entries")
    versions = relationship(
        "EntryVersion", back_populates="entry", cascade="all, delete-orphan", order_by="EntryVersion.created_at"
    )


class EntryVersion(Base):
    """One immutable snapshot of an entry's content -- the AI draft as generated, the content as approved, or a
    human edit made after approval. Never updated in place; a new row is appended at each of those three moments
    instead. `entries.content` remains the current-state row; this table is the append-only history alongside it.
    """

    __tablename__ = "entry_versions"

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(Enum(EntryVersionSource, name="entry_version_source"), nullable=False)
    content = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    entry = relationship("Entry", back_populates="versions")
