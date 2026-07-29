"""Project root and git branch, read straight off the filesystem at capture time.

The branch is captured live because it is unrecoverable later: by the time a session is reviewed or synced,
the worktree may be on a different branch entirely. Repo identity (owner/repo) is deliberately NOT derived
here — the backend's `resolve_github_identity(project_path)` already does that at the matching stage.
"""

from pathlib import Path
from typing import Optional


def find_project_root(path: Path) -> Optional[Path]:
    """Walks up from `path` to the nearest directory containing a `.git` entry, or None if there isn't one."""
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
    """Resolves the git directory whose HEAD reflects what `project_root` actually has checked out.

    Deliberately does NOT follow `commondir` the way the backend's `_resolve_git_common_dir` does. That helper
    is correct for reading `config` (worktrees don't duplicate the origin remote), but the main repo's HEAD
    names the *main* worktree's branch — following it would report the wrong branch for a linked worktree.
    """
    entry = project_root / ".git"
    if entry.is_dir():
        return entry
    if not entry.is_file():
        return None
    try:
        content = entry.read_text().strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = Path(content[len("gitdir:") :].strip())
    if not gitdir.is_absolute():
        gitdir = (project_root / gitdir).resolve()
    return gitdir


def current_branch(project_root: Path) -> Optional[str]:
    """Reads the checked-out branch name from HEAD. Returns None when detached, unreadable, or not a repo —
    never guesses."""
    git_dir = _git_dir(project_root)
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text().strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return None  # detached HEAD holds a bare sha, which is not a branch name
    ref = head[len("ref:") :].strip()
    if ref.startswith("refs/heads/"):
        ref = ref[len("refs/heads/") :]
    return ref or None
