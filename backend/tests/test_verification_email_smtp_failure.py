"""Tests for app/auth/routers.py::_send_verification_email under a genuine
SMTP failure.

_send_verification_email runs as a FastAPI BackgroundTask (see
_issue_and_queue_verification_email), which Starlette awaits with no
try/except of its own (starlette.background.BackgroundTask.__call__ just
does `await self.func(...)`). If the coroutine raises, nothing in our stack
catches it -- it is not surfaced to the original HTTP request (the response
was already sent) and, before this fix, nothing in the app's own logging
recorded that a verification email failed to send.

This mocks aiosmtplib.send (via app.core.email.aiosmtplib, mirroring the
isolation pattern in test_email_provider.py) to raise a realistic SMTP
auth failure and observes, with caplog, exactly what happens.
"""

import asyncio

import aiosmtplib
import pytest

from app.auth.routers import _send_verification_email


class TestSendVerificationEmailSMTPFailure:
    def test_smtp_failure_is_logged_at_error_level_and_not_raised(self, monkeypatch, caplog):
        async def raise_auth_failure(*args, **kwargs):
            raise aiosmtplib.SMTPAuthenticationError(535, b"Authentication failed")

        monkeypatch.setattr("app.core.email.aiosmtplib.send", raise_auth_failure)

        with caplog.at_level("ERROR", logger="app.auth.routers"):
            asyncio.run(_send_verification_email(user_id=123, email="someone@example.com", token="faketoken"))

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "ERROR"
        assert "123" in record.message
        assert "someone@example.com" in record.message
        assert "verification email" in record.message.lower()
        assert "Authentication failed" in record.message

    def test_smtp_failure_does_not_propagate_out_of_the_background_task(self, monkeypatch, caplog):
        async def raise_connect_failure(*args, **kwargs):
            raise aiosmtplib.SMTPConnectError("Connection refused")

        monkeypatch.setattr("app.core.email.aiosmtplib.send", raise_connect_failure)

        with caplog.at_level("ERROR", logger="app.auth.routers"):
            # Must not raise -- a failed background task should be logged and
            # swallowed, never left to crash silently or propagate further.
            asyncio.run(_send_verification_email(user_id=456, email="other@example.com", token="anothertoken"))

        assert any("456" in r.message for r in caplog.records)
