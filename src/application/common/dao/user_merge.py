from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from src.application.dto import UserDto


class UserMergeNotFoundError(Exception): ...


class UserMergeTargetConflictError(Exception): ...


class UserMergePaymentOperationConflictError(Exception): ...


class UserMergeReferralAttributionConflictError(Exception): ...


class EmailConflictResolution(StrEnum):
    REJECT = "REJECT"
    KEEP_TARGET = "KEEP_TARGET"


class TelegramConflictResolution(StrEnum):
    REJECT = "REJECT"
    KEEP_SOURCE = "KEEP_SOURCE"


class PaymentConflictResolution(StrEnum):
    REJECT = "REJECT"
    REKEY_SOURCE = "REKEY_SOURCE"


@dataclass(frozen=True)
class UserMergeTargetSnapshot:
    id: int
    email: str | None
    telegram_id: int | None
    is_email_verified: bool
    current_subscription_id: int | None


@dataclass(frozen=True)
class UserMergePlan:
    source_user_id: int
    target_user_id: int
    target: UserMergeTargetSnapshot
    moved: dict[str, int]
    conflicts: list[str] = field(default_factory=list)


@runtime_checkable
class UserMergeDao(Protocol):
    async def plan(
        self,
        source_user_id: int,
        target_user_id: int,
        *,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
        payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT,
    ) -> UserMergePlan: ...

    async def merge(
        self,
        *,
        actor: UserDto,
        source_user_id: int,
        target_user_id: int,
        reason: str,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
        payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT,
    ) -> UserMergePlan: ...
