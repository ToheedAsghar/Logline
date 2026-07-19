"""Provider-agnostic email sending"""

from abc import ABC, abstractmethod
from email.message import EmailMessage

import aiosmtplib

from app.config import settings


class EmailProvider(ABC):
    """Abstract boundary callers talk to -- never a concrete SDK."""

    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None:
        """Send a single email. Raises on delivery failure."""


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

        await aiosmtplib.send(
            message,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )


def get_email_provider() -> EmailProvider:
    return SMTPProvider(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_address=settings.smtp_from_address,
    )
