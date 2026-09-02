from typing import Any

from sqlalchemy import Numeric, and_, case, or_

from src.core.constants import (
    PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256,
    PROVIDER_SUCCEEDED_REFERRAL_REWARD_ID,
    PROVIDER_SUCCEEDED_REFERRAL_SOURCE_TRANSACTION_ID,
)
from src.core.enums import (
    PaymentGatewayType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)

LEGACY_COMPLETED_WITHOUT_PROOF = "LEGACY_COMPLETED_WITHOUT_PROOF"
ADMIN_COMPENSATED_RECOVERY_DECISION = "CONFIRM_ADMIN_COMPENSATED"
OPERATOR_DIRECTED_RECOVERY_DECISION = "RETRY_OPERATOR_DIRECTED"
LOCAL_COMPLETED_SOURCE_VALIDATION = "LOCAL_COMPLETED"
PROVIDER_SUCCEEDED_SOURCE_VALIDATION = "PROVIDER_SUCCEEDED"


def succeeded_referral_source_fulfillment(transaction: Any) -> Any:
    return and_(
        transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED,
        transaction.fulfillment_completed_at.is_not(None),
    )


def exact_legacy_referral_source_fulfillment(transaction: Any) -> Any:
    """Match only the immutable shape written by migration 0049."""

    return and_(
        transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED,
        transaction.fulfillment_completed_at.is_(None),
        transaction.fulfillment_last_error == LEGACY_COMPLETED_WITHOUT_PROOF,
        transaction.fulfillment_started_at.is_not(None),
        transaction.fulfillment_token_hash.is_(None),
        transaction.fulfillment_lease_expires_at.is_(None),
    )


def referral_source_evidence_at(transaction: Any, *, include_legacy: bool) -> Any:
    whens: list[tuple[Any, Any]] = [
        (
            succeeded_referral_source_fulfillment(transaction),
            transaction.fulfillment_completed_at,
        )
    ]
    if include_legacy:
        whens.append(
            (
                exact_legacy_referral_source_fulfillment(transaction),
                transaction.fulfillment_started_at,
            )
        )
    return case(*whens, else_=None)


def normalized_recovered_source_evidence_at(
    resolution: Any,
    transaction: Any,
) -> Any:
    """Order a recovered source by its immutable, audited timestamp kind."""

    selected = resolution.selected_provenance["selected"]
    evidence_kind = selected["source_evidence_timestamp_kind"].astext
    return case(
        (
            evidence_kind == "fulfillment_completed_at",
            transaction.fulfillment_completed_at,
        ),
        (
            evidence_kind == "fulfillment_started_at",
            transaction.fulfillment_started_at,
        ),
        else_=None,
    )


def normalized_admin_compensated_source_evidence_at(
    resolution: Any,
    transaction: Any,
) -> Any:
    """Backward-compatible semantic name for ADMIN recovery predicates."""

    return normalized_recovered_source_evidence_at(resolution, transaction)


def normalized_admin_compensated_source_predicate(
    resolution: Any,
    transaction: Any,
) -> tuple[Any, ...]:
    """Match immutable recovery provenance after mutable refund diagnostics change.

    ``CONFIRM_ADMIN_COMPENSATED`` can only be recorded after strict source
    validation. A later refund deliberately replaces ``fulfillment_last_error``,
    so future ON_FIRST fences must rely on that immutable decision and its
    normalized evidence instead of re-evaluating the historical error string.
    """

    selected = resolution.selected_provenance["selected"]
    fulfillment_status = selected["source_fulfillment_status"].astext
    evidence_kind = selected["source_evidence_timestamp_kind"].astext
    normalized_fulfillment = or_(
        and_(
            fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED.value,
            evidence_kind == "fulfillment_completed_at",
            transaction.fulfillment_completed_at.is_not(None),
        ),
        and_(
            fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED.value,
            evidence_kind == "fulfillment_started_at",
            transaction.fulfillment_started_at.is_not(None),
        ),
    )
    return (
        resolution.decision == ADMIN_COMPENSATED_RECOVERY_DECISION,
        resolution.source_status == TransactionStatus.COMPLETED.value,
        resolution.selected_source_transaction_id == transaction.id,
        transaction.status.in_((TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)),
        normalized_fulfillment,
        transaction.is_test.is_(False),
        transaction.pricing["final_amount"].astext.cast(Numeric) > 0,
        transaction.plan_snapshot["is_trial"].astext == "false",
    )


def paid_nontrial_referral_source_predicate(
    transaction: Any,
    *,
    include_refunded: bool,
    include_legacy: bool,
) -> tuple[Any, ...]:
    statuses = (
        (TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)
        if include_refunded
        else (TransactionStatus.COMPLETED,)
    )
    fulfillment = succeeded_referral_source_fulfillment(transaction)
    if include_legacy:
        fulfillment = or_(
            fulfillment,
            exact_legacy_referral_source_fulfillment(transaction),
        )
    return (
        transaction.status.in_(statuses),
        fulfillment,
        transaction.is_test.is_(False),
        transaction.pricing["final_amount"].astext.cast(Numeric) > 0,
        transaction.plan_snapshot["is_trial"].astext == "false",
    )


def provider_succeeded_local_failed_source_predicate(transaction: Any) -> tuple[Any, ...]:
    """The narrow local shape accepted only after a pinned provider recheck."""

    return (
        transaction.status == TransactionStatus.FAILED,
        transaction.gateway_type == PaymentGatewayType.YOOKASSA,
        transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED,
        transaction.fulfillment_completed_at.is_(None),
        transaction.fulfillment_started_at.is_not(None),
        transaction.fulfillment_token_hash.is_(None),
        transaction.fulfillment_lease_expires_at.is_(None),
        transaction.is_test.is_(False),
        transaction.pricing["final_amount"].astext.cast(Numeric) > 0,
        transaction.plan_snapshot["is_trial"].astext == "false",
    )


def operator_directed_source_predicate(
    resolution: Any,
    transaction: Any,
) -> tuple[Any, ...]:
    """Re-evaluate the source class committed by an operator manifest entry."""

    validation = resolution.selected_provenance["request"]["source_validation"].astext
    return (
        resolution.decision == OPERATOR_DIRECTED_RECOVERY_DECISION,
        resolution.selected_source_transaction_id == transaction.id,
        or_(
            and_(
                validation == LOCAL_COMPLETED_SOURCE_VALIDATION,
                resolution.source_status == TransactionStatus.COMPLETED.value,
                *paid_nontrial_referral_source_predicate(
                    transaction,
                    include_refunded=False,
                    include_legacy=True,
                ),
            ),
            and_(
                validation == PROVIDER_SUCCEEDED_SOURCE_VALIDATION,
                resolution.source_status == TransactionStatus.FAILED.value,
                resolution.reward_id == PROVIDER_SUCCEEDED_REFERRAL_REWARD_ID,
                transaction.id == PROVIDER_SUCCEEDED_REFERRAL_SOURCE_TRANSACTION_ID,
                resolution.evidence_sha256
                == PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256,
                *provider_succeeded_local_failed_source_predicate(transaction),
            ),
        ),
    )
