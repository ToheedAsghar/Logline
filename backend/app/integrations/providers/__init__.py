"""The integrations OAuth providers package: one concrete `OAuthProvider` per
source (`base.py` holds the ABC, `slack.py` the Slack implementation) plus the
single factory that dispatches by source.

This `__init__` is the one true source of truth for which sources have a working
OAuth connect/refresh flow. Both the generic routes and `ensure_token_fresh`
resolve providers exclusively through `get_oauth_provider()` here -- there is no
second per-source dispatch table anywhere. Adding GitHub/Jira/Calendar later is
one new OAuthProvider subclass (a `providers/<source>.py`) plus one entry in
`_PROVIDERS`.

Package shape and dispatch style mirror `app/agent/llm/`: `base.py` ~
`llm/base.py`, `slack.py` ~ `llm/openai_provider.py`, and this factory ~
`app/agent/llm/__init__.py::get_llm_provider()`.
"""

from app.integrations.constants import OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens
from app.integrations.providers.slack import SlackOAuthProvider

__all__ = [
    "OAuthProvider",
    "OAuthTokens",
    "get_oauth_provider",
    "is_source_registered",
]

# Providers are stateless singletons (they read config per call), so one shared
# instance per source is fine.
_PROVIDERS: dict[IntegrationSource, OAuthProvider] = {
    IntegrationSource.slack: SlackOAuthProvider(),
}


def is_source_registered(source: IntegrationSource) -> bool:
    """Whether `source` has a registered OAuth provider. Lets the generic
    routes 404 an unregistered (but enum-valid) source without catching."""
    return source in _PROVIDERS


def get_oauth_provider(source: IntegrationSource) -> OAuthProvider:
    """Return the provider handling `source`.

    Raises NotImplementedError for a valid IntegrationSource that has no
    registered provider yet (e.g. jira/github/calendar today) -- mirrors
    `get_llm_provider()`'s behavior for an unsupported provider.
    """
    provider = _PROVIDERS.get(source)
    if provider is None:
        raise NotImplementedError(
            OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE.format(source=source.value)
        )
    return provider
