from types import SimpleNamespace

from src.application.use_cases.plan.queries.match import (
    MatchPlan,
    MatchPlanDto,
    resolve_renew_plan,
)


def _plan(plan_id: int, device_limit: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=plan_id,
        type="DEVICES",
        traffic_limit=0,
        device_limit=device_limit,
        traffic_limit_strategy="NO_RESET",
        internal_squads=[],
        external_squad=None,
    )


async def test_changed_terms_are_not_reported_as_missing_plan() -> None:
    matcher = object.__new__(MatchPlan)
    snapshot = _plan(plan_id=1, device_limit=1)
    changed_plan = _plan(plan_id=1, device_limit=2)

    exact = await matcher._execute(
        SimpleNamespace(log="[SYSTEM]"),  # type: ignore[arg-type]
        MatchPlanDto(plan_snapshot=snapshot, plans=[changed_plan]),  # type: ignore[arg-type]
    )
    resolution = resolve_renew_plan(snapshot, [changed_plan], exact)  # type: ignore[arg-type]

    assert exact is None
    assert resolution.plan is changed_plan
    assert resolution.terms_changed is True


async def test_removed_plan_remains_unavailable() -> None:
    matcher = object.__new__(MatchPlan)
    snapshot = _plan(plan_id=1, device_limit=1)
    another_plan = _plan(plan_id=2, device_limit=1)

    exact = await matcher._execute(
        SimpleNamespace(log="[SYSTEM]"),  # type: ignore[arg-type]
        MatchPlanDto(plan_snapshot=snapshot, plans=[another_plan]),  # type: ignore[arg-type]
    )
    resolution = resolve_renew_plan(snapshot, [another_plan], exact)  # type: ignore[arg-type]

    assert exact is None
    assert resolution.plan is None
    assert resolution.terms_changed is False
