from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.dto import PlanDto, PlanSnapshotDto, UserDto


@dataclass(frozen=True)
class MatchPlanDto:
    plan_snapshot: PlanSnapshotDto
    plans: list[PlanDto]


@dataclass(frozen=True)
class RenewPlanResolution:
    plan: Optional[PlanDto]
    terms_changed: bool


def resolve_renew_plan(
    snapshot: PlanSnapshotDto,
    plans: list[PlanDto],
    exact_match: Optional[PlanDto],
) -> RenewPlanResolution:
    if exact_match is not None:
        return RenewPlanResolution(plan=exact_match, terms_changed=False)

    modified_plan = next((plan for plan in plans if plan.id == snapshot.id), None)
    return RenewPlanResolution(
        plan=modified_plan,
        terms_changed=modified_plan is not None,
    )


class MatchPlan(Interactor[MatchPlanDto, Optional[PlanDto]]):
    required_permission = None

    async def _execute(self, actor: UserDto, data: MatchPlanDto) -> Optional[PlanDto]:
        snapshot = data.plan_snapshot

        for plan in data.plans:
            if self._is_plan_equal(snapshot, plan):
                return plan

        if any(plan.id == snapshot.id for plan in data.plans):
            logger.info(
                f"{actor.log} Plan terms changed for snapshot '{snapshot.id}'; "
                "exact match unavailable"
            )
        else:
            logger.warning(f"{actor.log} No matching plan found for snapshot '{snapshot.id}'")
        return None

    def _is_plan_equal(self, snapshot: PlanSnapshotDto, plan: PlanDto) -> bool:
        return (
            snapshot.id == plan.id
            and snapshot.type == plan.type
            and snapshot.traffic_limit == plan.traffic_limit
            and snapshot.device_limit == plan.device_limit
            and snapshot.traffic_limit_strategy == plan.traffic_limit_strategy
            and sorted(snapshot.internal_squads) == sorted(plan.internal_squads)
            and snapshot.external_squad == plan.external_squad
        )
