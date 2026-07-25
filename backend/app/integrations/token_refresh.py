"""Refreshes OAuth tokens before they expire, routing refresh requests to the correct provider's API (Slack, GitHub,
etc. each have different endpoints).

`ensure_token_fresh()` works across all integration providers by resolving the provider from the shared OAuth registry
(`get_oauth_provider`) -- the same single source of truth the connect/callback routes use. The provider supplies its
refresh call, its error type, and its user-facing message wording, so this module has no per-source dispatch table of
its own. Adding a provider requires no change here.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.integrations.constants import OAUTH_TOKEN_REFRESH_MARGIN_SECONDS
from app.integrations.models import IntegrationSource, OAuthToken
from app.integrations.providers import get_oauth_provider


def _needs_refresh(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    return expires_at - datetime.now(timezone.utc) <= timedelta(seconds=OAUTH_TOKEN_REFRESH_MARGIN_SECONDS)


async def ensure_token_fresh(db: Session, source: IntegrationSource, integration_id: int) -> OAuthToken:
    """Check if an OAuth token is still valid, and refresh it if needed.

    Takes an integration (identified by source and integration_id), checks its stored token's expiry time, and
    refreshes it from the provider if it's getting close to expiring. Returns the valid token.

    Raises TokenRefreshError (with provider-specific details like which integration failed and why) if the token can't
    be refreshed. Raises NotImplementedError if the provider doesn't support refresh yet.
    """
    provider = get_oauth_provider(source)

    token = (
        db.query(OAuthToken)
        .filter(OAuthToken.integration_id == integration_id)
        .with_for_update()
        .first()
    )
    if token is None:
        raise provider.error_type(provider.token_not_found_message.format(integration_id=integration_id))

    if not _needs_refresh(token.expires_at):
        return token

    if not token.refresh_token:
        raise provider.error_type(
            provider.missing_refresh_token_message.format(integration_id=integration_id)
        )

    refreshed = await provider.refresh(token.refresh_token)

    token.access_token = refreshed.access_token
    if refreshed.refresh_token:
        token.refresh_token = refreshed.refresh_token
    token.expires_at = refreshed.expires_at
    try:
        db.commit()
    except Exception as exc:
        db.rollback()

        token = (
            db.query(OAuthToken)
            .filter(OAuthToken.integration_id == integration_id)
            .with_for_update()
            .first()
        )
        if token is None:
            raise provider.error_type(
                provider.token_not_found_message.format(integration_id=integration_id)
            ) from exc

        if not _needs_refresh(token.expires_at):
            db.refresh(token)
            return token

        token.access_token = refreshed.access_token
        if refreshed.refresh_token:
            token.refresh_token = refreshed.refresh_token
        token.expires_at = refreshed.expires_at

        try:
            db.commit()
        except Exception as retry_exc:
            db.rollback()
            raise provider.error_type(
                provider.persist_failed_message.format(integration_id=integration_id)
            ) from retry_exc

    db.refresh(token)
    return token
