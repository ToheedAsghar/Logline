"""Defines base classes and data structures for remote source fetchers."""

import logging
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from mcp import ClientSession

from app.mcp.connection import connect_mcp_source

logger = logging.getLogger(__name__)


class SourceUnavailable(RuntimeError):
    """Exception raised when an MCP server source cannot be reached or initialized."""


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


class SourceFetcher(ABC):
    """Abstract base class for remote source fetchers."""

    source: str

    async def fetch(self, user_id: int, since: Optional[datetime]) -> SourceFetchData:
        """Connect to source and fetch all events occurring after since timestamp."""

        async with AsyncExitStack() as stack:
            session = await connect_mcp_source(self.source, stack)
            if session is None:
                raise SourceUnavailable(f"could not connect to the {self.source} MCP server")
            return await self.fetch_with_session(session, user_id, since)

    @abstractmethod
    async def fetch_with_session(
        self, session: ClientSession, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        """Fetch events newer than `since` using an already-open session."""
