from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base
from app.models.integration import IntegrationSource


class RemoteEvent(Base):
    """One event fetched from an external source (GitHub, Slack, Jira, Calendar),
    stored as-is before any matching or reconciliation happens.

    This is raw staging data, not the final confidence-graded record that ends
    up in `events` -- it exists so the matching step (and later, AI
    reconciliation) has a stable, already-fetched dataset to work against
    instead of re-hitting the source API every time.

    `source` reuses the existing `integration_source` Postgres enum type
    already declared on `Integration.source` (app/models/integration.py) --
    an invalid source is rejected at the database level, not just by
    application code, and there's exactly one enum type for "which
    integration source is this" across the schema.

    `remote_project_id` holds whatever identifies "which project" this event
    belongs to in its source's own terms -- a GitHub repo's `owner/repo`, a
    Jira project key, a Slack channel ID. It's nullable because not every
    fetched event necessarily resolves to a project (e.g. a calendar event
    with no project context).
    """

    __tablename__ = "remote_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "external_id", name="uq_remote_events_user_source_external_id"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(Enum(IntegrationSource, name="integration_source"), nullable=False)
    event_type = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    summary = Column(String, nullable=True)
    description = Column(String, nullable=True)
    match_keys = Column(JSONB, nullable=True)
    raw_data = Column(JSONB, nullable=False)
    remote_project_id = Column(String, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="remote_events")


class ProjectMapping(Base):
    """A user-configured mapping from a local project (the tracker's folder/repo
    path string) to a remote project identity, for sources where that identity
    can't be derived from anything on disk.

    GitHub identity can be read straight from `.git/config` -- no mapping
    needed. Jira and Slack have no equivalent local signal (a folder doesn't
    know its own Jira project key or Slack channel ID), so the user configures
    that link once here, and the resolution step looks it up by
    (user, local_project, source) instead of guessing.
    """

    __tablename__ = "project_mappings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "local_project", "source", name="uq_project_mappings_user_local_project_source"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    local_project = Column(String, nullable=False)
    source = Column(Enum(IntegrationSource, name="integration_source"), nullable=False)
    remote_project_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="project_mappings")
