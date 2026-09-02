import hashlib
import secrets
from datetime import timedelta
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.dao import TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.use_cases.gateways.commands.payment import (
    PaymentEventNotAppliedError,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.misc.commands.maintenance import (
    CancelOldTransactions,
    ReplayPendingPaymentWebhooks,
    SweepPaymentFulfillments,
    SweepPaymentOperationAlerts,
)
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.infrastructure.taskiq.broker import broker

WEBHOOK_PROCESSING_LEASE = timedelta(minutes=5)
WEBHOOK_RETRY = timedelta(minutes=1)
WEBHOOK_MAX_ATTEMPTS = 5


def _webhook_token_hash() -> str:
    token = secrets.token_urlsafe(32)
    return hashlib.sha256(f"remnashop:webhook:v1\0{token}".encode()).hexdigest()


def _webhook_error_code(exc: Exception) -> str:
    name = "".join(character if character.isalnum() else "_" for character in type(exc).__name__)
    return f"WEBHOOK_{name.upper()}"[:64]


@broker.task()
@inject(patch_module=True)
async def handle_payment_transaction_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    gateway_type: PaymentGatewayType,
    process_payment: FromDishka[ProcessPayment],
    transaction_dao: FromDishka[TransactionDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    await _handle_payment_transaction(
        payment_id=payment_id,
        payment_status=payment_status,
        gateway_type=gateway_type,
        process_payment=process_payment,
        transaction_dao=transaction_dao,
        uow=uow,
    )


async def _handle_payment_transaction(
    *,
    payment_id: UUID,
    payment_status: TransactionStatus,
    gateway_type: PaymentGatewayType,
    process_payment: ProcessPayment,
    transaction_dao: TransactionDao,
    uow: UnitOfWork,
) -> None:
    token_hash = _webhook_token_hash()
    async with uow:
        event = await transaction_dao.claim_webhook_event_by_identity(
            payment_id=payment_id,
            gateway_type=gateway_type,
            status=payment_status,
            token_hash=token_hash,
            lease_for=WEBHOOK_PROCESSING_LEASE,
        )
        await uow.commit()
    if event is None:
        return

    try:
        await process_payment.system(
            ProcessPaymentDto(
                payment_id=payment_id,
                new_transaction_status=payment_status,
                gateway_type=gateway_type,
                selected_payment_method=event.selected_payment_method,
            )
        )
    except Exception as exc:
        manual_required = (
            isinstance(exc, PaymentEventNotAppliedError)
            or event.processing_attempt_count >= WEBHOOK_MAX_ATTEMPTS
        )
        async with uow:
            await transaction_dao.release_webhook_event(
                event.id,
                token_hash=token_hash,
                retry_after=timedelta(0) if manual_required else WEBHOOK_RETRY,
                error_code=_webhook_error_code(exc),
                manual_required=manual_required,
            )
            await uow.commit()
        raise

    async with uow:
        deleted = await transaction_dao.delete_webhook_event(event.id, token_hash=token_hash)
        await uow.commit()
    if not deleted:
        logger.warning(
            "Webhook event '{}' was retained because its processing fence changed",
            event.id,
        )


@broker.task(schedule=[{"cron": "*/30 * * * *"}])
@inject(patch_module=True)
async def cancel_old_transactions_task(
    cancel_old_transactions: FromDishka[CancelOldTransactions],
) -> None:
    await cancel_old_transactions.system()


@broker.task(schedule=[{"cron": "* * * * *"}])
@inject(patch_module=True)
async def sweep_payment_fulfillments_task(
    sweep_payment_fulfillments: FromDishka[SweepPaymentFulfillments],
) -> None:
    await sweep_payment_fulfillments.system()


@broker.task(schedule=[{"cron": "* * * * *"}])
@inject(patch_module=True)
async def replay_pending_payment_webhooks_task(
    replay_pending_payment_webhooks: FromDishka[ReplayPendingPaymentWebhooks],
) -> None:
    await replay_pending_payment_webhooks.system()


@broker.task(schedule=[{"cron": "* * * * *"}])
@inject(patch_module=True)
async def sweep_payment_operation_alerts_task(
    sweep_payment_operation_alerts: FromDishka[SweepPaymentOperationAlerts],
) -> None:
    await sweep_payment_operation_alerts.system()
