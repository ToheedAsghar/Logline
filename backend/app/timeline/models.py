import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ConfidenceLevel(str, enum.Enum):
    proven = "proven"
    estimated = "estimated"
    gap = "gap"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # NULLs are distinct in Postgres unique constraints, so events with no
        # external_id (nothing stable to key off of) are correctly left
        # unconstrained -- only genuine (user, source, type, external_id)
        # matches are rejected.
        UniqueConstraint(
            "user_id", "source", "type", "external_id", name="uq_events_user_source_type_external_id"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String, nullable=False)
    type = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    event_metadata = Column("metadata", JSONB, nullable=True)
    confidence = Column(Enum(ConfidenceLevel, name="confidence_level"), nullable=False)
    external_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="events")


class WorkBlock(Base):
    __tablename__ = "work_blocks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    confidence = Column(Enum(ConfidenceLevel, name="confidence_level"), nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="work_blocks")
