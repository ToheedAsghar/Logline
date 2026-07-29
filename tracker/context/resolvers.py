"""Per-app context resolvers, plus the dispatch registry.

Every resolver is a pure function of a WindowContext. Adding support for a new app means writing one resolver
and adding one REGISTRY entry — no schema change, since app-specific keys land in `context_detail`.
Unrecognized apps fall through to `resolve_generic`, which still captures everything app-agnostic; nothing is
ever skipped for being unknown.
"""

import re
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.parse import unquote, urlparse

from tracker.context.git import current_branch, find_project_root
from tracker.context.meet import parse_meet_title
from tracker.context.models import ContextResult, WindowContext

VSCODE_BUNDLE_ID = "com.microsoft.VSCode"
ANTIGRAVITY_BUNDLE_ID = "com.google.antigravity-ide"
CHROME_BUNDLE_ID = "com.google.Chrome"
FIREFOX_BUNDLE_ID = "org.mozilla.firefox"

EDITOR_SEPARATOR = "—"

ELLIPSIS = "…"

EDITOR_DECORATION_RE = re.compile(r"\s*\((?:Working Tree|Index|HEAD)\)(?:\s*\([^()]*\))?\s*$")

FILENAME_RE = re.compile(r"^[^/\\\s:]*\.([A-Za-z0-9_+-]{1,12})$")


def _split_editor_title(window_title: Optional[str]):
    if not window_title:
        return []
    return [part.strip() for part in window_title.split(EDITOR_SEPARATOR) if part.strip()]


def _clean_active_file(part: str) -> Optional[str]:
    """Returns `part` only if it actually looks like a file name. Editor titles also carry chat/task/terminal
    names in the same slot, and recording those as `active_file` would be a guess."""
    candidate = EDITOR_DECORATION_RE.sub("", part).strip()
    if not candidate or ELLIPSIS in candidate:
        return None
    match = FILENAME_RE.match(candidate)
    if match is None:
        return None
    return candidate if any(char.isalpha() for char in match.group(1)) else None


def _path_from_document_url(document_url: Optional[str]) -> Optional[Path]:
    """Converts an AXDocument value (a file:// URL) to a local path. Returns None for empty values, which is
    what editors report when the focused tab isn't a file."""
    if not document_url:
        return None
    parsed = urlparse(document_url)
    if parsed.scheme and parsed.scheme != "file":
        return None
    raw = unquote(parsed.path if parsed.scheme == "file" else document_url)
    return Path(raw) if raw else None


def _apply_project(result: ContextResult, document_url: Optional[str]) -> None:
    """Derives project_path from a real on-disk path and records the live git branch alongside it. Only ever
    set from a path the OS reported — never inferred from a project name in a title."""
    path = _path_from_document_url(document_url)
    if path is None:
        return
    root = find_project_root(path)
    if root is None:
        return
    result.project_path = str(root)
    result.set("git_branch", current_branch(root))


def _apply_meet(result: ContextResult, window_title: Optional[str]) -> None:
    is_meeting, meeting_name = parse_meet_title(window_title)
    if is_meeting:
        result.set("is_meeting", True)
        result.set("meeting_name", meeting_name)


def resolve_generic(ctx: WindowContext, detect_meetings: bool = True) -> ContextResult:
    """Fallback for every app without a dedicated resolver, and the shared base the others build on. Captures
    the project/branch when the app exposes a document path, and normalizes any Meet-looking title.

    `detect_meetings` defaults on because an unrecognized app may well be a browser, and missing a real
    meeting costs more than an over-tagged one. Resolvers for apps that are definitely not browsers turn it
    off.
    """
    result = ContextResult()
    _apply_project(result, ctx.document_url)
    if detect_meetings:
        _apply_meet(result, ctx.window_title)
    return result


def _resolve_editor(ctx: WindowContext, project_first: bool) -> ContextResult:
    result = resolve_generic(ctx, detect_meetings=False)
    parts = _split_editor_title(ctx.window_title)
    if not parts:
        return result
    if len(parts) == 1:
        result.set("project_name", parts[0])
        return result
    project_part = parts[0] if project_first else parts[-1]
    file_parts = parts[1:] if project_first else parts[:-1]
    result.set("project_name", project_part)
    for part in file_parts:
        active_file = _clean_active_file(part)
        if active_file:
            result.set("active_file", active_file)
            break
    return result


def resolve_vscode(ctx: WindowContext) -> ContextResult:
    """VS Code titles read `<file> — <project>`."""
    return _resolve_editor(ctx, project_first=False)


def resolve_antigravity(ctx: WindowContext) -> ContextResult:
    """Antigravity IDE titles read `<project> — <file>` — the reverse of VS Code."""
    return _resolve_editor(ctx, project_first=True)


def _resolve_browser(ctx: WindowContext, exposes_url: bool) -> ContextResult:
    result = resolve_generic(ctx)
    result.set("browser", ctx.app_name)
    if exposes_url and ctx.document_url and not result.project_path:
        parsed = urlparse(ctx.document_url)
        if parsed.scheme in ("http", "https"):
            result.set("url", ctx.document_url)
    return result


def resolve_chrome(ctx: WindowContext) -> ContextResult:
    """Chrome exposes the active tab's URL via AXDocument."""
    return _resolve_browser(ctx, exposes_url=True)


def resolve_firefox(ctx: WindowContext) -> ContextResult:
    """Firefox lists AXDocument but returns kAXErrorNoValue on read, so only the title is available. Confirmed
    live 2026-07-29 — the attribute being advertised is not evidence it has a value."""
    return _resolve_browser(ctx, exposes_url=False)


REGISTRY: Dict[str, Callable[[WindowContext], ContextResult]] = {
    VSCODE_BUNDLE_ID: resolve_vscode,
    ANTIGRAVITY_BUNDLE_ID: resolve_antigravity,
    CHROME_BUNDLE_ID: resolve_chrome,
    FIREFOX_BUNDLE_ID: resolve_firefox,
}


def resolver_for(bundle_id: str) -> Callable[[WindowContext], ContextResult]:
    return REGISTRY.get(bundle_id, resolve_generic)
