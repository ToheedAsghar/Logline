from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.core.timezones import TIMEZONE_NAME_MAX_LENGTH, resolve_timezone


class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None = None
    default_channel: str | None = None
    timezone: str | None = None
    created_at: datetime


class UserTimezoneUpdate(BaseModel):
    """Set the IANA timezone deciding which calendar day the user's work belongs to."""

    timezone: str = Field(min_length=1, max_length=TIMEZONE_NAME_MAX_LENGTH)

    @field_validator("timezone")
    @classmethod
    def _reject_unknown_timezone(cls, value: str) -> str:
        resolve_timezone(value)
        return value


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class MessageResponse(BaseModel):
    message: str


class OAuthExchangeRequest(BaseModel):
    code: str
