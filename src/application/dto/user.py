from dataclasses import dataclass, fields
from datetime import datetime
from typing import Optional, Self

from aiogram.types import User as AiogramUser

from src.core.constants import REMNASHOP_PREFIX, WEB_PREFIX
from src.core.enums import AuthType, Locale, OAuthProvider, Role
from src.core.utils.time import datetime_now

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class TempUserDto:
    telegram_id: int
    name: str
    role: Role = Role.USER
    language: Locale = Locale.EN

    @property
    def remna_name(self) -> str:
        return f"{REMNASHOP_PREFIX}{self.telegram_id}"

    @property
    def log(self) -> str:
        return f"[{self.role}:{self.remna_name} ({self.name})]"

    @classmethod
    def from_aiogram(cls, aiogram_user: AiogramUser) -> Self:
        return cls(
            telegram_id=aiogram_user.id,
            name=aiogram_user.full_name,
        )

    @classmethod
    def as_temp_owner(cls, telegram_id: int) -> Self:
        return cls(telegram_id=telegram_id, name="OWNER", role=Role.OWNER)


@dataclass(kw_only=True)
class UserDto(BaseDto, TrackableMixin, TimestampMixin):
    telegram_id: Optional[int] = None
    auth_type: AuthType = AuthType.TELEGRAM

    email: Optional[str] = None
    password_hash: Optional[str] = None
    is_email_verified: bool = False
    pending_email: Optional[str] = None
    email_verification_code_hash: Optional[str] = None
    email_verification_expires_at: Optional[datetime] = None
    password_reset_code_hash: Optional[str] = None
    password_reset_expires_at: Optional[datetime] = None
    password_reset_attempts: int = 0
    token_version: int = 0

    username: Optional[str] = None
    referral_code: str = ""

    name: str
    role: Role = Role.USER
    language: Locale = Locale.EN

    personal_discount: int = 0
    purchase_discount: int = 0
    points: int = 0

    is_blocked: bool = False
    is_bot_blocked: bool = False
    is_rules_accepted: bool = False
    is_trial_available: bool = True
    ad_link_id: Optional[int] = None
    referral_code_reset_at: Optional[datetime] = None

    @property
    def contact_label(self) -> str:
        if self.username:
            return self.username
        if self.telegram_id is not None:
            return str(self.telegram_id)
        return self.email or str(self.id)

    @property
    def is_privileged(self) -> bool:
        return self.role.includes(Role.ADMIN)

    @property
    def is_owner(self) -> bool:
        return self.role.includes(Role.OWNER)

    @property
    def age_days(self) -> Optional[int]:
        if self.created_at is None:
            return None

        return (datetime_now() - self.created_at).days

    @property
    def log(self) -> str:
        return f"[{self.role}:{self.id}:{self.remna_name} ({self.name})]"

    @property
    def remna_name(self) -> str:  # NOTE: DONT USE FOR GET USER!
        if self.telegram_id is not None:
            return f"{REMNASHOP_PREFIX}{self.telegram_id}"
        return f"{REMNASHOP_PREFIX}{WEB_PREFIX}{self.id}"

    @property
    def remna_description(self) -> str:
        description = f"name: {self.name}"

        if self.username:
            description += f"\nusername: {self.username}"
        if self.email:
            description += f"\nemail: {self.email}"

        return description


@dataclass(kw_only=True)
class UserOAuthProviderDto(BaseDto):
    user_id: int
    provider: OAuthProvider
    provider_id: str


@dataclass(kw_only=True)
class TelegramUserDto(UserDto):
    telegram_id: int

    @classmethod
    def from_user(cls, user: UserDto) -> "TelegramUserDto":
        # TelegramUserDto only narrows telegram_id; it shares every UserDto field. Copy all
        # public dataclass fields so the mapping stays correct automatically when fields
        # change. Centralized here (instead of inline in the middleware) for one tested home.
        return cls(
            **{f.name: getattr(user, f.name) for f in fields(user) if not f.name.startswith("_")}
        )
