"""The single source of truth for which remote sources can be fetched.

Owned here rather than inside the orchestrator so any other module (the manual
trigger router, the tests) can iterate the full source set without importing the
orchestrator. Kept out of `constants.py` because that module must stay a
dependency leaf -- the concrete fetchers here import from it, so importing them
back would cycle.
"""

from app.remote_fetch.base import SourceFetcher
from app.remote_fetch.sources.calendar import CalendarFetcher
from app.remote_fetch.sources.github import GitHubFetcher
from app.remote_fetch.sources.jira import JiraFetcher
from app.remote_fetch.sources.slack import SlackFetcher

ALL_FETCHERS: list[type[SourceFetcher]] = [
    GitHubFetcher,
    JiraFetcher,
    CalendarFetcher,
    SlackFetcher,
]

FETCHERS: dict[str, type[SourceFetcher]] = {cls.source: cls for cls in ALL_FETCHERS}
