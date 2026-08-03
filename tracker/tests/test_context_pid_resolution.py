"""Coverage for the real pid -> AX -> project_path path.

Every other resolver test bypasses the Accessibility read entirely by passing document_url= directly, so a
bug in how resolve_context wires the AX layer's return value into WindowContext.document_url — e.g. the
project_path confusion this branch's investigation turned up — could pass all of them unnoticed. These tests
only mock the AX layer itself; project_path/git_branch derivation runs against a real temporary git repo.
"""

import subprocess

import pytest

import tracker.context.ax as ax_module
from tracker.context import resolve_context
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


class TestPidResolvesThroughAxToProjectPath:
    def test_real_pid_reaches_ax_and_resolves_project_path(self, repo, monkeypatch):
        target = repo / "file.txt"
        calls = []

        def fake_focused_document_url(pid):
            calls.append(pid)
            return f"file://{target}"

        monkeypatch.setattr(ax_module, "focused_document_url", fake_focused_document_url)

        result = resolve_context(VSCODE_BUNDLE_ID, "Code", "file.txt — proj", pid=4242)

        assert calls == [4242]
        assert result.project_path == str(repo.resolve())
        assert result.detail["git_branch"] == "main"

    def test_no_pid_never_calls_ax(self, monkeypatch):
        def fail(pid):
            raise AssertionError("AXDocument was read without a pid")

        monkeypatch.setattr(ax_module, "focused_document_url", fail)

        result = resolve_context(VSCODE_BUNDLE_ID, "Code", "logline")

        assert result.project_path is None

    def test_ax_returning_none_yields_no_project_path(self, monkeypatch):
        """A window with no document (e.g. a New Tab) reports None, not an error."""
        monkeypatch.setattr(ax_module, "focused_document_url", lambda pid: None)

        result = resolve_context(VSCODE_BUNDLE_ID, "Code", "logline", pid=99)

        assert result.project_path is None
