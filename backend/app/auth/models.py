from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import expression, func

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String(100), nullable=True)
    default_channel = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, server_default=expression.false())
    is_sso_user = Column(Boolean, nullable=False, default=False, server_default=expression.false())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    integrations = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="user", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="user", cascade="all, delete-orphan")
    self_captures = relationship("SelfCapture", back_populates="user", cascade="all, delete-orphan")
    email_verification_tokens = relationship(
        "EmailVerificationToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (Index("ix_email_verification_tokens_user_id_created_at", "user_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="email_verification_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_tokens_user_id_created_at", "user_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="password_reset_tokens")
