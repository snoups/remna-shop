from dataclasses import dataclass, field, replace
from typing import Optional

from src.application.common import BotService, Interactor, TranslatorRunner
from src.application.common.dao import PlanDao, SettingsDao, SubscriptionDao
from src.application.common.policy import Permission
from src.application.dto import MenuButtonDto, PlanDto, SubscriptionDto, UserDto
from src.application.use_cases.user.queries.plans import GetAvailableTrial
from src.core.enums import Role


@dataclass(frozen=True)
class GetMenuDataResultDto:
    is_referral_enabled: bool
    is_trial_available: bool
    available_trial: Optional[PlanDto]
    current_subscription: Optional[SubscriptionDto]
    referral_url: str
    custom_buttons: list[MenuButtonDto] = field(default_factory=list)


class GetMenuData(Interactor[None, GetMenuDataResultDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        plan_dao: PlanDao,
        settings_dao: SettingsDao,
        subscription_dao: SubscriptionDao,
        bot_service: BotService,
        i18n: TranslatorRunner,
        get_available_trial: GetAvailableTrial,
    ) -> None:
        self.plan_dao = plan_dao
        self.settings_dao = settings_dao
        self.subscription_dao = subscription_dao
        self.bot_service = bot_service
        self.i18n = i18n
        self.get_available_trial = get_available_trial

    async def _execute(self, actor: UserDto, data: None) -> GetMenuDataResultDto:
        current_subscription = await self.subscription_dao.get_current(actor.id)

        plan = None
        if actor.is_trial_available:
            plan = await self.get_available_trial.system(actor)

        settings = await self.settings_dao.get()
        is_referral_enabled = settings.referral.enable
        referral_url = await self.bot_service.get_referral_url(actor.referral_code)

        custom_buttons = []
        for button in settings.menu.buttons:
            role_ok = actor.role.value >= button.required_role.value
            sub_ok = (
                not button.subscribers_only
                or actor.role > Role.USER
                or (current_subscription is not None and current_subscription.is_active)
            )
            if button.is_active and role_ok and sub_ok:
                custom_buttons.append(
                    replace(button, text=self.i18n.get_or_raw(button.text))
                )

        return GetMenuDataResultDto(
            is_referral_enabled=is_referral_enabled,
            is_trial_available=actor.is_trial_available,
            available_trial=plan,
            current_subscription=current_subscription,
            referral_url=referral_url,
            custom_buttons=custom_buttons,
        )
