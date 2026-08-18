import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.constants import REFRESH_REUSE_GRACE_SECONDS, SESSION_FAMILY_ADVISORY_LOCK_CLASS_ID
from app.auth.models import User, UserSession
from app.auth.security import generate_refresh_token, hash_refresh_token
from app.config import settings

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, hashed_password: str, name: str | None) -> User:
    user = User(email=normalize_email(email), hashed_password=hashed_password, name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == normalize_email(email)).first()


def get_user_by_google_id(db: Session, google_user_id: str) -> User | None:
    return db.query(User).filter(User.google_user_id == google_user_id).first()


def create_google_user(db: Session, *, email: str, google_user_id: str, name: str | None) -> User:
    """Fresh signup via Google: no password, active and SSO-linked immediately
    since Google's verified email is trustworthy proof.

    Two near-simultaneous callback requests for the same new Google account
    can both pass the caller's "no existing user" lookup before either
    commits. Rather than crash the loser with a raw IntegrityError, treat the
    unique-constraint conflict (on email or google_user_id) as proof a
    concurrent request already won and re-query for the row it created.
    """
    user = User(
        email=normalize_email(email),
        hashed_password=None,
        name=name,
        is_active=True,
        is_sso_user=True,
        google_user_id=google_user_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = get_user_by_google_id(db, google_user_id) or get_user_by_email(db, email)
        if winner is None:
            raise
        return link_google_account(db, winner, google_user_id=google_user_id)
    db.refresh(user)
    return user


def link_google_account(db: Session, user: User, *, google_user_id: str) -> User:
    """Bootstrap-links a Google login to an existing password account matched by email. Activates the account
    unconditionally because Google's verified email is trustworthy proof.

    If the row was not already active, its password hash is unproven and could have been set by an attacker who
    pre-registered the victim's email. Discard that hash so the account becomes Google-only. An already-active row is a
    verified account a real user is choosing to link, so its existing password is preserved.
    """
    if not user.is_active:
        user.hashed_password = None
    user.google_user_id = google_user_id
    user.is_sso_user = True
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


def _refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)


def create_session(db: Session, *, user_id: int) -> tuple[UserSession, str]:
    """Start a fresh refresh-token session (a new rotation family) at login, returning it alongside the plaintext
    refresh token. Only the token's hash is stored, so this return value is the only chance anything has to see it.

    `family_id` is set to the row's own `id` once known -- a placeholder value is written first because `family_id`
    is NOT NULL and the id doesn't exist until the row is flushed; the placeholder is never visible outside this
    transaction.
    """
    token = generate_refresh_token()
    session = UserSession(
        user_id=user_id,
        family_id=0,
        refresh_token_hash=hash_refresh_token(token),
        expires_at=_refresh_token_expires_at(),
    )
    db.add(session)
    db.flush()
    session.family_id = session.id
    db.commit()
    db.refresh(session)
    return session, token


class RotationOutcome(Enum):
    """Why a rotation attempt ended the way it did, to the level of detail the HTTP layer needs.

    `REJECTED` and `CONCURRENT_ROTATION` are both a 401 to the caller and must stay indistinguishable in the
    response body -- they differ only in whether the refresh cookie is cleared alongside it.
    """

    ROTATED = "rotated"
    REJECTED = "rejected"
    CONCURRENT_ROTATION = "concurrent_rotation"


class RevokedReason(str, Enum):
    """Why a `UserSession.revoked_at` was set. `ROTATED` means a normal `/auth/refresh` superseded this row -- a
    replay of it is genuine reuse evidence no matter what else has since happened to the rest of the family.
    `LOGOUT`/`LOGOUT_ALL`/`REUSE` mean the row was killed directly, so a replay of it is just an already-dead
    token, not new evidence.
    """

    ROTATED = "rotated"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    REUSE = "reuse"


@dataclass(frozen=True)
class RotationResult:
    """`session` and `token` are set only when `outcome` is `ROTATED`.

    `clear_refresh_cookie` tells the router whether the presented cookie is genuinely dead. It is deliberately
    False for `CONCURRENT_ROTATION`: the browser's cookie jar is shared by every tab, so the token this request
    presented is stale while the jar already holds the winner's newer one. Clearing on that response would delete
    the winning tab's fresh cookie and log the whole browser out -- the exact failure the grace window exists to
    prevent.
    """

    outcome: RotationOutcome
    session: UserSession | None = None
    token: str | None = None

    @property
    def clear_refresh_cookie(self) -> bool:
        return self.outcome is RotationOutcome.REJECTED


def _within_reuse_grace(revoked_at: datetime, now: datetime) -> bool:
    """Returns True if `revoked_at` is recent enough that token reuse is likely a harmless multi-tab race rather than
    token theft.

    No clock-skew tolerance is needed because both timestamps come from backend servers rather than client devices.
    Server clock drift via NTP is only a few milliseconds, which is negligible compared to the grace window, and a
    skewed app clock only ever widens this window -- it can never cause a wrongful revoke. That one-directional,
    low-stakes failure mode is why this comparison is allowed to use the app server's clock, unlike the retention
    cutoff in `retention.py`, which computes on the database's clock instead because a fast app clock there would
    mass-delete live sessions with no fail-safe direction.
    """
    return now - revoked_at < timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)


def _lock_family(db: Session, family_id: int) -> None:
    """Serializes every rotation/revocation touching one login family for the rest of the current transaction --
    released automatically at the next commit or rollback.

    Without this, `rotate_session` and `revoke_session_by_token` can each take a snapshot before the other commits
    and after it starts, so neither one's query ever sees the row the other one just wrote: a `/auth/refresh` and a
    `/auth/logout` racing on the same family could each work off a stale view of it, leaving a session alive that
    should have died. Callers must re-fetch whatever row they already read after calling this, since that earlier
    read may itself be the stale snapshot.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(:class_id, :family_id)"),
        {"class_id": SESSION_FAMILY_ADVISORY_LOCK_CLASS_ID, "family_id": family_id},
    )


def _revoke_family(db: Session, *, user_id: int, family_id: int, now: datetime, reason: RevokedReason) -> int:
    """Revoke all active sessions in a single login family (device session). Returns the number of revoked rows.

    Checking `revoked_at IS NULL` makes this safe against concurrent requests: the first call revokes the rows and any
    simultaneous second call safely updates 0 rows. Filtering by both `user_id` and `family_id` ensures this can never
    affect another user's account, even though `family_id` is already unique across users.
    """
    claimed = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.family_id == family_id,
            UserSession.revoked_at.is_(None),
        )
        .update({"revoked_at": now, "revoked_reason": reason})
    )
    db.commit()
    return claimed


def rotate_session(db: Session, *, refresh_token: str) -> RotationResult:
    """Validates and consumes a refresh token, issuing a new token in the same session family.

    The update is atomic, so if two requests race on the same token simultaneously, only the first succeeds. The
    second affects 0 rows and is safely rejected without double-issuing tokens or crashing.

    Using an old token revoked outside the grace window triggers theft detection: all sessions in that family are
    revoked. This logs out the entire session chain because the server cannot tell if the attacker or the real user
    holds the active token.

    Expiry is checked before reuse so that expired tokens are simply rejected without touching the active session
    family. This prevents dead tokens from being used to log out legitimate users.
    """
    token_hash = hash_refresh_token(refresh_token)
    old = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash).first()
    if old is None:
        return RotationResult(RotationOutcome.REJECTED)

    _lock_family(db, old.family_id)
    old = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash).first()

    now = datetime.now(timezone.utc)

    if old.expires_at <= now:
        return RotationResult(RotationOutcome.REJECTED)

    if old.revoked_at is not None:
        user_id, family_id, session_id = old.user_id, old.family_id, old.id
        revoked_at, revoked_reason = old.revoked_at, old.revoked_reason

        if _within_reuse_grace(revoked_at, now):
            logger.info(
                "refresh_token_replayed_inside_grace",
                extra={
                    "user_id": user_id,
                    "family_id": family_id,
                    "replayed_session_id": session_id,
                    "revoked_at": revoked_at.isoformat(),
                    "delta_seconds": (now - revoked_at).total_seconds(),
                },
            )
            return RotationResult(RotationOutcome.CONCURRENT_ROTATION)

        revoked_count = _revoke_family(
            db, user_id=user_id, family_id=family_id, now=now, reason=RevokedReason.REUSE
        )
        if revoked_reason == RevokedReason.ROTATED:
            logger.warning(
                "refresh_token_reuse_detected",
                extra={
                    "user_id": user_id,
                    "family_id": family_id,
                    "replayed_session_id": session_id,
                    "revoked_at": revoked_at.isoformat(),
                    "sessions_revoked": revoked_count,
                },
            )
        return RotationResult(RotationOutcome.REJECTED)

    claimed = (
        db.query(UserSession)
        .filter(UserSession.id == old.id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
        .update({"revoked_at": now, "revoked_reason": RevokedReason.ROTATED, "last_used_at": now})
    )
    if claimed == 0:
        db.rollback()
        return RotationResult(RotationOutcome.CONCURRENT_ROTATION)

    new_token = generate_refresh_token()
    new_session = UserSession(
        user_id=old.user_id,
        family_id=old.family_id,
        refresh_token_hash=hash_refresh_token(new_token),
        expires_at=_refresh_token_expires_at(),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return RotationResult(RotationOutcome.ROTATED, session=new_session, token=new_token)


def revoke_session_by_token(db: Session, *, refresh_token: str) -> bool:
    """Revoke every live session in the family of the session named by `refresh_token`, if any. Returns whether any
    live session was found and revoked -- callers should treat `False` the same as "already logged out", not as an
    error.

    Looks the row up by hash regardless of whether it is itself already revoked, then revokes by `family_id` rather
    than just that one row. A logout request can arrive at the server after a concurrent `/auth/refresh` has already
    rotated the presented token away -- the browser sent both requests with the same cookie value because it hadn't
    seen the refresh response yet. Revoking only the named row would then find it already revoked and do nothing,
    leaving the rotated successor alive and usable even though the user was just shown a logged-out UI. Locking the
    family (see `_lock_family`) and re-fetching afterward closes the same gap for a genuinely concurrent rotation,
    not just one that already finished before this request started.

    Refuses to act on an expired token, same as `rotate_session` and for the same reason: a long-dead ancestor
    token from a still-live family must not retain the power to log out every device in that family.
    """
    token_hash = hash_refresh_token(refresh_token)
    session = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash).first()
    if session is None:
        return False

    _lock_family(db, session.family_id)
    session = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash).first()

    now = datetime.now(timezone.utc)
    if session.expires_at <= now:
        return False

    revoked = _revoke_family(
        db, user_id=session.user_id, family_id=session.family_id, now=now, reason=RevokedReason.LOGOUT
    )
    return revoked > 0


def revoke_all_sessions(db: Session, *, user_id: int) -> int:
    """Revoke every live session for `user_id` ("log out of all devices"), across every family. Returns the number
    revoked."""
    now = datetime.now(timezone.utc)
    claimed = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .update({"revoked_at": now, "revoked_reason": RevokedReason.LOGOUT_ALL})
    )
    db.commit()
    return claimed
