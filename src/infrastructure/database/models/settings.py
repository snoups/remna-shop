from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import Currency

from .base import BaseSql
from .timestamp import TimestampMixin


class Settings(BaseSql, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)

    default_currency: Mapped[Currency]

    access: Mapped[dict[str, Any]]
    requirements: Mapped[dict[str, Any]]
    notifications: Mapped[dict[str, Any]]
    referral: Mapped[dict[str, Any]]
    menu: Mapped[dict[str, Any]]
    backup: Mapped[dict[str, Any]]
    blacklist: Mapped[dict[str, Any]]
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB)
    grace: Mapped[dict[str, Any]] = mapped_column(JSONB)
