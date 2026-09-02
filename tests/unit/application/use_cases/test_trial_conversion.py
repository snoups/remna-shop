from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from src.application.use_cases.subscription.commands.purchase import (
    PurchaseSubscription,
    PurchaseSubscriptionDto,
)
from src.core.enums import PurchaseType, SubscriptionStatus


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeMutationLock:
    def hold(self, user_id: int) -> "FakeMutationLock":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_paid_conversion_updates_trial_in_place_and_preserves_url() -> None:
    remna_id = UUID("00000000-0000-0000-0000-000000000777")
    trial_url = "https://sub.example.com/original-trial-token"
    trial_plan = SimpleNamespace(is_trial=True)
    paid_plan = SimpleNamespace(
        is_trial=False,
        duration=60,
        device_limit=3,
        traffic_limit=100,
        traffic_limit_strategy="NO_RESET",
        tag="paid",
        internal_squads=[UUID("00000000-0000-0000-0000-000000000001")],
        external_squad=None,
    )
    subscription = SimpleNamespace(
        id=7,
        is_trial=True,
        user_remna_id=remna_id,
        status=SubscriptionStatus.EXPIRED,
        expire_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        url=trial_url,
        traffic_limit=0,
        device_limit=1,
        traffic_limit_strategy="NO_RESET",
        tag=None,
        internal_squads=[],
        external_squad=None,
        plan_snapshot=trial_plan,
        grace_until=None,
    )
    paid_expiry = datetime(2026, 11, 1, tzinfo=timezone.utc)
    updated_user = SimpleNamespace(
        uuid=remna_id,
        status=SubscriptionStatus.ACTIVE.value,
        expire_at=paid_expiry,
        subscription_url="https://sub.example.com/unexpected-new-token",
    )
    user = SimpleNamespace(id=42, remna_name="trial-user", purchase_discount=0)
    transaction = SimpleNamespace(
        id=9,
        purchase_type=PurchaseType.NEW,
        plan_snapshot=paid_plan,
    )
    subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=subscription),
        create=AsyncMock(),
        update=AsyncMock(),
        update_status=AsyncMock(),
    )
    remnawave = SimpleNamespace(
        create_user=AsyncMock(),
        update_user=AsyncMock(return_value=updated_user),
    )
    uow = FakeUnitOfWork()
    purchase = PurchaseSubscription(
        uow=uow,  # type: ignore[arg-type]
        user_dao=SimpleNamespace(update=AsyncMock()),  # type: ignore[arg-type]
        subscription_dao=subscription_dao,  # type: ignore[arg-type]
        remnawave=remnawave,  # type: ignore[arg-type]
        subscription_mutation_lock=FakeMutationLock(),  # type: ignore[arg-type]
    )

    await purchase._execute(
        SimpleNamespace(log="[SYSTEM]"),
        PurchaseSubscriptionDto(user, transaction, subscription),  # type: ignore[arg-type]
    )

    subscription_dao.update_status.assert_not_awaited()
    subscription_dao.create.assert_not_awaited()
    subscription_dao.update.assert_awaited_once_with(subscription)
    assert subscription.id == 7
    assert subscription.user_remna_id == remna_id
    assert subscription.url == trial_url
    assert subscription.is_trial is False
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.expire_at == paid_expiry
    assert subscription.plan_snapshot is paid_plan
    assert uow.commits == 1
