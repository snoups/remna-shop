from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import AuthType, Locale, Role

from .base import BaseSql
from .timestamp import TimestampMixin


class User(BaseSql, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, index=True, unique=True, nullable=True
    )
    auth_type: Mapped[AuthType] = mapped_column(String(20), default=AuthType.TELEGRAM)

    email: Mapped[Optional[str]] = mapped_column(String(255), index=True, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(512))
    is_email_verified: Mapped[bool] = mapped_column(default=False)
    pending_email: Mapped[Optional[str]] = mapped_column(String(255))
    email_verification_code_hash: Mapped[Optional[str]] = mapped_column(String(128))
    email_verification_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    password_reset_code_hash: Mapped[Optional[str]] = mapped_column(String(128))
    password_reset_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    password_reset_attempts: Mapped[int] = mapped_column(Integer, default=0)
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    username: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    referral_code: Mapped[str] = mapped_column(String(64), index=True, unique=True)

    name: Mapped[str] = mapped_column(String())
    role: Mapped[Role] = mapped_column(index=True)
    language: Mapped[Locale]

    personal_discount: Mapped[int]
    purchase_discount: Mapped[int]
    points: Mapped[int]

    is_blocked: Mapped[bool]
    is_bot_blocked: Mapped[bool]
    is_rules_accepted: Mapped[bool]
    is_trial_available: Mapped[bool]

    ad_link_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("ad_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    referral_code_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    current_subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        index=True,
    )
