"""IDE extension process detection.

Tests avoid touching real processes by monkeypatching the proc helpers, and clear the
TTL cache between tests.
"""

import pytest

from tracker.context.ide_extension import find_ide_extension_tool
from tracker.tests.constants import CLAUDE_EXT_PATH


@pytest.fixture(autouse=True)
def _clear_cache():
    find_ide_extension_tool.cache_clear()
    yield
    find_ide_extension_tool.cache_clear()


def _comm(name):
    return name.encode()[:16].ljust(16, b"\x00")


class FakeInfo:
    def __init__(self, comm):
        self.pbi_comm = _comm(comm)


class FakeProcess:
    def __init__(self, pid, comm, exec_path=None, children=()):
        self.pid = pid
        self.comm = comm
        self.exec_path = exec_path
        self.children = list(children)


def install_tree(monkeypatch, processes):
    table = {p.pid: p for p in processes}

    def fake_bsd_info(pid):
        return FakeInfo(table[pid].comm) if pid in table else None

    def fake_child_pids(pid):
        return list(table[pid].children) if pid in table else []

    def fake_exec_path_and_argv(pid):
        if pid not in table:
            return None, []
        return table[pid].exec_path, []

    monkeypatch.setattr("tracker.context.ide_extension.bsd_info", fake_bsd_info)
    monkeypatch.setattr("tracker.context.ide_extension.child_pids", fake_child_pids)
    monkeypatch.setattr("tracker.context.ide_extension.exec_path_and_argv", fake_exec_path_and_argv)


def test_finds_claude_extension_binary(monkeypatch):
    install_tree(monkeypatch, [
        FakeProcess(100, "Code", children=[101, 102]),
        FakeProcess(101, "extensionHost", children=[200]),
        FakeProcess(200, "claude", CLAUDE_EXT_PATH),
        FakeProcess(102, "renderer"),
    ])
    assert find_ide_extension_tool(100) == "claude-code"


def test_cli_binary_in_terminal_is_not_an_extension(monkeypatch):
    """A homebrew claude CLI must not match the extension signature."""
    install_tree(monkeypatch, [
        FakeProcess(100, "Code", children=[200]),
        FakeProcess(200, "claude", "/opt/homebrew/bin/claude"),
    ])
    assert find_ide_extension_tool(100) is None


def test_matching_comm_without_signature_is_ignored(monkeypatch):
    """comm alone is not enough; the executable path must carry both signature substrings."""
    install_tree(monkeypatch, [
        FakeProcess(100, "Code", children=[200]),
        FakeProcess(200, "claude", "/tmp/native-binary/claude"),
    ])
    assert find_ide_extension_tool(100) is None


def test_unrelated_comm_skips_exec_path_read(monkeypatch):
    reads = []
    processes = [
        FakeProcess(100, "Code", children=[101, 102, 103]),
        FakeProcess(101, "renderer"),
        FakeProcess(102, "extensionHost"),
        FakeProcess(103, "languageServer"),
    ]
    table = {p.pid: p for p in processes}

    def fake_exec_path_and_argv(pid):
        reads.append(pid)
        return None, []

    monkeypatch.setattr("tracker.context.ide_extension.bsd_info", lambda pid: FakeInfo(table[pid].comm))
    monkeypatch.setattr("tracker.context.ide_extension.child_pids", lambda pid: list(table[pid].children))
    monkeypatch.setattr("tracker.context.ide_extension.exec_path_and_argv", fake_exec_path_and_argv)
    assert find_ide_extension_tool(100) is None
    assert reads == []


def test_skips_own_process(monkeypatch):
    """The tracker's own process must not be mistaken for an extension."""
    import os

    install_tree(monkeypatch, [
        FakeProcess(100, "Code", children=[os.getpid()]),
        FakeProcess(os.getpid(), "claude", CLAUDE_EXT_PATH),
    ])
    assert find_ide_extension_tool(100) is None


def test_result_cached_within_ttl(monkeypatch):
    import os

    import tracker.context.ide_extension as module

    call_count = [0]
    original_bsd_info = module.bsd_info

    def counting_bsd_info(pid):
        call_count[0] += 1
        if pid == os.getpid():
            return None
        return original_bsd_info(pid)

    monkeypatch.setattr(module.os, "getpid", lambda: 999999)
    monkeypatch.setattr(module, "bsd_info", counting_bsd_info)
    install_tree(monkeypatch, [
        FakeProcess(100, "Code", children=[200]),
        FakeProcess(200, "claude", CLAUDE_EXT_PATH),
    ])
    assert find_ide_extension_tool(100) == "claude-code"
    calls_after_first = call_count[0]
    assert find_ide_extension_tool(100) == "claude-code"
    assert call_count[0] == calls_after_first
