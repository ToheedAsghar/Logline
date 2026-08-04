"""Terminal dev-tool detection: registry matching, fail-closed fallbacks, and the no-title structural guarantee.

Process signatures here are real ones captured from live processes on macOS (Ghostty running codex/opencode,
Terminal.app running tmux, and a Python-shebang script standing in for aider's install shape).
"""

import dataclasses
import typing

import pytest

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS, PROC_WALK_MAX_PIDS, TERMINAL_TOOL_REGISTRY
from tracker.context import resolve_context
from tracker.context.models import TerminalToolContext
from tracker.context.terminal import _candidate_names, _foreground_processes, _match_tool, resolve_terminal_tool

# (exec_path, argv) exactly as sysctl(KERN_PROCARGS2) reported them for real running processes.
REAL_SIGNATURES = {
    "codex": ("/opt/homebrew/bin/codex", ["codex"]),
    "opencode": ("/Users/toheed.asghar/.opencode/bin/opencode", ["opencode"]),
    "claude-code": (
        "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
        ["/opt/homebrew/bin/claude"],
    ),
    # Captured from a Python-shebang script: the kernel reports the interpreter, tool is only in argv[1].
    "aider": (
        "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/Resources/"
        "Python.app/Contents/MacOS/Python",
        [
            "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/Resources/"
            "Python.app/Contents/MacOS/Python",
            "/Users/toheed.asghar/.local/bin/aider",
        ],
    ),
    "gemini-cli": ("/opt/homebrew/bin/node", ["node", "/opt/homebrew/bin/gemini", "--model", "pro"]),
}

TMUX_SIGNATURE = ("/opt/homebrew/bin/tmux", ["tmux"])
SHELL_SIGNATURE = ("/bin/zsh", ["-/bin/zsh"])


class FakeProcess:
    """One node in a synthetic process tree, standing in for the libproc reads."""

    def __init__(self, pid, exec_path=None, argv=(), tty=0x11, foreground=False, cwd=None, children=()):
        self.pid = pid
        self.exec_path = exec_path
        self.argv = list(argv)
        self.tty = tty
        self.foreground = foreground
        self.cwd = cwd
        self.children = list(children)


def install_tree(monkeypatch, processes):
    """Points the terminal resolver's process reads at a synthetic tree keyed by pid."""
    table = {p.pid: p for p in processes}

    class Info:
        def __init__(self, proc):
            self.e_tdev = proc.tty
            self.pbi_pgid = proc.pid
            self.e_tpgid = proc.pid if proc.foreground else 0

    monkeypatch.setattr("tracker.context.terminal.bsd_info", lambda pid: Info(table[pid]) if pid in table else None)
    monkeypatch.setattr("tracker.context.terminal.is_tty_foreground", lambda info: info.pbi_pgid == info.e_tpgid)
    monkeypatch.setattr(
        "tracker.context.terminal.child_pids", lambda pid: list(table[pid].children) if pid in table else []
    )
    monkeypatch.setattr(
        "tracker.context.terminal.exec_path_and_argv",
        lambda pid: (table[pid].exec_path, table[pid].argv) if pid in table else (None, []),
    )
    monkeypatch.setattr(
        "tracker.context.terminal.working_directory", lambda pid: table[pid].cwd if pid in table else None
    )


def terminal_running(signature, cwd="/Users/dev/project", tty=0x11):
    """A terminal (pid 100) -> login (101) -> shell (102) -> tool (103) tree, the real Ghostty shape."""
    exec_path, argv = signature
    return [
        FakeProcess(100, "/Applications/Ghostty.app/Contents/MacOS/ghostty", ["ghostty"], tty=0xFFFFFFFF,
                    children=[101]),
        FakeProcess(101, "/usr/bin/login", ["login"], tty=tty, children=[102]),
        FakeProcess(102, *SHELL_SIGNATURE, tty=tty, children=[103]),
        FakeProcess(103, exec_path, argv, tty=tty, foreground=True, cwd=cwd),
    ]


# --- structural guarantee -------------------------------------------------------------------------------------

def test_terminal_context_cannot_carry_title_text():
    """The type has exactly three fields, none of them free text that could hold a window title.

    Asserted over the declared fields rather than over one instance, so adding a `title`/`command`/`args` field
    later fails here instead of silently reintroducing the leak redaction exists to prevent.
    """
    fields = {f.name: f.type for f in dataclasses.fields(TerminalToolContext)}
    assert set(fields) == {"tool", "cwd", "branch"}


def test_terminal_context_is_frozen():
    """Immutable, so nothing downstream can graft a title onto a result after the fact."""
    ctx = TerminalToolContext(tool="codex", cwd="/tmp", branch="main")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.tool = "other"


def test_resolver_signature_accepts_no_title():
    """`resolve_terminal_tool` takes a pid and a registry — there is no parameter a title could arrive through."""
    hints = typing.get_type_hints(resolve_terminal_tool)
    assert set(hints) - {"return"} == {"terminal_pid", "registry"}
    assert hints["terminal_pid"] is int


# --- registry matching ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", sorted(TERMINAL_TOOL_REGISTRY))
def test_every_registry_entry_is_detected_from_a_real_signature(monkeypatch, tool):
    install_tree(monkeypatch, terminal_running(REAL_SIGNATURES[tool]))
    detected = resolve_terminal_tool(100)
    assert detected is not None, "%s not detected" % tool
    assert detected.tool == tool
    assert detected.cwd == "/Users/dev/project"


def test_script_based_tools_match_through_the_interpreter():
    """aider/gemini are shebang scripts, so the interpreter — not the tool — is argv[0]."""
    assert _match_tool(_candidate_names(*REAL_SIGNATURES["aider"]), TERMINAL_TOOL_REGISTRY) == "aider"
    assert _match_tool(_candidate_names(*REAL_SIGNATURES["gemini-cli"]), TERMINAL_TOOL_REGISTRY) == "gemini-cli"


@pytest.mark.parametrize(
    "signature",
    [
        ("/usr/bin/python3", ["python3", "-m", "pytest", "tests/codex"]),
        ("/usr/bin/python3", ["python3", "script.py", "tests/claude"]),
        ("/usr/local/bin/npm", ["npm", "install", "gemini"]),
        ("/bin/sleep", ["codex", "100"]),
    ],
)
def test_ordinary_commands_do_not_match_tool_names(signature):
    assert _match_tool(_candidate_names(*signature), TERMINAL_TOOL_REGISTRY) is None


def test_reported_tool_name_comes_from_the_registry_not_the_process(monkeypatch):
    """A process may name itself anything; only the registry's canonical key is ever recorded."""
    hostile = ("/tmp/evil/claude", ["claude", "--title", "SECRET ssh prod-db"])
    install_tree(monkeypatch, terminal_running(hostile))
    detected = resolve_terminal_tool(100)
    assert detected.tool == "claude-code"
    assert "SECRET" not in repr(detected)


def test_adding_a_registry_entry_changes_the_tool_label(monkeypatch):
    install_tree(monkeypatch, terminal_running(("/usr/local/bin/newtool", ["newtool"])))
    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.tool is None
    detected = resolve_terminal_tool(100, registry={"new-tool": frozenset({"newtool"})})
    assert detected.tool == "new-tool"


# --- fail-closed fallbacks ------------------------------------------------------------------------------------

def test_recognized_terminal_with_no_known_tool_reports_cwd_and_branch(monkeypatch):
    install_tree(monkeypatch, terminal_running(SHELL_SIGNATURE))
    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.tool is None
    assert detected.cwd == "/Users/dev/project"


def test_tmux_session_resolves_active_pane_cwd(monkeypatch):
    """When tmux is the foreground process and the multiplexer resolver can read the active pane's cwd, we
    attribute the session to that cwd."""
    from tracker.context.models import TerminalToolContext

    install_tree(monkeypatch, terminal_running(TMUX_SIGNATURE))
    monkeypatch.setattr(
        "tracker.context.terminal.resolve_multiplexer",
        lambda names, tty: TerminalToolContext(tool=None, cwd="/Users/dev/tmux-project", branch=None),
    )
    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.tool is None
    assert detected.cwd == "/Users/dev/tmux-project"


def test_tmux_session_falls_back_when_pane_cwd_is_unreadable(monkeypatch):
    """When tmux cannot report its active pane, we fall back to full redaction."""
    install_tree(monkeypatch, terminal_running(TMUX_SIGNATURE))
    monkeypatch.setattr("tracker.context.terminal.resolve_multiplexer", lambda names, tty: None)
    assert resolve_terminal_tool(100) is None


def test_tmux_resolved_when_it_is_the_only_foreground_process(monkeypatch):
    """A multiplexer in the foreground is resolved when no other process is also foreground."""
    from tracker.context.models import TerminalToolContext

    tree = terminal_running(REAL_SIGNATURES["codex"])
    tree[0].children.append(200)
    tree.append(FakeProcess(200, *TMUX_SIGNATURE, tty=0x11, foreground=True, cwd="/Users/dev/other"))
    tree[-2].foreground = False  # codex is background
    install_tree(monkeypatch, tree)
    monkeypatch.setattr(
        "tracker.context.terminal.resolve_multiplexer",
        lambda names, tty: TerminalToolContext(tool=None, cwd="/Users/dev/other", branch=None),
    )
    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.cwd == "/Users/dev/other"


def test_tracker_own_process_is_ignored_in_foreground_walk(monkeypatch):
    """The tracker can run from a tab of the same terminal app as tmux. Its own foreground process
    must not count as a competing hit, or the ambiguity check would redact the whole session."""
    import os

    from tracker.context.models import TerminalToolContext

    tree = terminal_running(REAL_SIGNATURES["codex"], tty=0x11)
    tree[0].children.append(200)
    tree.append(FakeProcess(200, *TMUX_SIGNATURE, tty=0x11, foreground=True, cwd="/Users/dev/project"))
    tree[-2].foreground = False  # codex is background
    self_pid = os.getpid()
    tree[0].children.append(self_pid)
    tree.append(FakeProcess(self_pid, "/usr/local/bin/python", ["python", "-m", "tracker.main"],
                            tty=0x22, foreground=True, cwd="/Users/dev/project"))
    install_tree(monkeypatch, tree)
    monkeypatch.setattr(
        "tracker.context.terminal.resolve_multiplexer",
        lambda names, tty: TerminalToolContext(tool=None, cwd="/Users/dev/project", branch=None),
    )
    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.tool is None
    assert detected.cwd == "/Users/dev/project"


def test_tmux_and_another_tool_in_foreground_is_ambiguous(monkeypatch):
    """A resolved tmux pane plus another foreground process on a different TTY is unknowable — fail closed."""
    from tracker.context.models import TerminalToolContext

    tree = terminal_running(REAL_SIGNATURES["codex"])
    tree[0].children.append(200)
    tree.append(FakeProcess(200, *TMUX_SIGNATURE, tty=0x22, foreground=True, cwd="/Users/dev/other"))
    install_tree(monkeypatch, tree)
    monkeypatch.setattr(
        "tracker.context.terminal.resolve_multiplexer",
        lambda names, tty: TerminalToolContext(tool=None, cwd="/Users/dev/other", branch=None),
    )
    assert resolve_terminal_tool(100) is None


def test_two_tools_in_two_tabs_is_ambiguous_and_falls_back(monkeypatch):
    """Live-confirmed case: Ghostty with codex in one tab and opencode in another. Which has focus is unknowable
    without reading the title, so nothing is recorded."""
    tree = terminal_running(REAL_SIGNATURES["codex"], tty=0x11)
    tree[0].children.append(200)
    tree.append(FakeProcess(200, *REAL_SIGNATURES["opencode"], tty=0x22, foreground=True, cwd="/Users/dev/other"))
    install_tree(monkeypatch, tree)
    assert resolve_terminal_tool(100) is None


def test_tool_running_but_not_in_foreground_falls_back(monkeypatch):
    """Present in the tree is not the same as holding the tty's foreground process group."""
    tree = terminal_running(REAL_SIGNATURES["codex"])
    tree[-1].foreground = False
    install_tree(monkeypatch, tree)
    assert resolve_terminal_tool(100) is None


def test_unreadable_cwd_falls_back(monkeypatch):
    tree = terminal_running(REAL_SIGNATURES["codex"])
    tree[-1].cwd = None
    install_tree(monkeypatch, tree)
    assert resolve_terminal_tool(100) is None


def test_cycle_in_process_tree_terminates(monkeypatch):
    """pid 0 reports itself as its own child; an unguarded walk would hang the 5-second poll forever."""
    install_tree(monkeypatch, [
        FakeProcess(100, "/bin/terminal", ["terminal"], tty=0xFFFFFFFF, children=[100, 101]),
        FakeProcess(101, *SHELL_SIGNATURE, tty=0x11, children=[100, 101]),
    ])
    assert resolve_terminal_tool(100) is None


def test_dead_process_tree_falls_back(monkeypatch):
    install_tree(monkeypatch, [])
    assert resolve_terminal_tool(100) is None


def test_wide_process_tree_fails_closed(monkeypatch):
    """An extremely wide terminal process tree must not consume unbounded CPU/memory."""
    width = PROC_WALK_MAX_PIDS + 50
    processes = [
        FakeProcess(100, "/bin/terminal", ["terminal"], tty=0xFFFFFFFF,
                    children=list(range(101, 101 + width))),
    ]
    for pid in range(101, 101 + width):
        processes.append(
            FakeProcess(pid, "/bin/sleep", ["sleep", "100"], tty=0x11,
                        foreground=True, cwd="/tmp")
        )
    install_tree(monkeypatch, processes)
    assert _foreground_processes(100, TERMINAL_TOOL_REGISTRY) is None
    assert resolve_terminal_tool(100) is None


def test_tool_and_cwd_are_read_together_for_the_same_pid(monkeypatch):
    """exec_path/argv and cwd must be read at the same time for the PID that matched,
    not collected first and read later in a separate pass. This keeps the reported
    {tool, cwd} internally consistent even if the PID is reused between the two reads.
    """
    processes = [
        FakeProcess(100, "/bin/terminal", ["terminal"], tty=0xFFFFFFFF,
                    children=[101, 200]),
        FakeProcess(101, *SHELL_SIGNATURE, tty=0x11, children=[103]),
        FakeProcess(103, *REAL_SIGNATURES["codex"], tty=0x11, foreground=True,
                    cwd="/Users/dev/project"),
        FakeProcess(200, "/bin/zsh", ["zsh"], tty=0x11, foreground=False, cwd="/tmp"),
    ]
    table = {p.pid: p for p in processes}
    install_tree(monkeypatch, processes)

    calls = []

    def tracking_exec_path_and_argv(pid):
        calls.append(("exec", pid))
        return (table[pid].exec_path, table[pid].argv) if pid in table else (None, [])

    def tracking_working_directory(pid):
        calls.append(("cwd", pid))
        return table[pid].cwd if pid in table else None

    monkeypatch.setattr("tracker.context.terminal.exec_path_and_argv", tracking_exec_path_and_argv)
    monkeypatch.setattr("tracker.context.terminal.working_directory", tracking_working_directory)

    detected = resolve_terminal_tool(100)
    assert detected is not None
    assert detected.tool == "codex"
    assert detected.cwd == "/Users/dev/project"

    # The cwd read must happen immediately after the exec/argv read for the matched PID,
    # not after the whole tree has been enumerated.
    exec_103 = calls.index(("exec", 103))
    cwd_103 = calls.index(("cwd", 103))
    assert cwd_103 == exec_103 + 1


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_every_known_terminal_dispatches_to_process_detection(monkeypatch, bundle_id):
    install_tree(monkeypatch, terminal_running(REAL_SIGNATURES["codex"]))
    monkeypatch.setattr("tracker.context.terminal.find_project_root", lambda path: None)
    result = resolve_context(bundle_id=bundle_id, app_name="Terminal", window_title=None, pid=100)
    assert result.detail["tool"] == "codex"
    assert result.detail["cwd"] == "/Users/dev/project"


def test_unrecognized_terminal_bundle_gets_no_process_detection(monkeypatch):
    """An unknown terminal is not redacted at all, so it must not reach the process path either."""
    install_tree(monkeypatch, terminal_running(REAL_SIGNATURES["codex"]))
    result = resolve_context(bundle_id="com.example.UnknownTerm", app_name="Unknown", window_title=None, pid=100)
    assert "tool" not in result.detail


def test_redacted_terminal_without_pid_is_fully_redacted(monkeypatch):
    result = resolve_context(bundle_id="com.apple.Terminal", app_name="Terminal", window_title=None, pid=None)
    assert result.project_path is None and result.detail == {}


def test_redacted_terminal_with_plain_shell_reports_cwd_and_project(monkeypatch):
    """A plain shell in a project directory should still attribute the session, without a tool label."""
    install_tree(monkeypatch, terminal_running(SHELL_SIGNATURE))
    monkeypatch.setattr("tracker.context.terminal.find_project_root", lambda path: path)
    result = resolve_context(
        bundle_id="com.apple.Terminal", app_name="Terminal", window_title="SECRET COMMAND", pid=100
    )
    assert "SECRET" not in repr(result)
    assert "hunter2" not in repr(result)
    assert result.project_path == "/Users/dev/project"
    assert result.detail == {"cwd": "/Users/dev/project"}


def test_title_is_never_recorded_even_when_one_leaks_in(monkeypatch):
    """Defence in depth: even if a caller passes a title for a redacted app, no part of it reaches the output."""
    install_tree(monkeypatch, terminal_running(REAL_SIGNATURES["codex"]))
    monkeypatch.setattr("tracker.context.terminal.find_project_root", lambda path: None)
    leaked = "ssh prod-db -- export AWS_SECRET_ACCESS_KEY=hunter2"
    result = resolve_context(
        bundle_id="com.apple.Terminal", app_name="Terminal", window_title=leaked, pid=100
    )
    assert leaked not in repr(result)
    assert "hunter2" not in repr(result)
