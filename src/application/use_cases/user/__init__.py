from typing import Final

from src.application.common import Interactor

from .commands.activity import TrackUserActivity
from .commands.blocking import (
    BlockUsersByIds,
    ClearBlockedIds,
    SetBotBlockedStatus,
    ToggleUserBlockedStatus,
    UnblockAllUsers,
)
from .commands.merge import MergeUsers
from .commands.messaging import SendMessageToUser
from .commands.profile_edit import (
    ChangeUserPoints,
    ResetOwnReferralCode,
    ResetUserReferralCode,
    SetUserPersonalDiscount,
    SetUserPurchaseDiscount,
    ToggleUserTrialAvailable,
)
from .commands.registration import GetOrCreateUser, UpdateUserProfile
from .commands.roles import GetAdmins, RevokeRole, SetUserRole
from .commands.web_registration import RegisterWebUser
from .queries.activity import GetRecentActivityUsers
from .queries.plans import GetAvailablePlanByCode, GetAvailablePlans, GetAvailableTrial
from .queries.profile import GetUserDevices, GetUserProfile, GetUserProfileSubscription
from .queries.search import SearchUsers, SmartSearch

USER_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    BlockUsersByIds,
    ClearBlockedIds,
    GetAdmins,
    GetOrCreateUser,
    SetBotBlockedStatus,
    ToggleUserBlockedStatus,
    RevokeRole,
    SetUserRole,
    SearchUsers,
    SmartSearch,
    UnblockAllUsers,
    GetUserProfile,
    GetUserProfileSubscription,
    GetUserDevices,
    GetAvailablePlans,
    SetUserPersonalDiscount,
    SetUserPurchaseDiscount,
    ToggleUserTrialAvailable,
    ChangeUserPoints,
    ResetOwnReferralCode,
    ResetUserReferralCode,
    SendMessageToUser,
    MergeUsers,
    GetAvailableTrial,
    GetAvailablePlanByCode,
    UpdateUserProfile,
    RegisterWebUser,
    TrackUserActivity,
    GetRecentActivityUsers,
)
