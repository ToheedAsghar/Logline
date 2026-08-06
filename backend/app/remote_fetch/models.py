from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.integrations.models import IntegrationSource


class RemoteFetchState(Base):
    """The high-water mark for one (user, source) pair: how far through time we have already fetched remote events.

    The three timestamps are deliberately distinct:

      `last_fetched_through` -- high-water mark. Advanced ONLY after a genuinely successful fetch. NULL means
      "never successfully fetched", triggering a bounded first-fetch lookback rather than an unbounded crawl.

      `last_attempted_at` -- advanced on every attempt (success or failure). Without it, a source failing continuously
      for a week is indistinguishable from one nobody asked for.

      `last_error` -- the failure reason, cleared back to NULL on success so the row always reflects latest outcome
      rather than an accumulating log.
    """

    __tablename__ = "remote_fetch_state"
    __table_args__ = (
        UniqueConstraint("user_id", "source", name="uq_remote_fetch_state_user_source"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(Enum(IntegrationSource, name="integration_source"), nullable=False)
    last_fetched_through = Column(DateTime(timezone=True), nullable=True)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String, nullable=True)

    user = relationship("User", back_populates="remote_fetch_states")
