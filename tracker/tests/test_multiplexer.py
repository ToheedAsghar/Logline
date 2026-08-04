"""Terminal multiplexer context resolution.

These tests avoid calling real tmux or scanning the real /dev tree by monkeypatching the
subprocess and filesystem helpers.
"""

import os
import subprocess
from pathlib import Path

import pytest

from tracker.context.models import TerminalToolContext
from tracker.context.multiplexer import (
    _multiplexer_name, _resolve_tmux, _run_tmux, _tmux_client_session, _tmux_executable, _tty_path, resolve_multiplexer,
)


@pytest.fixture(autouse=True)
def _clear_tmux_executable_cache():
    """The executable path is cached for the lifetime of the process; reset it between tests."""
    import tracker.context.multiplexer as mux
    mux._tmux_executable_cache = None
    yield
    mux._tmux_executable_cache = None


@pytest.fixture
def fake_tty_devices(monkeypatch, tmp_path):
    """Replace /dev with a temp dir containing a few fake tty entries."""
    (tmp_path / "ttys001").write_text("")
    (tmp_path / "ttys002").write_text("")
    (tmp_path / "notatty").write_text("")

    class FakeStat:
        def __init__(self, rdev):
            self.st_rdev = rdev

    def fake_stat(path):
        if path == "/dev/ttys001":
            return FakeStat(0x1001)
        if path == "/dev/ttys002":
            return FakeStat(0x1002)
        return os.stat(path)

    monkeypatch.setattr("tracker.context.multiplexer.os.listdir", lambda path: ["ttys001", "ttys002", "notatty"])
    monkeypatch.setattr("tracker.context.multiplexer.os.stat", fake_stat)
    return tmp_path


@pytest.fixture
def no_git(monkeypatch):
    """Ensure git helpers do not depend on the test-machine filesystem."""
    monkeypatch.setattr("tracker.context.multiplexer.find_project_root", lambda path: None)
    monkeypatch.setattr("tracker.context.multiplexer.current_branch", lambda path: None)


@pytest.fixture
def logline_git(monkeypatch):
    """Pretend the cwd is inside the logline repo."""
    monkeypatch.setattr("tracker.context.multiplexer.find_project_root", lambda path: Path("/Users/dev/project"))
    monkeypatch.setattr("tracker.context.multiplexer.current_branch", lambda path: "main")


def test_tty_path_maps_device_to_name(fake_tty_devices):
    assert _tty_path(0x1001) == "/dev/ttys001"
    assert _tty_path(0x1002) == "/dev/ttys002"
    assert _tty_path(0x9999) is None
    assert _tty_path(0xFFFFFFFF) is None


def test_tmux_executable_prefers_known_paths(monkeypatch, tmp_path):
    existing = tmp_path / "tmux"
    existing.write_text("#!/bin/sh\n")
    existing.chmod(0o755)
    monkeypatch.setattr("tracker.context.multiplexer.shutil.which", lambda name: None)
    monkeypatch.setattr("tracker.context.multiplexer.TMUX_CANDIDATES", (str(existing),))
    assert _tmux_executable() == str(existing)


def test_tmux_executable_falls_back_to_path(monkeypatch, tmp_path):
    path_tmux = tmp_path / "tmux"
    path_tmux.write_text("#!/bin/sh\n")
    path_tmux.chmod(0o755)

    def fake_which(name):
        return str(path_tmux) if name == "tmux" else None

    monkeypatch.setattr("tracker.context.multiplexer.shutil.which", fake_which)
    monkeypatch.setattr("tracker.context.multiplexer.TMUX_CANDIDATES", ())
    assert _tmux_executable() == str(path_tmux)


def test_tmux_executable_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr("tracker.context.multiplexer.shutil.which", lambda name: None)
    monkeypatch.setattr("tracker.context.multiplexer.TMUX_CANDIDATES", ())
    assert _tmux_executable() is None


def test_run_tmux_returns_stdout(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        class Result:
            returncode = 0
            stdout = " ".join(args[1:]) + "\n"
        calls.append(args)
        return Result()

    monkeypatch.setattr("tracker.context.multiplexer._tmux_executable", lambda: "/opt/homebrew/bin/tmux")
    monkeypatch.setattr("tracker.context.multiplexer.subprocess.run", fake_run)
    assert _run_tmux(["list-clients"]) == "list-clients"
    assert calls == [["/opt/homebrew/bin/tmux", "list-clients"]]


def test_run_tmux_returns_none_on_failure(monkeypatch):
    def fake_run(args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
        return Result()

    monkeypatch.setattr("tracker.context.multiplexer.subprocess.run", fake_run)
    assert _run_tmux(["list-clients"]) is None


def test_run_tmux_returns_none_on_timeout(monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=1.0)

    monkeypatch.setattr("tracker.context.multiplexer.subprocess.run", fake_run)
    assert _run_tmux(["list-clients"]) is None


def test_run_tmux_returns_none_on_oserror(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", args[0])

    monkeypatch.setattr("tracker.context.multiplexer.subprocess.run", fake_run)
    assert _run_tmux(["list-clients"]) is None


def test_run_tmux_returns_none_when_executable_not_found(monkeypatch):
    monkeypatch.setattr("tracker.context.multiplexer._tmux_executable", lambda: None)
    assert _run_tmux(["list-clients"]) is None


def test_tmux_client_session_matches_tty(monkeypatch):
    monkeypatch.setattr(
        "tracker.context.multiplexer._run_tmux",
        lambda args: "/dev/ttys001\tsession-a\n/dev/ttys002\tsession-b",
    )
    assert _tmux_client_session("/dev/ttys001") == "session-a"
    assert _tmux_client_session("/dev/ttys002") == "session-b"
    assert _tmux_client_session("/dev/ttys003") is None


def test_resolve_tmux_full_flow(monkeypatch, logline_git):
    monkeypatch.setattr("tracker.context.multiplexer._tty_path", lambda dev: "/dev/ttys001" if dev == 0x1001 else None)
    monkeypatch.setattr("tracker.context.multiplexer._tmux_client_session", lambda tty: "session-a")
    monkeypatch.setattr(
        "tracker.context.multiplexer._run_tmux",
        lambda args: "/Users/dev/project\topencode" if args[0] == "display-message" else None,
    )
    detected = _resolve_tmux(0x1001)
    assert detected == TerminalToolContext(tool="opencode", cwd="/Users/dev/project", branch="main")


def test_resolve_tmux_reports_shell_with_no_tool(monkeypatch, no_git):
    monkeypatch.setattr("tracker.context.multiplexer._tty_path", lambda dev: "/dev/ttys001" if dev == 0x1001 else None)
    monkeypatch.setattr("tracker.context.multiplexer._tmux_client_session", lambda tty: "session-a")
    monkeypatch.setattr(
        "tracker.context.multiplexer._run_tmux",
        lambda args: "/Users/dev/project\t-zsh" if args[0] == "display-message" else None,
    )
    detected = _resolve_tmux(0x1001)
    assert detected is not None
    assert detected.tool is None
    assert detected.cwd == "/Users/dev/project"


def test_resolve_tmux_returns_none_on_malformed_output(monkeypatch, no_git):
    monkeypatch.setattr("tracker.context.multiplexer._tty_path", lambda dev: "/dev/ttys001" if dev == 0x1001 else None)
    monkeypatch.setattr("tracker.context.multiplexer._tmux_client_session", lambda tty: "session-a")
    monkeypatch.setattr(
        "tracker.context.multiplexer._run_tmux",
        lambda args: "no-tab-character" if args[0] == "display-message" else None,
    )
    assert _resolve_tmux(0x1001) is None


def test_resolve_tmux_returns_none_when_command_fails(monkeypatch):
    monkeypatch.setattr("tracker.context.multiplexer._tty_path", lambda dev: "/dev/ttys001" if dev == 0x1001 else None)
    monkeypatch.setattr("tracker.context.multiplexer._tmux_client_session", lambda tty: "session-a")
    monkeypatch.setattr("tracker.context.multiplexer._run_tmux", lambda args: None)
    assert _resolve_tmux(0x1001) is None


def test_resolve_multiplexer_dispatches_tmux(monkeypatch):
    monkeypatch.setattr(
        "tracker.context.multiplexer._resolve_tmux",
        lambda dev: TerminalToolContext(tool=None, cwd="/Users/dev/project", branch=None),
    )
    detected = resolve_multiplexer(["tmux"], 0x1001)
    assert detected is not None
    assert detected.cwd == "/Users/dev/project"


def test_resolve_multiplexer_returns_none_for_unsupported(monkeypatch):
    assert resolve_multiplexer(["screen"], 0x1001) is None


def test_resolve_multiplexer_rescues_exceptions(monkeypatch):
    def boom(dev):
        raise KeyError("simulated")

    monkeypatch.setattr("tracker.context.multiplexer._resolve_tmux", boom)
    assert resolve_multiplexer(["tmux"], 0x1001) is None


def test_multiplexer_name_selects_known_name():
    assert _multiplexer_name(["tmux", "zsh"]) == "tmux"
    assert _multiplexer_name(["zsh"]) is None
