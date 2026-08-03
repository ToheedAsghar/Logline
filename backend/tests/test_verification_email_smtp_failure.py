"""Tests for app/auth/routers.py::_send_token_email under a genuine SMTP
failure, exercised with the verification-email spec.

_send_token_email runs as a FastAPI BackgroundTask (see
_issue_and_queue_email), which Starlette awaits with no try/except of its
own (starlette.background.BackgroundTask.__call__ just does
`await self.func(...)`). If the coroutine raises, nothing in our stack
catches it -- it is not surfaced to the original HTTP request (the response
was already sent) and, before this fix, nothing in the app's own logging
recorded that a verification email failed to send.

This mocks aiosmtplib.send (via app.core.email.aiosmtplib, mirroring the
isolation pattern in test_email_provider.py) to raise a realistic SMTP
auth failure and observes, with caplog, exactly what happens.
"""

import asyncio

import aiosmtplib

from app.auth.routers import _VERIFICATION_EMAIL, _send_token_email


def _verification_email_args(user_id: int, email: str, token: str) -> dict:
    """Build the exact _send_token_email arguments _issue_and_queue_email would queue for a verification email."""
    return {
        "user_id": user_id,
        "email": email,
        "subject": _VERIFICATION_EMAIL.subject,
        "body": _VERIFICATION_EMAIL.body.format(url=f"https://example.test/verify-email?token={token}"),
        "kind": _VERIFICATION_EMAIL.kind,
    }


class TestSendTokenEmailSMTPFailure:
    def test_smtp_failure_is_logged_at_error_level_and_not_raised(self, monkeypatch, caplog):
        async def raise_auth_failure(*args, **kwargs):
            raise aiosmtplib.SMTPAuthenticationError(535, b"Authentication failed")

        monkeypatch.setattr("app.core.email.aiosmtplib.send", raise_auth_failure)

        with caplog.at_level("ERROR", logger="app.auth.routers"):
            asyncio.run(_send_token_email(**_verification_email_args(123, "someone@example.com", "faketoken")))

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
            asyncio.run(_send_token_email(**_verification_email_args(456, "other@example.com", "anothertoken")))

        assert any("456" in r.message for r in caplog.records)
