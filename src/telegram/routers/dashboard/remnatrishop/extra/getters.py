from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import SettingsDao


@inject
async def extra_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    extra = settings.extra
    return {
        "grace_enabled": settings.grace.enabled,
        "device_single_enabled": extra.device_single_reset.enabled,
        "device_single_cooldown": extra.device_single_reset.cooldown_hours,
        "device_all_enabled": extra.device_all_reset.enabled,
        "device_all_cooldown": extra.device_all_reset.cooldown_hours,
        "link_reset_enabled": extra.link_reset.enabled,
        "link_reset_cooldown": extra.link_reset.cooldown_hours,
        "referral_reset_enabled": extra.referral_reset.enabled,
        "referral_reset_cooldown": extra.referral_reset.cooldown_hours,
        "trial_channel_guard_enabled": extra.trial_channel_guard,
        "mini_app_reserve_enabled": extra.mini_app_reserve,
        "stars_paid_requirement_enabled": extra.stars_require_paid_purchase,
    }
