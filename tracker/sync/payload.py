"""The complete, explicit allowlist of what may leave this machine in a sync payload.

Nothing else in the sync path builds an outgoing session dict, so a field added to the local `sessions` table
cannot reach the network without a deliberate edit here.
"""

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

ALLOWED_FIELDS = (
    "id",
    "bundle_id",
    "app_name",
    "window_title",
    "started_at",
    "ended_at",
    "end_reason",
    "is_idle",
    "project_path",
    "context_detail",
)

SELECT_COLUMNS = ", ".join(ALLOWED_FIELDS)


@dataclass(frozen=True)
class SyncSessionOut:
    """One closed session, in the only shape that may be transmitted."""

    id: str
    bundle_id: str
    app_name: str
    window_title: Optional[str]
    started_at: str
    ended_at: str
    end_reason: str
    is_idle: bool
    project_path: Optional[str]
    context_detail: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SyncSessionOut":
        """Reads each allowlisted column by name. Never `dict(row)` -- that would forward whatever the table
        happens to hold, which is the failure mode this type exists to prevent."""
        return cls(
            id=str(row["id"]),
            bundle_id=row["bundle_id"],
            app_name=row["app_name"],
            window_title=row["window_title"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            end_reason=row["end_reason"],
            is_idle=bool(row["is_idle"]),
            project_path=row["project_path"],
            context_detail=row["context_detail"],
        )

    def to_payload(self) -> Dict[str, Any]:
        """The JSON body for one session. `context_detail` stays the stored JSON string, since the backend column
        is text and re-encoding it here would only risk changing it."""
        return {field: getattr(self, field) for field in ALLOWED_FIELDS}
