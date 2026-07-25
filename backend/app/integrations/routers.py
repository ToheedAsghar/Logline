import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.config import settings
from app.core.oauth_state import OAuthStateError
from app.db.session import get_db
from app.integrations import crud
from app.integrations.connect_state import consume_connect_state, create_connect_state
from app.integrations.errors import TokenRefreshError
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.integrations.providers import OAuthProvider, OAuthTokens, get_oauth_provider, is_source_registered
from app.integrations.schemas import IntegrationResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationResponse])
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud.list_integrations_for_user(db, current_user.id)


def _require_provider(source: IntegrationSource) -> OAuthProvider:
    """Resolve the provider for `source`, 404ing cleanly for a valid IntegrationSource that has no registered OAuth
    flow yet.
    """
    if not is_source_registered(source):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OAuth connect flow for '{source.value}' is not available",
        )
    return get_oauth_provider(source)


@router.get("/{source}/connect")
def connect_integration(
    source: IntegrationSource,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = _require_provider(source)
    state = create_connect_state(db, user_id=current_user.id, source=source)
    return RedirectResponse(url=provider.build_authorize_url(state))


@router.get("/{source}/callback")
async def integration_callback(
    source: IntegrationSource,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    provider = _require_provider(source)

    if state is None:
        return RedirectResponse(
            url=_result_redirect(source, result_status="error", detail=provider.missing_params_message)
        )

    try:
        user_id = consume_connect_state(db, token=state, expected_source=source)
    except OAuthStateError as exc:
        logger.info("%s connect state validation failed: %s", source.value, exc.message)
        return RedirectResponse(url=_result_redirect(source, result_status="error", detail=exc.message))

    if error is not None:
        logger.info("%s connect callback reported an error: %s", source.value, error)
        return RedirectResponse(
            url=_result_redirect(source, result_status="error", detail=provider.callback_error_detail(error))
        )

    if code is None:
        return RedirectResponse(
            url=_result_redirect(source, result_status="error", detail=provider.missing_params_message)
        )

    try:
        tokens = await provider.exchange_code(code)
    except TokenRefreshError as exc:
        logger.info("%s OAuth exchange failed: %s", source.value, exc)
        return RedirectResponse(url=_result_redirect(source, result_status="error", detail=str(exc)))

    integration = _get_or_create_integration(db, user_id, source)
    _upsert_oauth_token(db, integration.id, tokens)
    db.commit()

    return RedirectResponse(url=_result_redirect(source, result_status="connected"))


@router.delete("/{source}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_integration(
    source: IntegrationSource,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integration = crud.get_integration_by_source(db, current_user.id, source)
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

    crud.delete_integration(db, integration)


def _result_redirect(source: IntegrationSource, *, result_status: str, detail: str | None = None) -> str:
    params = {"integration": source.value, "status": result_status}
    if detail is not None:
        params["detail"] = detail
    return f"{settings.frontend_base_url}/settings?{urlencode(params)}"


def _get_or_create_integration(db: Session, user_id: int, source: IntegrationSource) -> Integration:
    integration = (
        db.query(Integration)
        .filter(Integration.user_id == user_id, Integration.source == source)
        .first()
    )
    if integration is None:
        integration = Integration(user_id=user_id, source=source, status=IntegrationStatus.connected)
        db.add(integration)
        db.flush()
    else:
        integration.status = IntegrationStatus.connected
    return integration


def _upsert_oauth_token(db: Session, integration_id: int, tokens: OAuthTokens) -> OAuthToken:
    token = db.query(OAuthToken).filter(OAuthToken.integration_id == integration_id).first()
    if token is None:
        token = OAuthToken(integration_id=integration_id)
        db.add(token)

    token.access_token = tokens.access_token
    token.refresh_token = tokens.refresh_token
    token.expires_at = tokens.expires_at
    return token
