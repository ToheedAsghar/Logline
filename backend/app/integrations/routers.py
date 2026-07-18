from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.integrations import crud
from app.integrations.models import IntegrationSource
from app.integrations.schemas import IntegrationResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationResponse])
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud.list_integrations_for_user(db, current_user.id)


@router.post("/{source}/connect", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def connect_integration(source: IntegrationSource, current_user: User = Depends(get_current_user)):
    return {"detail": f"OAuth connect flow for '{source.value}' is not yet implemented"}


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
