"""Read the project root and current git branch from the filesystem.

Read the branch while the session is active. It may be different by the time the session is reviewed or synced.
This module does not find the repository's owner or name. The backend's `resolve_github_identity(project_path)`
does that later.
"""

import os
import stat
from pathlib import Path
from typing import Optional, TypeVar

from tracker.constants import GIT_BRANCH_MAX_LENGTH
from tracker.context.cache import ttl_cache

T = TypeVar("T")

FORBIDDEN_BRANCH_CHARACTERS = set(" ~^:?*[\\\x7f")
GIT_FILE_MAX_BYTES = 4096

_ttl_cache = ttl_cache


def _is_valid_branch_name(ref: str) -> bool:
    """Return whether `ref` follows git's branch-name rules.

    `.git/HEAD` is a plain file, so its contents cannot be treated as trusted. Without this check, crafted content
    could become a long, multi-line branch name in the database and sync data. Checking it here protects every
    resolver that uses the branch.
    """
    if not ref or len(ref) > GIT_BRANCH_MAX_LENGTH:
        return False
    if any(char in FORBIDDEN_BRANCH_CHARACTERS or ord(char) < 0x20 for char in ref):
        return False
    if ref.startswith("/") or ref.endswith("/") or ref.startswith("-") or ref.endswith("."):
        return False
    if ".." in ref or "//" in ref or "@{" in ref:
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock") for part in ref.split("/"))


def _read_git_file(path: Path) -> Optional[str]:
    """Read a small regular git file, or return None when it is unsafe or unreadable.

    Open without following symlinks and without blocking on special files. Check the file type and size again
    after opening, because the path could change between the first check and the open.
    """
    fd = None
    try:
        path_info = path.stat()
        if not stat.S_ISREG(path_info.st_mode) or path_info.st_size > GIT_FILE_MAX_BYTES:
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > GIT_FILE_MAX_BYTES:
            return None
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = None
            return handle.read()
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


@_ttl_cache(ttl_seconds=60.0)
def find_project_root(path: Path) -> Optional[Path]:
    """Walk up from `path` to the nearest directory containing a `.git` entry, or return None.

    Cached for 60 seconds. A newly-created repository may not be detected until the cache entry
    for that path expires; use `find_project_root.cache_clear()` if you need to force a refresh.
    """
    current = path if path.is_dir() else path.parent
    try:
        current = current.resolve()
    except OSError:
        return None
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _git_dir(project_root: Path) -> Optional[Path]:
    """Return the git directory whose HEAD describes the checkout at `project_root`.

    Do not follow `commondir` as the backend's `_resolve_git_common_dir` does. That helper is right for reading
    `config`, but a linked worktree has its own branch. Following `commondir` would report the main worktree's
    branch instead.
    """
    entry = project_root / ".git"
    if entry.is_dir():
        return entry
    if not entry.is_file():
        return None
    content = _read_git_file(entry)
    if content is None:
        return None
    content = content.strip()
    if not content.startswith("gitdir:"):
        return None
    gitdir = Path(content[len("gitdir:") :].strip())
    if not gitdir.is_absolute():
        gitdir = (project_root / gitdir).resolve()
    return gitdir


@_ttl_cache(ttl_seconds=10.0)
def current_branch(project_root: Path) -> Optional[str]:
    """Read the checked-out branch from HEAD, or return None if it is detached, unreadable, or invalid.

    Never guess or return unchecked file content. Cached for 10 seconds because the branch is polled
    on every title/context poll but changes far less often. Use `current_branch.cache_clear()` to
    force a refresh.
    """
    git_dir = _git_dir(project_root)
    if git_dir is None:
        return None
    head = _read_git_file(git_dir / "HEAD")
    if head is None:
        return None
    head = head.strip()
    if not head.startswith("ref:"):
        return None
    ref_content = head[len("ref:") :]
    ref_line = ref_content.splitlines()[0].strip() if ref_content.strip() else ""
    branch_prefix = "refs/heads/"
    branch_name = ref_line[len(branch_prefix) :] if ref_line.startswith(branch_prefix) else ref_line
    return branch_name if _is_valid_branch_name(branch_name) else None
