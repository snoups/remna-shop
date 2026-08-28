from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.constants import EMAIL_CODE_LENGTH
from src.core.enums import AuthType


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    referral_code: Optional[str] = Field(default=None, min_length=3, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("referral_code")
    @classmethod
    def normalize_referral_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class RequestPasswordResetRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ConfirmPasswordResetRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    code: str = Field(
        min_length=EMAIL_CODE_LENGTH,
        max_length=EMAIL_CODE_LENGTH,
        pattern=r"^\d{6}$",
    )
    new_password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class MigrateTelegramRequest(RegisterRequest):
    pass


class AuthResponse(BaseModel):
    expires_at: datetime
    refresh_expires_at: datetime


class MeResponse(BaseModel):
    telegram_id: Optional[int]
    auth_type: AuthType
    email: Optional[str]
    is_email_verified: bool
    pending_email: Optional[str]
    name: str
    username: Optional[str]
    language: str


class ChangePasswordResponse(BaseModel):
    success: bool


class PasswordResetResponse(BaseModel):
    success: bool


class ChangeEmailRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ChangeEmailResponse(BaseModel):
    success: bool
    pending_email: str


class RequestEmailVerificationCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: Optional[str] = Field(
        default=None,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.lower()


class RequestEmailVerificationCodeResponse(BaseModel):
    success: bool
    target_email: str
    expires_at: datetime


class ConfirmEmailVerificationRequest(BaseModel):
    code: str = Field(
        min_length=EMAIL_CODE_LENGTH,
        max_length=EMAIL_CODE_LENGTH,
        pattern=r"^\d{6}$",
    )


class ConfirmEmailVerificationResponse(BaseModel):
    success: bool
    email: str


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class TelegramWebAppAuthRequest(BaseModel):
    init_data: str


class LogoutResponse(BaseModel):
    success: bool
