from typing import Any, Optional, Union
from uuid import UUID

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from remnapy import RemnawaveSDK
from remnapy.exceptions import NotFoundError

from src.application.common import TranslatorRunner
from src.application.common.dao import (
    PlanDao,
    ReferralDao,
    SubscriptionDao,
    TransactionDao,
    UserDao,
)
from src.application.dto import (
    PlanDurationDto,
    RemnaSubscriptionDto,
    SubscriptionDto,
    TelegramUserDto,
)
from src.application.use_cases.remnawave.queries.squads import (
    GetExternalSquads,
    GetInternalSquads,
)
from src.application.use_cases.statistics.queries.users import GetUserStatistics
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.application.use_cases.user.queries.profile import (
    GetUserDevices,
    GetUserProfile,
    GetUserProfileSubscription,
)
from src.core.constants import (
    DATETIME_VIEW_FORMAT,
    FROM_REFERRAL_USER_ID,
    TARGET_TELEGRAM_ID,
    TARGET_USER_ID,
    USER_KEY,
)
from src.core.enums import PlanAvailability, Role
from src.core.types import RemnaUserDto
from src.core.utils.i18n_helpers import (
    i18n_format_bytes_to_unit,
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.core.utils.i18n_keys import ByteUnitKey


@inject
async def user_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    get_user_profile: FromDishka[GetUserProfile],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    dialog_manager.dialog_data.pop("payload", None)
    target_user_id: int = dialog_manager.start_data[TARGET_USER_ID]  # type: ignore[call-overload, index, assignment]
    dialog_manager.dialog_data[TARGET_USER_ID] = target_user_id
    from_referral_user_id = dialog_manager.start_data.get(FROM_REFERRAL_USER_ID)  # type: ignore[union-attr]
    dialog_manager.dialog_data[FROM_REFERRAL_USER_ID] = from_referral_user_id
    profile = await get_user_profile(user, target_user_id)
    # telegram_id may be None for web-only users; required for redirect operations
    if profile.target_user.telegram_id:
        dialog_manager.dialog_data[TARGET_TELEGRAM_ID] = profile.target_user.telegram_id

    data: dict[str, Any] = {
        "from_referral_user_id": from_referral_user_id,
        "telegram_id": profile.target_user.telegram_id,
        "email": profile.target_user.email,
        "username": profile.target_user.username or False,
        "name": profile.target_user.name,
        "role": profile.target_user.role,
        "language": profile.target_user.language,
        "show_points": profile.show_points,
        "points": profile.target_user.points,
        "personal_discount": profile.target_user.personal_discount,
        "purchase_discount": profile.target_user.purchase_discount,
        "is_blocked": profile.target_user.is_blocked,
        "is_bot_blocked": profile.target_user.is_bot_blocked,
        "is_trial_available": profile.target_user.is_trial_available,
        "is_not_self": profile.target_user.id != user.id,
        "can_edit": profile.can_edit,
        "status": None,
        "is_trial": False,
        "has_subscription": profile.subscription is not None,
    }

    if profile.subscription:
        data.update(
            {
                "status": profile.subscription.current_status,
                "is_trial": profile.subscription.is_trial,
                "plan_name": i18n.get_or_raw(profile.subscription.plan_snapshot.name),
                "traffic_limit": i18n_format_traffic_limit(profile.subscription.traffic_limit),
                "device_limit": i18n_format_device_limit(profile.subscription.device_limit),
                "expire_time": i18n_format_expire_time(profile.subscription.expire_at),
            }
        )

    return data


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    get_user_profile_subscription: FromDishka[GetUserProfileSubscription],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    user_profile_subscription = await get_user_profile_subscription(user, target_user_id)

    subscription = user_profile_subscription.subscription
    remna_user = user_profile_subscription.remna_user

    return {
        "is_trial": subscription.is_trial,
        "is_active": subscription.is_active,
        "has_devices_limit": subscription.has_devices_limit,
        "has_traffic_limit": subscription.has_traffic_limit,
        "url": remna_user.subscription_url,
        #
        "subscription_id": subscription.user_remna_id,
        "subscription_status": subscription.current_status,
        "traffic_used": i18n_format_bytes_to_unit(
            remna_user.used_traffic_bytes,
            min_unit=ByteUnitKey.MEGABYTE,
        ),
        "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
        "device_limit": i18n_format_device_limit(subscription.device_limit),
        "expire_time": i18n_format_expire_time(subscription.expire_at),
        #
        "internal_squads": user_profile_subscription.formatted_internal_squads or False,
        "external_squad": user_profile_subscription.formatted_external_squad or False,
        "first_connected_at": (
            remna_user.first_connected_at.strftime(DATETIME_VIEW_FORMAT)
            if remna_user.first_connected_at
            else False
        ),
        "last_connected_at": (
            remna_user.user_traffic.online_at.strftime(DATETIME_VIEW_FORMAT)
            if remna_user.user_traffic.online_at
            else False
        ),
        "node_name": user_profile_subscription.last_node_name,
        #
        "is_trial_plan": subscription.plan_snapshot.is_trial,
        "plan_name": i18n.get_or_raw(subscription.plan_snapshot.name),
        "plan_type": subscription.plan_snapshot.type,
        "plan_traffic_limit": i18n_format_traffic_limit(subscription.plan_snapshot.traffic_limit),
        "plan_device_limit": i18n_format_device_limit(subscription.plan_snapshot.device_limit),
        "plan_duration": i18n_format_days(subscription.plan_snapshot.duration),
        "can_edit": user_profile_subscription.can_edit,
    }


@inject
async def devices_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    get_user_devices: FromDishka[GetUserDevices],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    data = await get_user_devices(user, target_user_id)

    formatted_devices = [
        {
            "short_hwid": device.hwid[:32],
            "hwid": device.hwid,
            "platform": device.platform,
            "device_model": device.device_model,
            "user_agent": device.user_agent,
        }
        for device in data.devices
    ]

    dialog_manager.dialog_data["hwid_map"] = formatted_devices

    return {
        "current_count": data.current_count,
        "max_count": i18n_format_device_limit(data.max_count),
        "devices": formatted_devices,
    }


async def discount_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"percentages": [0, 5, 10, 25, 40, 50, 70, 80, 100]}


@inject
async def points_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)

    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    formatted_points = [
        {
            "operation": "+" if value > 0 else "",
            "points": value,
        }
        for value in [5, -5, 25, -25, 50, -50, 100, -100]
    ]

    return {
        "current_points": target_user.points,
        "points": formatted_points,
    }


async def traffic_limit_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    formatted_traffic = [
        {
            "traffic_limit": i18n_format_traffic_limit(value),
            "traffic": value,
        }
        for value in [100, 200, 300, 500, 1024, 2048, 0]
    ]

    return {"traffic_count": formatted_traffic}


async def device_limit_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"devices_count": [1, 2, 3, 4, 5, 10, 0]}


@inject
async def squads_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    get_internal_squads: FromDishka[GetInternalSquads],
    get_external_squads: FromDishka[GetExternalSquads],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    target_user = await user_dao.get_by_id(target_user_id)
    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    subscription = await subscription_dao.get_current(target_user.id)

    if not subscription:
        raise ValueError(f"Subscription for user '{target_user_id}' not found")

    internal_squads = await get_internal_squads.system()
    external_squads = await get_external_squads.system()

    internal_dict = {s.uuid: s.name for s in internal_squads}
    internal_names = ", ".join(
        internal_dict.get(uuid, str(uuid)) for uuid in subscription.internal_squads
    )

    external_dict = {s.uuid: s.name for s in external_squads}
    external_name = (
        external_dict.get(subscription.external_squad) if subscription.external_squad else None
    )

    return {
        "internal_squads": internal_names or None,
        "external_squad": external_name or None,
    }


@inject
async def internal_squads_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    get_internal_squads: FromDishka[GetInternalSquads],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    target_user = await user_dao.get_by_id(target_user_id)
    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    subscription = await subscription_dao.get_current(target_user.id)

    if not subscription:
        raise ValueError(f"Current subscription for user '{target_user_id}' not found")

    squads = await get_internal_squads.system()

    return {
        "squads": [
            {
                "uuid": squad.uuid,
                "name": squad.name,
                "selected": squad.uuid in subscription.internal_squads,
            }
            for squad in squads
        ]
    }


@inject
async def external_squads_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    get_external_squads: FromDishka[GetExternalSquads],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    target_user = await user_dao.get_by_id(target_user_id)
    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    subscription = await subscription_dao.get_current(target_user.id)

    if not subscription:
        raise ValueError(f"Current subscription for user '{target_user_id}' not found")

    squads = await get_external_squads.system()
    existing_squad_uuids = {squad.uuid for squad in squads}

    # Compute selected_uuid locally — do NOT mutate subscription (M10 fix)
    selected_uuid = (
        subscription.external_squad if subscription.external_squad in existing_squad_uuids else None
    )

    return {
        "squads": [
            {
                "uuid": squad.uuid,
                "name": squad.name,
                "selected": squad.uuid == selected_uuid,
            }
            for squad in squads
        ]
    }


@inject
async def expire_time_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    target_user = await user_dao.get_by_id(target_user_id)
    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    subscription = await subscription_dao.get_current(target_user.id)

    if not subscription:
        raise ValueError(f"Current subscription for user '{target_user_id}' not found")

    formatted_durations = []
    for value in [1, -1, 3, -3, 7, -7, 14, -14, 30, -30]:
        key, kw = i18n_format_days(value)
        key2, kw2 = i18n_format_days(-value)
        formatted_durations.append(
            {
                "operation": "+" if value > 0 else "-",
                "duration": i18n.get(key, **kw) if value > 0 else i18n.get(key2, **kw2),
                "days": value,
            }
        )

    return {
        "expire_time": i18n_format_expire_time(subscription.expire_at),
        "durations": formatted_durations,
    }


@inject
async def statistics_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    get_user_statistics: FromDishka[GetUserStatistics],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    data = await get_user_statistics(user, target_user_id)

    payment_amounts = (
        "\n".join(
            i18n.get(
                "msg-user-statistics-payment-amount",
                currency=p.currency,
                amount=p.total_amount,
            )
            for p in data.payment_amounts
        )
        or False
    )

    return {
        "has_referrals": data.referrals_level_1 > 0,
        "last_payment_at": data.last_payment_at or 0,
        "payment_amounts": payment_amounts,
        "registered_at": data.registered_at,
        "referrer_telegram_id": data.referrer_telegram_id or 0,
        "referrer_email": data.referrer_email or 0,
        "referrer_username": data.referrer_username or 0,
        "referrals_level_1": data.referrals_level_1,
        "referrals_level_2": data.referrals_level_2,
        "reward_points": data.reward_points,
        "reward_days": data.reward_days,
    }


@inject
async def referrals_getter(
    dialog_manager: DialogManager,
    referral_dao: FromDishka[ReferralDao],
    **kwargs: Any,
) -> dict[str, Any]:
    if TARGET_USER_ID not in dialog_manager.dialog_data:
        dialog_manager.dialog_data[TARGET_USER_ID] = dialog_manager.start_data[TARGET_USER_ID]  # type: ignore[call-overload, index]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    referrals = await referral_dao.get_referrals_list(referrer_id=target_user_id, limit=100)

    return {
        "referrals": [
            {
                "id": r.referred.id,
                "telegram_id": r.referred.telegram_id,
                "name": r.referred.name,
            }
            for r in referrals
        ]
    }


@inject
async def transactions_getter(
    dialog_manager: DialogManager,
    transaction_dao: FromDishka[TransactionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    transactions = await transaction_dao.get_by_user(target_user_id)

    if not transactions:
        return {"transactions": []}

    formatted_transactions = [
        {
            "payment_id": transaction.payment_id,
            "status": transaction.status,
            "created_at": transaction.created_at.strftime(DATETIME_VIEW_FORMAT),  # type: ignore[union-attr]
            "gateway_type": transaction.gateway_type,
        }
        for transaction in transactions
    ]

    return {"transactions": formatted_transactions}


@inject
async def transaction_getter(
    dialog_manager: DialogManager,
    transaction_dao: FromDishka[TransactionDao],
    user_dao: FromDishka[UserDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    if TARGET_USER_ID not in dialog_manager.dialog_data:
        dialog_manager.dialog_data[TARGET_USER_ID] = dialog_manager.start_data.get(  # type: ignore[union-attr]
            TARGET_USER_ID
        )
    if "selected_transaction" not in dialog_manager.dialog_data:
        dialog_manager.dialog_data["selected_transaction"] = UUID(
            dialog_manager.start_data.get("selected_transaction")  # type: ignore[union-attr]
        )
    if "transaction_origin" not in dialog_manager.dialog_data:
        dialog_manager.dialog_data["transaction_origin"] = (
            dialog_manager.start_data.get("origin")  # type: ignore[union-attr]
            if dialog_manager.start_data
            else None
        ) or "user"

    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    selected_transaction = dialog_manager.dialog_data["selected_transaction"]
    origin = dialog_manager.dialog_data["transaction_origin"]
    transaction = await transaction_dao.get_by_payment_id(selected_transaction)

    if not transaction:
        raise ValueError(
            f"Transaction '{selected_transaction}' not found for user '{target_user_id}'"
        )

    initiator = await user_dao.get_by_id(transaction.user_id)

    return {
        "is_from_all_transactions": origin == "all_transactions",
        "user_name": initiator.name if initiator else "—",
        "user_telegram_id": (initiator.telegram_id if initiator else None) or 0,
        "user_email": (initiator.email if initiator else None) or "—",
        "is_test": transaction.is_test,
        "is_trial_plan": transaction.plan_snapshot.is_trial,
        "payment_id": transaction.payment_id,
        "purchase_type": transaction.purchase_type,
        "transaction_status": transaction.status,
        "gateway_type": transaction.gateway_type,
        "final_amount": transaction.pricing.final_amount,
        "currency": transaction.currency.symbol,
        "discount_percent": transaction.pricing.discount_percent,
        "original_amount": transaction.pricing.original_amount,
        "created_at": transaction.created_at.strftime(DATETIME_VIEW_FORMAT),  # type: ignore[union-attr]
        "plan_name": i18n.get_or_raw(transaction.plan_snapshot.name),
        "plan_type": transaction.plan_snapshot.type,
        "plan_traffic_limit": i18n_format_traffic_limit(transaction.plan_snapshot.traffic_limit),
        "plan_device_limit": i18n_format_device_limit(transaction.plan_snapshot.device_limit),
        "plan_duration": i18n_format_days(transaction.plan_snapshot.duration),
    }


@inject
async def give_access_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    user_dao: FromDishka[UserDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)
    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    plans = await plan_dao.filter_by_availability(PlanAvailability.ALLOWED)

    if not plans:
        raise ValueError("Allowed plans not found")

    formatted_plans = [
        {
            "plan_name": i18n.get_or_raw(plan.name),
            "plan_id": plan.id,
            "selected": (
                target_user.telegram_id is not None
                and target_user.telegram_id in plan.allowed_telegram_ids
            )
            or (target_user.email is not None and target_user.email in plan.allowed_emails),
        }
        for plan in plans
    ]

    return {"plans": formatted_plans}


@inject
async def give_subscription_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    i18n: FromDishka[TranslatorRunner],
    get_available_plans: FromDishka[GetAvailablePlans],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)

    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    plans = await get_available_plans.system(target_user)

    if not plans:
        raise ValueError("Available plans not found")

    formatted_plans = [
        {
            "plan_name": i18n.get_or_raw(plan.name),
            "plan_id": plan.id,
        }
        for plan in plans
    ]

    return {"plans": formatted_plans}


@inject
async def subscription_duration_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    selected_plan_id = dialog_manager.dialog_data["selected_plan_id"]
    plan = await plan_dao.get_by_id(selected_plan_id)

    if not plan:
        raise ValueError(f"Plan '{selected_plan_id}' not found")

    return {"durations": retort.dump(plan.durations, list[PlanDurationDto])}


@inject
async def role_getter(
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)

    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    roles = [
        role
        for role in Role
        if role != target_user.role and role not in [Role.SYSTEM, Role.OWNER, Role.PREVIEW]
    ]
    return {"roles": roles[::-1]}


@inject
async def sync_getter(  # noqa: C901
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    remnawave_sdk: FromDishka[RemnawaveSDK],
    **kwargs: Any,
) -> dict[str, Any]:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)

    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    bot_sub = await subscription_dao.get_current(target_user.id)
    remna_sub: Optional[RemnaSubscriptionDto] = None
    remna_updated_at = None

    if target_user.telegram_id:
        try:
            result = await remnawave_sdk.users.get_users_by_telegram_id(
                telegram_id=str(target_user.telegram_id)
            )
            if result:
                remna_user: RemnaUserDto = result[0]
                remna_sub = RemnaSubscriptionDto.from_remna_user(remna_user)
                remna_updated_at = remna_user.updated_at
        except NotFoundError:
            pass

    squads_res = await remnawave_sdk.internal_squads.get_internal_squads()
    squads_map = {s.uuid: s.name for s in squads_res.internal_squads}

    def format_subscription(sub: Union[None, SubscriptionDto, RemnaSubscriptionDto]) -> str:
        if not sub:
            return ""

        sub_id = str(getattr(sub, "user_remna_id", getattr(sub, "uuid", "")))

        squad_names = ", ".join(squads_map.get(s, str(s)) for s in sub.internal_squads)

        kw = {
            "id": sub_id,
            "status": sub.status,
            "url": sub.url,
            "traffic_limit": i18n_format_traffic_limit(sub.traffic_limit),
            "device_limit": i18n_format_device_limit(sub.device_limit),
            "expire_time": i18n_format_expire_time(sub.expire_at),
            "internal_squads": squad_names or False,
            "external_squad": str(sub.external_squad) if sub.external_squad else False,
            "traffic_limit_strategy": sub.traffic_limit_strategy or False,
            "tag": sub.tag or False,
        }
        return i18n.get("msg-user-sync-subscription", **kw)

    bot_version_key = "UNKNOWN"
    remna_version_key = "UNKNOWN"

    if bot_sub and remna_sub:
        if bot_sub.updated_at > remna_updated_at:  # type: ignore[operator]
            bot_version_key, remna_version_key = "NEWER", "OLDER"
        elif bot_sub.updated_at < remna_updated_at:  # type: ignore[operator]
            bot_version_key, remna_version_key = "OLDER", "NEWER"

    return {
        "has_bot_subscription": bool(bot_sub),
        "has_remna_subscription": bool(remna_sub),
        "bot_version": i18n.get("msg-user-sync-version", version=bot_version_key),
        "remna_version": i18n.get("msg-user-sync-version", version=remna_version_key),
        "bot_subscription": format_subscription(bot_sub),
        "remna_subscription": format_subscription(remna_sub),
    }
