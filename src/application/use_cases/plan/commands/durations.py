from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor
from src.application.common.policy import Permission
from src.application.dto import PlanDto, PlanDurationDto, PlanPriceDto, UserDto
from src.core.constants import DEFAULT_DURATION_PRICES
from src.core.enums import Currency
from src.core.exceptions import DurationAlreadyExistsError


@dataclass(frozen=True)
class AddPlanDurationDto:
    plan: PlanDto
    input_duration: str


class AddPlanDuration(Interactor[AddPlanDurationDto, PlanDto]):
    required_permission = Permission.REMNASHOP_PLAN_EDITOR

    async def _execute(self, actor: UserDto, data: AddPlanDurationDto) -> PlanDto:
        if data.input_duration == "-1":
            days = 0
        elif data.input_duration.isdigit() and int(data.input_duration) >= 0:
            days = int(data.input_duration)
        else:
            logger.warning(f"{actor.log} Invalid duration input: '{data.input_duration}'")
            raise ValueError(
                f"Duration must be a non-negative integer or -1, got '{data.input_duration}'"
            )

        if any(d.days == days for d in data.plan.durations):
            logger.warning(f"{actor.log} Duration '{days}' already exists in plan")
            raise DurationAlreadyExistsError(f"Duration '{days}' already exists")

        next_order_index = max((d.order_index for d in data.plan.durations), default=0) + 1
        new_duration = PlanDurationDto(
            days=days,
            order_index=next_order_index,
            prices=[PlanPriceDto(currency=c, price=DEFAULT_DURATION_PRICES[c]) for c in Currency],
        )

        data.plan.durations.append(new_duration)
        logger.info(f"{actor.log} Added new duration '{days}' days to plan in memory")
        return data.plan


@dataclass(frozen=True)
class RemovePlanDurationDto:
    plan: PlanDto
    duration: int


class RemovePlanDuration(Interactor[RemovePlanDurationDto, PlanDto]):
    required_permission = Permission.REMNASHOP_PLAN_EDITOR

    async def _execute(self, actor: UserDto, data: RemovePlanDurationDto) -> PlanDto:
        if len(data.plan.durations) <= 1:
            logger.warning(
                f"{actor.log} Failed to remove duration: plan must have at least one duration"
            )
            raise ValueError("Cannot remove the last duration of a plan")

        original_count = len(data.plan.durations)
        data.plan.durations = [d for d in data.plan.durations if d.days != data.duration]

        if len(data.plan.durations) == original_count:
            logger.warning(
                f"{actor.log} Duration '{data.duration}' not found in plan '{data.plan.id}'"
            )
            return data.plan

        logger.info(f"{actor.log} Removed duration '{data.duration}' from plan in memory")
        return data.plan
