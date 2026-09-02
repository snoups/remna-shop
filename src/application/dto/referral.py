from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from src.core.enums import (
    LegacyReferralRewardRecoveryAction,
    LegacyReferralRewardSourceValidation,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardStrategy,
    ReferralRewardType,
)

from .base import BaseDto, TimestampMixin, TrackableMixin
from .user import UserDto


@dataclass(kw_only=True)
class ReferralDto(BaseDto, TrackableMixin, TimestampMixin):
    level: ReferralLevel

    referrer: "UserDto"
    referred: "UserDto"


@dataclass(kw_only=True)
class ReferralRewardDto(BaseDto, TrackableMixin, TimestampMixin):
    user_id: int

    type: ReferralRewardType
    amount: int
    is_issued: bool = False
    referral_id: Optional[int] = None
    source_transaction_id: Optional[int] = None
    origin_referral_id: Optional[int] = None
    level: Optional[ReferralLevel] = None
    accrual_strategy_snapshot: Optional[ReferralAccrualStrategy] = None
    accrual_strategy: Optional[ReferralAccrualStrategy] = None
    reward_strategy: Optional[ReferralRewardStrategy] = None
    config_value: Optional[int] = None
    state: ReferralRewardState = ReferralRewardState.PENDING
    attempt_count: int = 0
    next_attempt_at: Optional[datetime] = None
    processing_token_hash: Optional[str] = None
    processing_lease_expires_at: Optional[datetime] = None
    last_error: Optional[str] = None
    manual_alerted_at: Optional[datetime] = None
    refund_detected_at: Optional[datetime] = None
    manual_incident_version: int = 0
    manual_cause: Optional[str] = None
    issued_at: Optional[datetime] = None
    target_subscription_id: Optional[int] = None
    baseline_expire_at: Optional[datetime] = None
    target_expire_at: Optional[datetime] = None
    operator_recovery_manifest_sha256: Optional[str] = None

    @property
    def rewarded_at(self) -> Optional[datetime]:
        return self.issued_at or self.created_at


@dataclass(frozen=True, kw_only=True)
class LegacyReferralRewardRecoveryDto:
    reward_id: int
    action: LegacyReferralRewardRecoveryAction
    expected_version: int
    source_transaction_id: Optional[int]
    origin_referral_id: Optional[int]
    level: Optional[ReferralLevel]
    expected_reward_amount: int
    accrual_strategy_snapshot: Optional[ReferralAccrualStrategy]
    reward_strategy: Optional[ReferralRewardStrategy]
    config_value: Optional[int]
    operator_reference: str
    reason: str
    evidence_sha256: str
    expected_user_id: Optional[int] = None
    expected_referral_id: Optional[int] = None
    expected_created_at: Optional[datetime] = None
    expected_participant_merge_audit_ids: tuple[int, ...] = ()
    source_validation: Optional[LegacyReferralRewardSourceValidation] = None
    authorization_manifest_sha256: Optional[str] = None
    resolved_by: str = "ADMIN_API"


@dataclass(frozen=True)
class UserReferralStatsDto:
    referrer_telegram_id: Optional[int]
    referrer_email: Optional[str]
    referrer_username: Optional[str]
    referrals_level_1: int
    referrals_level_2: int
    reward_points: int
    reward_days: int


@dataclass(frozen=True)
class ReferralRewardBackfillAuditDto:
    id: int
    request_hash: str
    status: str
    operator_identity: str
    operator_reference: str
    reason: str
    source_transaction_ids: list[int]
    config_snapshot: dict[str, Any]
    preview_snapshot: dict[str, Any]
    applied_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
