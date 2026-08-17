from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import expression, func

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=True)
    name = Column(String(100), nullable=True)
    default_channel = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, server_default=expression.false())
    is_sso_user = Column(Boolean, nullable=False, default=False, server_default=expression.false())
    google_user_id = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    integrations = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="user", cascade="all, delete-orphan")
    email_verification_tokens = relationship(
        "EmailVerificationToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    remote_events = relationship("RemoteEvent", back_populates="user", cascade="all, delete-orphan")
    project_mappings = relationship("ProjectMapping", back_populates="user", cascade="all, delete-orphan")
    local_sessions = relationship("LocalSession", back_populates="user", cascade="all, delete-orphan")
    remote_fetch_states = relationship("RemoteFetchState", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


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


class UserSession(Base):
    """A single refresh-token session issued at login (or Google exchange) and consumed by `/auth/refresh`.

    `refresh_token_hash` stores only a SHA-256 hash -- the raw token is returned to the client once (as an httpOnly
    cookie) and is never recoverable afterwards, same pattern as `TrackerDevice.token_hash`.

    Refresh tokens rotate on every use: a successful `/auth/refresh` call marks this row `revoked_at` and creates a
    brand-new row for the replacement token. `family_id` links every row descended from the same login across that
    rotation chain, and `crud.rotate_session` uses it for reuse detection: replaying a token that was rotated away
    revokes the entire family.

    Rows are deleted by `retention.purge_expired_sessions` once they are well past `expires_at` -- never merely
    because they are revoked, since a revoked row is what makes that reuse detection possible. `expires_at` is
    indexed for that purge.

    `revoked_reason` (see `crud.RevokedReason`) records why `revoked_at` was set: `rotated` means a normal
    `/auth/refresh` superseded this row, so replaying it is genuine reuse evidence regardless of what else has since
    happened to the rest of the family; `logout`/`logout_all`/`reuse` mean the row was killed directly and a replay
    of it is not new evidence. `crud.rotate_session` uses this distinction to decide whether a reuse replay is worth
    a security warning.
    """

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    family_id = Column(Integer, nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(20), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")
