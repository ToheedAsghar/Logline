"""Shapes passed into and out of the context resolvers."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WindowContext:
    """One frontmost-window observation, with every Accessibility read already done. Resolvers take this and
    stay pure functions, so they can be tested without a live AX session or a running app."""

    bundle_id: str
    app_name: str
    window_title: Optional[str] = None
    document_url: Optional[str] = None


@dataclass
class ContextResult:
    """`project_path` maps to its own column; `detail` becomes the `context_detail` JSON blob. Resolvers add
    whatever keys their app supports — new keys never need a migration.

    `project_path` is authoritative: it comes from a path the OS reported, so where it disagrees with the
    title-derived `detail["project_name"]`, the path is the one to trust.
    """

    project_path: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """Records a detail key, ignoring None/empty so callers never have to guard each assignment."""
        if value is not None and value != "":
            self.detail[key] = value
