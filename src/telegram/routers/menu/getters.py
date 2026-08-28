from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, Remnawave, TranslatorRunner
from src.application.common.dao import ReferralDao, SettingsDao, SubscriptionDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.misc.queries.menu import GetMenuData
from src.core.config import AppConfig
from src.core.exceptions import MenuRenderError
from src.core.utils.i18n_helpers import (
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.core.utils.time import get_traffic_reset_delta


@inject
async def menu_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    get_menu_data: FromDishka[GetMenuData],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        menu_data = await get_menu_data(user)
        settings = await settings_dao.get()
        support_url = bot_service.get_support_url(text=i18n.get("message.help"))
        web_cabinet_url = config.web_cabinet_url.strip()

        purchase_discount = user.purchase_discount or 0
        personal_discount = user.personal_discount or 0
        show_purchase_discount = purchase_discount > 0 and purchase_discount >= personal_discount
        show_personal_discount = personal_discount > 0 and not show_purchase_discount

        data: dict[str, Any] = {
            # user
            "telegram_id": user.telegram_id,
            "email": user.email,
            "name": user.name,
            "personal_discount": personal_discount,
            "show_personal_discount": show_personal_discount,
            "purchase_discount": purchase_discount,
            "show_purchase_discount": show_purchase_discount,
            # ui / config
            "is_mini_app": config.bot.is_mini_app,
            "is_mini_app_reserve": config.bot.is_mini_app and settings.extra.mini_app_reserve,
            "support_url": support_url,
            "web_enabled": config.web_enabled and bool(web_cabinet_url),
            "web_cabinet_url": web_cabinet_url,
            # referral
            "referral_enabled": menu_data.is_referral_enabled,
            # defaults
            "has_subscription": False,
            "connectable": False,
            "trial_available": False,
            "trial_is_free": True,
            "trial_price": "",
            "has_device_limit": False,
            "is_trial": False,
            # subscription-related (nullable)
            "status": None,
            "subscription_type": None,
            "traffic_limit": None,
            "device_limit": None,
            "expire_time": None,
            "reset_time": None,
            "connection_url": None,
            "subscription_url": None,
            "row_1_buttons": [b for b in menu_data.custom_buttons if b.index in (1, 2)],
            "row_2_buttons": [b for b in menu_data.custom_buttons if b.index in (3, 4)],
            "row_3_buttons": [b for b in menu_data.custom_buttons if b.index in (5, 6)],
        }

        if not menu_data.current_subscription:
            logger.debug(f"{user.log} has no active subscription")
            trial_plan = menu_data.available_trial
            trial_is_free = True
            trial_price_str = ""
            if trial_plan and menu_data.is_trial_available:
                currency = settings.default_currency
                raw_price = trial_plan.durations[0].get_price(currency)
                trial_is_free = raw_price == 0
                trial_price_str = (
                    f"{raw_price.normalize():f} {currency.symbol}" if not trial_is_free else ""
                )
            data["trial_available"] = menu_data.is_trial_available and menu_data.available_trial
            data["trial_is_free"] = trial_is_free
            data["trial_price"] = trial_price_str
            return data

        subscription = menu_data.current_subscription

        data.update(
            {
                "has_subscription": True,
                "is_trial": subscription.is_trial,
                "traffic_strategy": subscription.traffic_limit_strategy,
                "status": subscription.current_status,
                "subscription_type": subscription.limit_type,
                "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
                "device_limit": i18n_format_device_limit(subscription.device_limit),
                "expire_time": i18n_format_expire_time(subscription.expire_at),
                "reset_time": i18n_format_expire_time(
                    get_traffic_reset_delta(
                        subscription.traffic_limit_strategy,
                        subscription.created_at,
                    )
                ),
                "connectable": subscription.is_active,
                "has_device_limit": (
                    subscription.has_devices_limit or subscription.device_limit == 0
                )
                if subscription.is_active
                else False,
                "connection_url": config.bot.mini_app_url
                if isinstance(config.bot.mini_app_url, str)
                else subscription.url,
                "subscription_url": subscription.url,
            }
        )
        logger.debug(f"Menu data for user {user.log}: {data}")
        return data

    except Exception as e:
        raise MenuRenderError(str(e)) from e


def get_platform_icon(i18n: TranslatorRunner, platform: str | None) -> str:
    known_platforms = {"ios", "android", "windows", "macos", "linux"}

    if platform and platform.lower() in known_platforms:
        return i18n.get(f"platform-icon.{platform.lower()}")
    return i18n.get("platform-icon.default")


@inject
async def devices_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
    remnawave: FromDishka[Remnawave],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)

    if not current_subscription:
        raise ValueError(f"Current subscription for user '{user.telegram_id}' not found")

    devices = await remnawave.get_devices(current_subscription.user_remna_id)

    formatted_devices = [
        {
            "index": index,
            "hwid": device.hwid,
            "platform": device.platform or False,
            "device_model": device.device_model or False,
            "user_agent": device.user_agent,
            "platform_icon": get_platform_icon(i18n, device.platform),
            "created_at": device.created_at.strftime("%d.%m.%Y"),
            "label": i18n.get(
                "btn-devices.item",
                platform_icon=get_platform_icon(i18n, device.platform),
                platform=device.platform or False,
                device_model=device.device_model or False,
                created_at=device.created_at.strftime("%d.%m.%Y"),
            ),
        }
        for index, device in enumerate(devices)
    ]

    dialog_manager.dialog_data["hwid_map"] = formatted_devices

    settings = await settings_dao.get()

    return {
        "current_count": len(devices),
        "max_count": current_subscription.device_limit,
        "devices": formatted_devices,
        "devices_empty": len(devices) == 0,
        "has_devices": len(devices) > 0,
        "device_single_enabled": int(settings.extra.device_single_reset.enabled),
        "device_all_enabled": int(settings.extra.device_all_reset.enabled),
        "link_reset_enabled": int(settings.extra.link_reset.enabled),
    }


@inject
async def device_confirm_delete_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    return {
        "device_model": dialog_manager.dialog_data.get("selected_device_model", ""),
        "platform": dialog_manager.dialog_data.get("selected_platform", ""),
        "platform_icon": dialog_manager.dialog_data.get("selected_platform_icon", ""),
        "created_at": dialog_manager.dialog_data.get("selected_created_at", ""),
    }


@inject
async def invite_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    referral_dao: FromDishka[ReferralDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    referrals = await referral_dao.get_referrals_count(user.id)
    payments = await referral_dao.get_referrals_with_payment_count(user.id)
    referral_url = await bot_service.get_referral_url(user.referral_code)
    support_url = bot_service.get_support_url(text=i18n.get("message.withdraw-points"))

    return {
        "reward_type": settings.referral.reward.type,
        "referrals": referrals,
        "payments": payments,
        "points": user.points,
        "is_points_reward": settings.referral.reward.is_points,
        "has_points": True if user.points > 0 else False,
        "referral_url": referral_url,
        "withdraw": support_url,
        "referral_reset_enabled": int(settings.extra.referral_reset.enabled),
    }


@inject
async def invite_about_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    reward_config = settings.referral.reward.config

    max_level = settings.referral.level.value
    identical_reward = settings.referral.reward.is_identical

    reward_levels: dict[str, str] = {}
    for lvl, val in reward_config.items():
        if lvl.value <= max_level:
            reward_levels[f"reward_level_{lvl.value}"] = i18n.get(
                "msg-invite-reward",
                value=val,
                reward_strategy_type=settings.referral.reward.strategy,
                reward_type=settings.referral.reward.type,
            )

    return {
        **reward_levels,
        "reward_type": settings.referral.reward.type,
        "reward_strategy_type": settings.referral.reward.strategy,
        "accrual_strategy": settings.referral.accrual_strategy,
        "identical_reward": identical_reward,
        "max_level": max_level,
    }
