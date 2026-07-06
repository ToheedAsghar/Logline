from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.integration import Integration, IntegrationSource
from app.models.user import User
from app.schemas.integration import IntegrationResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationResponse])
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(Integration).filter(Integration.user_id == current_user.id).all()


@router.post("/{source}/connect", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def connect_integration(source: IntegrationSource, current_user: User = Depends(get_current_user)):
    return {"detail": f"OAuth connect flow for '{source.value}' is not yet implemented"}


@router.delete("/{source}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_integration(
    source: IntegrationSource,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integration = (
        db.query(Integration)
        .filter(Integration.user_id == current_user.id, Integration.source == source)
        .first()
    )
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

    db.delete(integration)  # cascades to oauth_tokens
    db.commit()
