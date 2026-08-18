"""Fails if any file in app/ uses print() instead of the structured logger.

A stray print() skips every redaction check in app/core/redaction.py. This repo has no CI, so this test is
what actually enforces the rule day to day, not just flake8-print's T201.

`agent/runner.py` and `agent/toolbelt.py` are the OLD agent architecture (LLM-decides-tool-calls-live),
exempted from this ban pending a separate decision on whether to remove them entirely -- their logging
convention is out of scope for the structured-logging rollout.
"""

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
PRINT_CALL_RE = re.compile(r"(?<![\w.])print\(")

OLD_AGENT_ARCHITECTURE_FILES = frozenset({"agent/runner.py", "agent/toolbelt.py"})


class TestNoRawPrint:
    def test_app_contains_no_raw_print_calls(self):
        offenders = []
        for path in APP_ROOT.rglob("*.py"):
            if path.relative_to(APP_ROOT).as_posix() in OLD_AGENT_ARCHITECTURE_FILES:
                continue
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if PRINT_CALL_RE.search(line) and "noqa: T201" not in line:
                    offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{line_number}: {line.strip()}")

        assert offenders == [], "raw print() found outside an explicit noqa escape hatch:\n" + "\n".join(offenders)
