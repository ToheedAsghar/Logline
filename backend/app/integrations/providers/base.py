"""Provider-agnostic OAuth boundary for integration connect flows.

Everything in this file is neutral with respect to which external service is actually behind it. The generic
connect/callback routes and the token-refresh flow talk to providers only through the `OAuthProvider` interface here
-- they never branch on `source`. Provider-specific HTTP/parse logic (and the exact user-facing message wording) lives
in the concrete subclass, e.g. `app/integrations/providers/slack.py::SlackOAuthProvider`.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel

from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource


class OAuthTokens(BaseModel):
    """Neutral token shape returned by every provider's exchange/refresh.

    `scope` and `authed_user_id` are populated when the provider surfaces them (both are optional, generic account-level
    metadata). Everything except `scope` is persisted to `oauth_tokens`; `scope` is informational only, used to build
    provider error messages rather than stored.
    """

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str = ""
    authed_user_id: str = ""


class OAuthProvider(ABC):
    """The single seam the generic routes and token-refresh flow talk to.

    A provider owns not just the three OAuth calls but also its own identity (`source`), its error type, and the
    user-facing message wording for the connect/refresh flows. Keeping the messages here -- rather than in a separate
    per-source lookup table -- is deliberate: it makes this registry the one true source of truth per source, so the
    routes and `ensure_token_fresh` stay completely source-agnostic.
    """

    #: Which IntegrationSource this provider handles.
    source: IntegrationSource
    #: The TokenRefreshError subclass this provider raises (carries `source`).
    error_type: type[TokenRefreshError]

    #: Token-refresh-flow message templates, formatted with `integration_id`.
    token_not_found_message: str
    missing_refresh_token_message: str
    persist_failed_message: str

    #: Callback message for a request missing the required code/state params.
    missing_params_message: str

    @abstractmethod
    def build_authorize_url(self, state: str) -> str:
        """Build the provider's authorize URL to redirect the user to, embedding `state` for CSRF/round-trip
        validation on callback.
        """

    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthTokens:
        """Exchange an authorization `code` for a token pair. Raises this provider's `error_type` on rejection or a
        network/parse failure.
        """

    @abstractmethod
    async def refresh(self, refresh_token: str) -> OAuthTokens:
        """Exchange a `refresh_token` for a fresh token pair. Raises this provider's `error_type` on rejection or a
        network/parse failure.
        """

    @abstractmethod
    def callback_error_detail(self, error_code: str) -> str:
        """Map a provider-reported callback `error` code (e.g. Slack's `access_denied`) to a fixed, internal-facing
        user message. The raw provider string is never reflected into the redirect directly.
        """
