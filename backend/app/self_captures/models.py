from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class SelfCapture(Base):
    __tablename__ = "self_captures"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    linked_gap_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="self_captures")
    linked_gap = relationship("Event")
