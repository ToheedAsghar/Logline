"""OAuth provider registry: manages which OAuth sources (Slack, GitHub, etc.) are available and routes requests to the
right provider.

`base.py` defines the shared OAuthProvider interface that all providers must implement. `slack.py`, `github.py`,
`jira.py`, and `calendar.py` are concrete implementations for those sources. This `__init__.py` file exports the
factory function that returns the right provider for a given source.

To add a new OAuth source, create one new file under `providers/` with your implementation and register it in the
`PROVIDERS` dict below.
"""

from app.integrations.constants import OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens
from app.integrations.providers.calendar import CalendarOAuthProvider
from app.integrations.providers.github import GitHubOAuthProvider
from app.integrations.providers.jira import JiraOAuthProvider
from app.integrations.providers.slack import SlackOAuthProvider

__all__ = [
    "OAuthProvider",
    "OAuthTokens",
    "get_oauth_provider",
    "is_source_registered",
]


PROVIDERS: dict[IntegrationSource, OAuthProvider] = {
    IntegrationSource.slack: SlackOAuthProvider(),
    IntegrationSource.github: GitHubOAuthProvider(),
    IntegrationSource.jira: JiraOAuthProvider(),
    IntegrationSource.calendar: CalendarOAuthProvider(),
}


def is_source_registered(source: IntegrationSource) -> bool:
    """Check whether a source has an OAuth provider. Returns False for valid IntegrationSource values that don't have
    a provider yet.
    """
    return source in PROVIDERS


def get_oauth_provider(source: IntegrationSource) -> OAuthProvider:
    """Get the OAuth provider for a source.

    Raises NotImplementedError if the source is valid as an IntegrationSource but doesn't have a registered OAuth
    provider yet.
    """
    provider = PROVIDERS.get(source)
    if provider is None:
        raise NotImplementedError(
            OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE.format(source=source.value)
        )
    return provider

