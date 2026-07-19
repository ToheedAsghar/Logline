# Import every domain's models module here so all mapped classes are
# registered on Base.metadata before Alembic autogenerate (or anything
# else) inspects it -- regardless of which folder a model physically
# lives in. This is the single place that must be updated whenever a
# new domain gains a models.py.
from app.auth.models import EmailVerificationToken, PasswordResetToken, User
from app.db.session import Base
from app.entries.models import Entry, EntryFormat, EntryStatus
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.models.work_block import WorkBlock
from app.self_captures.models import SelfCapture
from app.timeline.models import ConfidenceLevel, Event

__all__ = [
    "Base",
    "User",
    "EmailVerificationToken",
    "PasswordResetToken",
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
]
