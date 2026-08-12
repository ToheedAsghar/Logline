"""Checks that Uvicorn's own access log, not just our app's logger calls, goes through redaction too.

Boots a real Uvicorn process instead of using Starlette's TestClient, since TestClient talks to the app
directly and never triggers Uvicorn's own access logger at all.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

BOOT_SCRIPT = (
    "import uvicorn\n"
    "uvicorn.run('tests._uvicorn_layer0_boot:app', host='127.0.0.1', port={port}, log_level='info')\n"
)

A_FAKE_OAUTH_STATE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJmYWtlLWp0aSIsInB1cnBvc2UiOiJmYWtlIn0.FAKESIGNATUREHERE"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_accepting_connections(port: int, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"uvicorn did not start accepting connections on port {port} in time")


@pytest.fixture
def booted_uvicorn_with_configured_logging():
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-c", BOOT_SCRIPT.format(port=port)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_until_accepting_connections(port)
        yield port, process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


class TestUvicornAccessLogRedaction:
    def test_query_string_leak_shape_never_reaches_stdout_unredacted(
        self, booted_uvicorn_with_configured_logging
    ):
        port, process = booted_uvicorn_with_configured_logging
        query = urllib.parse.urlencode({"state": A_FAKE_OAUTH_STATE_JWT, "code": "fake_code_value"})
        url = f"http://127.0.0.1:{port}/auth/google/callback?{query}"
        try:
            urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError:
            pass
        process.terminate()
        stdout, _ = process.communicate(timeout=10)

        assert A_FAKE_OAUTH_STATE_JWT not in stdout, (
            f"fake secret leaked into uvicorn's own stdout unredacted:\n{stdout}"
        )

        access_log_lines = [
            line for line in stdout.splitlines()
            if '"event":' in line and "/auth/google/callback" in line
        ]
        assert access_log_lines, f"no access-log line found for the request in:\n{stdout}"
        for line in access_log_lines:
            parsed = json.loads(line)
            assert "level" in parsed and "event" in parsed
