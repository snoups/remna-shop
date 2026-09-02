from datetime import datetime, timedelta

from sqlalchemy import delete, extract, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import SubscriptionEmailReminderDao
from src.application.dto import (
    SubscriptionEmailDeliveryDto,
    SubscriptionEmailReminderDto,
)
from src.core.constants import UNLIMITED_EXPIRE_YEAR
from src.core.enums import SubscriptionStatus
from src.infrastructure.database.models import (
    Subscription,
    SubscriptionEmailReminder,
    User,
)

PENDING = "PENDING"
PROCESSING = "PROCESSING"
RETRY_WAITING = "RETRY_WAITING"
SENT = "SENT"
CANCELED = "CANCELED"
FAILED = "FAILED"

# Keep this literal predicate identical to the terminal-retention partial index.
# PostgreSQL cannot generally prove a parameterized state IN (...) implies a
# partial-index predicate when it switches to a generic prepared-statement plan.
TERMINAL_RETENTION_PREDICATE = text(
    "state IN ('SENT', 'CANCELED', 'FAILED')"
)


class SubscriptionEmailReminderDaoImpl(SubscriptionEmailReminderDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_dto(row: SubscriptionEmailReminder) -> SubscriptionEmailReminderDto:
        return SubscriptionEmailReminderDto(
            id=row.id,
            user_id=row.user_id,
            subscription_id=row.subscription_id,
            expire_at_snapshot=row.expire_at_snapshot,
            days_before=row.days_before,
            due_at=row.due_at,
            state=row.state,
            attempt_count=row.attempt_count,
            next_attempt_at=row.next_attempt_at,
            processing_token_hash=row.processing_token_hash,
            processing_lease_expires_at=row.processing_lease_expires_at,
            last_error_code=row.last_error_code,
            sent_at=row.sent_at,
            canceled_at=row.canceled_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def generate(
        self,
        *,
        now: datetime,
        days_before: tuple[int, ...],
        candidate_limit: int,
        generation_grace: timedelta,
    ) -> int:
        if not days_before or candidate_limit <= 0:
            return 0

        horizon = now + timedelta(days=max(days_before) + 1)
        already_generated = (
            select(SubscriptionEmailReminder.id)
            .where(
                SubscriptionEmailReminder.user_id == Subscription.user_id,
                SubscriptionEmailReminder.subscription_id == Subscription.id,
                SubscriptionEmailReminder.expire_at_snapshot == Subscription.expire_at,
            )
            .exists()
        )
        candidates_stmt = (
            select(Subscription.id, Subscription.user_id, Subscription.expire_at)
            .join(User, User.id == Subscription.user_id)
            .where(
                User.current_subscription_id == Subscription.id,
                User.merged_into_user_id.is_(None),
                User.is_blocked.is_(False),
                User.email.is_not(None),
                User.is_email_verified.is_(True),
                User.subscription_expiration_email_enabled.is_(True),
                User.subscription_expiration_email_enabled_at.is_not(None),
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.is_trial.is_(False),
                # A snapshot with less than the smallest threshold remaining
                # cannot produce a useful reminder and would otherwise occupy a
                # bounded candidate batch forever.
                Subscription.expire_at > (
                    now + timedelta(days=min(days_before)) - generation_grace
                ),
                Subscription.expire_at <= horizon,
                extract("year", Subscription.expire_at) != UNLIMITED_EXPIRE_YEAR,
                ~already_generated,
            )
            .order_by(Subscription.expire_at, Subscription.id)
            .limit(candidate_limit)
        )
        candidates = (await self.session.execute(candidates_stmt)).all()

        values: list[dict[str, object]] = []
        earliest_due = now - generation_grace
        for subscription_id, user_id, expire_at in candidates:
            for threshold in days_before:
                due_at = expire_at - timedelta(days=threshold)
                # Do not emit several overdue thresholds immediately when a user
                # opts in shortly before expiration. Future rows are generated in
                # advance, so ordinary scheduler downtime cannot lose them.
                if due_at < earliest_due:
                    continue
                values.append(
                    {
                        "user_id": user_id,
                        "subscription_id": subscription_id,
                        "expire_at_snapshot": expire_at,
                        "days_before": threshold,
                        "due_at": due_at,
                        "next_attempt_at": due_at,
                        "state": PENDING,
                    }
                )

        if not values:
            return 0

        insert_stmt = insert(SubscriptionEmailReminder).values(values)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            constraint="uq_subscription_email_reminder_identity"
        )
        returning_stmt = insert_stmt.returning(SubscriptionEmailReminder.id)
        inserted_ids = await self.session.scalars(returning_stmt)
        return len(inserted_ids.all())

    async def claim_due(
        self,
        *,
        now: datetime,
        delivery_not_before: datetime,
        token_hash: str,
        lease_for: timedelta,
        max_attempts: int,
        limit: int,
    ) -> list[SubscriptionEmailReminderDto]:
        if limit <= 0 or max_attempts <= 0:
            return []

        claimable = or_(
            SubscriptionEmailReminder.state.in_([PENDING, RETRY_WAITING]),
            (
                (SubscriptionEmailReminder.state == PROCESSING)
                & (SubscriptionEmailReminder.processing_lease_expires_at <= now)
            ),
        )
        stmt = (
            select(SubscriptionEmailReminder)
            .where(
                claimable,
                SubscriptionEmailReminder.due_at <= now,
                SubscriptionEmailReminder.due_at >= delivery_not_before,
                SubscriptionEmailReminder.next_attempt_at <= now,
                SubscriptionEmailReminder.attempt_count < max_attempts,
            )
            .order_by(
                SubscriptionEmailReminder.next_attempt_at,
                SubscriptionEmailReminder.due_at,
                SubscriptionEmailReminder.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self.session.scalars(stmt)).all())
        lease_expires_at = now + lease_for
        for row in rows:
            row.state = PROCESSING
            row.processing_token_hash = token_hash
            row.processing_lease_expires_at = lease_expires_at
            row.attempt_count += 1
        await self.session.flush()
        return [self._to_dto(row) for row in rows]

    async def sweep_undeliverable(
        self,
        *,
        now: datetime,
        delivery_not_before: datetime,
        max_attempts: int,
        limit: int,
    ) -> int:
        if limit <= 0 or max_attempts <= 0:
            return 0

        inactive_processing = (
            (SubscriptionEmailReminder.state == PROCESSING)
            & (SubscriptionEmailReminder.processing_lease_expires_at <= now)
        )
        mutable_state = or_(
            SubscriptionEmailReminder.state.in_([PENDING, RETRY_WAITING]),
            inactive_processing,
        )
        stale = SubscriptionEmailReminder.due_at < delivery_not_before
        exhausted = SubscriptionEmailReminder.attempt_count >= max_attempts
        stmt = (
            select(SubscriptionEmailReminder)
            .where(mutable_state, or_(stale, exhausted))
            .order_by(
                SubscriptionEmailReminder.due_at,
                SubscriptionEmailReminder.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        reminders = list((await self.session.scalars(stmt)).all())
        for reminder in reminders:
            if reminder.attempt_count >= max_attempts:
                reminder.state = FAILED
                reminder.last_error_code = "ATTEMPTS_EXHAUSTED"
            else:
                reminder.state = CANCELED
                reminder.canceled_at = now
                reminder.last_error_code = "DELIVERY_WINDOW_EXPIRED"
            reminder.processing_token_hash = None
            reminder.processing_lease_expires_at = None
        if reminders:
            await self.session.flush()
        return len(reminders)

    async def prepare_delivery(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        now: datetime,
    ) -> SubscriptionEmailDeliveryDto | None:
        stmt = (
            select(SubscriptionEmailReminder, User, Subscription)
            .join(User, User.id == SubscriptionEmailReminder.user_id)
            .join(Subscription, Subscription.id == SubscriptionEmailReminder.subscription_id)
            .where(SubscriptionEmailReminder.id == reminder_id)
            .with_for_update()
        )
        record = (await self.session.execute(stmt)).one_or_none()
        if record is None:
            return None

        reminder, user, subscription = record
        owns_fence = (
            reminder.state == PROCESSING
            and reminder.processing_token_hash == token_hash
            and reminder.processing_lease_expires_at is not None
            and reminder.processing_lease_expires_at > now
        )
        if not owns_fence:
            return None

        eligible = (
            user.merged_into_user_id is None
            and not user.is_blocked
            and user.email is not None
            and user.is_email_verified
            and user.subscription_expiration_email_enabled
            and user.subscription_expiration_email_enabled_at is not None
            and user.subscription_expiration_email_enabled_at <= reminder.due_at
            and user.current_subscription_id == subscription.id
            and subscription.user_id == user.id
            and subscription.status == SubscriptionStatus.ACTIVE
            and not subscription.is_trial
            and subscription.expire_at == reminder.expire_at_snapshot
            and subscription.expire_at > now
            and subscription.expire_at.year != UNLIMITED_EXPIRE_YEAR
        )
        if not eligible:
            reminder.state = CANCELED
            reminder.canceled_at = now
            reminder.last_error_code = "STALE_OR_INELIGIBLE"
            reminder.processing_token_hash = None
            reminder.processing_lease_expires_at = None
            await self.session.flush()
            return None

        return SubscriptionEmailDeliveryDto(
            reminder_id=reminder.id,
            recipient_email=user.email,
            expire_at=subscription.expire_at,
            days_before=reminder.days_before,
            attempt_count=reminder.attempt_count,
        )

    async def renew_processing_lease(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> bool:
        server_now = func.clock_timestamp()
        stmt = (
            update(SubscriptionEmailReminder)
            .where(
                SubscriptionEmailReminder.id == reminder_id,
                SubscriptionEmailReminder.state == PROCESSING,
                SubscriptionEmailReminder.processing_token_hash == token_hash,
                SubscriptionEmailReminder.processing_lease_expires_at > server_now,
            )
            .values(processing_lease_expires_at=server_now + lease_for)
            .returning(SubscriptionEmailReminder.id)
        )
        return await self.session.scalar(stmt) is not None

    async def mark_sent(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        sent_at: datetime,
    ) -> bool:
        stmt = (
            update(SubscriptionEmailReminder)
            .where(
                SubscriptionEmailReminder.id == reminder_id,
                SubscriptionEmailReminder.state == PROCESSING,
                SubscriptionEmailReminder.processing_token_hash == token_hash,
            )
            .values(
                state=SENT,
                sent_at=sent_at,
                last_error_code=None,
                processing_token_hash=None,
                processing_lease_expires_at=None,
            )
            .returning(SubscriptionEmailReminder.id)
        )
        return await self.session.scalar(stmt) is not None

    async def release_failed(
        self,
        reminder_id: int,
        *,
        token_hash: str,
        now: datetime,
        error_code: str,
        max_attempts: int,
        retry_after: timedelta,
    ) -> bool:
        stmt = (
            select(SubscriptionEmailReminder)
            .where(
                SubscriptionEmailReminder.id == reminder_id,
                SubscriptionEmailReminder.state == PROCESSING,
                SubscriptionEmailReminder.processing_token_hash == token_hash,
            )
            .with_for_update()
        )
        reminder = await self.session.scalar(stmt)
        if reminder is None:
            return False

        exhausted = reminder.attempt_count >= max_attempts
        reminder.state = FAILED if exhausted else RETRY_WAITING
        reminder.next_attempt_at = now + retry_after
        reminder.last_error_code = error_code[:64]
        reminder.processing_token_hash = None
        reminder.processing_lease_expires_at = None
        await self.session.flush()
        return True

    async def delete_terminal_before(
        self,
        *,
        before: datetime,
        limit: int,
    ) -> int:
        if limit <= 0:
            return 0
        candidates = (
            select(SubscriptionEmailReminder.id)
            .where(
                TERMINAL_RETENTION_PREDICATE,
                SubscriptionEmailReminder.updated_at < before,
            )
            .order_by(
                SubscriptionEmailReminder.updated_at,
                SubscriptionEmailReminder.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("terminal_subscription_email_reminders")
        )
        stmt = (
            delete(SubscriptionEmailReminder)
            .where(
                SubscriptionEmailReminder.id.in_(select(candidates.c.id))
            )
            .returning(SubscriptionEmailReminder.id)
        )
        deleted_ids = await self.session.scalars(stmt)
        return len(deleted_ids.all())
