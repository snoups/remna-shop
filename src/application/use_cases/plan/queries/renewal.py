from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import PlanDao, SubscriptionDao
from src.application.dto import PlanDto, SubscriptionDto, UserDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.enums import PlanAvailability


@dataclass(frozen=True)
class RenewalPlanContextDto:
    current_subscription: Optional[SubscriptionDto]
    available_plans: list[PlanDto]
    renewal_plans: list[PlanDto]


class GetRenewalPlanContext(Interactor[UserDto, RenewalPlanContextDto]):
    """Return plans eligible for renewing the user's current subscription.

    A ``NEW`` plan remains hidden from normal purchases. The sole exception is
    the active plan referenced by this user's current active subscription.
    """

    required_permission = None

    def __init__(
        self,
        subscription_dao: SubscriptionDao,
        plan_dao: PlanDao,
        get_available_plans: GetAvailablePlans,
    ) -> None:
        self.subscription_dao = subscription_dao
        self.plan_dao = plan_dao
        self.get_available_plans = get_available_plans

    async def _execute(self, actor: UserDto, user: UserDto) -> RenewalPlanContextDto:
        plans = await self.get_available_plans.system(user)
        current_subscription = await self.subscription_dao.get_current(user.id)

        if current_subscription is None:
            return RenewalPlanContextDto(
                current_subscription=None,
                available_plans=plans,
                renewal_plans=plans,
            )

        if current_subscription.user_id != user.id:
            logger.error(
                f"{user.log} Ignoring current subscription with mismatched owner during renewal"
            )
            return RenewalPlanContextDto(
                current_subscription=None,
                available_plans=plans,
                renewal_plans=plans,
            )

        if not current_subscription.is_active:
            return RenewalPlanContextDto(
                current_subscription=current_subscription,
                available_plans=plans,
                renewal_plans=plans,
            )

        snapshot_plan_id = current_subscription.plan_snapshot.id
        if any(plan.id == snapshot_plan_id for plan in plans):
            return RenewalPlanContextDto(
                current_subscription=current_subscription,
                available_plans=plans,
                renewal_plans=plans,
            )

        snapshot_plan = await self.plan_dao.get_by_id(snapshot_plan_id)
        if (
            snapshot_plan is None
            or snapshot_plan.id != snapshot_plan_id
            or not snapshot_plan.is_active
            or snapshot_plan.availability != PlanAvailability.NEW
        ):
            return RenewalPlanContextDto(
                current_subscription=current_subscription,
                available_plans=plans,
                renewal_plans=plans,
            )

        logger.info(
            f"{user.log} Allowing active current plan '{snapshot_plan_id}' for renewal only"
        )
        return RenewalPlanContextDto(
            current_subscription=current_subscription,
            available_plans=plans,
            renewal_plans=[*plans, snapshot_plan],
        )
