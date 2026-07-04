from cryptography.fernet import Fernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import settings


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts a string column at rest using Fernet."""

    impl = String
    cache_ok = True

    def _fernet(self) -> Fernet:
        return Fernet(settings.encryption_key)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self._fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self._fernet().decrypt(value.encode()).decode()
