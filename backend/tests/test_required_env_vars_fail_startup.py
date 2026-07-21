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

# Valid dummy values for every var app.config._require_env guards, so each
# parametrized case blanks exactly one var against an otherwise-complete,
# hermetic baseline instead of depending on whatever happens to be in the
# developer's local .env.
BASELINE_ENV = {
    "JWT_SECRET_KEY": "test-jwt-secret",
    "ITSDANGEROUS_SECRET_KEY": "test-itsdangerous-secret",
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USERNAME": "test",
    "SMTP_PASSWORD": "test",
    "SMTP_FROM_ADDRESS": "test@example.com",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
    "GOOGLE_REDIRECT_URI": "http://localhost:8000/auth/callback/google",
}
REQUIRED_VARS = list(BASELINE_ENV)


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_app_fails_to_start_when_required_var_missing(missing_var):
    env = os.environ.copy()
    env.update(BASELINE_ENV)
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
    env.update(BASELINE_ENV)

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
