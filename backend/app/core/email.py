"""Provider-agnostic email sending"""

from abc import ABC, abstractmethod
from email.message import EmailMessage

import aiosmtplib

from app.config import settings


class EmailDeliveryError(Exception):
    """Raised by EmailProvider.send on delivery failure.

    The provider-specific cause (SMTP auth failure, connection refused, a
    future provider's own SDK error, ...) is wrapped in this so callers can
    catch one bounded type without importing any concrete SDK.
    """


class EmailProvider(ABC):
    """Abstract boundary callers talk to -- never a concrete SDK."""

    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None:
        """Send a single email. Raises EmailDeliveryError on delivery failure."""


class SMTPProvider(EmailProvider):
    def __init__(self, host: str, port: int, username: str, password: str, from_address: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            await aiosmtplib.send(
                message, hostname=self.host, port=self.port, username=self.username, password=self.password
            )
        except aiosmtplib.SMTPException as exc:
            raise EmailDeliveryError(str(exc)) from exc


def get_email_provider() -> EmailProvider:
    return SMTPProvider(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_address=settings.smtp_from_address,
    )
