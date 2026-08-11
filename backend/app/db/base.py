"""Import every domain's models module here so all mapped classes are registered on Base.metadata before the migration
tool inspects it -- regardless of which folder a model physically lives in. This is the single place that must be
updated whenever a new domain gains a models.py.
"""
from app.agent.reconciliation.models import ReconciliationDraft, ReconciliationDraftState
from app.auth.models import EmailVerificationToken, PasswordResetToken, User
from app.core.oauth_state import OAuthState
from app.db.session import Base
from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource
from app.integrations.models import ConnectLinkToken, Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.matching.models import ProjectMapping, RemoteEvent
from app.remote_fetch.models import RemoteFetchState
from app.self_captures.models import SelfCapture
from app.timeline.models import ConfidenceLevel, Event
from app.tracker_sync.models import LocalSession

__all__ = [
    "Base",
    "User",
    "EmailVerificationToken",
    "PasswordResetToken",
    "OAuthState",
    "Integration",
    "IntegrationSource",
    "IntegrationStatus",
    "OAuthToken",
    "ConnectLinkToken",
    "Event",
    "ConfidenceLevel",
    "Entry",
    "EntryFormat",
    "EntryStatus",
    "EntryVersion",
    "EntryVersionSource",
    "ReconciliationDraft",
    "ReconciliationDraftState",
    "SelfCapture",
    "RemoteEvent",
    "ProjectMapping",
    "RemoteFetchState",
    "LocalSession",
]
