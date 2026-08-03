"""Regression tests for `.git/HEAD` being untrusted input.

Pre-existing issue, not introduced with terminal detection: a `.git` directory travels inside any tarball, zip
or copied tree, so HEAD's contents are attacker-controlled. Before validation, a crafted HEAD yielded an
unbounded, multi-line "branch name" that flowed into `context_detail` for every resolver that records a branch.
"""

import os

import pytest

from tracker.constants import GIT_BRANCH_MAX_LENGTH
from tracker.context.git import current_branch


def make_repo(tmp_path, head_contents):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_bytes(head_contents)
    return repo


def test_well_formed_head_still_resolves(tmp_path):
    assert current_branch(make_repo(tmp_path, b"ref: refs/heads/main\n")) == "main"


@pytest.mark.parametrize("branch", ["feature/terminal-detection", "toheed/feature/x", "release-1.2.3", "fix_bug"])
def test_realistic_branch_names_survive_validation(tmp_path, branch):
    repo = make_repo(tmp_path, ("ref: refs/heads/%s\n" % branch).encode())
    assert current_branch(repo) == branch


def test_trailing_payload_after_the_ref_is_dropped(tmp_path):
    """The exact confirmed exploit: text after the ref line previously became part of the branch name."""
    repo = make_repo(tmp_path, b"ref: refs/heads/pwned\nwindow_title_injection: SECRET\n")
    assert current_branch(repo) == "pwned"


def test_oversized_branch_name_is_rejected(tmp_path):
    """A 10KB HEAD previously produced a 10,007-character branch name."""
    repo = make_repo(tmp_path, b"ref: refs/heads/" + b"A" * 5000 + b"\nmore: " + b"B" * 5000)
    assert current_branch(repo) is None


def test_branch_name_at_the_length_cap_is_kept(tmp_path):
    name = "a" * GIT_BRANCH_MAX_LENGTH
    assert current_branch(make_repo(tmp_path, ("ref: refs/heads/%s\n" % name).encode())) == name


@pytest.mark.parametrize("payload", [
    b"ref: refs/heads/a\x00b\n",
    b"ref: refs/heads/a\x1bb\n",
    b"ref: refs/heads/has space\n",
    b"ref: refs/heads/a~b\n",
    b"ref: refs/heads/a^b\n",
    b"ref: refs/heads/a:b\n",
    b"ref: refs/heads/a?b\n",
    b"ref: refs/heads/a*b\n",
    b"ref: refs/heads/a[b\n",
    b"ref: refs/heads/a\\b\n",
    b"ref: refs/heads/a..b\n",
    b"ref: refs/heads/a//b\n",
    b"ref: refs/heads/a@{b\n",
    b"ref: refs/heads/.hidden\n",
    b"ref: refs/heads/trailing.\n",
    b"ref: refs/heads/branch.lock\n",
    b"ref: refs/heads/-leading-dash\n",
    b"ref: refs/heads/\n",
    b"ref: refs/heads//\n",
])
def test_malformed_refs_are_rejected(tmp_path, payload):
    assert current_branch(make_repo(tmp_path, payload)) is None


def test_detached_head_is_not_a_branch(tmp_path):
    repo = make_repo(tmp_path, b"9c1f4a2b3d4e5f60718293a4b5c6d7e8f9012345\n")
    assert current_branch(repo) is None


def test_undecodable_head_does_not_raise(tmp_path):
    assert current_branch(make_repo(tmp_path, b"ref: refs/heads/\xff\xfe\x00bad")) is None


def test_head_fifo_is_rejected_without_blocking(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    os.mkfifo(repo / ".git" / "HEAD")
    assert current_branch(repo) is None


def test_head_symlink_to_special_file_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").symlink_to("/dev/zero")
    assert current_branch(repo) is None


def test_sparse_head_over_size_cap_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    head = repo / ".git" / "HEAD"
    with head.open("wb") as handle:
        handle.seek(1024 * 1024)
        handle.write(b"x")
    assert current_branch(repo) is None


def test_gitdir_pointer_fifo_is_rejected_without_blocking(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    os.mkfifo(repo / ".git")
    assert current_branch(repo) is None


def test_missing_head_returns_none(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert current_branch(repo) is None


def test_at_sign_branch_name_is_valid(tmp_path):
    """@ is a legitimate git branch name and must not be rejected as a ref-sequence sentinel."""
    assert current_branch(make_repo(tmp_path, b"ref: refs/heads/@\n")) == "@"
