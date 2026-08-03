"""The Session shape — single source of truth mirroring the `sessions` table contract.
Every other module references this; never redefine the shape inline."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Session:
    """`project_path` gets a dedicated field/column because the aggregation pipeline's `RawSessionRow.project`
    depends on it by name. Every other captured detail — git_branch, active_file, meeting_name, url — goes in
    `context_detail` instead, keeping new app support to resolver code rather than a schema change."""

    id: str
    bundle_id: str
    app_name: str
    window_title: Optional[str]
    started_at: str
    ended_at: str
    end_reason: Optional[str] = None
    is_idle: bool = False
    project_path: Optional[str] = None
    context_detail: Optional[Dict[str, Any]] = None
