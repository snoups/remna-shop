import base64
import io
from typing import Optional
from uuid import UUID

from adaptix import Retort
from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common import Notifier
from src.application.common.dao import PlanDao
from src.application.dto import MediaDescriptorDto, MessagePayloadDto, PlanDto, TelegramUserDto
from src.application.use_cases.plan.commands.access import (
    AddAllowedUserToPlan,
    AddAllowedUserToPlanDto,
)
from src.application.use_cases.plan.commands.commit import CommitPlan, CommitPlansBatch
from src.application.use_cases.plan.commands.durations import (
    AddPlanDuration,
    AddPlanDurationDto,
    RemovePlanDuration,
    RemovePlanDurationDto,
)
from src.application.use_cases.plan.commands.edit import (
    UpdatePlanDescription,
    UpdatePlanDescriptionDto,
    UpdatePlanDevice,
    UpdatePlanDeviceDto,
    UpdatePlanName,
    UpdatePlanNameDto,
    UpdatePlanPrice,
    UpdatePlanPriceDto,
    UpdatePlanTag,
    UpdatePlanTagDto,
    UpdatePlanTraffic,
    UpdatePlanTrafficDto,
    UpdatePlanType,
    UpdatePlanTypeDto,
)
from src.application.use_cases.plan.commands.order import (
    DeletePlan,
    MoveDurationUp,
    MoveDurationUpDto,
    MovePlanUp,
)
from src.application.use_cases.plan.commands.squads import (
    SanitizePlanSquads,
    SanitizePlanSquadsDto,
)
from src.application.use_cases.plan.exchange import ExportPlans, ParsePlansImport
from src.application.use_cases.plan.queries.squads import CheckSquadsAvailable
from src.core.constants import USER_KEY
from src.core.enums import Currency, MediaType, PlanAvailability, PlanType
from src.core.exceptions import (
    DurationAlreadyExistsError,
    PlanError,
    PlanNameAlreadyExistsError,
    SquadsEmptyError,
    TrialDurationError,
    UserAlreadyAllowedError,
)
from src.telegram.states import RemnashopPlans
from src.telegram.utils import is_double_click


@inject
async def on_import_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    bot: FromDishka[Bot],
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    parse_plans: FromDishka[ParsePlansImport],
    commit_plans_batch: FromDishka[CommitPlansBatch],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.document:
        await notifier.notify_user(user, i18n_key="ntf-plan.not-file")
        return

    file_in_memory = io.BytesIO()
    await bot.download(message.document.file_id, destination=file_in_memory)
    content = file_in_memory.getvalue().decode("utf-8")
    logger.info(
        f"{user.log} Received import file '{message.document.file_name}' and started processing"
    )

    try:
        plans = await parse_plans(user, content)

        if len(plans) == 1:
            plan = plans[0]
            dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
            logger.info(f"{user.log} Single plan '{plan.name}' loaded into configurator")
            await dialog_manager.switch_to(RemnashopPlans.CONFIGURATOR)
            return

        await commit_plans_batch(user, plans)

        await notifier.notify_user(user, MessagePayloadDto(i18n_key="ntf-plan.import-success"))
        await dialog_manager.switch_to(RemnashopPlans.MAIN)

    except Exception as e:
        logger.warning(f"{user.log} Plan import failed with message: '{e}'")
        await notifier.notify_user(user, MessagePayloadDto(i18n_key="ntf-plan.import-failed"))


async def on_export_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan: int,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    selected_plans: list = dialog_manager.dialog_data.get("selected_plans", [])

    if selected_plan in selected_plans:
        selected_plans.remove(selected_plan)
        logger.info(f"{user.log} Unselect plan '{selected_plan}' for export")
    else:
        selected_plans.append(selected_plan)
        logger.info(f"{user.log} Select plan '{selected_plan}' for export")

    dialog_manager.dialog_data["selected_plans"] = selected_plans


@inject
async def on_export(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    export_plans: FromDishka[ExportPlans],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    selected_plans: list = dialog_manager.dialog_data.get("selected_plans", [])

    if not selected_plans:
        await notifier.notify_user(user, i18n_key="ntf-plan.export-plans-not-selected")
        return

    try:
        raw_json = await export_plans(user, selected_plans)
        json_bytes = raw_json.encode("utf-8")

        media = MediaDescriptorDto(
            kind="bytes",
            value=base64.b64encode(json_bytes).decode("ascii"),
            filename="exported_plans.json",
        )

        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-plan.export-success",
                media=media,
                media_type=MediaType.DOCUMENT,
                disable_default_markup=False,
                delete_after=None,
            ),
        )
        logger.info(f"{user.log} Exported '{len(selected_plans)}' plans successfully")
        await dialog_manager.switch_to(state=RemnashopPlans.MAIN)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-plan.export-failed")


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    plan_dao: FromDishka[PlanDao],
) -> None:
    plan_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan: Optional[PlanDto] = await plan_dao.get_by_id(plan_id)

    if not plan:
        raise ValueError(f"Attempted to select non-existent plan '{plan_id}'")

    logger.info(f"{user.log} Selected plan '{plan.id}'")

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    dialog_manager.dialog_data["is_edit"] = True
    await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)


@inject
async def on_plan_move(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    move_plan_up: FromDishka[MovePlanUp],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await move_plan_up(user, int(dialog_manager.item_id))  # type: ignore[attr-defined]


@inject
async def on_plan_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    delete_plan: FromDishka[DeletePlan],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    if is_double_click(dialog_manager, key=f"delete_confirm_{plan.id}", cooldown=10):
        await delete_plan(user, plan.id)

        await notifier.notify_user(user, i18n_key="ntf-plan.deleted")
        await dialog_manager.start(state=RemnashopPlans.MAIN, mode=StartMode.RESET_STACK)
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
    logger.debug(f"{user.log} Clicked delete for plan ID '{plan.id}' (awaiting confirmation)")


@inject
async def on_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_name: FromDishka[UpdatePlanName],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_name(user, UpdatePlanNameDto(current_plan, message.text))
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)

    except PlanNameAlreadyExistsError:
        await notifier.notify_user(user, i18n_key="ntf-plan.name-already-exists")
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_description_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_description: FromDishka[UpdatePlanDescription],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_description(
            user,
            UpdatePlanDescriptionDto(current_plan, message.text),
        )

        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_description_remove(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.description = None

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    logger.info(f"{user.log} Removed description for plan ID '{plan.id}'")


@inject
async def on_tag_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_tag: FromDishka[UpdatePlanTag],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_tag(user, UpdatePlanTagDto(current_plan, message.text))
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_tag_remove(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.tag = None

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    logger.info(f"{user.log} Removed tag for plan ID '{plan.id}'")


# NOTE: The following toggles/selects mutate an in-memory PlanDto draft kept in
# dialog_data during the configuration stage. Nothing is persisted until CommitPlan,
# so these trivial flag/enum flips are a deliberate exception to "no business logic in
# handlers" — extracting them into use cases would add classes without value. Non-trivial
# logic (validation, parsing, persistence) stays in use cases.
@inject
async def on_trial_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.is_trial = not plan.is_trial

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    logger.info(f"{user.log} Toggled trial status for plan ID '{plan.id}'")


@inject
async def on_type_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_type: PlanType,
    retort: FromDishka[Retort],
    update_plan_type: FromDishka[UpdatePlanType],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    updated_plan = await update_plan_type(user, UpdatePlanTypeDto(current_plan, selected_type))

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
    await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)


@inject
async def on_availability_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_availability: PlanAvailability,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.availability = selected_availability
    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)

    logger.info(f"{user.log} Updated plan availability to '{selected_availability.name}'")
    await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.is_active = not plan.is_active

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    logger.info(f"{user.log} Toggled plan active status to '{plan.is_active}'")


@inject
async def on_traffic_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_traffic: FromDishka[UpdatePlanTraffic],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_traffic(
            user,
            UpdatePlanTrafficDto(current_plan, message.text),
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_strategy_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_strategy: TrafficLimitStrategy,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    plan.traffic_limit_strategy = selected_strategy
    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)

    logger.info(f"{user.log} Updated plan traffic strategy to '{selected_strategy.name}'")
    await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)


@inject
async def on_devices_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_device: FromDishka[UpdatePlanDevice],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_device(
            user,
            UpdatePlanDeviceDto(current_plan, message.text),
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.CONFIGURATOR)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_duration_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    duration_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    dialog_manager.dialog_data["selected_duration"] = duration_id

    logger.debug(f"{user.log} Selected duration '{duration_id}'")
    await dialog_manager.switch_to(state=RemnashopPlans.PRICES)


@inject
async def on_duration_move(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    move_duration_up: FromDishka[MoveDurationUp],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    plan = await move_duration_up(
        user,
        MoveDurationUpDto(current_plan, int(dialog_manager.item_id)),  # type: ignore[attr-defined]
    )

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)


@inject
async def on_duration_remove(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    remove_plan_duration: FromDishka[RemovePlanDuration],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    duration_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await remove_plan_duration(
            user,
            RemovePlanDurationDto(current_plan, duration_id),
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        logger.debug(f"{user.log} UI updated after duration removal")

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_duration_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    add_plan_duration: FromDishka[AddPlanDuration],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await add_plan_duration(user, AddPlanDurationDto(current_plan, message.text))
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.DURATIONS)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
    except DurationAlreadyExistsError:
        await notifier.notify_user(user, i18n_key="ntf-plan.duration-already-exists")


async def on_currency_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_currency: Currency,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    dialog_manager.dialog_data["selected_currency"] = selected_currency.value
    logger.info(f"{user.log} Selected currency '{selected_currency.name}'")
    await dialog_manager.switch_to(state=RemnashopPlans.PRICE)


@inject
async def on_price_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_plan_price: FromDishka[UpdatePlanPrice],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    duration_days = dialog_manager.dialog_data.get("selected_duration")
    currency_val = dialog_manager.dialog_data.get("selected_currency")

    if duration_days is None or currency_val is None:
        raise ValueError("Missing selection context in dialog data")

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await update_plan_price(
            user,
            UpdatePlanPriceDto(
                current_plan,
                duration_days,
                Currency(currency_val),
                message.text,
            ),
        )

        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)
        await dialog_manager.switch_to(state=RemnashopPlans.PRICES)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_allowed_user_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    add_allowed_user: FromDishka[AddAllowedUserToPlan],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    current_plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    try:
        updated_plan = await add_allowed_user(
            user,
            AddAllowedUserToPlanDto(plan=current_plan, input_value=message.text),
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(updated_plan)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
    except UserAlreadyAllowedError:
        await notifier.notify_user(user, i18n_key="ntf-plan.user-already-allowed")


@inject
async def on_allowed_user_remove(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    item_id: str = dialog_manager.item_id  # type: ignore[attr-defined]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    if item_id.startswith("tg:"):
        tg_id = int(item_id[3:])
        if tg_id in plan.allowed_telegram_ids:
            plan.allowed_telegram_ids.remove(tg_id)
            dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
            logger.info(f"{user.log} Removed allowed telegram ID '{tg_id}' from plan in memory")
        else:
            logger.warning(
                f"{user.log} Tried to remove non-existent telegram ID '{tg_id}' from plan"
            )
    elif item_id.startswith("em:"):
        email = item_id[3:]
        if email in plan.allowed_emails:
            plan.allowed_emails.remove(email)
            dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
            logger.info(f"{user.log} Removed allowed email '{email}' from plan in memory")
        else:
            logger.warning(f"{user.log} Tried to remove non-existent email '{email}' from plan")


@inject
async def on_squads(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    check_squads: FromDishka[CheckSquadsAvailable],
    sanitize_squads: FromDishka[SanitizePlanSquads],
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not await check_squads(user):
        logger.warning(f"{user.log} Cancelled transition: squads list is empty")
        await notifier.notify_user(user, i18n_key="ntf-common.squads-empty")
        return

    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    sanitized = await sanitize_squads(user, SanitizePlanSquadsDto(plan=plan))
    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(sanitized)

    await dialog_manager.switch_to(state=RemnashopPlans.SQUADS)


@inject
async def on_internal_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    if selected_squad in plan.internal_squads:
        plan.internal_squads.remove(selected_squad)
        logger.info(f"{user.log} Removed squad '{selected_squad}' from plan")
    else:
        plan.internal_squads.append(selected_squad)
        logger.info(f"{user.log} Added squad '{selected_squad}' to plan")

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)


@inject
async def on_external_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    if selected_squad == plan.external_squad:
        plan.external_squad = None
        logger.info(f"{user.log} Removed squad '{selected_squad}' from plan")
    else:
        plan.external_squad = selected_squad
        logger.info(f"{user.log} Added squad '{selected_squad}' to plan")

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)


@inject
async def on_plan_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    commit_plan: FromDishka[CommitPlan],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan_dto = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    # Guard against accidental double-submit (same as plan deletion): require an
    # explicit second click within the cooldown before committing.
    if not is_double_click(dialog_manager, key=f"plan_confirm_{plan_dto.id}", cooldown=10):
        await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
        logger.debug(f"{user.log} Clicked confirm for plan (awaiting confirmation)")
        return

    try:
        result = await commit_plan(user, plan_dto)

        if result.is_created:
            i18n_key = "ntf-plan.created"
        else:
            i18n_key = "ntf-plan.updated"

        await notifier.notify_user(user, i18n_key=i18n_key)
        await dialog_manager.reset_stack()
        await dialog_manager.start(state=RemnashopPlans.MAIN)

    except PlanError as e:
        error_map = {
            SquadsEmptyError: "ntf-common.internal-squads-empty",
            TrialDurationError: "ntf-plan.trial-single-duration",
            PlanNameAlreadyExistsError: "ntf-plan.name-already-exists",
        }

        i18n_key = error_map.get(type(e), "ntf-error.unknown")

        await notifier.notify_user(user, i18n_key=i18n_key)
