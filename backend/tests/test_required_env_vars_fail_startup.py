"""Proves the app refuses to boot into a vulnerable/broken state when a
required secret is missing -- not just that individual token operations
later fail, but that config loading (and therefore app startup, since
app.main imports `settings` at module load time) blows up immediately.

Run as a real subprocess (not an in-process reload) so each case gets a
clean module cache and the test exercises the actual startup path.
"""
import os
import subprocess
import sys

import pytest

REQUIRED_VARS = ["JWT_SECRET_KEY", "ITSDANGEROUS_SECRET_KEY", "DATABASE_URL"]


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_app_fails_to_start_when_required_var_missing(missing_var):
    env = os.environ.copy()
    env[missing_var] = ""

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0, (
        f"app.main imported successfully with {missing_var} empty -- "
        f"it should have crashed at startup.\nstdout: {result.stdout}"
    )
    assert "RuntimeError" in result.stderr
    assert missing_var in result.stderr


def test_app_starts_when_all_required_vars_present():
    env = os.environ.copy()

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"app.main failed to import with a normal environment.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
