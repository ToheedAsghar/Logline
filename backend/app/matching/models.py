from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base
from app.integrations.models import IntegrationSource


class RemoteEvent(Base):
    """One event fetched from an external source (GitHub, Slack, Jira, Calendar), stored as-is before matching.

    This is raw staging data, not the final confidence-graded record in `events` -- it provides a stable dataset for
    matching and AI reconciliation without re-querying external APIs.

    `source` reuses the `integration_source` Postgres enum declared on `Integration.source`
    (app/integrations/models.py). Invalid sources are rejected at the database level.

    `remote_project_id` holds the project identity in the source's native terms (e.g. `owner/repo`, Jira project key,
    Slack channel ID). Nullable for events without project context.
    """

    __tablename__ = "remote_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "external_id", name="uq_remote_events_user_source_external_id"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(Enum(IntegrationSource, name="integration_source", create_type=False), nullable=False)
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
    """Mapping from a local project path string to a remote project identity when un-derivable from disk.

    GitHub identity is read from `.git/config`. Jira and Slack lack local folder signals, so this table records
    manual (user, local_project, source) mappings for resolution.
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
    source = Column(
        Enum(IntegrationSource, name="integration_source", create_type=False), nullable=False
    )
    remote_project_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="project_mappings")
