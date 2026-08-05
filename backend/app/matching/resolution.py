"""Resolves a local project path to its remote project identity, per source.

This is the one part of the matching pipeline that touches the outside world
-- the filesystem (reading .git/config) and the database (project_mappings
lookups) -- so it's kept deliberately separate from matcher.py, which must
stay pure. Nothing in here should be imported by matcher.py, and nothing
in matcher.py should import from here.
"""

import configparser
import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.matching.constants import GITHUB_HOSTS
from app.matching.models import ProjectMapping

URL_LIKE_REMOTE = re.compile(r"^(?:ssh|https?)://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+)$")
SCP_LIKE_REMOTE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^/:]+):(?P<path>.+)$")


def _extract_host_and_path(url: str) -> tuple[Optional[str], Optional[str]]:
    match = URL_LIKE_REMOTE.match(url) or SCP_LIKE_REMOTE.match(url)
    if not match:
        return None, None
    return match.group("host"), match.group("path")


def _parse_github_identity(url: str) -> Optional[str]:
    """Normalize a GitHub remote URL (SSH or HTTPS) to an "owner/repo" string.

    Both `git@github.com:owner/repo.git` and `https://github.com/owner/repo.git`
    point at the same repository and must produce the exact same identity --
    otherwise a remote event fetched by one auth style would never match a
    local block resolved from a clone using the other style. Anything that
    isn't a recognizable github.com remote (wrong host, wrong shape, deep
    link instead of a repo root) returns None rather than a partial guess.
    """

    host, path = _extract_host_and_path(url.strip())
    if host is None or host.lower() not in GITHUB_HOSTS:
        return None

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]

    parts = path.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return f"{parts[0]}/{parts[1]}"


def _find_git_root(start: Path) -> Optional[Path]:
    """Walk upward from `start` through parent directories until one contains
    a `.git` entry, or the filesystem root is reached with none found.

    The path a local block records is whatever directory the tracker saw as
    active -- often a subfolder inside a repo (e.g. `backend/`), not the repo
    root, since people work inside subfolders all the time. Only the actual
    root has `.git`, so this climbs up looking for it. It only ever climbs
    up, never down or sideways -- a `.git` inside some unrelated child
    directory doesn't belong to the repo actually being worked in.
    """

    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _resolve_git_common_dir(git_root: Path) -> Optional[Path]:
    """Resolve the actual git directory holding `config` (and thus the
    origin remote) for `git_root`.

    Ordinarily `git_root / ".git"` is that directory directly. But in a git
    worktree or a submodule, `.git` is a *file* containing a single
    `gitdir: <path>` line pointing elsewhere -- a private per-worktree (or
    per-submodule) git directory. For a worktree, that private directory
    does NOT itself hold `config` (worktrees intentionally don't duplicate
    the origin remote per-worktree); it holds a `commondir` file pointing
    back to the main repository's real git directory, which is where
    `config` actually lives. A submodule's private directory has no
    `commondir` file and keeps a full, independent git directory --
    `config` included -- so the private directory itself is already
    correct for that case.
    """

    git_entry = git_root / ".git"
    if git_entry.is_dir():
        return git_entry

    if not git_entry.is_file():
        return None

    try:
        content = git_entry.read_text()
    except OSError:
        return None

    line = content.strip()
    if not line.startswith("gitdir:"):
        return None

    gitdir = Path(line[len("gitdir:") :].strip())
    if not gitdir.is_absolute():
        gitdir = (git_root / gitdir).resolve()

    commondir_file = gitdir / "commondir"
    if not commondir_file.is_file():
        return gitdir

    try:
        common_value = commondir_file.read_text().strip()
    except OSError:
        return gitdir

    common_dir = Path(common_value)
    if not common_dir.is_absolute():
        common_dir = (gitdir / common_dir).resolve()
    return common_dir


def _read_origin_url(git_root: Path) -> Optional[str]:
    git_dir = _resolve_git_common_dir(git_root)
    if git_dir is None:
        return None

    config_path = git_dir / "config"
    if not config_path.is_file():
        return None

    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read(config_path)
    except configparser.Error:
        return None

    section = 'remote "origin"'
    if not parser.has_section(section) or not parser.has_option(section, "url"):
        return None
    return parser.get(section, "url")


def resolve_github_identity(project_path: str) -> Optional[str]:
    """Resolve a local project path to its GitHub "owner/repo" identity, by
    walking up to the repo root and reading its origin remote -- or None if
    the path isn't inside a git repo, has no origin configured, or the
    origin isn't a recognizable GitHub remote. Never guesses.
    """

    path_obj = Path(project_path)
    if ".." in path_obj.parts:
        return None

    try:
        resolved_path = path_obj.resolve(strict=False)
    except (ValueError, RuntimeError):
        return None

    git_root = _find_git_root(resolved_path)
    if git_root is None:
        return None

    origin_url = _read_origin_url(git_root)
    if origin_url is None:
        return None

    return _parse_github_identity(origin_url)


def resolve_mapped_identity(db: Session, user_id: int, local_project: str, source: str) -> Optional[str]:
    """Look up a user's manually-configured remote project mapping, for
    sources (Jira, Slack) with nothing on disk that identifies which remote
    project a local folder belongs to. Returns None if no mapping has been
    configured yet -- never guesses.
    """

    mapping = (
        db.query(ProjectMapping)
        .filter(
            ProjectMapping.user_id == user_id,
            ProjectMapping.local_project == local_project,
            ProjectMapping.source == source,
        )
        .first()
    )
    return mapping.remote_project_id if mapping else None


def resolve_project_identities(db: Session, user_id: int, project_path: str) -> dict[str, Optional[str]]:
    """Resolve a local project path to its remote identity for every source
    the matching step cares about. Each value is independently None if that
    source's identity couldn't be resolved -- a miss on one source never
    blocks resolution of the others.
    """

    return {
        "github": resolve_github_identity(project_path),
        "jira": resolve_mapped_identity(db, user_id, project_path, "jira"),
        "slack": resolve_mapped_identity(db, user_id, project_path, "slack"),
    }
