import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.encrypted_types import EncryptedString
from app.db.session import Base


class IntegrationSource(str, enum.Enum):
    github = "github"
    slack = "slack"
    jira = "jira"
    calendar = "calendar"


class IntegrationStatus(str, enum.Enum):
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(Enum(IntegrationSource, name="integration_source"), nullable=False)
    status = Column(
        Enum(IntegrationStatus, name="integration_status"),
        nullable=False,
        default=IntegrationStatus.disconnected,
    )
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    integration_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="integrations")
    oauth_tokens = relationship("OAuthToken", back_populates="integration", cascade="all, delete-orphan")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False, index=True)
    access_token = Column(EncryptedString, nullable=False)
    refresh_token = Column(EncryptedString, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    integration = relationship("Integration", back_populates="oauth_tokens")


class ConnectLinkToken(Base):
    """Database row that backs a one-time pass for browser navigation. Once the
    pass is used (consumed by connect_link_token.py), the used_at timestamp is
    set and it can never be used again.
    """

    __tablename__ = "connect_link_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(Enum(IntegrationSource, name="integration_source"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    used_at = Column(DateTime(timezone=True), nullable=True)
