from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from src.application.use_cases.subscription.commands.purchase import (
    PurchaseSubscription,
    PurchaseSubscriptionDto,
)
from src.core.enums import PurchaseType


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class FakeMutationLock:
    def hold(self, user_id: int) -> "FakeMutationLock":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_delayed_new_payment_extends_subscription_created_by_first_payment() -> None:
    initial_expiry = datetime(2036, 8, 20, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        duration=30,
        device_limit=1,
        traffic_limit=0,
        traffic_limit_strategy="NO_RESET",
        tag=None,
        internal_squads=[],
        external_squad=None,
    )
    subscription = SimpleNamespace(
        id=7,
        is_trial=False,
        user_remna_id=UUID("00000000-0000-0000-0000-000000000777"),
        expire_at=initial_expiry,
        grace_until=None,
    )
    user = SimpleNamespace(
        id=42,
        remna_name="paid-user",
        purchase_discount=0,
    )
    transaction = SimpleNamespace(
        id=9,
        purchase_type=PurchaseType.NEW,
        plan_snapshot=plan,
    )
    subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=subscription),
        create=AsyncMock(),
        update=AsyncMock(),
        update_status=AsyncMock(),
    )
    user_dao = SimpleNamespace(set_trial_available=AsyncMock(), update=AsyncMock())
    remnawave = SimpleNamespace(create_user=AsyncMock(), update_user=AsyncMock())
    uow = FakeUnitOfWork()
    purchase = PurchaseSubscription(
        uow=uow,  # type: ignore[arg-type]
        user_dao=user_dao,  # type: ignore[arg-type]
        subscription_dao=subscription_dao,  # type: ignore[arg-type]
        remnawave=remnawave,  # type: ignore[arg-type]
        subscription_mutation_lock=FakeMutationLock(),  # type: ignore[arg-type]
    )

    await purchase._execute(
        SimpleNamespace(log="[SYSTEM]"),
        PurchaseSubscriptionDto(user, transaction, subscription),  # type: ignore[arg-type]
    )

    remnawave.create_user.assert_not_awaited()
    remnawave.update_user.assert_awaited_once()
    subscription_dao.create.assert_not_awaited()
    subscription_dao.update.assert_awaited_once_with(subscription)
    assert subscription.expire_at == initial_expiry + timedelta(days=30)
    assert uow.commits == 1
