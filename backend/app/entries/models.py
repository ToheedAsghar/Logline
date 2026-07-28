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

    user = relationship("User", back_populates="entries")
