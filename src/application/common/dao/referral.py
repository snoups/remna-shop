from datetime import datetime, timedelta
from typing import Any, Optional, Protocol, runtime_checkable

from src.application.dto import (
    LegacyReferralRewardRecoveryDto,
    ReferralDto,
    ReferralRewardBackfillAuditDto,
    ReferralRewardDto,
    ReferralStatisticsDto,
    UserReferralStatsDto,
)
from src.core.enums import TransactionStatus


@runtime_checkable
class ReferralDao(Protocol):
    async def lock_referral_graph(self) -> None: ...

    async def has_referral_path(
        self,
        ancestor_user_id: int,
        descendant_user_id: int,
    ) -> bool: ...

    async def create_referral(self, referral: ReferralDto) -> ReferralDto: ...

    async def get_by_referred_id(self, referred_id: int) -> Optional[ReferralDto]: ...

    async def get_referrals_count(self, referrer_id: int) -> int: ...

    async def get_referrals_list(
        self,
        referrer_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReferralDto]: ...

    async def create_reward(
        self,
        reward: ReferralRewardDto,
        referral_id: int,
    ) -> Optional[ReferralRewardDto]: ...

    async def get_rewards_by_source_transaction(
        self,
        source_transaction_id: int,
    ) -> list[ReferralRewardDto]: ...

    async def has_legacy_ambiguous_reward(
        self,
        *,
        referral_ids: list[int],
        recipient_user_ids: list[int],
    ) -> bool: ...

    async def acquire_historical_backfill_lock(self) -> None: ...

    async def create_or_get_backfill_preview(
        self,
        *,
        request_hash: str,
        operator_identity: str,
        operator_reference: str,
        reason: str,
        source_transaction_ids: list[int],
        config_snapshot: dict[str, Any],
        preview_snapshot: dict[str, Any],
    ) -> ReferralRewardBackfillAuditDto: ...

    async def get_backfill_preview_for_update(
        self,
        preview_id: int,
    ) -> Optional[ReferralRewardBackfillAuditDto]: ...

    async def mark_backfill_preview_applied(self, preview_id: int) -> bool: ...

    async def get_reward_by_id(
        self,
        reward_id: int,
        *,
        for_update: bool = False,
    ) -> Optional[ReferralRewardDto]: ...

    async def lock_manual_reward_source_status(
        self,
        reward_id: int,
    ) -> Optional[TransactionStatus]: ...

    async def claim_pending_rewards(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[ReferralRewardDto]: ...

    async def defer_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
    ) -> bool: ...

    async def mark_reward_manual_required(
        self,
        reward_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool: ...

    async def lock_reward_source_if_eligible(
        self,
        reward_id: int,
        *,
        token_hash: str,
    ) -> bool: ...

    async def cancel_claimed_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool: ...

    async def set_extra_days_target(
        self,
        reward_id: int,
        *,
        token_hash: str,
        subscription_id: int,
        baseline_expire_at: datetime,
        target_expire_at: datetime,
    ) -> bool: ...

    async def issue_points_reward(
        self,
        reward_id: int,
        *,
        user_id: int,
        amount: int,
        token_hash: str,
    ) -> bool: ...

    async def finish_extra_days_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
    ) -> bool: ...

    async def get_reward_referred_name(self, reward_id: int) -> str: ...

    async def get_manual_required_rewards(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReferralRewardDto]: ...

    async def claim_manual_required_rewards_for_alert(
        self,
        *,
        limit: int = 100,
    ) -> list[ReferralRewardDto]: ...

    async def mark_manual_rewards_alerted(self, reward_ids: list[int]) -> None: ...

    async def resolve_manual_reward(
        self,
        reward_id: int,
        *,
        expected_version: int,
        confirm_issued: bool,
        operator_reference: str,
        resolved_by: str,
        reason: str,
        allow_drift: bool = False,
        observed_subscription_id: Optional[int] = None,
        observed_remote_uuid: Optional[str] = None,
        observed_expire_at: Optional[datetime] = None,
        source_status: Optional[TransactionStatus] = None,
        ack_admin_compensated_refund: bool = False,
    ) -> bool: ...

    async def manual_resolution_match(
        self,
        reward_id: int,
        *,
        expected_version: int,
        confirm_issued: bool,
        operator_reference: str,
        resolved_by: str,
        reason: str,
        allow_drift: bool = False,
        ack_admin_compensated_refund: bool = False,
    ) -> Optional[bool]: ...

    async def recover_legacy_extra_days_reward(
        self,
        recovery: LegacyReferralRewardRecoveryDto,
    ) -> bool: ...

    async def get_referral_chain(
        self,
        referred_id: int,
    ) -> tuple[Optional[ReferralDto], Optional[ReferralDto]]: ...

    async def lock_referral_attribution(
        self,
        referred_id: int,
        referrer_ids: tuple[int, ...] = (),
    ) -> None: ...

    async def get_stats(self) -> ReferralStatisticsDto: ...

    async def get_user_referral_stats(self, user_id: int) -> UserReferralStatsDto: ...

    async def get_referrals_with_payment_count(self, user_id: int) -> int: ...
