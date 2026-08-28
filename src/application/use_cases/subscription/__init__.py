from typing import Final

from src.application.common import Interactor

from .commands.grace import EnterGraceMode
from .commands.management import (
    AddSubscriptionDuration,
    DeleteSubscription,
    DisableTrialSubscription,
    EnableTrialSubscription,
    ToggleExternalSquad,
    ToggleInternalSquad,
    ToggleSubscriptionStatus,
    UpdateDeviceLimit,
    UpdateTrafficLimit,
)
from .commands.purchase import ActivateTrialSubscription, PurchaseSubscription
from .commands.set_plan import SetUserSubscription
from .commands.sync import (
    CheckSubscriptionSyncState,
    SyncSubscriptionFromRemnashop,
    SyncSubscriptionFromRemnawave,
)
from .queries.match import MatchSubscription

SUBSCRIPTION_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ToggleSubscriptionStatus,
    DeleteSubscription,
    UpdateTrafficLimit,
    UpdateDeviceLimit,
    ToggleInternalSquad,
    ToggleExternalSquad,
    AddSubscriptionDuration,
    DisableTrialSubscription,
    EnableTrialSubscription,
    MatchSubscription,
    CheckSubscriptionSyncState,
    SyncSubscriptionFromRemnawave,
    SyncSubscriptionFromRemnashop,
    SetUserSubscription,
    ActivateTrialSubscription,
    PurchaseSubscription,
    EnterGraceMode,
)
