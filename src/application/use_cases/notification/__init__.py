from typing import Final

from src.application.common import Interactor

from .commands import (
    DeliverSubscriptionExpirationEmailReminders,
    GenerateSubscriptionExpirationEmailReminders,
    GetNotificationPreferences,
    UpdateNotificationPreferences,
)

NOTIFICATION_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetNotificationPreferences,
    UpdateNotificationPreferences,
    GenerateSubscriptionExpirationEmailReminders,
    DeliverSubscriptionExpirationEmailReminders,
)

__all__ = [
    "DeliverSubscriptionExpirationEmailReminders",
    "GenerateSubscriptionExpirationEmailReminders",
    "GetNotificationPreferences",
    "NOTIFICATION_USE_CASES",
    "UpdateNotificationPreferences",
]
