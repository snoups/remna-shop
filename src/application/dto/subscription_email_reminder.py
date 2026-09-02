from dataclasses import dataclass
from datetime import datetime

from .base import BaseDto, TimestampMixin


@dataclass(kw_only=True)
class SubscriptionEmailReminderDto(BaseDto, TimestampMixin):
    user_id: int
    subscription_id: int
    expire_at_snapshot: datetime
    days_before: int
    due_at: datetime
    state: str
    attempt_count: int
    next_attempt_at: datetime
    processing_token_hash: str | None = None
    processing_lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    sent_at: datetime | None = None
    canceled_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class SubscriptionEmailDeliveryDto:
    reminder_id: int
    recipient_email: str
    expire_at: datetime
    days_before: int
    attempt_count: int


@dataclass(frozen=True, kw_only=True)
class NotificationPreferencesDto:
    subscription_expiration_email_enabled: bool
    email_eligible: bool
    sender_email: str | None
    days_before: tuple[int, ...]
