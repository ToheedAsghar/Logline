"""Git branch/root resolution, tested against real temporary git repositories rather than mocks — the
worktree behaviour these guard is exactly what mocks would paper over."""

import subprocess

import pytest

from tracker.context import resolve_context
from tracker.context.git import current_branch, find_project_root
from tracker.context.resolvers import VSCODE_BUNDLE_ID


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "file.txt").write_text("hi")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


class TestProjectRoot:
    def test_finds_root_from_nested_file(self, repo):
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)
        target = nested / "deep.py"
        target.write_text("")
        assert find_project_root(target) == repo.resolve()

    def test_returns_none_outside_repo(self, tmp_path):
        lonely = tmp_path / "lonely"
        lonely.mkdir()
        assert find_project_root(lonely) is None


class TestCurrentBranch:
    def test_reads_branch(self, repo):
        assert current_branch(repo) == "main"

    def test_reads_slashed_branch_name(self, repo):
        _git(repo, "checkout", "-b", "toheed/feature/rich-context")
        assert current_branch(repo) == "toheed/feature/rich-context"

    def test_detached_head_returns_none(self, repo):
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
        ).stdout.strip()
        _git(repo, "checkout", sha)
        assert current_branch(repo) is None

    def test_non_repo_returns_none(self, tmp_path):
        assert current_branch(tmp_path) is None

    def test_linked_worktree_reports_its_own_branch(self, repo, tmp_path):
        """The reason this deliberately avoids the backend's common-dir-following helper: that would follow to
        the main repo and report *its* branch, not the worktree's."""
        worktree = tmp_path / "wt"
        _git(repo, "worktree", "add", "-b", "side-branch", str(worktree))
        assert current_branch(worktree) == "side-branch"
        assert current_branch(repo) == "main"


class TestProjectPathFromDocument:
    def test_derives_project_path_and_branch_from_file_url(self, repo):
        target = repo / "file.txt"
        result = resolve_context(
            VSCODE_BUNDLE_ID, "Code", "file.txt — proj", document_url=f"file://{target}"
        )
        assert result.project_path == str(repo.resolve())
        assert result.detail["git_branch"] == "main"

    def test_percent_encoded_path_decoded(self, tmp_path):
        root = tmp_path / "my proj"
        root.mkdir()
        _git(root, "init", "-b", "main")
        target = root / "a.py"
        target.write_text("")
        result = resolve_context(
            VSCODE_BUNDLE_ID, "Code", "a.py — my proj", document_url=f"file://{str(target).replace(' ', '%20')}"
        )
        assert result.project_path == str(root.resolve())

    def test_empty_document_url_yields_no_project_path(self):
        """Editors report an empty AXDocument when the focused tab isn't a file."""
        result = resolve_context(VSCODE_BUNDLE_ID, "Code", "Claude Code — logline", document_url="")
        assert result.project_path is None

    def test_path_outside_repo_yields_no_project_path(self, tmp_path):
        target = tmp_path / "loose.txt"
        target.write_text("")
        result = resolve_context(VSCODE_BUNDLE_ID, "Code", "loose.txt", document_url=f"file://{target}")
        assert result.project_path is None
