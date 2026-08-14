"""Tests for the EmailProvider abstraction (app/core/email.py): SMTPProvider
delegates to aiosmtplib.send with the right envelope, and -- mirroring the
isolation guarantee already enforced for the OpenAI SDK in
app/agent/llm/openai_provider.py -- no file outside app/core/email.py may
import aiosmtplib directly.
"""

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock

from app.core.email import EmailProvider, SMTPProvider

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
EMAIL_MODULE = APP_ROOT / "core" / "email.py"
AIOSMTPLIB_IMPORT_RE = re.compile(r"^\s*(import aiosmtplib|from aiosmtplib\b)", re.MULTILINE)


class TestSMTPProviderSend:
    def test_send_delegates_to_aiosmtplib_with_expected_envelope(self, monkeypatch):
        mock_send = AsyncMock()
        monkeypatch.setattr("app.core.email.aiosmtplib.send", mock_send)

        provider = SMTPProvider(
            host="smtp.example.com",
            port=587,
            username="user",
            password="secret",
            from_address="noreply@logline.local",
        )
        asyncio.run(provider.send(to="someone@example.com", subject="Hello", body="World"))

        mock_send.assert_awaited_once()
        message, kwargs = mock_send.call_args.args[0], mock_send.call_args.kwargs
        assert message["From"] == "noreply@logline.local"
        assert message["To"] == "someone@example.com"
        assert message["Subject"] == "Hello"
        assert message.get_content().strip() == "World"
        assert kwargs == {
            "hostname": "smtp.example.com",
            "port": 587,
            "username": "user",
            "password": "secret",
        }

    def test_smtp_provider_is_an_email_provider(self):
        assert issubclass(SMTPProvider, EmailProvider)


class TestAiosmtplibImportIsolation:
    def test_only_core_email_imports_aiosmtplib(self):
        offenders = []
        for path in APP_ROOT.rglob("*.py"):
            if path == EMAIL_MODULE:
                continue
            if AIOSMTPLIB_IMPORT_RE.search(path.read_text()):
                offenders.append(str(path.relative_to(APP_ROOT.parent)))

        assert offenders == []
