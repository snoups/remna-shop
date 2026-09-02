from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardStrategy,
    ReferralRewardType,
)
from src.infrastructure.database.constraints import (
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_V2_SQL,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL,
)

from .base import BaseSql
from .subscription import Subscription
from .timestamp import NOW_FUNC, TimestampMixin
from .transaction import Transaction
from .user import User


class Referral(BaseSql, TimestampMixin):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    referred_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )

    # Legacy, non-null edge metadata. New rows store FIRST because every row is
    # a direct attribution; relative L2 is derived by traversing referral edges.
    level: Mapped[ReferralLevel]

    referrer: Mapped["User"] = relationship(
        lazy="selectin",
        foreign_keys=[referrer_id],
    )
    referred: Mapped["User"] = relationship(
        lazy="selectin",
        foreign_keys=[referred_id],
    )
    rewards: Mapped[list["ReferralReward"]] = relationship(
        back_populates="referral",
        foreign_keys="ReferralReward.referral_id",
        passive_deletes=True,
        lazy="selectin",
    )


class ReferralReward(BaseSql, TimestampMixin):
    __tablename__ = "referral_rewards"
    __table_args__ = (
        CheckConstraint(
            REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL,
            name=REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        ),
        CheckConstraint(
            "state != 'ISSUED' OR accrual_strategy_snapshot IS NULL "
            "OR accrual_strategy_snapshot != 'ON_FIRST_PAYMENT' "
            "OR accrual_strategy = 'ON_FIRST_PAYMENT'",
            name="ck_referral_rewards_issued_first_payment_claimed",
        ),
        UniqueConstraint(
            "source_transaction_id",
            "origin_referral_id",
            "level",
            name="uq_referral_rewards_source_transaction_origin_level",
        ),
        Index(
            "uq_referral_rewards_first_payment_origin_level",
            "origin_referral_id",
            "level",
            unique=True,
            postgresql_where=text("accrual_strategy = 'ON_FIRST_PAYMENT'"),
        ),
        Index(
            "uq_referral_rewards_processing_recipient",
            "user_id",
            unique=True,
            postgresql_where=text("state = 'PROCESSING'"),
        ),
        Index(
            "ix_referral_rewards_retryable",
            "next_attempt_at",
            "id",
            postgresql_where=text("state IN ('PENDING', 'RETRY_WAITING', 'PROCESSING')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(
        ForeignKey("referrals.id", ondelete="RESTRICT"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    source_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        index=True,
    )
    origin_referral_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("referrals.id", ondelete="RESTRICT"),
        index=True,
    )

    type: Mapped[ReferralRewardType]
    amount: Mapped[int]
    is_issued: Mapped[bool]
    # Migration 0052 owns the rolling-deploy server default. Keeping it out of
    # runtime metadata prevents new ORM inserts from silently becoming manual cases.
    state: Mapped[ReferralRewardState]

    level: Mapped[Optional[ReferralLevel]]
    accrual_strategy_snapshot: Mapped[Optional[ReferralAccrualStrategy]]
    accrual_strategy: Mapped[Optional[ReferralAccrualStrategy]]
    reward_strategy: Mapped[Optional[ReferralRewardStrategy]]
    config_value: Mapped[Optional[int]]

    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    next_attempt_at: Mapped[Optional[datetime]]
    processing_token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    processing_lease_expires_at: Mapped[Optional[datetime]]
    last_error: Mapped[Optional[str]] = mapped_column(String(64))
    manual_alerted_at: Mapped[Optional[datetime]]
    refund_detected_at: Mapped[Optional[datetime]]
    manual_incident_version: Mapped[int] = mapped_column(default=0, server_default="0")
    manual_cause: Mapped[Optional[str]] = mapped_column(String(64))
    issued_at: Mapped[Optional[datetime]]
    target_subscription_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("subscriptions.id", ondelete="RESTRICT"),
        index=True,
    )
    baseline_expire_at: Mapped[Optional[datetime]]
    target_expire_at: Mapped[Optional[datetime]]
    operator_recovery_manifest_sha256: Mapped[Optional[str]] = mapped_column(String(64))

    referral: Mapped["Referral"] = relationship(
        back_populates="rewards",
        lazy="selectin",
        foreign_keys=[referral_id],
    )

    user: Mapped["User"] = relationship(lazy="selectin", foreign_keys=[user_id])

    source_transaction: Mapped[Optional["Transaction"]] = relationship(
        lazy="selectin",
        foreign_keys=[source_transaction_id],
    )
    origin_referral: Mapped[Optional["Referral"]] = relationship(
        lazy="selectin",
        foreign_keys=[origin_referral_id],
    )
    target_subscription: Mapped[Optional["Subscription"]] = relationship(
        lazy="selectin",
        foreign_keys=[target_subscription_id],
    )


class ReferralRewardResolution(BaseSql, TimestampMixin):
    __tablename__ = "referral_reward_resolutions"
    __table_args__ = (
        CheckConstraint(
            REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_V2_SQL,
            name=REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        ),
        UniqueConstraint(
            "reward_id",
            "incident_version",
            name="uq_referral_reward_resolutions_reward_incident",
        ),
        Index(
            "uq_referral_reward_resolutions_recovery_source_level",
            "selected_source_transaction_id",
            "selected_level",
            unique=True,
            postgresql_where=text(
                "decision IN ('RETRY_PROVEN_MISSING', 'CONFIRM_ADMIN_COMPENSATED', "
                "'RETRY_OPERATOR_DIRECTED')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reward_id: Mapped[int] = mapped_column(
        ForeignKey("referral_rewards.id", ondelete="RESTRICT"),
        index=True,
    )
    incident_version: Mapped[int]
    decision: Mapped[str] = mapped_column(String(32))
    operator_reference: Mapped[str] = mapped_column(String(256))
    resolved_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(1024))
    allow_drift: Mapped[bool] = mapped_column(default=False, server_default="false")
    observed_subscription_id: Mapped[Optional[int]]
    observed_remote_uuid: Mapped[Optional[str]] = mapped_column(String(64))
    observed_expire_at: Mapped[Optional[datetime]]
    source_status: Mapped[Optional[str]] = mapped_column(String(32))
    selected_provenance: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    evidence_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    selected_source_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="RESTRICT"),
    )
    selected_origin_referral_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("referrals.id", ondelete="RESTRICT"),
    )
    selected_level: Mapped[Optional[ReferralLevel]]
    authorization_manifest_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    resolved_at: Mapped[datetime] = mapped_column(server_default=NOW_FUNC)

    reward: Mapped["ReferralReward"] = relationship(lazy="selectin")


class ReferralRewardBackfillAudit(BaseSql, TimestampMixin):
    __tablename__ = "referral_reward_backfill_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREVIEWED', 'APPLIED')",
            name="ck_referral_reward_backfill_audits_status",
        ),
        UniqueConstraint(
            "request_hash",
            name="uq_referral_reward_backfill_audits_request_hash",
        ),
        Index(
            "ix_referral_reward_backfill_audits_request_hash",
            "request_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="PREVIEWED")
    operator_identity: Mapped[str] = mapped_column(String(128))
    operator_reference: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(String(1024))
    source_transaction_ids: Mapped[list[int]] = mapped_column(JSONB)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    preview_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    applied_at: Mapped[Optional[datetime]]
