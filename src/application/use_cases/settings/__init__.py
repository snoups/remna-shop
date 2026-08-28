from typing import Final

from src.application.common import Interactor

from .commands.access import ChangeAccessMode, TogglePayments, ToggleRegistration
from .commands.backup import (
    ToggleBackupEnabled,
    ToggleBackupSendToChat,
    UpdateBackupInterval,
    UpdateBackupMaxFiles,
)
from .commands.currency import UpdateDefaultCurrency
from .commands.defaults import CreateDefaultSettings
from .commands.extra import (
    ToggleMiniAppReserve,
    ToggleResetFeature,
    ToggleStarsPaidRequirement,
    ToggleTrialChannelGuard,
    UpdateResetCooldown,
)
from .commands.grace import (
    SetGraceExternalSquad,
    SetGraceStrategy,
    ToggleGraceEnabled,
    ToggleGraceInternalSquad,
    UpdateGraceDuration,
    UpdateGraceTag,
    UpdateGraceTraffic,
)
from .commands.notifications import (
    ToggleNotification,
    UpdateDefaultNotificationRoute,
    UpdateSystemNotificationRoute,
)
from .commands.referral import (
    ToggleReferralSystem,
    UpdateReferralAccrualStrategy,
    UpdateReferralLevel,
    UpdateReferralRewardConfig,
    UpdateReferralRewardStrategy,
    UpdateReferralRewardType,
)
from .commands.requirements import (
    ToggleConditionRequirement,
    UpdateChannelRequirement,
    UpdateRulesRequirement,
)

SETTINGS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    CreateDefaultSettings,
    ChangeAccessMode,
    ToggleConditionRequirement,
    ToggleNotification,
    TogglePayments,
    ToggleReferralSystem,
    ToggleRegistration,
    UpdateChannelRequirement,
    UpdateReferralAccrualStrategy,
    UpdateReferralLevel,
    UpdateReferralRewardConfig,
    UpdateReferralRewardStrategy,
    UpdateReferralRewardType,
    UpdateRulesRequirement,
    UpdateDefaultCurrency,
    UpdateSystemNotificationRoute,
    UpdateDefaultNotificationRoute,
    ToggleBackupEnabled,
    ToggleBackupSendToChat,
    UpdateBackupInterval,
    UpdateBackupMaxFiles,
    ToggleResetFeature,
    ToggleTrialChannelGuard,
    ToggleMiniAppReserve,
    ToggleStarsPaidRequirement,
    UpdateResetCooldown,
    SetGraceExternalSquad,
    SetGraceStrategy,
    ToggleGraceEnabled,
    ToggleGraceInternalSquad,
    UpdateGraceDuration,
    UpdateGraceTag,
    UpdateGraceTraffic,
)
