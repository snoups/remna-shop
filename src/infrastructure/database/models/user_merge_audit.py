from typing import Optional

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class UserMergeAudit(BaseSql, TimestampMixin):
    __tablename__ = "user_merge_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)
    moved: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
