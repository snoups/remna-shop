from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import PromocodeDto
from src.application.use_cases.promocode.queries.get import (
    GetPromocodeList,
    GetPromocodeListDto,
)
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.constants import USER_KEY
from src.core.enums import PromocodeAvailability, PromocodeRewardType

PROMO_PAGE_KEY = "promo_page"
PAGE_SIZE = 10
PROMO_PLAN_ID_KEY = "promo_plan_id"


@inject
async def getter_promocodes_main(
    dialog_manager: DialogManager,
    get_promocode_list: FromDishka[GetPromocodeList],
    **kwargs: Any,
) -> dict[str, Any]:
    user = dialog_manager.middleware_data[USER_KEY]
    page = dialog_manager.dialog_data.get(PROMO_PAGE_KEY, 0)
    promos = await get_promocode_list(
        user, GetPromocodeListDto(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    )
    can_manage = PermissionPolicy.has_permission(user, Permission.MANAGE_PROMOCODE)
    return {
        "promos": [
            {
                "id": p.id,
                "code": p.code,
                "reward_type": p.reward_type.value,
            }
            for p in promos
        ],
        "page": page,
        "has_next": len(promos) == PAGE_SIZE,
        "has_prev": page > 0,
        "can_manage": can_manage,
    }


@inject
async def getter_configurator(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    bot_service: FromDishka[BotService],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(PromocodeDto.__name__)

    if raw is None:
        promo = PromocodeDto(
            code="",
            is_active=True,
            reward_type=PromocodeRewardType.DURATION,
            reward=None,  # reward unset until the admin enters a value
            availability=PromocodeAvailability.ALL,
        )
        dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promo)
        dialog_manager.dialog_data.setdefault("is_edit", False)
    else:
        promo = retort.load(raw, PromocodeDto)

    user = dialog_manager.middleware_data[USER_KEY]
    can_manage = PermissionPolicy.has_permission(user, Permission.MANAGE_PROMOCODE)
    is_subscription = promo.reward_type == PromocodeRewardType.SUBSCRIPTION
    promo_url = await bot_service.get_promocode_url(promo.code) if promo.code else ""
    return {
        "is_edit": dialog_manager.dialog_data.get("is_edit", False),
        "promo_url": promo_url,
        "is_active": int(promo.is_active),
        "is_reusable": int(promo.is_reusable),
        "code": promo.code or "—",
        "reward": _reward_display(promo, i18n),
        "promocode_type": promo.reward_type.value,
        "is_subscription": is_subscription,  # used by when= in dialog
        "availability_type": promo.availability.value,  # used by FTL fragment
        "availability": promo.availability.value,  # used by when= in dialog
        "expires": promo.expires_at.strftime("%d.%m.%Y %H:%M")
        if promo.expires_at is not None
        else i18n.get("unlimited"),
        "max_activations": str(promo.max_activations)
        if promo.max_activations is not None
        else i18n.get("unlimited"),
        "can_manage": can_manage,
    }


def _format_plan_snapshot(snapshot: dict[str, Any] | None, i18n: TranslatorRunner) -> str:
    if not snapshot:
        return "—"
    raw_name = snapshot.get("name", "?")
    name = i18n.get(raw_name) if raw_name else "?"
    duration = snapshot.get("duration")
    return f"{name} ({i18n.get('unit-day', value=duration)})" if duration else str(name)


def _reward_display(promo: PromocodeDto, i18n: TranslatorRunner) -> str:
    if promo.reward_type != PromocodeRewardType.SUBSCRIPTION and promo.reward is None:
        return "—"
    return i18n.get(
        "frg-promocode-reward",
        promocode_type=promo.reward_type.value,
        reward=promo.reward if promo.reward is not None else 0,
        plan_name=_format_plan_snapshot(promo.plan_snapshot, i18n),
    )


async def getter_type_select(**kwargs: Any) -> dict[str, Any]:
    return {
        "types": [{"value": t.value} for t in PromocodeRewardType],
    }


@inject
async def getter_plan_select(
    dialog_manager: DialogManager,
    get_available_plans: FromDishka[GetAvailablePlans],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    user = dialog_manager.middleware_data[USER_KEY]
    plans = await get_available_plans.system(user)
    return {
        "plans": [{"id": p.id, "name": i18n.get(p.name)} for p in plans],
    }


@inject
async def getter_plan_duration_select(
    dialog_manager: DialogManager,
    get_available_plans: FromDishka[GetAvailablePlans],
    **kwargs: Any,
) -> dict[str, Any]:
    user = dialog_manager.middleware_data[USER_KEY]
    plan_id = dialog_manager.dialog_data.get(PROMO_PLAN_ID_KEY)
    plans = await get_available_plans.system(user)
    plan = next((p for p in plans if p.id == plan_id), None)
    durations = plan.durations if plan else []
    return {
        "durations": [{"days": d.days} for d in durations],
    }


async def getter_availability_select(**kwargs: Any) -> dict[str, Any]:
    return {
        "availability_types": [{"value": a.value} for a in PromocodeAvailability],
    }


@inject
async def getter_code(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(PromocodeDto.__name__)
    if not raw:
        return {"code": 0}
    promo = retort.load(raw, PromocodeDto)
    return {
        "code": promo.code or 0,
    }


@inject
async def getter_reward(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(PromocodeDto.__name__)
    promo = retort.load(raw, PromocodeDto) if raw else None
    promocode_type = promo.reward_type.value if promo else ""
    # Numeric 0 is the sentinel for "not set" (-> [0] branch shows nothing). A real reward
    # is a pre-rendered string (never numeric 0), so it falls to the [HAS] branch as-is.
    if promo is None or promo.reward is None:
        return {"reward": 0, "promocode_type": promocode_type}
    return {
        "reward": _reward_display(promo, i18n),
        "promocode_type": promocode_type,
    }


@inject
async def getter_expires(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(PromocodeDto.__name__)
    if not raw:
        return {"has_expires": False, "expires": 0}
    promo = retort.load(raw, PromocodeDto)
    return {
        "has_expires": promo.expires_at is not None,
        "expires": promo.expires_at.strftime("%d.%m.%Y %H:%M")
        if promo.expires_at is not None
        else 0,
    }


@inject
async def getter_max_activations(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(PromocodeDto.__name__)
    if not raw:
        return {"has_max_activations": False, "max_activations": 0}
    promo = retort.load(raw, PromocodeDto)
    return {
        "has_max_activations": promo.max_activations is not None,
        "max_activations": str(promo.max_activations) if promo.max_activations is not None else 0,
    }
