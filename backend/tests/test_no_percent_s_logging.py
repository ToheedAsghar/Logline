"""Fails if any logger call in app/ uses %s-style or f-string interpolation instead of structured kwargs.

Both styles squash the message into one opaque string with no field name, which lets it skip the field-name
redaction check in redaction.py entirely. Use `logger.info("msg", extra={"key": value})` instead.

This reads real Python code with the `ast` module rather than searching the file text, since a %s-style
format string can hide behind a named constant, e.g. `logger.info(USAGE_LOG_FORMAT, call_kind)`, with no
visible "%s" in the call itself.

`agent/runner.py` and `agent/toolbelt.py` are the OLD agent architecture (LLM-decides-tool-calls-live),
exempted from this ban pending a separate decision on whether to remove them entirely -- their logging
convention is out of scope for the structured-logging rollout.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
LOGGING_MODULE = APP_ROOT / "core" / "logging.py"
LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}

OLD_AGENT_ARCHITECTURE_FILES = frozenset({"agent/runner.py", "agent/toolbelt.py"})


def _is_logger_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LOGGER_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    )


def _message_arg_count(node: ast.Call) -> int:
    """Counts positional args, skipping `.log()`'s leading level arg since it isn't part of the message."""
    return len(node.args) - 1 if node.func.attr == "log" else len(node.args)


def _has_interpolated_fstring_arg(node: ast.Call) -> bool:
    return any(
        isinstance(arg, ast.JoinedStr) and any(isinstance(value, ast.FormattedValue) for value in arg.values)
        for arg in node.args
    )


class TestNoPercentStyleLogging:
    def test_app_contains_no_multi_positional_or_fstring_logger_calls(self):
        offenders = []
        for path in APP_ROOT.rglob("*.py"):
            if path == LOGGING_MODULE or path.relative_to(APP_ROOT).as_posix() in OLD_AGENT_ARCHITECTURE_FILES:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not _is_logger_call(node):
                    continue
                if _message_arg_count(node) > 1 or _has_interpolated_fstring_arg(node):
                    offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}")

        assert offenders == [], (
            "logger call collapsing dynamic content into one opaque message string found "
            "(either %s-style multiple positional args, or an interpolated f-string) -- convert "
            "to structured kwargs (see backend/tasks/plan.md §7):\n" + "\n".join(offenders)
        )
