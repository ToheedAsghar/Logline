"""Fetches recently updated Jira issues assigned to the user, via Atlassian's REST API v3.

Queries issues using JQL and converts them into normalized events, optionally narrowed by mapped
project keys.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.integrations.config import get_cached_jira_cloud_id, get_mapped_remote_project_ids, set_cached_jira_cloud_id
from app.remote_fetch.base import FetchedEvent, SourceCredentials, SourceFetchData, SourceFetcher, SourceUnavailable
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.parsing import first_non_empty_string, parse_iso_datetime

logger = logging.getLogger(__name__)

SOURCE = "jira"
EVENT_TYPE_ISSUE_UPDATED = "issue_updated"

JIRA_API_BASE_URL = "https://api.atlassian.com"
JIRA_ACCESSIBLE_RESOURCES_PATH = "/oauth/token/accessible-resources"

JIRA_PAGE_LIMIT = 50
JIRA_MAX_PAGES = 10

JIRA_FIELDS = ("summary", "description", "status", "issuetype", "assignee", "reporter", "priority", "labels",
               "created", "updated")

PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+$")

ADF_BLOCK_NODE_TYPES = frozenset({"doc", "paragraph", "heading", "listItem", "codeBlock", "blockquote"})


def _auth_headers(credentials: SourceCredentials) -> dict[str, str]:
    return {"Authorization": f"Bearer {credentials.access_token}", "Accept": "application/json"}


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


def _adf_node_to_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        text_value = node.get("text")
        return text_value if isinstance(text_value, str) else ""
    if node_type == "hardBreak":
        return "\n"
    if node_type in ("mention", "emoji"):
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        return first_non_empty_string(attrs.get("text"), attrs.get("shortName")) or ""

    content = node.get("content")
    if not isinstance(content, list):
        return ""

    text = "".join(_adf_node_to_text(child) for child in content)
    if node_type in ADF_BLOCK_NODE_TYPES:
        text = text.rstrip("\n") + "\n"
    return text


def _adf_to_plain_text(document: Any) -> Optional[str]:
    """Render an Atlassian Document Format node tree to plain text.

    A basic, non-exhaustive walker: recurses through each node's `content` array, concatenating
    `text` leaf nodes and inserting a newline after each block-level node (paragraph, heading,
    list item, etc). Inline marks (bold, links, code spans) and non-text embeds (tables, media,
    panels, expands) are flattened to whatever visible text they carry, or dropped entirely if
    they carry none -- this preserves a description's readable content, not its structure.
    """

    if not isinstance(document, dict):
        return None
    text = _adf_node_to_text(document).strip()
    return text or None


def _issue_description(fields: dict[str, Any]) -> Optional[str]:
    """Read the issue description, rendering Atlassian Document Format to plain text.

    Jira Cloud's REST API v3 always returns rich text as ADF, unlike the old MCP server, which
    rendered it to markdown for us "usually, but not always" -- there is no longer a plain-string
    case from the real API. A string is still accepted defensively for the offline test fixtures
    and any other flattened value.
    """

    description = fields.get("description")
    if isinstance(description, str):
        return first_non_empty_string(description)
    if isinstance(description, dict):
        return _adf_to_plain_text(description)
    return None


class JiraFetcher(SourceFetcher):
    source = SOURCE

    async def fetch_with_client(
        self, client: httpx.AsyncClient, credentials: SourceCredentials, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        headers = _auth_headers(credentials)
        cloud_id = await self._resolve_cloud_id(client, headers, user_id)
        jql = self._build_jql(user_id, since)
        search_url = f"{JIRA_API_BASE_URL}/ex/jira/{cloud_id}/rest/api/3/search"

        events_by_key: dict[str, FetchedEvent] = {}

        for page in range(JIRA_MAX_PAGES):
            response = await client.post(
                search_url,
                headers=headers,
                json={
                    "jql": jql,
                    "fields": list(JIRA_FIELDS),
                    "maxResults": JIRA_PAGE_LIMIT,
                    "startAt": page * JIRA_PAGE_LIMIT,
                },
            )
            response.raise_for_status()
            issues = _issues_from_payload(response.json())
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

    async def _resolve_cloud_id(self, client: httpx.AsyncClient, headers: dict[str, str], user_id: int) -> str:
        """Return this user's Jira cloud ID, using the cached value from a prior fetch when available.

        The cloud ID is stable per connection -- discovering it on every fetch would be one wasted
        round trip per run, forever, for a value that never changes after the user connects Jira.
        """

        cached = get_cached_jira_cloud_id(user_id)
        if cached:
            return cached

        response = await client.get(f"{JIRA_API_BASE_URL}{JIRA_ACCESSIBLE_RESOURCES_PATH}", headers=headers)
        response.raise_for_status()
        resources = response.json()
        if not isinstance(resources, list) or not resources:
            raise SourceUnavailable(f"jira: no accessible Atlassian sites for user_id={user_id}")
        if len(resources) > 1:
            logger.warning(
                "jira_multiple_accessible_sites_using_first",
                extra={"user_id": user_id, "site_count": len(resources)},
            )

        cloud_id = first_non_empty_string(resources[0].get("id")) if isinstance(resources[0], dict) else None
        if cloud_id is None:
            raise SourceUnavailable(f"jira: accessible-resources response had no cloud id for user_id={user_id}")

        set_cached_jira_cloud_id(user_id, cloud_id)
        return cloud_id

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
                logger.warning("jira_malformed_project_key", extra={"key": key, "user_id": user_id})

        if valid_project_keys:
            quoted = ", ".join(f'"{key}"' for key in valid_project_keys)
            clauses.append(f"project in ({quoted})")
        else:
            logger.info("jira_no_project_mappings_scoping_by_assignee", extra={"user_id": user_id})

        clauses.append("assignee = currentUser()")

        if since is not None:
            since_utc = since.astimezone(timezone.utc)
            clauses.append(f'updated >= "{since_utc.strftime("%Y-%m-%d %H:%M")}"')

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
