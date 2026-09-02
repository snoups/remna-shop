from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, TypeVar, cast
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy

from src.application.dto import PlanSnapshotDto, PriceDetailsDto, TransactionDto
from src.core.enums import Currency, PaymentGatewayType, PlanType, PurchaseType, TransactionStatus

SNAPSHOT_VERSION = 1


class InvalidPaymentRecoverySnapshotError(ValueError): ...


EnumValue = TypeVar("EnumValue", bound=Enum)


def _enum_member(value: object, enum_type: type[EnumValue], name: str) -> EnumValue:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}") from exc


def build_resolved_payment_snapshot(transaction: TransactionDto) -> dict[str, Any]:
    plan = transaction.plan_snapshot
    pricing = transaction.pricing
    purchase_type = _enum_member(transaction.purchase_type, PurchaseType, "purchase_type")
    gateway_type = _enum_member(transaction.gateway_type, PaymentGatewayType, "gateway_type")
    currency = _enum_member(transaction.currency, Currency, "currency")
    plan_type = _enum_member(plan.type, PlanType, "plan.type")
    traffic_limit_strategy = _enum_member(
        plan.traffic_limit_strategy,
        TrafficLimitStrategy,
        "plan.traffic_limit_strategy",
    )
    return {
        "version": SNAPSHOT_VERSION,
        "user_id": transaction.user_id,
        "purchase_type": purchase_type.value,
        "gateway_type": gateway_type.value,
        "gateway_display_name": transaction.gateway_display_name,
        "payment_method": transaction.payment_method,
        "pricing": {
            "original_amount": str(pricing.original_amount),
            "discount_percent": pricing.discount_percent,
            "final_amount": str(pricing.final_amount),
        },
        "currency": currency.value,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "tag": plan.tag,
            "type": plan_type.value,
            "traffic_limit_strategy": traffic_limit_strategy.value,
            "traffic_limit": plan.traffic_limit,
            "device_limit": plan.device_limit,
            "duration": plan.duration,
            "internal_squads": [str(value) for value in plan.internal_squads],
            "external_squad": str(plan.external_squad) if plan.external_squad else None,
            "is_trial": plan.is_trial,
        },
    }


def _strict_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}")
    return value


def _strict_str(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _strict_str(value, name)


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}")
    return cast(dict[str, Any], value)


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(_strict_str(value, name))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}") from exc
    if not result.is_finite() or result < 0:
        raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}")
    return result


def transaction_from_resolved_snapshot(  # noqa: C901
    snapshot: dict[str, Any],
    *,
    expected_user_id: int,
    payment_id: UUID,
) -> TransactionDto:
    if set(snapshot) != {
        "version",
        "user_id",
        "purchase_type",
        "gateway_type",
        "gateway_display_name",
        "payment_method",
        "pricing",
        "currency",
        "plan",
    }:
        raise InvalidPaymentRecoverySnapshotError("Unexpected resolved snapshot shape")
    if _strict_int(snapshot["version"], "version", minimum=1) != SNAPSHOT_VERSION:
        raise InvalidPaymentRecoverySnapshotError("Unsupported snapshot version")
    if _strict_int(snapshot["user_id"], "user_id", minimum=1) != expected_user_id:
        raise InvalidPaymentRecoverySnapshotError("Snapshot owner mismatch")

    pricing_data = _object(snapshot["pricing"], "pricing")
    if set(pricing_data) != {"original_amount", "discount_percent", "final_amount"}:
        raise InvalidPaymentRecoverySnapshotError("Unexpected pricing shape")
    pricing = PriceDetailsDto(
        original_amount=_decimal(pricing_data["original_amount"], "original_amount"),
        discount_percent=_strict_int(
            pricing_data["discount_percent"],
            "discount_percent",
        ),
        final_amount=_decimal(pricing_data["final_amount"], "final_amount"),
    )
    if pricing.discount_percent > 100 or pricing.final_amount > pricing.original_amount:
        raise InvalidPaymentRecoverySnapshotError("Invalid pricing relationship")

    plan_data = _object(snapshot["plan"], "plan")
    if set(plan_data) != {
        "id",
        "name",
        "tag",
        "type",
        "traffic_limit_strategy",
        "traffic_limit",
        "device_limit",
        "duration",
        "internal_squads",
        "external_squad",
        "is_trial",
    }:
        raise InvalidPaymentRecoverySnapshotError("Unexpected plan shape")
    raw_internal_squads = plan_data["internal_squads"]
    if not isinstance(raw_internal_squads, list):
        raise InvalidPaymentRecoverySnapshotError("Invalid internal_squads")
    try:
        internal_squads = [
            UUID(_strict_str(value, "internal_squad")) for value in raw_internal_squads
        ]
        raw_external = plan_data["external_squad"]
        external_squad = UUID(_strict_str(raw_external, "external_squad")) if raw_external else None
        plan = PlanSnapshotDto(
            id=_strict_int(plan_data["id"], "plan.id"),
            name=_strict_str(plan_data["name"], "plan.name"),
            tag=_optional_str(plan_data["tag"], "plan.tag"),
            type=PlanType(_strict_str(plan_data["type"], "plan.type")),
            traffic_limit_strategy=TrafficLimitStrategy(
                _strict_str(plan_data["traffic_limit_strategy"], "plan.traffic_limit_strategy")
            ),
            traffic_limit=_strict_int(plan_data["traffic_limit"], "plan.traffic_limit"),
            device_limit=_strict_int(plan_data["device_limit"], "plan.device_limit"),
            duration=_strict_int(plan_data["duration"], "plan.duration"),
            internal_squads=internal_squads,
            external_squad=external_squad,
            is_trial=plan_data["is_trial"],
        )
        if not isinstance(plan.is_trial, bool):
            raise InvalidPaymentRecoverySnapshotError("Invalid plan.is_trial")
        return TransactionDto(
            payment_id=payment_id,
            user_id=expected_user_id,
            status=TransactionStatus.PENDING,
            purchase_type=PurchaseType(_strict_str(snapshot["purchase_type"], "purchase_type")),
            gateway_type=PaymentGatewayType(_strict_str(snapshot["gateway_type"], "gateway_type")),
            gateway_display_name=_optional_str(
                snapshot["gateway_display_name"],
                "gateway_display_name",
            ),
            payment_method=_optional_str(snapshot["payment_method"], "payment_method"),
            pricing=pricing,
            currency=Currency(_strict_str(snapshot["currency"], "currency")),
            plan_snapshot=plan,
        )
    except (ValueError, TypeError) as exc:
        if isinstance(exc, InvalidPaymentRecoverySnapshotError):
            raise
        raise InvalidPaymentRecoverySnapshotError("Invalid resolved snapshot value") from exc


def build_payment_response(
    transaction: TransactionDto,
    *,
    payment_url: str | None,
) -> dict[str, Any]:
    purchase_type = _enum_member(transaction.purchase_type, PurchaseType, "purchase_type")
    status = _enum_member(transaction.status, TransactionStatus, "status")
    currency = _enum_member(transaction.currency, Currency, "currency")
    return {
        "payment_id": str(transaction.payment_id),
        "payment_url": payment_url,
        "purchase_type": purchase_type.value,
        "status": status.value,
        "is_free": transaction.pricing.is_free,
        "final_amount": str(transaction.pricing.final_amount),
        "currency": currency.symbol,
    }
