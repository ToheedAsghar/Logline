from sqlalchemy.orm import Session

from app.integrations.models import Integration, IntegrationSource


def list_integrations_for_user(db: Session, user_id: int) -> list[Integration]:
    return db.query(Integration).filter(Integration.user_id == user_id).all()


def get_integration_by_source(db: Session, user_id: int, source: IntegrationSource) -> Integration | None:
    return db.query(Integration).filter(Integration.user_id == user_id, Integration.source == source).first()


def delete_integration(db: Session, integration: Integration) -> None:
    db.delete(integration)  # cascades to oauth_tokens
    db.commit()
