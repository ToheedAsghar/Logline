# Import every domain's models module here so all mapped classes are
# registered on Base.metadata before Alembic autogenerate (or anything
# else) inspects it -- regardless of which folder a model physically
# lives in. This is the single place that must be updated whenever a
# new domain gains a models.py.
from app.auth.models import User
from app.db.session import Base
from app.entries.models import Entry, EntryFormat, EntryStatus
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.self_captures.models import SelfCapture
from app.timeline.models import ConfidenceLevel, Event, WorkBlock
from app.tracker_sync.models import LocalSession


__all__ = [
    "Base",
    "User",
    "Integration",
    "IntegrationSource",
    "IntegrationStatus",
    "OAuthToken",
    "Event",
    "ConfidenceLevel",
    "WorkBlock",
    "Entry",
    "EntryFormat",
    "EntryStatus",
    "SelfCapture",
    "LocalSession",
]
