from decimal import Decimal
from typing import Any, Optional, Union

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common import BotService, Remnawave, TranslatorRunner
from src.application.common.dao import PlanDao
from src.application.dto import PlanDto, PlanDurationDto, PlanPriceDto
from src.core.enums import Currency, PlanAvailability, PlanType


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_dao.get_all()

    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "is_active": plan.is_active,
        }
        for plan in plans
    ]

    return {
        "has_plans": bool(plans),
        "plans": formatted_plans,
    }


@inject
async def export_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_dao.get_all()
    selected_plans = dialog_manager.dialog_data.get("selected_plans", [])

    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "selected": plan.id in selected_plans,
        }
        for plan in plans
    ]

    return {
        "plans": formatted_plans,
    }


@inject
async def configurator_getter(
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if raw_plan is None:
        plan = PlanDto(
            name=i18n.get("plan-default-name"),
            durations=[
                PlanDurationDto(
                    days=7,
                    order_index=1,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(0.5)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(30)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(50)),
                    ],
                ),
                PlanDurationDto(
                    days=30,
                    order_index=2,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(1)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(60)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(100)),
                    ],
                ),
                PlanDurationDto(
                    days=365,
                    order_index=3,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(10)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(600)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(1000)),
                    ],
                ),
                PlanDurationDto(
                    days=0,
                    order_index=4,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(100)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(6000)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(10000)),
                    ],
                ),
            ],
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    else:
        plan = retort.load(raw_plan, PlanDto)

    helpers = {
        "name": plan.name,
        "is_edit": dialog_manager.dialog_data.get("is_edit", False),
        "is_unlimited_traffic": plan.is_unlimited_traffic,
        "is_unlimited_devices": plan.is_unlimited_devices,
        "plan_type": plan.type,
        "availability_type": plan.availability,
        "plan_url": f"{await bot_service.get_plan_url(plan.public_code)}"
        if plan.public_code
        else False,
    }

    data: dict = retort.dump(plan)
    data.update(helpers)
    return data


@inject
async def name_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"name": plan.name}


@inject
async def description_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"description": plan.description}


@inject
async def tag_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"tag": plan.tag}


@inject
async def type_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {
        "is_trial": plan.is_trial,
        "types": list(PlanType),
    }


async def availability_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"availability": list(PlanAvailability)}


@inject
async def traffic_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    strategys = [
        {
            "strategy": strategy,
            "selected": strategy.name == plan.traffic_limit_strategy,
        }
        for strategy in TrafficLimitStrategy
    ]

    return {"strategys": strategys}


@inject
async def durations_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    durations = [retort.dump(duration) for duration in plan.durations]

    return {
        "deletable": len(durations) > 1,
        "durations": durations,
    }


def get_prices_for_duration(
    durations: list[PlanDurationDto],
    target_days: int,
) -> Optional[list[PlanPriceDto]]:
    for duration in durations:
        if duration.days == target_days:
            return duration.prices
    return []


@inject
async def prices_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    prices = get_prices_for_duration(plan.durations, selected_duration)
    prices_data = [retort.dump(price) for price in prices] if prices else []

    return {
        "duration": selected_duration,
        "prices": prices_data,
    }


async def price_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    selected_duration = dialog_manager.dialog_data.get("selected_duration")
    selected_currency = dialog_manager.dialog_data.get("selected_currency")
    return {
        "duration": selected_duration,
        "currency": selected_currency,
    }


@inject
async def allowed_users_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    combined: list[str] = [f"tg:{tg_id}" for tg_id in plan.allowed_telegram_ids]
    combined += [f"em:{email}" for email in plan.allowed_emails]
    return {"allowed_users": combined}


@inject
async def squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    internal_dict = {s.uuid: s.name for s in await remnawave.get_internal_squads()}

    if not plan.internal_squads:
        internal_squads_data: Union[str, bool] = False
    else:
        internal_squads_data = ", ".join(
            internal_dict.get(squad, str(squad)) for squad in plan.internal_squads
        )

    external_dict = {s.uuid: s.name for s in await remnawave.get_external_squads()}
    external_squad_data = external_dict.get(plan.external_squad) if plan.external_squad else False

    return {
        "internal_squads": internal_squads_data,
        "external_squad": external_squad_data,
    }


@inject
async def internal_squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid in plan.internal_squads,
        }
        for squad in await remnawave.get_internal_squads()
    ]

    return {
        "squads": squads,
    }


@inject
async def external_squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid == plan.external_squad,
        }
        for squad in await remnawave.get_external_squads()
    ]

    return {
        "squads": squads,
    }
