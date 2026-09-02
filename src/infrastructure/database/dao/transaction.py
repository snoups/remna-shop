from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import TransactionDao
from src.application.common.dao.transaction import TransactionOwnerUnavailableError
from src.application.dto import (
    GatewayStatsDto,
    PaymentWebhookEventDto,
    PlanIncomeDto,
    TransactionDto,
    UserPaymentStatsDto,
)
from src.core.enums import (
    PaymentGatewayType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import PaymentWebhookEvent, Transaction, User
from src.infrastructure.database.referral_reward_source import (
    exact_legacy_referral_source_fulfillment,
    paid_nontrial_referral_source_predicate,
    referral_source_evidence_at,
)


class TransactionDaoImpl(TransactionDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_dto = self.conversion_retort.get_converter(Transaction, TransactionDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Transaction],
            list[TransactionDto],
        )

    @staticmethod
    def _webhook_event_to_dto(event: PaymentWebhookEvent) -> PaymentWebhookEventDto:
        return PaymentWebhookEventDto(
            id=event.id,
            payment_id=event.payment_id,
            gateway_type=event.gateway_type,
            status=event.status,
            selected_payment_method=event.selected_payment_method,
            processing_token_hash=event.processing_token_hash,
            processing_lease_expires_at=event.processing_lease_expires_at,
            processing_attempt_count=event.processing_attempt_count,
            processing_next_attempt_at=event.processing_next_attempt_at,
            processing_last_error=event.processing_last_error,
            manual_required_at=event.manual_required_at,
            alerted_at=event.alerted_at,
            created_at=event.created_at,
        )

    async def create(self, transaction: TransactionDto) -> TransactionDto:
        transaction_data = self.retort.dump(transaction)
        transaction_data.pop("id", None)
        db_transaction = Transaction(**transaction_data)

        self.session.add(db_transaction)
        await self.session.flush()

        logger.debug(f"Created new transaction '{transaction.payment_id}'")
        return self._convert_to_dto(db_transaction)

    async def update(self, transaction: TransactionDto) -> Optional[TransactionDto]:
        if not transaction.changed_data:
            logger.warning("No changes detected in transaction, skipping update")
            return None

        stmt = (
            update(Transaction)
            .where(Transaction.payment_id == transaction.payment_id)
            .values(**transaction.changed_data)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(
                f"Transaction '{transaction.payment_id}' updated with '{transaction.changed_data}'"
            )
            return self._convert_to_dto(db_transaction)

        logger.warning(f"Failed to update transaction '{transaction.payment_id}': not found")
        return None

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]:
        stmt = select(Transaction).where(Transaction.payment_id == payment_id)
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' found")
            return self._convert_to_dto(db_transaction)

        logger.debug(f"Transaction '{payment_id}' not found")
        return None

    async def get_by_payment_id_for_user(
        self,
        user_id: int,
        payment_id: UUID,
    ) -> Optional[TransactionDto]:
        db_transaction = await self.session.scalar(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.payment_id == payment_id,
            )
        )
        return self._convert_to_dto(db_transaction) if db_transaction is not None else None

    async def get_by_internal_id_for_user(
        self,
        user_id: int,
        transaction_id: int,
    ) -> Optional[TransactionDto]:
        db_transaction = await self.session.scalar(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.id == transaction_id,
            )
        )
        return self._convert_to_dto(db_transaction) if db_transaction is not None else None

    @staticmethod
    def _successful_paid_nontrial_predicate(
        *,
        include_refunded: bool,
    ) -> tuple[Any, ...]:
        return paid_nontrial_referral_source_predicate(
            Transaction,
            include_refunded=include_refunded,
            include_legacy=False,
        )

    async def list_historical_referral_reward_sources(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[TransactionDto]:
        rows = cast(
            list,
            (
                await self.session.scalars(
                    select(Transaction)
                    .where(*self._successful_paid_nontrial_predicate(include_refunded=False))
                    .order_by(
                        Transaction.fulfillment_completed_at,
                        Transaction.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all(),
        )
        return self._convert_to_dto_list(rows)

    async def get_historical_referral_reward_sources(
        self,
        transaction_ids: list[int],
        *,
        for_update: bool = False,
    ) -> list[TransactionDto]:
        if not transaction_ids:
            return []
        stmt = (
            select(Transaction)
            .where(
                Transaction.id.in_(sorted(set(transaction_ids))),
                *self._successful_paid_nontrial_predicate(include_refunded=False),
            )
            .order_by(Transaction.id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        rows = cast(list, (await self.session.scalars(stmt)).all())
        return self._convert_to_dto_list(rows)

    async def get_first_successful_paid_transaction_id(self, user_id: int) -> Optional[int]:
        return cast(
            Optional[int],
            await self.session.scalar(
                select(Transaction.id)
                .where(
                    Transaction.user_id == user_id,
                    *paid_nontrial_referral_source_predicate(
                        Transaction,
                        include_refunded=True,
                        include_legacy=True,
                    ),
                )
                .order_by(
                    referral_source_evidence_at(Transaction, include_legacy=True),
                    Transaction.id,
                )
                .limit(1)
            ),
        )

    async def get_by_user(self, user_id: int) -> list[TransactionDto]:
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Retrieved '{len(db_transactions)}' transactions for user_id '{user_id}'")
        return self._convert_to_dto_list(db_transactions)

    async def get_page_by_user(
        self,
        user_id: int,
        *,
        limit: int,
        before_created_at: Optional[datetime] = None,
        before_id: Optional[int] = None,
    ) -> list[TransactionDto]:
        if (before_created_at is None) != (before_id is None):
            raise ValueError("Both keyset cursor values must be provided together")
        stmt = select(Transaction).where(Transaction.user_id == user_id)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                or_(
                    Transaction.created_at < before_created_at,
                    and_(
                        Transaction.created_at == before_created_at,
                        Transaction.id < before_id,
                    ),
                )
            )
        stmt = stmt.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(limit)
        rows = cast(list, (await self.session.scalars(stmt)).all())
        return self._convert_to_dto_list(rows)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[TransactionDto]:
        stmt = (
            select(Transaction).limit(limit).offset(offset).order_by(Transaction.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(
            f"Retrieved '{len(db_transactions)}' transactions "
            f"with limit '{limit}' and offset '{offset}'"
        )
        return self._convert_to_dto_list(db_transactions)

    async def get_by_status(self, status: TransactionStatus) -> list[TransactionDto]:
        stmt = select(Transaction).where(Transaction.status == status)
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Found '{len(db_transactions)}' transactions with status '{status}'")
        return self._convert_to_dto_list(db_transactions)

    async def update_status(
        self,
        payment_id: UUID,
        status: TransactionStatus,
    ) -> Optional[TransactionDto]:
        stmt = (
            update(Transaction)
            .where(Transaction.payment_id == payment_id)
            .values(status=status)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' status updated to '{status}'")
            return self._convert_to_dto(db_transaction)

        logger.warning(f"Failed to update transaction '{payment_id}': not found")
        return None

    async def set_payment_method_if_absent_or_equal(
        self,
        payment_id: UUID,
        *,
        payment_method: str,
    ) -> bool:
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.gateway_type == PaymentGatewayType.PLATEGA,
                or_(
                    Transaction.payment_method.is_(None),
                    Transaction.payment_method == payment_method,
                ),
            )
            .values(payment_method=func.coalesce(Transaction.payment_method, payment_method))
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def transition_status(
        self,
        payment_id: UUID,
        new_status: TransactionStatus,
        allowed_current: Iterable[TransactionStatus],
    ) -> Optional[TransactionDto]:
        stmt = (
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status.in_(tuple(allowed_current)),
            )
            .values(status=new_status)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)
        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' transitioned to '{new_status}'")
            return self._convert_to_dto(db_transaction)
        logger.info(f"Transaction '{payment_id}' transition to '{new_status}' did not match")
        return None

    async def transition_refunded(self, payment_id: UUID) -> Optional[TransactionDto]:
        transaction = await self.session.scalar(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                or_(
                    and_(
                        Transaction.status.in_(
                            (
                                TransactionStatus.PENDING,
                                TransactionStatus.CANCELED,
                            )
                        ),
                        Transaction.fulfillment_status == TransactionFulfillmentStatus.NOT_STARTED,
                    ),
                    and_(
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED,
                        Transaction.fulfillment_completed_at.is_not(None),
                    ),
                ),
            )
            .values(
                status=TransactionStatus.REFUNDED,
                cancellation_reason=None,
            )
            .returning(Transaction)
        )
        return self._convert_to_dto(transaction) if transaction is not None else None

    async def cancel_by_provider(self, payment_id: UUID) -> Optional[TransactionDto]:
        transaction = await self.session.scalar(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status.in_((TransactionStatus.PENDING, TransactionStatus.CANCELED)),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.NOT_STARTED,
            )
            .values(
                status=TransactionStatus.CANCELED,
                cancellation_reason="PROVIDER",
            )
            .returning(Transaction)
        )
        return self._convert_to_dto(transaction) if transaction is not None else None

    async def _lock_active_payment_owner(self, payment_id: UUID) -> None:
        owner_id = await self.session.scalar(
            select(Transaction.user_id).where(Transaction.payment_id == payment_id)
        )
        if owner_id is None:
            return
        owner = (
            await self.session.execute(
                select(User.id, User.merged_into_user_id)
                .where(User.id == owner_id)
                .with_for_update(read=True, key_share=True)
            )
        ).one_or_none()
        if owner is None or owner.merged_into_user_id is not None:
            raise TransactionOwnerUnavailableError

    async def claim_fulfillment(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[TransactionDto]:
        await self._lock_active_payment_owner(payment_id)
        now = func.clock_timestamp()
        transaction = await self.session.scalar(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                or_(
                    Transaction.status == TransactionStatus.PENDING,
                    and_(
                        Transaction.status == TransactionStatus.CANCELED,
                        Transaction.cancellation_reason == "LOCAL_TIMEOUT",
                    ),
                ),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.NOT_STARTED,
            )
            .values(
                status=TransactionStatus.COMPLETED,
                cancellation_reason=None,
                fulfillment_status=TransactionFulfillmentStatus.PROCESSING,
                fulfillment_token_hash=token_hash,
                fulfillment_started_at=now,
                fulfillment_lease_expires_at=now + lease_for,
                fulfillment_completed_at=None,
                fulfillment_last_error=None,
            )
            .returning(Transaction)
        )
        return self._convert_to_dto(transaction) if transaction is not None else None

    async def mark_refund_manual_required(self, payment_id: UUID) -> bool:
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.fulfillment_status.in_(
                    (
                        TransactionFulfillmentStatus.PROCESSING,
                        TransactionFulfillmentStatus.MANUAL_REQUIRED,
                    )
                ),
            )
            .values(
                status=TransactionStatus.REFUNDED,
                # Keep the exact migration-0049 provenance marker immutable.
                # Status records the refund; overwriting this marker would make
                # a later ON_FIRST candidate forget an ambiguous earlier paid
                # source and could permit a duplicate referral reward.
                fulfillment_last_error=case(
                    (
                        exact_legacy_referral_source_fulfillment(Transaction),
                        Transaction.fulfillment_last_error,
                    ),
                    else_="REFUND_DURING_UNPROVEN_FULFILLMENT",
                ),
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def complete_fulfillment(self, payment_id: UUID, *, token_hash: str) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_token_hash == token_hash,
                Transaction.fulfillment_lease_expires_at > now,
            )
            .values(
                fulfillment_status=TransactionFulfillmentStatus.SUCCEEDED,
                fulfillment_token_hash=None,
                fulfillment_lease_expires_at=None,
                fulfillment_completed_at=now,
                fulfillment_last_error=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_fulfillment_manual_required(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status.in_((TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)),
                Transaction.fulfillment_status.in_(
                    (
                        TransactionFulfillmentStatus.PROCESSING,
                        TransactionFulfillmentStatus.MANUAL_REQUIRED,
                    )
                ),
                Transaction.fulfillment_token_hash == token_hash,
            )
            .values(
                fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
                fulfillment_lease_expires_at=None,
                fulfillment_last_error=error_code,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def expire_fulfillment(self, payment_id: UUID) -> bool:
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status.in_((TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_lease_expires_at <= func.clock_timestamp(),
            )
            .values(
                fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
                fulfillment_lease_expires_at=None,
                fulfillment_last_error="FULFILLMENT_LEASE_EXPIRED",
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def expire_fulfillments(self, *, limit: int) -> int:
        now = func.clock_timestamp()
        candidates = (
            select(Transaction.id)
            .where(
                Transaction.status.in_((TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_lease_expires_at <= now,
            )
            .order_by(Transaction.fulfillment_lease_expires_at, Transaction.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.id.in_(candidates),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_lease_expires_at <= now,
            )
            .values(
                fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
                fulfillment_lease_expires_at=None,
                fulfillment_last_error="FULFILLMENT_LEASE_EXPIRED",
            )
        )
        return cast(int, result.rowcount)  # type: ignore[attr-defined]

    async def claim_manual_fulfillment_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[TransactionDto]:
        now = func.clock_timestamp()
        candidates = (
            select(Transaction.id)
            .where(
                Transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED,
                Transaction.fulfillment_alerted_at.is_(None),
                or_(
                    Transaction.fulfillment_alert_next_attempt_at.is_(None),
                    Transaction.fulfillment_alert_next_attempt_at <= now,
                ),
                or_(
                    Transaction.fulfillment_alert_token_hash.is_(None),
                    Transaction.fulfillment_alert_lease_expires_at <= now,
                ),
            )
            .order_by(
                Transaction.fulfillment_alert_next_attempt_at.asc().nullsfirst(),
                Transaction.fulfillment_started_at,
                Transaction.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        transactions = list(
            (
                await self.session.scalars(
                    update(Transaction)
                    .where(Transaction.id.in_(candidates))
                    .values(
                        fulfillment_alert_token_hash=token_hash,
                        fulfillment_alert_lease_expires_at=now + lease_for,
                        fulfillment_alert_attempt_count=(
                            Transaction.fulfillment_alert_attempt_count + 1
                        ),
                    )
                    .returning(Transaction)
                )
            ).all()
        )
        return self._convert_to_dto_list(transactions)

    async def mark_fulfillment_alerted(
        self,
        payment_id: UUID,
        *,
        token_hash: Optional[str] = None,
    ) -> bool:
        token_predicate = (
            Transaction.fulfillment_alert_token_hash.is_(None)
            if token_hash is None
            else Transaction.fulfillment_alert_token_hash == token_hash
        )
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED,
                Transaction.fulfillment_alerted_at.is_(None),
                token_predicate,
            )
            .values(
                fulfillment_alerted_at=func.clock_timestamp(),
                fulfillment_alert_token_hash=None,
                fulfillment_alert_lease_expires_at=None,
                fulfillment_alert_next_attempt_at=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def release_fulfillment_alert(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.fulfillment_alerted_at.is_(None),
                Transaction.fulfillment_alert_token_hash == token_hash,
            )
            .values(
                fulfillment_alert_token_hash=None,
                fulfillment_alert_lease_expires_at=None,
                fulfillment_alert_next_attempt_at=now + retry_after,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def store_webhook_event(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        selected_payment_method: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        now = func.clock_timestamp()
        insert_stmt = insert(PaymentWebhookEvent).values(
            payment_id=payment_id,
            gateway_type=gateway_type,
            status=status,
            selected_payment_method=selected_payment_method,
            manual_required_at=now if error_code is not None else None,
            processing_last_error=error_code,
        )
        metadata_conflict = and_(
            PaymentWebhookEvent.selected_payment_method.is_not(None),
            insert_stmt.excluded.selected_payment_method.is_not(None),
            PaymentWebhookEvent.selected_payment_method
            != insert_stmt.excluded.selected_payment_method,
        )
        incoming_error = insert_stmt.excluded.manual_required_at.is_not(None)
        manual_disposition = or_(metadata_conflict, incoming_error)
        await self.session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_payment_webhook_events_identity",
                set_={
                    "selected_payment_method": func.coalesce(
                        PaymentWebhookEvent.selected_payment_method,
                        insert_stmt.excluded.selected_payment_method,
                    ),
                    "manual_required_at": case(
                        (
                            manual_disposition,
                            func.coalesce(PaymentWebhookEvent.manual_required_at, now),
                        ),
                        else_=PaymentWebhookEvent.manual_required_at,
                    ),
                    "processing_last_error": case(
                        (metadata_conflict, "WEBHOOK_METADATA_CONFLICT"),
                        (incoming_error, insert_stmt.excluded.processing_last_error),
                        else_=PaymentWebhookEvent.processing_last_error,
                    ),
                    "processing_next_attempt_at": case(
                        (manual_disposition, None),
                        else_=PaymentWebhookEvent.processing_next_attempt_at,
                    ),
                    "processing_token_hash": case(
                        (manual_disposition, None),
                        else_=PaymentWebhookEvent.processing_token_hash,
                    ),
                    "processing_lease_expires_at": case(
                        (manual_disposition, None),
                        else_=PaymentWebhookEvent.processing_lease_expires_at,
                    ),
                },
            )
        )

    async def claim_webhook_event_by_identity(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[PaymentWebhookEventDto]:
        now = func.clock_timestamp()
        event = await self.session.scalar(
            update(PaymentWebhookEvent)
            .where(
                PaymentWebhookEvent.payment_id == payment_id,
                PaymentWebhookEvent.gateway_type == gateway_type,
                PaymentWebhookEvent.status == status,
                PaymentWebhookEvent.manual_required_at.is_(None),
                or_(
                    PaymentWebhookEvent.processing_next_attempt_at.is_(None),
                    PaymentWebhookEvent.processing_next_attempt_at <= now,
                ),
                or_(
                    PaymentWebhookEvent.processing_token_hash.is_(None),
                    PaymentWebhookEvent.processing_lease_expires_at <= now,
                ),
            )
            .values(
                processing_token_hash=token_hash,
                processing_lease_expires_at=now + lease_for,
                processing_attempt_count=PaymentWebhookEvent.processing_attempt_count + 1,
            )
            .returning(PaymentWebhookEvent)
        )
        return self._webhook_event_to_dto(event) if event is not None else None

    async def claim_replayable_webhook_events(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]:
        now = func.clock_timestamp()
        candidates = (
            select(PaymentWebhookEvent.id)
            .join(
                Transaction,
                and_(
                    Transaction.payment_id == PaymentWebhookEvent.payment_id,
                    Transaction.gateway_type == PaymentWebhookEvent.gateway_type,
                ),
            )
            .where(
                PaymentWebhookEvent.manual_required_at.is_(None),
                or_(
                    PaymentWebhookEvent.processing_next_attempt_at.is_(None),
                    PaymentWebhookEvent.processing_next_attempt_at <= now,
                ),
                or_(
                    PaymentWebhookEvent.processing_token_hash.is_(None),
                    PaymentWebhookEvent.processing_lease_expires_at <= now,
                ),
            )
            .order_by(
                PaymentWebhookEvent.processing_next_attempt_at.asc().nullsfirst(),
                PaymentWebhookEvent.created_at,
                PaymentWebhookEvent.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(
            (
                await self.session.scalars(
                    update(PaymentWebhookEvent)
                    .where(PaymentWebhookEvent.id.in_(candidates))
                    .values(
                        processing_token_hash=token_hash,
                        processing_lease_expires_at=now + lease_for,
                        processing_attempt_count=(PaymentWebhookEvent.processing_attempt_count + 1),
                    )
                    .returning(PaymentWebhookEvent)
                )
            ).all()
        )
        return [self._webhook_event_to_dto(event) for event in events]

    async def delete_webhook_event(self, event_id: int, *, token_hash: str) -> bool:
        result = await self.session.execute(
            delete(PaymentWebhookEvent).where(
                PaymentWebhookEvent.id == event_id,
                PaymentWebhookEvent.processing_token_hash == token_hash,
                PaymentWebhookEvent.manual_required_at.is_(None),
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def release_webhook_event(
        self,
        event_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
        manual_required: bool,
    ) -> bool:
        now = func.clock_timestamp()
        values: dict[str, Any] = {
            "processing_token_hash": None,
            "processing_lease_expires_at": None,
            "processing_last_error": error_code,
            "processing_next_attempt_at": now + retry_after,
        }
        if manual_required:
            values["manual_required_at"] = func.coalesce(
                PaymentWebhookEvent.manual_required_at,
                now,
            )
        result = await self.session.execute(
            update(PaymentWebhookEvent)
            .where(
                PaymentWebhookEvent.id == event_id,
                PaymentWebhookEvent.processing_token_hash == token_hash,
            )
            .values(**values)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def claim_manual_webhook_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]:
        now = func.clock_timestamp()
        candidates = (
            select(PaymentWebhookEvent.id)
            .where(
                PaymentWebhookEvent.manual_required_at.is_not(None),
                PaymentWebhookEvent.alerted_at.is_(None),
                or_(
                    PaymentWebhookEvent.processing_next_attempt_at.is_(None),
                    PaymentWebhookEvent.processing_next_attempt_at <= now,
                ),
                or_(
                    PaymentWebhookEvent.processing_token_hash.is_(None),
                    PaymentWebhookEvent.processing_lease_expires_at <= now,
                ),
            )
            .order_by(PaymentWebhookEvent.manual_required_at, PaymentWebhookEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(
            (
                await self.session.scalars(
                    update(PaymentWebhookEvent)
                    .where(PaymentWebhookEvent.id.in_(candidates))
                    .values(
                        processing_token_hash=token_hash,
                        processing_lease_expires_at=now + lease_for,
                    )
                    .returning(PaymentWebhookEvent)
                )
            ).all()
        )
        return [self._webhook_event_to_dto(event) for event in events]

    async def mark_webhook_alerted(self, event_id: int, *, token_hash: str) -> bool:
        result = await self.session.execute(
            update(PaymentWebhookEvent)
            .where(
                PaymentWebhookEvent.id == event_id,
                PaymentWebhookEvent.manual_required_at.is_not(None),
                PaymentWebhookEvent.alerted_at.is_(None),
                PaymentWebhookEvent.processing_token_hash == token_hash,
            )
            .values(
                alerted_at=func.clock_timestamp(),
                processing_token_hash=None,
                processing_lease_expires_at=None,
                processing_next_attempt_at=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def delete_webhook_event_by_identity(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
    ) -> bool:
        result = await self.session.execute(
            delete(PaymentWebhookEvent).where(
                PaymentWebhookEvent.payment_id == payment_id,
                PaymentWebhookEvent.gateway_type == gateway_type,
                PaymentWebhookEvent.status == status,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_expired_orphaned_webhook_events(
        self,
        *,
        retention: timedelta,
        limit: int,
    ) -> int:
        matching_transaction = select(Transaction.id).where(
            Transaction.payment_id == PaymentWebhookEvent.payment_id,
            Transaction.gateway_type == PaymentWebhookEvent.gateway_type,
        )
        candidates = (
            select(PaymentWebhookEvent.id)
            .where(
                PaymentWebhookEvent.created_at < func.clock_timestamp() - retention,
                PaymentWebhookEvent.manual_required_at.is_(None),
                or_(
                    PaymentWebhookEvent.processing_token_hash.is_(None),
                    PaymentWebhookEvent.processing_lease_expires_at <= func.clock_timestamp(),
                ),
                ~matching_transaction.exists(),
            )
            .order_by(PaymentWebhookEvent.created_at, PaymentWebhookEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            update(PaymentWebhookEvent)
            .where(PaymentWebhookEvent.id.in_(candidates))
            .values(
                manual_required_at=func.clock_timestamp(),
                processing_last_error="ORPHAN_RETENTION_EXPIRED",
                processing_token_hash=None,
                processing_lease_expires_at=None,
                processing_next_attempt_at=None,
            )
        )
        return cast(int, result.rowcount)  # type: ignore[attr-defined]

    async def exists(self, payment_id: UUID) -> bool:
        stmt = select(select(Transaction).where(Transaction.payment_id == payment_id).exists())
        is_exists = await self.session.scalar(stmt) or False

        logger.debug(f"Transaction '{payment_id}' existence status is '{is_exists}'")
        return is_exists

    async def has_paid_purchase_excluding_stars(self, user_id: int) -> bool:
        stmt = select(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.is_test.is_(False),
                Transaction.gateway_type != PaymentGatewayType.TELEGRAM_STARS,
            )
            .exists()
        )
        result = await self.session.scalar(stmt) or False

        logger.debug(f"User '{user_id}' has non-stars paid purchase: '{result}'")
        return result

    async def cancel_old(self, minutes: int = 30) -> int:
        threshold = datetime_now() - timedelta(minutes=minutes)

        stmt = (
            update(Transaction)
            .where(Transaction.status == TransactionStatus.PENDING)
            .where(Transaction.created_at < threshold)
            .values(
                status=TransactionStatus.CANCELED,
                cancellation_reason="LOCAL_TIMEOUT",
            )
        )
        result = await self.session.execute(stmt)
        count = result.rowcount  # type: ignore[attr-defined]

        if count > 0:
            logger.debug(f"Cancelled '{count}' pending transactions older than '{minutes}' minutes")
        else:
            logger.debug(f"No pending transactions older than '{minutes}' minutes found to cancel")

        return cast(int, count)

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Transaction)
        total = await self.session.scalar(stmt) or 0

        logger.debug(f"Total transactions count is '{total}'")
        return total

    async def count_paying_users(self) -> int:
        stmt = select(func.count(func.distinct(Transaction.user_id))).where(
            Transaction.status == TransactionStatus.COMPLETED
        )

        return await self.session.scalar(stmt) or 0

    async def count_total(self) -> int:
        stmt = select(func.count()).select_from(Transaction)
        return await self.session.scalar(stmt) or 0

    async def count_completed(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.status == TransactionStatus.COMPLETED)
        )
        return await self.session.scalar(stmt) or 0

    async def count_free(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.pricing["final_amount"].as_float() == 0)
        )
        return await self.session.scalar(stmt) or 0

    async def get_gateway_stats(self) -> list[GatewayStatsDto]:
        now = datetime_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        month_ago = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (last_month_end - timedelta(days=1)).replace(day=1)

        final_amount = Transaction.pricing["final_amount"].as_float()
        original_amount = Transaction.pricing["original_amount"].as_float()
        is_free = final_amount == 0
        is_completed = Transaction.status == TransactionStatus.COMPLETED

        stmt = select(
            Transaction.gateway_type,
            func.count().label("total_transactions"),
            func.sum(case((is_completed, 1), else_=0)).label("completed_transactions"),
            func.sum(case((is_free, 1), else_=0)).label("free_transactions"),
            func.sum(case((is_completed, final_amount), else_=0.0)).label("total_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= today_start),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("daily_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= week_ago),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("weekly_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= month_ago),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("monthly_income"),
            func.sum(
                case(
                    (
                        and_(
                            is_completed,
                            Transaction.created_at >= last_month_start,
                            Transaction.created_at < last_month_end,
                        ),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("last_month_income"),
            func.sum(case((and_(is_completed, ~is_free), 1), else_=0)).label("paid_count"),
            func.sum(case((and_(is_completed, ~is_free), 1), else_=0)).label("paid_count"),
            func.sum(case((is_completed, original_amount - final_amount), else_=0.0)).label(
                "total_discounts"
            ),
        ).group_by(Transaction.gateway_type)

        result = await self.session.execute(stmt)
        rows = result.mappings().all()

        logger.debug(f"Gateway stats fetched for {len(rows)} gateways")
        return [
            GatewayStatsDto(
                gateway_type=row["gateway_type"],
                total_income=Decimal(row["total_income"] or 0),
                daily_income=Decimal(row["daily_income"] or 0),
                weekly_income=Decimal(row["weekly_income"] or 0),
                monthly_income=Decimal(row["monthly_income"] or 0),
                last_month_income=Decimal(row["last_month_income"] or 0),
                paid_count=int(row["paid_count"] or 0),
                total_discounts=Decimal(row["total_discounts"] or 0),
                total_transactions=int(row["total_transactions"] or 0),
                completed_transactions=int(row["completed_transactions"] or 0),
                free_transactions=int(row["free_transactions"] or 0),
            )
            for row in rows
        ]

    async def get_plan_income(self) -> list[PlanIncomeDto]:
        plan_id_expr = Transaction.plan_snapshot["id"].as_integer()
        final_amount_expr = Transaction.pricing["final_amount"].as_float()

        stmt = (
            select(
                plan_id_expr.label("plan_id"),
                Transaction.currency.label("currency"),
                func.sum(final_amount_expr).label("total_income"),
            )
            .where(
                Transaction.status == TransactionStatus.COMPLETED,
                plan_id_expr.isnot(None),
            )
            .group_by(plan_id_expr, Transaction.currency)
        )

        result = await self.session.execute(stmt)
        logger.debug("Plan income stats fetched")
        return [
            PlanIncomeDto(
                plan_id=row["plan_id"],
                currency=row["currency"].symbol,
                total_income=float(row["total_income"] or 0),
            )
            for row in result.mappings()
        ]

    async def get_recent_pending(
        self,
        user_id: int,
        plan_id: int,
        duration_days: int,
        gateway_type: PaymentGatewayType,
    ) -> Optional[TransactionDto]:
        threshold = datetime_now() - timedelta(minutes=15)
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.gateway_type == gateway_type,
                Transaction.status == TransactionStatus.PENDING,
                Transaction.plan_snapshot["id"].as_integer() == plan_id,
                Transaction.plan_snapshot["duration"].as_integer() == duration_days,
                Transaction.created_at >= threshold,
            )
            .order_by(Transaction.created_at.desc())
            .limit(1)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(
                f"Found recent pending transaction for user_id '{user_id}', "
                f"plan_id '{plan_id}', duration '{duration_days}'"
            )
            return self._convert_to_dto(db_transaction)

        logger.debug(
            f"No recent pending transaction for user_id '{user_id}', "
            f"plan_id '{plan_id}', duration '{duration_days}'"
        )
        return None

    async def get_user_payment_stats(
        self,
        user_id: int,
    ) -> tuple[Optional[datetime], list[UserPaymentStatsDto]]:
        last_payment_stmt = (
            select(Transaction.created_at)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .order_by(Transaction.created_at.desc())
            .limit(1)
        )

        amounts_stmt = (
            select(
                Transaction.currency.label("currency"),
                func.sum(Transaction.pricing["final_amount"].as_float()).label("total_amount"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.pricing["final_amount"].as_float() > 0,
            )
            .group_by(Transaction.currency)
        )

        last_payment_at = await self.session.scalar(last_payment_stmt)
        amounts_rows = (await self.session.execute(amounts_stmt)).mappings().all()

        return last_payment_at, [
            UserPaymentStatsDto(
                currency=row["currency"].symbol,
                total_amount=float(row["total_amount"] or 0),
            )
            for row in amounts_rows
        ]
