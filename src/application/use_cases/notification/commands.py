import asyncio
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from src.application.common import EmailSender, Interactor
from src.application.common.dao import SubscriptionEmailReminderDao, UserDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import NotificationPreferencesDto, UserDto
from src.core.config import AppConfig
from src.core.utils.time import datetime_now

REMINDER_DAYS_BEFORE = (7, 3, 1)
GENERATION_CANDIDATE_LIMIT = 500
GENERATION_GRACE = timedelta(hours=1)
GENERATION_MAX_ROWS_PER_RUN = GENERATION_CANDIDATE_LIMIT * len(REMINDER_DAYS_BEFORE)
TERMINAL_RETENTION = timedelta(days=90)
# Hourly retention throughput must stay strictly above worst-case hourly
# generation, otherwise a sustained eligible population can grow the table
# even after every row has passed the retention window.
TERMINAL_CLEANUP_BATCH_SIZE = GENERATION_MAX_ROWS_PER_RUN * 2
DELIVERY_BATCH_SIZE = 10
# smtplib's 20-second timeout applies to each socket operation, not to the
# complete SMTP transaction. Claim only one row immediately before its network
# call; this lease covers multiple operations and the bounded auth retry.
DELIVERY_LEASE = timedelta(minutes=10)
DELIVERY_HEARTBEAT_INTERVAL = timedelta(minutes=1)
DELIVERY_MAX_ATTEMPTS = 5
DELIVERY_RETRY_MAX_SECONDS = 60 * 60
DELIVERY_GRACE = timedelta(hours=1)
DELIVERY_MAINTENANCE_BATCH_SIZE = 500


class NotificationEmailNotEligibleError(Exception): ...


class NotificationDeliveryUnavailableError(Exception): ...


def _delivery_ready(config: AppConfig, email_sender: EmailSender) -> bool:
    return bool(
        config.email.subscription_expiration_reminders_enabled
        and email_sender.is_enabled
        and config.email.from_email.strip()
        and config.email.subscription_expiration_cabinet_url.strip()
    )


def _user_email_eligible(
    actor: UserDto,
    *,
    config: AppConfig,
    email_sender: EmailSender,
) -> bool:
    return bool(
        actor.email
        and actor.is_email_verified
        and not actor.is_blocked
        and _delivery_ready(config, email_sender)
    )


def _preferences(
    actor: UserDto,
    *,
    config: AppConfig,
    email_sender: EmailSender,
) -> NotificationPreferencesDto:
    eligible = _user_email_eligible(actor, config=config, email_sender=email_sender)
    return NotificationPreferencesDto(
        # Consent and current delivery capability are intentionally independent.
        # A stored opt-in must remain visible (and therefore revocable) during an
        # SMTP/global-switch outage; the worker still fails closed on eligibility.
        subscription_expiration_email_enabled=(
            actor.subscription_expiration_email_enabled
        ),
        email_eligible=eligible,
        sender_email=config.email.from_email.strip() or None,
        days_before=REMINDER_DAYS_BEFORE,
    )


class GetNotificationPreferences(Interactor[None, NotificationPreferencesDto]):
    required_permission = Permission.PUBLIC

    def __init__(self, config: AppConfig, email_sender: EmailSender) -> None:
        self.config = config
        self.email_sender = email_sender

    async def _execute(self, actor: UserDto, data: None) -> NotificationPreferencesDto:
        return _preferences(actor, config=self.config, email_sender=self.email_sender)


@dataclass(frozen=True)
class UpdateNotificationPreferencesDto:
    subscription_expiration_email_enabled: bool


class UpdateNotificationPreferences(
    Interactor[UpdateNotificationPreferencesDto, NotificationPreferencesDto]
):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        config: AppConfig,
        email_sender: EmailSender,
        user_dao: UserDao,
        uow: UnitOfWork,
    ) -> None:
        self.config = config
        self.email_sender = email_sender
        self.user_dao = user_dao
        self.uow = uow

    async def _execute(
        self,
        actor: UserDto,
        data: UpdateNotificationPreferencesDto,
    ) -> NotificationPreferencesDto:
        if data.subscription_expiration_email_enabled:
            if not actor.email or not actor.is_email_verified:
                raise NotificationEmailNotEligibleError(
                    "A verified email address is required"
                )
            if not _delivery_ready(self.config, self.email_sender):
                raise NotificationDeliveryUnavailableError(
                    "Subscription email reminders are unavailable"
                )
            if actor.is_blocked:
                raise NotificationEmailNotEligibleError("User is not eligible")

        async with self.uow:
            updated = await self.user_dao.set_subscription_expiration_email_preference(
                actor.id,
                enabled=data.subscription_expiration_email_enabled,
            )
            if updated is None:
                raise NotificationEmailNotEligibleError(
                    "Verified email eligibility changed; refresh and try again"
                )
            await self.uow.commit()
        return _preferences(updated, config=self.config, email_sender=self.email_sender)


class GenerateSubscriptionExpirationEmailReminders(Interactor[None, int]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        email_sender: EmailSender,
        reminder_dao: SubscriptionEmailReminderDao,
        uow: UnitOfWork,
    ) -> None:
        self.config = config
        self.email_sender = email_sender
        self.reminder_dao = reminder_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, data: None) -> int:
        now = datetime_now()
        async with self.uow:
            generated = 0
            if _delivery_ready(self.config, self.email_sender):
                generated = await self.reminder_dao.generate(
                    now=now,
                    days_before=REMINDER_DAYS_BEFORE,
                    candidate_limit=GENERATION_CANDIDATE_LIMIT,
                    generation_grace=GENERATION_GRACE,
                )
            deleted = await self.reminder_dao.delete_terminal_before(
                before=now - TERMINAL_RETENTION,
                limit=TERMINAL_CLEANUP_BATCH_SIZE,
            )
            await self.uow.commit()
        if generated:
            logger.info("Generated '{}' subscription email reminders", generated)
        if deleted:
            logger.info("Deleted '{}' retained terminal email reminders", deleted)
        return generated


def _processing_token_hash() -> str:
    token = secrets.token_urlsafe(32)
    return hashlib.sha256(f"remnashop:subscription-email:v1\0{token}".encode()).hexdigest()


def _error_code(exc: Exception) -> str:
    error_type = re.sub(r"[^A-Za-z0-9]", "_", type(exc).__name__).upper()
    return f"EMAIL_{error_type}"[:64]


def _retry_after(attempt_count: int) -> timedelta:
    seconds = min(60 * (2 ** max(attempt_count - 1, 0)), DELIVERY_RETRY_MAX_SECONDS)
    return timedelta(seconds=seconds)


def _message_id(reminder_id: int, sender_email: str, secret: str) -> str:
    candidate = sender_email.rpartition("@")[2].lower()
    domain = candidate if re.fullmatch(r"[a-z0-9.-]+", candidate) else "remnashop.local"
    opaque_id = hmac.new(
        secret.encode("utf-8"),
        f"remnashop:subscription-expiration-message-id:v1\0{reminder_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"<subscription-expiration-{opaque_id}@{domain}>"


def _days_text(days: int) -> str:
    if days == 1:
        return "1 день"
    if days in (2, 3, 4):
        return f"{days} дня"
    return f"{days} дней"


def _email_content(
    *,
    expire_at: datetime,
    days_before: int,
    cabinet_url: str,
    sender_email: str,
) -> tuple[str, str]:
    days = _days_text(days_before)
    subject = f"Напоминание: подписка истекает через {days}"
    expire_text = expire_at.strftime("%d.%m.%Y в %H:%M UTC")
    body = (
        "Здравствуйте!\n\n"
        f"Ваша оплаченная подписка истекает {expire_text}. "
        "Это только напоминание — автопродление не выполняется.\n\n"
        f"Открыть личный кабинет и продлить подписку: {cabinet_url}\n\n"
        "Если вы уже продлили подписку, просто проигнорируйте это письмо.\n\n"
        "Если письмо попало в спам, отметьте его как «Не спам» и добавьте "
        f"адрес отправителя {sender_email} в контакты или белый список, чтобы "
        "не пропустить следующие напоминания.\n\n"
        "Отключить напоминания можно в личном кабинете."
    )
    return subject, body


class DeliverSubscriptionExpirationEmailReminders(Interactor[None, int]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        email_sender: EmailSender,
        reminder_dao: SubscriptionEmailReminderDao,
        uow: UnitOfWork,
    ) -> None:
        self.config = config
        self.email_sender = email_sender
        self.reminder_dao = reminder_dao
        self.uow = uow

    async def _send_with_lease_heartbeat(
        self,
        *,
        reminder_id: int,
        token_hash: str,
        to: str,
        subject: str,
        body: str,
        message_id: str,
    ) -> tuple[bool, Exception | None]:
        send_task = asyncio.create_task(
            self.email_sender.send(
                to=to,
                subject=subject,
                body=body,
                message_id=message_id,
            ),
            name=f"subscription-email-send-{reminder_id}",
        )
        fence_owned = True
        while not send_task.done():
            done, _ = await asyncio.wait(
                (send_task,),
                timeout=DELIVERY_HEARTBEAT_INTERVAL.total_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if done:
                break

            try:
                async with self.uow:
                    renewed = await self.reminder_dao.renew_processing_lease(
                        reminder_id,
                        token_hash=token_hash,
                        lease_for=DELIVERY_LEASE,
                    )
                    await self.uow.commit()
            except Exception as exc:
                # A transient DB failure does not cancel the underlying SMTP
                # thread. Retry the heartbeat while its existing lease remains;
                # the final state transition is independently fenced.
                logger.warning(
                    "Email reminder '{}' lease heartbeat failed with code '{}'",
                    reminder_id,
                    _error_code(exc),
                )
                continue

            if not renewed:
                # asyncio cancellation cannot stop an SMTP call already running
                # in a worker thread. Await its real completion, but never mutate
                # an outbox row now owned (or terminalized) by another worker.
                fence_owned = False
                logger.warning(
                    "Email reminder '{}' lost its processing fence during SMTP",
                    reminder_id,
                )
                break

        try:
            await send_task
        except Exception as exc:
            return fence_owned, exc
        return fence_owned, None

    async def _deliver_one(
        self,
        *,
        reminder_id: int,
        token_hash: str,
        sender_email: str,
        cabinet_url: str,
    ) -> bool:
        async with self.uow:
            delivery = await self.reminder_dao.prepare_delivery(
                reminder_id,
                token_hash=token_hash,
                now=datetime_now(),
            )
            await self.uow.commit()
        if delivery is None:
            return False

        subject, body = _email_content(
            expire_at=delivery.expire_at,
            days_before=delivery.days_before,
            cabinet_url=cabinet_url,
            sender_email=sender_email,
        )
        # Revalidation and its SELECT FOR UPDATE transaction have already
        # committed here. Never hold user/subscription locks during SMTP:
        # opt-out, renewal and merge requests must remain responsive.
        # A narrow consent/renewal race between this commit and SMTP is
        # unavoidable without provider-side transactional delivery.
        fence_owned, send_error = await self._send_with_lease_heartbeat(
            reminder_id=delivery.reminder_id,
            token_hash=token_hash,
            to=delivery.recipient_email,
            subject=subject,
            body=body,
            message_id=_message_id(
                delivery.reminder_id,
                sender_email,
                self.config.crypt_key.get_secret_value(),
            ),
        )
        if send_error is not None:
            code = _error_code(send_error)
            if not fence_owned:
                logger.warning(
                    "Subscription email reminder '{}' SMTP failed after fence loss",
                    delivery.reminder_id,
                )
                return False
            async with self.uow:
                released = await self.reminder_dao.release_failed(
                    delivery.reminder_id,
                    token_hash=token_hash,
                    now=datetime_now(),
                    error_code=code,
                    max_attempts=DELIVERY_MAX_ATTEMPTS,
                    retry_after=_retry_after(delivery.attempt_count),
                )
                await self.uow.commit()
            if not released:
                logger.warning(
                    "Subscription email reminder '{}' lost its processing fence",
                    delivery.reminder_id,
                )
            logger.warning(
                "Subscription email reminder '{}' failed with code '{}'",
                delivery.reminder_id,
                code,
            )
            return False

        if not fence_owned:
            logger.warning(
                "Subscription email reminder '{}' SMTP completed after fence loss",
                delivery.reminder_id,
            )
            return False

        # SMTP success and the durable state transition cannot be atomic.
        # The stable Message-ID limits duplicate impact if this commit is lost.
        async with self.uow:
            marked = await self.reminder_dao.mark_sent(
                delivery.reminder_id,
                token_hash=token_hash,
                sent_at=datetime_now(),
            )
            await self.uow.commit()
        if not marked:
            logger.warning(
                "Subscription email reminder '{}' lost its processing fence",
                delivery.reminder_id,
            )
        return marked

    async def _execute(self, actor: UserDto, data: None) -> int:
        maintenance_now = datetime_now()
        async with self.uow:
            terminalized = await self.reminder_dao.sweep_undeliverable(
                now=maintenance_now,
                delivery_not_before=maintenance_now - DELIVERY_GRACE,
                max_attempts=DELIVERY_MAX_ATTEMPTS,
                limit=DELIVERY_MAINTENANCE_BATCH_SIZE,
            )
            await self.uow.commit()
        if terminalized:
            logger.info(
                "Terminalized '{}' stale or exhausted email reminders",
                terminalized,
            )
        if not _delivery_ready(self.config, self.email_sender):
            return 0

        sent_count = 0
        processed_count = 0
        sender_email = self.config.email.from_email.strip()
        cabinet_url = self.config.email.subscription_expiration_cabinet_url.strip()
        for _ in range(DELIVERY_BATCH_SIZE):
            claim_now = datetime_now()
            token_hash = _processing_token_hash()
            async with self.uow:
                reminders = await self.reminder_dao.claim_due(
                    now=claim_now,
                    delivery_not_before=claim_now - DELIVERY_GRACE,
                    token_hash=token_hash,
                    lease_for=DELIVERY_LEASE,
                    max_attempts=DELIVERY_MAX_ATTEMPTS,
                    limit=1,
                )
                await self.uow.commit()
            if not reminders:
                break

            reminder = reminders[0]
            processed_count += 1
            delivered = await self._deliver_one(
                reminder_id=reminder.id,
                token_hash=token_hash,
                sender_email=sender_email,
                cabinet_url=cabinet_url,
            )
            if delivered:
                sent_count += 1

        if processed_count:
            logger.info(
                "Processed '{}' subscription email reminders; sent '{}'",
                processed_count,
                sent_count,
            )
        return sent_count


__all__ = [
    "DeliverSubscriptionExpirationEmailReminders",
    "GenerateSubscriptionExpirationEmailReminders",
    "GetNotificationPreferences",
    "NotificationDeliveryUnavailableError",
    "NotificationEmailNotEligibleError",
    "REMINDER_DAYS_BEFORE",
    "UpdateNotificationPreferences",
    "UpdateNotificationPreferencesDto",
]
