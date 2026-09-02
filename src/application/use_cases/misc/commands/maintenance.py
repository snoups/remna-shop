import hashlib
import secrets
from datetime import timedelta

from loguru import logger

from src.application.common import Interactor, Notifier
from src.application.common.dao import (
    BroadcastDao,
    PaymentOperationDao,
    TransactionDao,
    UserDao,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MessagePayloadDto,
    PaymentWebhookEventDto,
    TransactionDto,
    UserDto,
)
from src.application.use_cases.gateways.commands.payment import (
    PaymentEventNotAppliedError,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.core.enums import Currency, Role, SystemNotificationType

FULFILLMENT_SWEEP_BATCH = 100
WEBHOOK_REPLAY_BATCH = 100
WEBHOOK_RETENTION = timedelta(days=7)
PAYMENT_OPERATION_ALERT_BATCH = 100
ALERT_LEASE = timedelta(minutes=5)
ALERT_RETRY = timedelta(minutes=5)
WEBHOOK_PROCESSING_LEASE = timedelta(minutes=15)
WEBHOOK_RETRY = timedelta(minutes=1)
WEBHOOK_MAX_ATTEMPTS = 5


def _alert_token_hash(kind: str) -> str:
    token = secrets.token_urlsafe(32)
    return hashlib.sha256(f"remnashop:{kind}:v1\0{token}".encode()).hexdigest()


def _webhook_error_code(exc: Exception) -> str:
    name = "".join(character if character.isalnum() else "_" for character in type(exc).__name__)
    return f"WEBHOOK_{name.upper()}"[:64]


class CancelOldTransactions(Interactor[None, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, transaction_dao: TransactionDao) -> None:
        self.uow = uow
        self.transaction_dao = transaction_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            await self.transaction_dao.cancel_old()
            await self.uow.commit()

        logger.info("Canceled old transactions from database")


class SweepPaymentFulfillments(Interactor[None, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        transaction_dao: TransactionDao,
        user_dao: UserDao,
        notifier: Notifier,
    ) -> None:
        self.uow = uow
        self.transaction_dao = transaction_dao
        self.user_dao = user_dao
        self.notifier = notifier

    async def _execute(self, actor: UserDto, data: None) -> None:
        token_hash = _alert_token_hash("fulfillment-alert")
        async with self.uow:
            expired = await self.transaction_dao.expire_fulfillments(
                limit=FULFILLMENT_SWEEP_BATCH
            )
            transactions = await self.transaction_dao.claim_manual_fulfillment_alerts(
                token_hash=token_hash,
                lease_for=ALERT_LEASE,
                limit=FULFILLMENT_SWEEP_BATCH,
            )
            alerts = [
                (transaction, await self.user_dao.get_by_id(transaction.user_id))
                for transaction in transactions
            ]
            await self.uow.commit()

        for transaction, user in alerts:
            try:
                await self._notify(transaction, user)
            except Exception:
                logger.exception(
                    "Failed to alert manual payment fulfillment '{}'",
                    transaction.payment_id,
                )
                async with self.uow:
                    await self.transaction_dao.release_fulfillment_alert(
                        transaction.payment_id,
                        token_hash=token_hash,
                        retry_after=ALERT_RETRY,
                    )
                    await self.uow.commit()
                continue
            async with self.uow:
                await self.transaction_dao.mark_fulfillment_alerted(
                    transaction.payment_id,
                    token_hash=token_hash,
                )
                await self.uow.commit()

        if expired or alerts:
            logger.warning(
                "Payment fulfillment sweep expired '{}' and processed '{}' alerts",
                expired,
                len(alerts),
            )

    async def _notify(
        self,
        transaction: TransactionDto,
        user: UserDto | None,
    ) -> None:
        await self.notifier.notify_system(
            MessagePayloadDto(
                i18n_key="event-payment.purchase-failed",
                i18n_kwargs={
                    "payment_id": str(transaction.payment_id),
                    "gateway_type": transaction.gateway_type,
                    "final_amount": transaction.pricing.final_amount,
                    "original_amount": transaction.pricing.original_amount,
                    "discount_percent": transaction.pricing.discount_percent,
                    "currency": transaction.currency.symbol,
                    "telegram_id": user.telegram_id if user and user.telegram_id else 0,
                    "username": user.username if user and user.username else 0,
                    "name": user.name if user else f"user:{transaction.user_id}",
                    "email": user.email if user else None,
                },
            ),
            roles=[Role.OWNER, Role.DEV],
            notification_type=SystemNotificationType.SYSTEM,
        )


class ReplayPendingPaymentWebhooks(Interactor[None, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        transaction_dao: TransactionDao,
        process_payment: ProcessPayment,
        notifier: Notifier,
    ) -> None:
        self.uow = uow
        self.transaction_dao = transaction_dao
        self.process_payment = process_payment
        self.notifier = notifier

    async def _execute(self, actor: UserDto, data: None) -> None:
        replay_token_hash = _alert_token_hash("webhook-replay")
        async with self.uow:
            expired = await self.transaction_dao.mark_expired_orphaned_webhook_events(
                retention=WEBHOOK_RETENTION,
                limit=WEBHOOK_REPLAY_BATCH
            )
            events = await self.transaction_dao.claim_replayable_webhook_events(
                token_hash=replay_token_hash,
                lease_for=WEBHOOK_PROCESSING_LEASE,
                limit=WEBHOOK_REPLAY_BATCH,
            )
            await self.uow.commit()

        for event in events:
            try:
                await self.process_payment.system(
                    ProcessPaymentDto(
                        payment_id=event.payment_id,
                        new_transaction_status=event.status,
                        gateway_type=event.gateway_type,
                        selected_payment_method=event.selected_payment_method,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "Failed to replay early payment webhook '{}'",
                    event.id,
                )
                manual_required = (
                    isinstance(exc, PaymentEventNotAppliedError)
                    or event.processing_attempt_count >= WEBHOOK_MAX_ATTEMPTS
                )
                async with self.uow:
                    await self.transaction_dao.release_webhook_event(
                        event.id,
                        token_hash=replay_token_hash,
                        retry_after=(
                            timedelta(0) if manual_required else WEBHOOK_RETRY
                        ),
                        error_code=_webhook_error_code(exc),
                        manual_required=manual_required,
                    )
                    await self.uow.commit()
                continue
            async with self.uow:
                await self.transaction_dao.delete_webhook_event(
                    event.id,
                    token_hash=replay_token_hash,
                )
                await self.uow.commit()

        alert_token_hash = _alert_token_hash("webhook-alert")
        async with self.uow:
            alerts = await self.transaction_dao.claim_manual_webhook_alerts(
                token_hash=alert_token_hash,
                lease_for=ALERT_LEASE,
                limit=WEBHOOK_REPLAY_BATCH,
            )
            await self.uow.commit()

        for event in alerts:
            try:
                await self._notify_manual(event)
            except Exception:
                logger.exception("Failed to alert manual webhook event '{}'", event.id)
                async with self.uow:
                    await self.transaction_dao.release_webhook_event(
                        event.id,
                        token_hash=alert_token_hash,
                        retry_after=ALERT_RETRY,
                        error_code=(
                            event.processing_last_error or "WEBHOOK_MANUAL_REQUIRED"
                        ),
                        manual_required=True,
                    )
                    await self.uow.commit()
                continue
            async with self.uow:
                await self.transaction_dao.mark_webhook_alerted(
                    event.id,
                    token_hash=alert_token_hash,
                )
                await self.uow.commit()

        if expired or events or alerts:
            logger.warning(
                "Webhook sweep marked '{}' orphans, replayed '{}' events, and alerted '{}'",
                expired,
                len(events),
                len(alerts),
            )

    async def _notify_manual(self, event: PaymentWebhookEventDto) -> None:
        await self.notifier.notify_system(
            MessagePayloadDto(
                i18n_key="event-payment.purchase-failed",
                i18n_kwargs={
                    "payment_id": f"webhook:{event.payment_id}:{event.status}",
                    "gateway_type": event.gateway_type,
                    "final_amount": 0,
                    "original_amount": 0,
                    "discount_percent": 0,
                    "currency": Currency.RUB.symbol,
                    "telegram_id": 0,
                    "username": 0,
                    "name": event.processing_last_error or "payment-webhook-inbox",
                    "email": None,
                },
            ),
            roles=[Role.OWNER, Role.DEV],
            notification_type=SystemNotificationType.SYSTEM,
        )


class SweepPaymentOperationAlerts(Interactor[None, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        payment_operation_dao: PaymentOperationDao,
        user_dao: UserDao,
        notifier: Notifier,
    ) -> None:
        self.uow = uow
        self.payment_operation_dao = payment_operation_dao
        self.user_dao = user_dao
        self.notifier = notifier

    async def _execute(self, actor: UserDto, data: None) -> None:
        token_hash = _alert_token_hash("reconciliation-alert")
        async with self.uow:
            expired = await self.payment_operation_dao.expire_reconciliations(
                limit=PAYMENT_OPERATION_ALERT_BATCH
            )
            operations = (
                await self.payment_operation_dao.claim_manual_reconciliation_alerts(
                    token_hash=token_hash,
                    lease_for=ALERT_LEASE,
                    limit=PAYMENT_OPERATION_ALERT_BATCH,
                )
            )
            alerts = [
                (operation, await self.user_dao.get_by_id(operation.user_id))
                for operation in operations
            ]
            await self.uow.commit()

        if expired:
            logger.warning("Expired '{}' reconciliation leases into manual review", expired)

        for operation, user in alerts:
            try:
                await self.notifier.notify_system(
                    MessagePayloadDto(
                        i18n_key="event-payment.purchase-failed",
                        i18n_kwargs={
                            "payment_id": f"operation:{operation.id}",
                            "gateway_type": operation.gateway_type or "UNKNOWN",
                            "final_amount": 0,
                            "original_amount": 0,
                            "discount_percent": 0,
                            "currency": Currency.RUB.symbol,
                            "telegram_id": user.telegram_id if user and user.telegram_id else 0,
                            "username": user.username if user and user.username else 0,
                            "name": user.name if user else f"user:{operation.user_id}",
                            "email": user.email if user else None,
                        },
                    ),
                    roles=[Role.OWNER, Role.DEV],
                    notification_type=SystemNotificationType.SYSTEM,
                )
            except Exception:
                logger.exception(
                    "Failed to alert manual payment operation '{}'",
                    operation.id,
                )
                async with self.uow:
                    await self.payment_operation_dao.release_reconciliation_alert(
                        operation.id,
                        token_hash=token_hash,
                        retry_after=ALERT_RETRY,
                    )
                    await self.uow.commit()
                continue
            async with self.uow:
                await self.payment_operation_dao.mark_reconciliation_alerted(
                    operation.id,
                    token_hash=token_hash,
                )
                await self.uow.commit()


class ClearOldBroadcasts(Interactor[None, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, broadcast_dao: BroadcastDao) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            await self.broadcast_dao.delete_old()
            await self.uow.commit()

        logger.info("Cleaned up old broadcasts from database")
