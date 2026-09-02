from dataclasses import asdict
from typing import Any, Optional

from aiogram_dialog import DialogManager
from aiogram_dialog.api.exceptions import UnknownIntent
from aiogram_dialog.widgets.common import ManagedScroll
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import TranslatorRunner
from src.application.dto import TelegramUserDto
from src.application.use_cases.promocode.queries.get import GetPromocodeList, GetPromocodeListDto
from src.application.use_cases.statistics.queries.plans import GetPlanStatistics
from src.application.use_cases.statistics.queries.promocodes import (
    GetPromocodeDetailStatistics,
    GetPromocodeStatistics,
)
from src.application.use_cases.statistics.queries.referrals import GetReferralStatistics
from src.application.use_cases.statistics.queries.subscriptions import GetSubscriptionStatistics
from src.application.use_cases.statistics.queries.transactions import GetTransactionStatistics
from src.application.use_cases.statistics.queries.users import GetUsersStatistics
from src.core.constants import USER_KEY
from src.core.enums import Currency, PromocodeRewardType
from src.core.utils.i18n_helpers import i18n_format_days

PROMO_STAT_PAGE_KEY = "promo_stat_page"
PROMO_STAT_ID_KEY = "promo_stat_id"
PROMO_STAT_PAGE_SIZE = 10


def remaining_activations(max_activations: Optional[int], used: int) -> Optional[int]:
    if max_activations is None:
        return None
    return max(0, max_activations - used)


@inject
async def users_getter(
    dialog_manager: DialogManager,
    get_users_statistics: FromDishka[GetUsersStatistics],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    data = await get_users_statistics(user)
    return asdict(data)


@inject
async def transactions_getter(
    dialog_manager: DialogManager,
    get_transaction_statistics: FromDishka[GetTransactionStatistics],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    widget: Optional[ManagedScroll] = dialog_manager.find("scroll_transactions")
    if not widget:
        raise ValueError("scroll_transactions widget not found")

    data = await get_transaction_statistics(user)
    current_page = await widget.get_page()
    total_pages = 1 + len(data.gateway_stats)

    pager_pages = [
        {
            "page": 0,
            "gateway_type": False,
            "is_current": current_page == 0,
        }
    ] + [
        {
            "page": i + 1,
            "gateway_type": g.gateway_type,
            "is_current": current_page == i + 1,
        }
        for i, g in enumerate(data.gateway_stats)
    ]

    if current_page == 0:
        return {
            "pages": total_pages,
            "current_page": 1,
            "pager_pages": pager_pages,
            "gateway_type": False,
            **asdict(data),
            # Normalize None → 0 so the Fluent selector { $popular_gateway -> [0]... } matches.
            "popular_gateway": data.popular_gateway or 0,
        }

    gateway_index = current_page - 1
    if gateway_index >= len(data.gateway_stats):
        await widget.set_page(0)
        return await transactions_getter(
            dialog_manager=dialog_manager,
            get_transaction_statistics=get_transaction_statistics,
            i18n=i18n,
            **kwargs,
        )

    gateway = data.gateway_stats[gateway_index]

    return {
        "pages": total_pages,
        "current_page": current_page + 1,
        "pager_pages": pager_pages,
        "total_transactions": gateway.total_transactions,
        "completed_transactions": gateway.completed_transactions,
        "free_transactions": gateway.free_transactions,
        "gateway_type": gateway.gateway_type,
        "total_income": gateway.total_income,
        "daily_income": gateway.daily_income,
        "weekly_income": gateway.weekly_income,
        "monthly_income": gateway.monthly_income,
        "last_month_income": gateway.last_month_income,
        "average_check": round(gateway.total_income / max(1, gateway.paid_count)),
        "total_discounts": gateway.total_discounts,
        "currency": Currency.from_gateway_type(gateway.gateway_type).symbol,
    }


@inject
async def subscriptions_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    get_subscription_statistics: FromDishka[GetSubscriptionStatistics],
    get_plan_statistics: FromDishka[GetPlanStatistics],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    widget: Optional[ManagedScroll] = dialog_manager.find("scroll_subscriptions")
    if not widget:
        raise ValueError("scroll_subscriptions widget not found")

    common_data = await get_subscription_statistics(user)
    plans_data = await get_plan_statistics(user)
    current_page = await widget.get_page()
    total_pages = 1 + len(plans_data.plans)

    pager_pages = [
        {
            "page": 0,
            "plan_name": False,
            "is_current": current_page == 0,
        }
    ] + [
        {
            "page": i + 1,
            "plan_name": p.plan_name,
            "is_current": current_page == i + 1,
        }
        for i, p in enumerate(plans_data.plans)
    ]

    if current_page == 0:
        return {
            "pages": total_pages,
            "current_page": 1,
            "pager_pages": pager_pages,
            "plan_name": False,
            **asdict(common_data),
        }

    plan_index = current_page - 1
    if plan_index >= len(plans_data.plans):
        await widget.set_page(0)
        return await subscriptions_getter(
            dialog_manager=dialog_manager,
            i18n=i18n,
            get_subscription_statistics=get_subscription_statistics,
            get_plan_statistics=get_plan_statistics,
            **kwargs,
        )

    plan = plans_data.plans[plan_index]

    incomes = [r for r in plans_data.income if r.plan_id == plan.plan_id]
    all_income = (
        "\n".join(
            i18n.get(
                "msg-statistics-subscriptions-plan-income",
                income=r.total_income,
                currency=r.currency,
            )
            for r in incomes
        )
        or "-"
    )

    # None = no data ("unknown"); 0 is a valid duration (unlimited) handled by the formatter.
    duration = plan.popular_duration
    key, kw = ("unknown", {}) if duration is None else i18n_format_days(duration)

    return {
        # asdict(plan) FIRST so the localized popular_duration below is not overwritten
        # by the raw int field it contains.
        **asdict(plan),
        "pages": total_pages,
        "current_page": current_page + 1,
        "pager_pages": pager_pages,
        "all_income": all_income,
        "popular_duration": i18n.get(key, **kw),
    }


@inject
async def promocodes_getter(
    dialog_manager: DialogManager,
    get_promocode_statistics: FromDishka[GetPromocodeStatistics],
    get_promocode_list: FromDishka[GetPromocodeList],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    data = await get_promocode_statistics(user)
    page = dialog_manager.dialog_data.get(PROMO_STAT_PAGE_KEY, 0)
    promos = await get_promocode_list(
        user,
        GetPromocodeListDto(limit=PROMO_STAT_PAGE_SIZE, offset=page * PROMO_STAT_PAGE_SIZE),
    )
    return {
        **asdict(data),
        "promos": [
            {"id": p.id, "code": p.code, "reward_type": p.reward_type.value} for p in promos
        ],
        "has_next": len(promos) == PROMO_STAT_PAGE_SIZE,
        "has_prev": page > 0,
    }


def _detail_reward(
    reward_type: PromocodeRewardType,
    reward: Optional[int],
    plan_snapshot: Optional[dict[str, Any]],
    i18n: TranslatorRunner,
) -> str:
    if reward_type != PromocodeRewardType.SUBSCRIPTION and reward is None:
        return "—"
    plan_name = "—"
    if plan_snapshot:
        raw_name = plan_snapshot.get("name", "?")
        name = i18n.get_or_raw(raw_name) if raw_name else "?"
        duration = plan_snapshot.get("duration")
        plan_name = f"{name} ({i18n.get('unit-day', value=duration)})" if duration else str(name)
    return i18n.get(
        "frg-promocode-reward",
        promocode_type=reward_type.value,
        reward=reward if reward is not None else 0,
        plan_name=plan_name,
    )


@inject
async def promocode_detail_getter(
    dialog_manager: DialogManager,
    get_promocode_detail_statistics: FromDishka[GetPromocodeDetailStatistics],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    promocode_id = dialog_manager.dialog_data[PROMO_STAT_ID_KEY]
    data = await get_promocode_detail_statistics(user, promocode_id)
    if data is None:
        raise UnknownIntent("Promocode not found for detail statistics")

    remaining = remaining_activations(data.max_activations, data.total_activations)
    return {
        "code": data.code,
        "reward": _detail_reward(data.reward_type, data.reward, data.plan_snapshot, i18n),
        "promocode_type": data.reward_type.value,
        "is_active": int(data.is_active),
        "is_reusable": int(data.is_reusable),
        "created_at": data.created_at.strftime("%d.%m.%Y %H:%M"),
        "expires_at": data.expires_at.strftime("%d.%m.%Y %H:%M")
        if data.expires_at is not None
        else i18n.get("unlimited"),
        "max_activations": str(data.max_activations)
        if data.max_activations is not None
        else i18n.get("unlimited"),
        "remaining": str(remaining) if remaining is not None else i18n.get("unlimited"),
        "total_activations": data.total_activations,
        "activations_today": data.activations_today,
        "activations_week": data.activations_week,
        "activations_month": data.activations_month,
    }


@inject
async def referrals_getter(
    dialog_manager: DialogManager,
    get_referral_statistics: FromDishka[GetReferralStatistics],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    data = await get_referral_statistics(user)
    result = asdict(data)
    result["top_referrer_id"] = data.top_referrer_id or 0
    result["top_referrer_telegram_id"] = data.top_referrer_telegram_id or 0
    result["top_referrer_email"] = data.top_referrer_email or 0
    result["top_referrer_username"] = data.top_referrer_username or 0
    return result
