"""Defines base classes and data structures for remote source fetchers."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from app.db.session import SessionLocal
from app.integrations import crud
from app.integrations.config import RemoteFetchConfig
from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource, IntegrationStatus
from app.integrations.token_refresh import ensure_token_fresh
from app.remote_fetch.constants import HTTP_CLIENT_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class SourceUnavailable(RuntimeError):
    """Exception raised when a remote source isn't connected, has no usable token, or can't be reached."""


@dataclass(frozen=True)
class FetchedEvent:
    """Normalized remote event data structure for storage in remote_events."""

    source: str
    event_type: str
    external_id: str
    occurred_at: datetime
    summary: Optional[str]
    description: Optional[str]
    raw_data: dict[str, Any]
    remote_project_id: Optional[str] = None
    match_keys: Optional[dict[str, Any]] = None


@dataclass
class SourceFetchData:
    """Container for events returned by a fetcher and optional high-water mark override."""

    events: list[FetchedEvent] = field(default_factory=list)
    fetched_through_override: Optional[datetime] = None


@dataclass(frozen=True)
class SourceCredentials:
    """Per-fetch OAuth credentials resolved for one user's connected integration.

    `authed_user_id` is the provider-reported identity of the connected account, populated only for
    sources whose OAuth response actually carries one (currently Slack only -- see
    `OAuthToken.authed_user_id`'s docstring). It rides alongside the token rather than being fetched
    separately so a fetcher never needs its own DB read to resolve identity.
    """

    access_token: str
    authed_user_id: Optional[str] = None


class SourceFetcher(ABC):
    """Abstract base class for remote source fetchers."""

    source: str

    def __init__(self) -> None:
        self.remote_fetch_config: Optional[RemoteFetchConfig] = None

    async def fetch(self, user_id: int, since: Optional[datetime]) -> SourceFetchData:
        """Resolve this user's OAuth credentials for `self.source` and fetch events since `since`.

        Raises SourceUnavailable if the integration isn't connected, or its token can't be resolved
        or refreshed -- both collapse to the same "can't fetch right now" outcome for the caller.
        """

        credentials = await self._resolve_credentials(user_id)
        async with httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT_SECONDS) as client:
            return await self.fetch_with_client(client, credentials, user_id, since)

    async def _resolve_credentials(self, user_id: int) -> SourceCredentials:
        source_enum = IntegrationSource(self.source)
        with SessionLocal() as db:
            integration = crud.get_integration_by_source(db, user_id, source_enum)
            if integration is None or integration.status != IntegrationStatus.connected:
                raise SourceUnavailable(f"{self.source} is not connected for user_id={user_id}")

            try:
                token = await ensure_token_fresh(db, source_enum, integration.id)
            except TokenRefreshError as exc:
                raise SourceUnavailable(str(exc)) from exc

            return SourceCredentials(access_token=token.access_token, authed_user_id=token.authed_user_id)

    @abstractmethod
    async def fetch_with_client(
        self, client: httpx.AsyncClient, credentials: SourceCredentials, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        """Fetch events newer than `since` using an authenticated HTTP client."""
