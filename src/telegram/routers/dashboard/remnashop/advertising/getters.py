from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService
from src.application.dto import AdLinkDto
from src.application.use_cases.ad_link.queries.list import GetAdLinks
from src.application.use_cases.ad_link.queries.stats import GetAdLinkStats
from src.core.constants import USER_KEY


@inject
async def links_getter(
    dialog_manager: DialogManager,
    get_ad_links: FromDishka[GetAdLinks],
    **kwargs: Any,
) -> dict[str, Any]:
    user = dialog_manager.middleware_data[USER_KEY]
    links = await get_ad_links(user)
    return {
        "links": [
            {"id": lnk.id, "name": lnk.name, "code": lnk.code, "is_active": int(lnk.is_active)}
            for lnk in links
        ],
    }


@inject
async def configurator_getter(
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")
    is_edit = bool(raw and link.id)

    link_url = await bot_service.get_ad_link_url(link.code) if link.code else ""

    return {
        "name": link.name,
        "code": link.code or "0",
        "is_active": int(link.is_active),
        "is_edit": is_edit,
        "link_url": link_url,
    }


@inject
async def name_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")
    return {"name": link.name}


@inject
async def code_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")
    return {"code": link.code or "0"}


@inject
async def stats_getter(
    dialog_manager: DialogManager,
    get_stats: FromDishka[GetAdLinkStats],
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    user = dialog_manager.middleware_data[USER_KEY]
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")
    stats = await get_stats(user, link.id)

    revenue_lines = (
        "\n".join(
            f"• <b>Доход ({currency})</b>: {amount:.2f}"
            for currency, amount in stats.revenue.items()
        )
        or "• <b>Доход</b>: —"
    )

    first_revenue_lines = (
        "\n".join(
            f"• <b>Доход ({currency})</b>: {amount:.2f}"
            for currency, amount in stats.first_purchase_revenue.items()
        )
        or "• <b>Доход</b>: —"
    )

    return {
        "name": link.name,
        "registrations": stats.registrations,
        "trials": stats.trials,
        "buyers": stats.buyers,
        "reg_to_buy_rate": stats.reg_to_buy_rate,
        "trial_to_buy_rate": stats.trial_to_buy_rate,
        "revenue_lines": revenue_lines,
        "first_revenue_lines": first_revenue_lines,
    }
