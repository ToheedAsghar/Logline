"""Data passed into and out of the context resolvers."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from tracker.constants import CONTEXT_DETAIL_KEYS


@dataclass(frozen=True)
class WindowContext:
    """One observation of the frontmost window, after all Accessibility reads are complete.

    Resolvers take this data so they can be tested without Accessibility or a running app.
    """

    bundle_id: str
    app_name: str
    window_title: Optional[str] = None
    document_url: Optional[str] = None


@dataclass(frozen=True)
class TerminalToolContext:
    """The details we can safely report about a recognized terminal tool.

    These are the only fields on purpose. Terminal titles are redacted because command lines can contain secrets.
    The values here come from process data or the filesystem. Adding a title, command, or argument field would
    defeat that protection.

    `tool` is None when the foreground process is not a known development tool (e.g. a plain shell). The cwd and
    branch are still reported in that case so regular terminal work inside a project is attributed correctly.
    """

    tool: Optional[str]
    cwd: str
    branch: Optional[str] = None


@dataclass
class ContextResult:
    """The context for one observation.

    `project_path` is stored in its own column. `detail` becomes the `context_detail` JSON data. Resolvers can add
    supported keys without a database migration. Trust `project_path` over a title-based project name because the
    operating system supplied the path.
    """

    project_path: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Remove detail keys that are not part of the supported context format."""
        self.detail = {key: value for key, value in self.detail.items() if key in CONTEXT_DETAIL_KEYS}

    def set(self, key: str, value: Any) -> None:
        """Store a detail value unless it is None or empty."""
        if key in CONTEXT_DETAIL_KEYS and value is not None and value != "":
            self.detail[key] = value
