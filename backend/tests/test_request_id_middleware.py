"""Tests for RequestIDMiddleware (app/core/request_context.py): header echo for both the
supplied-id and generated-id cases, and that a log line emitted mid-request carries the bound
`request_id` via structlog's contextvars.
"""

import json
import logging
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestIDMiddleware

logger = logging.getLogger("tests.test_request_id_middleware")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    def ping():
        logger.info("ping_handled")
        return {"ok": True}

    return app


class TestRequestIDMiddleware:
    def test_generates_a_request_id_when_none_supplied(self):
        client = TestClient(_build_app())
        response = client.get("/ping")
        assert REQUEST_ID_HEADER in response.headers
        uuid.UUID(response.headers[REQUEST_ID_HEADER])

    def test_echoes_a_supplied_request_id_exactly(self):
        client = TestClient(_build_app())
        supplied_id = "a-caller-supplied-id-123"
        response = client.get("/ping", headers={REQUEST_ID_HEADER: supplied_id})
        assert response.headers[REQUEST_ID_HEADER] == supplied_id

    def test_a_log_line_emitted_mid_request_carries_the_bound_request_id(self, capsys):
        configure_logging()
        client = TestClient(_build_app())
        supplied_id = "trace-me-through-the-logs"

        client.get("/ping", headers={REQUEST_ID_HEADER: supplied_id})

        lines = [line for line in capsys.readouterr().out.splitlines() if "ping_handled" in line]
        assert len(lines) == 1
        assert json.loads(lines[0])["request_id"] == supplied_id

    def test_request_id_does_not_leak_into_a_later_unrelated_request(self, capsys):
        configure_logging()
        client = TestClient(_build_app())

        client.get("/ping", headers={REQUEST_ID_HEADER: "first-request"})
        client.get("/ping")

        lines = [line for line in capsys.readouterr().out.splitlines() if "ping_handled" in line]
        assert len(lines) == 2
        assert json.loads(lines[0])["request_id"] == "first-request"
        assert json.loads(lines[1])["request_id"] != "first-request"
