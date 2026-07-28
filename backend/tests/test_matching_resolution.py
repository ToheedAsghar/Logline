"""
Tests for the project-identity resolution step (app/matching/resolution.py) --
the one part of the matching pipeline that touches the filesystem and the
database.

resolve_github_identity is tested against real temporary git repositories
(subprocess `git init` + `git remote add origin ...`), not mocked away,
since what's actually being verified is real filesystem/config-parsing
behavior: walking upward from a subfolder to find the repo root, and
normalizing both SSH-style and HTTPS-style remote URLs to the same identity.

resolve_mapped_identity is tested against the real Postgres database (same
DB the app runs against), covering both the found and not-found cases.
"""

import subprocess
from pathlib import Path

import pytest

from app.db.session import SessionLocal
from app.matching.models import ProjectMapping
from app.matching.resolution import resolve_github_identity, resolve_mapped_identity
from app.auth.models import User

REPO_IDENTITY = "ToheedAsghar/Logline"
SSH_REMOTE = "git@github.com:ToheedAsghar/Logline.git"
HTTPS_REMOTE = "https://github.com/ToheedAsghar/Logline.git"


def _init_repo(root: Path, remote_url: str | None = None) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    if remote_url is not None:
        subprocess.run(
            ["git", "-C", str(root), "remote", "add", "origin", remote_url], check=True, capture_output=True
        )


class TestGitHubIdentityRootAndSubfolders:
    def test_project_path_is_repo_root(self, tmp_path):
        _init_repo(tmp_path, SSH_REMOTE)

        assert resolve_github_identity(str(tmp_path)) == REPO_IDENTITY

    def test_project_path_is_subfolder_one_level_deep(self, tmp_path):
        _init_repo(tmp_path, SSH_REMOTE)
        subfolder = tmp_path / "backend"
        subfolder.mkdir()

        assert resolve_github_identity(str(subfolder)) == REPO_IDENTITY

    def test_project_path_is_subfolder_two_levels_deep(self, tmp_path):
        """Confirms the upward walk doesn't stop too early -- it must keep
        climbing past the first parent, not just check one level up."""
        _init_repo(tmp_path, SSH_REMOTE)
        subfolder = tmp_path / "backend" / "app"
        subfolder.mkdir(parents=True)

        assert resolve_github_identity(str(subfolder)) == REPO_IDENTITY


class TestRemoteUrlFormats:
    def test_ssh_style_remote_resolves(self, tmp_path):
        _init_repo(tmp_path, SSH_REMOTE)

        assert resolve_github_identity(str(tmp_path)) == REPO_IDENTITY

    def test_https_style_remote_resolves(self, tmp_path):
        _init_repo(tmp_path, HTTPS_REMOTE)

        assert resolve_github_identity(str(tmp_path)) == REPO_IDENTITY

    def test_ssh_and_https_normalize_to_the_same_identity(self, tmp_path):
        """Both remote styles must produce the exact same identity string --
        otherwise matching against remote_events' remote_project_id would
        silently fail depending on which URL style a given clone used."""
        ssh_repo = tmp_path / "ssh-clone"
        ssh_repo.mkdir()
        _init_repo(ssh_repo, SSH_REMOTE)

        https_repo = tmp_path / "https-clone"
        https_repo.mkdir()
        _init_repo(https_repo, HTTPS_REMOTE)

        ssh_identity = resolve_github_identity(str(ssh_repo))
        https_identity = resolve_github_identity(str(https_repo))

        assert ssh_identity == https_identity == REPO_IDENTITY


class TestGitWorktree:
    def test_worktree_resolves_origin_from_main_repos_common_git_dir(self, tmp_path):
        """In a real git worktree, `.git` inside the worktree is a *file*
        (`gitdir: <path>`), not a directory, and the worktree's own private
        git directory has no `config`/origin of its own -- it points back
        to the main repo's common git dir via a `commondir` file. Confirms
        _read_origin_url follows that chain instead of silently returning
        None (indistinguishable from "not a git repo") the way a naive
        `git_root / ".git" / "config"` lookup would."""
        main_repo = tmp_path / "main"
        _init_repo(main_repo, SSH_REMOTE)
        subprocess.run(
            ["git", "-C", str(main_repo), "-c", "user.email=test@test.com", "-c", "user.name=test",
             "commit", "--allow-empty", "-m", "init", "--quiet"],
            check=True, capture_output=True,
        )

        worktree_path = tmp_path / "worktree"
        subprocess.run(
            ["git", "-C", str(main_repo), "worktree", "add", str(worktree_path), "-b", "feature-branch", "--quiet"],
            check=True, capture_output=True,
        )

        assert (worktree_path / ".git").is_file()
        assert resolve_github_identity(str(worktree_path)) == REPO_IDENTITY
        assert resolve_github_identity(str(worktree_path)) == resolve_github_identity(str(main_repo))


class TestNoResolutionCases:
    def test_no_git_anywhere_in_parent_chain_returns_none(self, tmp_path):
        """A folder with no .git anywhere up to the filesystem root must
        return None cleanly -- no error, no infinite loop. tmp_path is
        rooted under the OS temp directory, which is not inside any git
        repository on this machine, so the walk genuinely reaches the
        filesystem root before finding anything."""
        lonely_folder = tmp_path / "not-a-repo"
        lonely_folder.mkdir()

        assert resolve_github_identity(str(lonely_folder)) is None

    def test_git_config_with_no_origin_remote_returns_none(self, tmp_path):
        """A fresh local-only repo that was never pushed anywhere has a
        .git/config with no [remote "origin"] section at all."""
        _init_repo(tmp_path, remote_url=None)

        assert resolve_github_identity(str(tmp_path)) is None

    def test_non_github_remote_returns_none(self, tmp_path):
        _init_repo(tmp_path, "git@gitlab.com:someone/somerepo.git")

        assert resolve_github_identity(str(tmp_path)) is None


TEST_EMAIL = "matching-resolution-test@example.com"


@pytest.fixture
def real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(ProjectMapping).filter(ProjectMapping.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(ProjectMapping).filter(ProjectMapping.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestMappedIdentityLookup:
    def test_configured_mapping_is_found(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                ProjectMapping(
                    user_id=real_db_user,
                    local_project="/Users/dev/logline",
                    source="jira",
                    remote_project_id="LOG",
                )
            )
            db.commit()
        finally:
            db.close()

        db = SessionLocal()
        try:
            identity = resolve_mapped_identity(db, real_db_user, "/Users/dev/logline", "jira")
        finally:
            db.close()

        assert identity == "LOG"

    def test_no_configured_mapping_returns_none(self, real_db_user):
        db = SessionLocal()
        try:
            identity = resolve_mapped_identity(db, real_db_user, "/Users/dev/unmapped-project", "slack")
        finally:
            db.close()

        assert identity is None
