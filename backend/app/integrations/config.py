"""Provides functions to query user integration settings and project mappings."""

from typing import Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.integrations.models import Integration, IntegrationSource
from app.matching.models import ProjectMapping


def get_user_github_repos(user_id: int, db: Optional[Session] = None) -> Optional[list[str]]:
    """Read the user's configured GitHub repositories from integration metadata."""

    if db is not None:
        return _query_user_github_repos(db, user_id)
    with SessionLocal() as session:
        return _query_user_github_repos(session, user_id)


def _query_user_github_repos(db: Session, user_id: int) -> Optional[list[str]]:
    integration = (
        db.query(Integration)
        .filter(Integration.user_id == user_id, Integration.source == IntegrationSource.github)
        .first()
    )
    if integration is None or not integration.integration_metadata:
        return None
    repos = integration.integration_metadata.get("repos")
    return repos or None


def get_mapped_remote_project_ids(user_id: int, source: str, db: Optional[Session] = None) -> list[str]:
    """Return distinct remote project IDs mapped by the user for a given source."""

    if db is not None:
        return _query_mapped_remote_project_ids(db, user_id, source)
    with SessionLocal() as session:
        return _query_mapped_remote_project_ids(session, user_id, source)


def _query_mapped_remote_project_ids(db: Session, user_id: int, source: str) -> list[str]:
    rows = (
        db.query(ProjectMapping.remote_project_id)
        .filter(ProjectMapping.user_id == user_id, ProjectMapping.source == source)
        .distinct()
        .all()
    )
    return [row[0] for row in rows if row[0]]
