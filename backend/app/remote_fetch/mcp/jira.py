"""Fetches recently updated Jira issues assigned to the user.

Queries issues using JQL and converts them into normalized events, optionally
narrowed by mapped project keys.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from mcp import ClientSession

from app.integrations.config import get_mapped_remote_project_ids
from app.remote_fetch.base import FetchedEvent, SourceFetchData, SourceFetcher
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.mcp.connection import mcp_result_to_json
from app.remote_fetch.parsing import first_non_empty_string, parse_iso_datetime

logger = logging.getLogger(__name__)

SOURCE = "jira"
EVENT_TYPE_ISSUE_UPDATED = "issue_updated"

JIRA_PAGE_LIMIT = 50
JIRA_MAX_PAGES = 10

JIRA_FIELDS = "summary,description,status,issuetype,assignee,reporter,priority,labels,created,updated"

PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+$")


def _project_key_from_issue_key(issue_key: Optional[str]) -> Optional[str]:
    """Extract project key prefix from a Jira issue key (e.g. 'PROJ-123' -> 'PROJ')."""

    if not issue_key or "-" not in issue_key:
        return None
    prefix = issue_key.rsplit("-", 1)[0].strip()
    return prefix or None


def _nested_name(fields: dict[str, Any], key: str) -> Optional[str]:
    value = fields.get(key)
    if isinstance(value, dict):
        return first_non_empty_string(value.get("name"), value.get("displayName"))
    return first_non_empty_string(value)


def _issue_event(issue: dict[str, Any]) -> Optional[FetchedEvent]:
    """Build a FetchedEvent from a Jira issue dictionary payload."""

    issue_key = first_non_empty_string(issue.get("key"))
    if issue_key is None:
        return None

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else issue
    occurred_at = parse_iso_datetime(fields.get("updated")) or parse_iso_datetime(fields.get("created"))
    if occurred_at is None:
        return None

    status = _nested_name(fields, "status")
    issue_type = _nested_name(fields, "issuetype")
    title = first_non_empty_string(fields.get("summary"))

    summary_parts = [issue_key]
    if status:
        summary_parts.append(f"[{status}]")
    if title:
        summary_parts.append(title)

    return FetchedEvent(
        source=SOURCE,
        event_type=EVENT_TYPE_ISSUE_UPDATED,
        external_id=issue_key,
        occurred_at=occurred_at,
        summary=" ".join(summary_parts),
        description=_issue_description(fields),
        remote_project_id=_project_key_from_issue_key(issue_key),
        match_keys={
            "issue_key": issue_key,
            "status": status,
            "issue_type": issue_type,
            "assignee": _nested_name(fields, "assignee"),
        },
        raw_data=issue,
    )


def _issue_description(fields: dict[str, Any]) -> Optional[str]:
    """Read the issue description, tolerating Atlassian Document Format.

    Jira Cloud returns rich text as an ADF document rather than a string. The
    MCP server usually renders it to markdown for us, but not always -- when
    it doesn't, a dict would otherwise be stored where a string belongs.
    """

    description = fields.get("description")
    if isinstance(description, str):
        return first_non_empty_string(description)
    if isinstance(description, dict):
        return first_non_empty_string(description.get("text")) or None
    return None


class JiraFetcher(SourceFetcher):
    source = SOURCE

    async def fetch_with_session(
        self, session: ClientSession, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        jql = self._build_jql(user_id, since)
        events_by_key: dict[str, FetchedEvent] = {}

        for page in range(JIRA_MAX_PAGES):
            result = await session.call_tool(
                "jira_search",
                arguments={
                    "jql": jql,
                    "fields": JIRA_FIELDS,
                    "limit": JIRA_PAGE_LIMIT,
                    "start_at": page * JIRA_PAGE_LIMIT,
                },
            )
            issues = _issues_from_payload(mcp_result_to_json(result))
            if not issues:
                break

            for issue in issues:
                event = _issue_event(issue)
                if event is None:
                    continue
                previous = events_by_key.get(event.external_id)
                if previous is None or event.occurred_at > previous.occurred_at:
                    events_by_key[event.external_id] = event

            if len(issues) < JIRA_PAGE_LIMIT or len(events_by_key) >= MAX_EVENTS_PER_SOURCE:
                break

        events = sorted(events_by_key.values(), key=lambda event: event.occurred_at)
        return SourceFetchData(events=events[:MAX_EVENTS_PER_SOURCE])

    def _build_jql(self, user_id: int, since: Optional[datetime]) -> str:
        """Build the JQL for this user: always assignee-scoped, narrowed by
        mapped projects when there are any.

        Ordered by `updated ASC` so pagination is stable: with a descending or
        unspecified order, an issue updated mid-pagination can shift between
        pages and be missed entirely.
        """

        clauses: list[str] = []

        project_keys = (
            self.remote_fetch_config.projects_for(SOURCE)
            if self.remote_fetch_config is not None
            else get_mapped_remote_project_ids(user_id, SOURCE)
        )
        valid_project_keys = []
        for key in project_keys:
            if PROJECT_KEY_PATTERN.match(key):
                valid_project_keys.append(key)
            else:
                logger.warning(
                    "jira: skipping malformed project key %r for user %s (want e.g. 'LOG')", key, user_id
                )

        if valid_project_keys:
            quoted = ", ".join(f'"{key}"' for key in valid_project_keys)
            clauses.append(f"project in ({quoted})")
        else:
            logger.info("jira: no project_mappings for user %s; scoping by assignee = currentUser() only", user_id)

        clauses.append("assignee = currentUser()")

        if since is not None:
            since_utc = since.astimezone(timezone.utc)
            clauses.append(f'updated >= "{since_utc.isoformat(timespec="seconds")}"')

        return " AND ".join(clauses) + " ORDER BY updated ASC, key ASC"


def _issues_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("issues", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []
