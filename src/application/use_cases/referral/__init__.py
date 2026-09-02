from typing import Final

from src.application.common import Interactor

from .commands.attachment import AttachReferral
from .commands.backfill import ManageHistoricalReferralRewards
from .commands.rewards import (
    AssignReferralRewards,
    GiveReferrerReward,
    RecoverLegacyReferralReward,
    ResolveManualReferralReward,
    RetryPendingReferralRewards,
)
from .queries.calculations import CalculateReferralReward
from .queries.code import GenerateReferralQr, ValidateReferralCode

REFERRAL_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    AttachReferral,
    ValidateReferralCode,
    GenerateReferralQr,
    CalculateReferralReward,
    GiveReferrerReward,
    AssignReferralRewards,
    RetryPendingReferralRewards,
    ResolveManualReferralReward,
    RecoverLegacyReferralReward,
    ManageHistoricalReferralRewards,
)
