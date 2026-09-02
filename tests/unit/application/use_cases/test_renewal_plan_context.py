from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.use_cases.plan.queries.renewal import GetRenewalPlanContext
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.enums import PlanAvailability


def _plan(plan_id: int, availability: PlanAvailability) -> SimpleNamespace:
    return SimpleNamespace(
        id=plan_id,
        name=f"plan-{plan_id}",
        availability=availability,
        is_active=True,
        allowed_telegram_ids=[],
        allowed_emails=[],
    )


def _user(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        telegram_id=user_id,
        email=None,
        log=f"[USER:{user_id}]",
    )


def _subscription(user_id: int, plan_id: int, *, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        is_active=is_active,
        plan_snapshot=SimpleNamespace(id=plan_id),
    )


def _build_use_case(
    *,
    plans: list[SimpleNamespace],
    current_subscription: SimpleNamespace,
    snapshot_plan: SimpleNamespace,
) -> tuple[GetRenewalPlanContext, SimpleNamespace]:
    user_dao = SimpleNamespace(
        has_any_subscription=AsyncMock(return_value=True),
        is_invited_user=AsyncMock(return_value=False),
    )
    plan_dao = SimpleNamespace(
        get_active_plans=AsyncMock(return_value=plans),
        get_by_id=AsyncMock(return_value=snapshot_plan),
    )
    subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=current_subscription),
    )
    get_available_plans = GetAvailablePlans(user_dao, plan_dao)  # type: ignore[arg-type]
    return (
        GetRenewalPlanContext(  # type: ignore[arg-type]
            subscription_dao,
            plan_dao,
            get_available_plans,
        ),
        plan_dao,
    )


async def test_current_active_new_plan_is_available_for_renewal() -> None:
    user = _user(7)
    current_new_plan = _plan(3, PlanAvailability.NEW)
    regular_plan = _plan(8, PlanAvailability.ALL)
    current_subscription = _subscription(user.id, current_new_plan.id)
    use_case, plan_dao = _build_use_case(
        plans=[current_new_plan, regular_plan],
        current_subscription=current_subscription,
        snapshot_plan=current_new_plan,
    )

    context = await use_case._execute(user, user)  # type: ignore[arg-type]

    assert context.current_subscription is current_subscription
    assert context.available_plans == [regular_plan]
    assert [plan.id for plan in context.renewal_plans] == [
        regular_plan.id,
        current_new_plan.id,
    ]
    plan_dao.get_by_id.assert_awaited_once_with(current_new_plan.id)


async def test_unrelated_new_plan_remains_unavailable_during_renewal() -> None:
    user = _user(7)
    current_new_plan = _plan(3, PlanAvailability.NEW)
    unrelated_new_plan = _plan(4, PlanAvailability.NEW)
    regular_plan = _plan(8, PlanAvailability.ALL)
    use_case, _ = _build_use_case(
        plans=[current_new_plan, unrelated_new_plan, regular_plan],
        current_subscription=_subscription(user.id, current_new_plan.id),
        snapshot_plan=current_new_plan,
    )

    context = await use_case._execute(user, user)  # type: ignore[arg-type]

    assert context.available_plans == [regular_plan]
    assert [plan.id for plan in context.renewal_plans] == [
        regular_plan.id,
        current_new_plan.id,
    ]
    assert unrelated_new_plan not in context.renewal_plans


@pytest.mark.parametrize(
    ("subscription_user_id", "is_active"),
    [(8, True), (7, False)],
)
async def test_grandfather_rule_requires_same_user_and_active_subscription(
    subscription_user_id: int,
    is_active: bool,
) -> None:
    user = _user(7)
    current_new_plan = _plan(3, PlanAvailability.NEW)
    regular_plan = _plan(8, PlanAvailability.ALL)
    use_case, plan_dao = _build_use_case(
        plans=[current_new_plan, regular_plan],
        current_subscription=_subscription(
            subscription_user_id,
            current_new_plan.id,
            is_active=is_active,
        ),
        snapshot_plan=current_new_plan,
    )

    context = await use_case._execute(user, user)  # type: ignore[arg-type]

    assert context.available_plans == [regular_plan]
    assert context.renewal_plans == [regular_plan]
    plan_dao.get_by_id.assert_not_awaited()
