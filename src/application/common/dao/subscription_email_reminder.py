from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from src.application.dto import (
    SubscriptionEmailDeliveryDto,
    SubscriptionEmailReminderDto,
)


@runtime_checkable
class SubscriptionEmailReminderDao(Protocol):
    async def generate(
        self,
        *,
        now: datetime,
        days_before: tuple[int, ...],
        candidate_limit: int,
        generation_grace: timedelta,
    ) -> int: ...

    async def claim_due(
        self,
        *,
        now: datetime,
        delivery_not_before: datetime,
        token_hash: str,
        lease_for: timedelta,
        max_attempts: int,
        limit: int,
    ) -> list[SubscriptionEmailReminderDto]: ...

    async def sweep_undeliverable(
        self,
        *,
        now: datetime,
        delivery_not_before: datetime,
        max_attempts: int,
        limit: int,
    ) -> int: ...

    async def prepare_delivery(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        now: datetime,
    ) -> SubscriptionEmailDeliveryDto | None: ...

    async def renew_processing_lease(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> bool: ...

    async def mark_sent(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        sent_at: datetime,
    ) -> bool: ...

    async def release_failed(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        now: datetime,
        error_code: str,
        max_attempts: int,
        retry_after: timedelta,
    ) -> bool: ...

    async def delete_terminal_before(
        self,
        *,
        before: datetime,
        limit: int,
    ) -> int: ...
