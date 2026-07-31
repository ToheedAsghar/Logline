"""The Session shape — single source of truth mirroring the `sessions` table contract.
Every other module references this; never redefine the shape inline."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    id: str
    bundle_id: str
    app_name: str
    window_title: Optional[str]
    started_at: str
    ended_at: str
    end_reason: Optional[str] = None
    is_idle: bool = False
