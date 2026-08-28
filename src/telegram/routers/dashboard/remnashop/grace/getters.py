from typing import Any, Union

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common import Remnawave
from src.application.common.dao import SettingsDao


@inject
async def grace_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    grace = (await settings_dao.get()).grace

    internal_dict = {s.uuid: s.name for s in await remnawave.get_internal_squads()}
    if not grace.internal_squads:
        internal_squads_data: Union[str, bool] = False
    else:
        internal_squads_data = ", ".join(
            internal_dict.get(squad, str(squad)) for squad in grace.internal_squads
        )

    external_dict = {s.uuid: s.name for s in await remnawave.get_external_squads()}
    external_squad_data = external_dict.get(grace.external_squad) if grace.external_squad else False

    return {
        "enabled": grace.enabled,
        "traffic_mb": grace.traffic_mb,
        "strategy": grace.traffic_strategy,
        "duration_days": grace.duration_days,
        "tag": grace.tag or False,
        "internal_squads": internal_squads_data,
        "external_squad": external_squad_data,
    }


@inject
async def grace_value_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    grace = (await settings_dao.get()).grace
    return {
        "traffic_mb": grace.traffic_mb,
        "duration_days": grace.duration_days,
        "tag": grace.tag or False,
    }


@inject
async def grace_strategy_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    grace = (await settings_dao.get()).grace

    strategys = [
        {
            "strategy": strategy,
            "selected": strategy == grace.traffic_strategy,
        }
        for strategy in TrafficLimitStrategy
    ]

    return {"strategys": strategys}


@inject
async def grace_internal_squads_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    grace = (await settings_dao.get()).grace

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid in grace.internal_squads,
        }
        for squad in await remnawave.get_internal_squads()
    ]

    return {"squads": squads}


@inject
async def grace_external_squads_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    grace = (await settings_dao.get()).grace

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid == grace.external_squad,
        }
        for squad in await remnawave.get_external_squads()
    ]

    return {"squads": squads}
