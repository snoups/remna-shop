from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.infrastructure.database.constraints import (
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_V2_SQL,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL,
)

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRE_0055_RESOLUTION_CONSTRAINT_SQL = (
    "decision IN ('CONFIRM_ISSUED', 'CANCEL', 'RETRY_PROVEN_MISSING', "
    "'CONFIRM_ADMIN_COMPENSATED', 'ACK_ADMIN_COMPENSATED_REFUND') AND "
    "((decision IN ('RETRY_PROVEN_MISSING', 'CONFIRM_ADMIN_COMPENSATED') "
    "AND selected_provenance IS NOT NULL "
    "AND jsonb_typeof(selected_provenance) = 'object' "
    "AND evidence_sha256 IS NOT NULL "
    "AND evidence_sha256 ~ '^[0-9a-f]{64}$' "
    "AND selected_source_transaction_id IS NOT NULL "
    "AND selected_origin_referral_id IS NOT NULL "
    "AND selected_level IS NOT NULL "
    "AND authorization_manifest_sha256 IS NOT NULL "
    "AND authorization_manifest_sha256 ~ '^[0-9a-f]{64}$') OR "
    "(decision = 'ACK_ADMIN_COMPENSATED_REFUND' "
    "AND selected_provenance IS NULL AND evidence_sha256 IS NULL "
    "AND selected_source_transaction_id IS NOT NULL "
    "AND selected_origin_referral_id IS NOT NULL "
    "AND selected_level IS NOT NULL "
    "AND authorization_manifest_sha256 IS NOT NULL "
    "AND authorization_manifest_sha256 ~ '^[0-9a-f]{64}$' "
    "AND source_status = 'REFUNDED' AND NOT allow_drift) OR "
    "(decision IN ('CONFIRM_ISSUED', 'CANCEL') "
    "AND selected_provenance IS NULL AND evidence_sha256 IS NULL "
    "AND selected_source_transaction_id IS NULL "
    "AND selected_origin_referral_id IS NULL "
    "AND selected_level IS NULL "
    "AND authorization_manifest_sha256 IS NULL))"
)

PRE_0055_REWARD_CONSTRAINT_SQL = (
    "((state = 'ISSUED' AND is_issued AND issued_at IS NOT NULL "
    "AND processing_token_hash IS NULL AND processing_lease_expires_at IS NULL) OR "
    "(state = 'PROCESSING' AND NOT is_issued "
    "AND processing_token_hash IS NOT NULL "
    "AND processing_lease_expires_at IS NOT NULL) OR "
    "(state IN ('PENDING', 'RETRY_WAITING', 'SUPERSEDED') "
    "AND NOT is_issued AND processing_token_hash IS NULL "
    "AND processing_lease_expires_at IS NULL) OR "
    "(state = 'MANUAL_REQUIRED' AND processing_token_hash IS NULL "
    "AND processing_lease_expires_at IS NULL "
    "AND ((NOT is_issued) OR (is_issued AND issued_at IS NOT NULL)))) AND "
    "((target_expire_at IS NULL AND baseline_expire_at IS NULL "
    "AND target_subscription_id IS NULL) OR "
    "(type = 'EXTRA_DAYS' AND target_expire_at IS NOT NULL "
    "AND baseline_expire_at IS NOT NULL AND target_subscription_id IS NOT NULL)) "
    "AND ((source_transaction_id IS NULL AND origin_referral_id IS NULL "
    "AND level IS NULL AND accrual_strategy_snapshot IS NULL "
    "AND accrual_strategy IS NULL AND reward_strategy IS NULL "
    "AND config_value IS NULL "
    "AND state IN ('ISSUED', 'MANUAL_REQUIRED', 'SUPERSEDED')) OR "
    "(source_transaction_id IS NOT NULL AND origin_referral_id IS NOT NULL "
    "AND level IS NOT NULL AND accrual_strategy_snapshot IS NOT NULL "
    "AND reward_strategy IS NOT NULL AND config_value IS NOT NULL "
    "AND ((accrual_strategy_snapshot = 'ON_FIRST_PAYMENT' "
    "AND (accrual_strategy IS NULL OR accrual_strategy = 'ON_FIRST_PAYMENT')) "
    "OR (accrual_strategy_snapshot = 'ON_EACH_PAYMENT' "
    "AND accrual_strategy = 'ON_EACH_PAYMENT'))))"
)

DOWNGRADE_GUARD_SQL = """
DO $downgrade_guard$
BEGIN
    LOCK TABLE referral_rewards, referral_reward_resolutions IN SHARE MODE;

    IF EXISTS (
        SELECT 1 FROM referral_rewards
        WHERE operator_recovery_manifest_sha256 IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM referral_reward_resolutions
        WHERE decision = 'RETRY_OPERATOR_DIRECTED'
    ) THEN
        RAISE EXCEPTION
            'Migration 0055 downgrade refused: operator-directed recovery evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$downgrade_guard$;
"""


def upgrade() -> None:
    op.add_column(
        "referral_rewards",
        sa.Column("operator_recovery_manifest_sha256", sa.String(length=64), nullable=True),
    )
    op.drop_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        type_="check",
    )
    op.create_check_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL,
    )
    op.drop_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        type_="check",
    )
    op.create_check_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_V2_SQL,
    )
    op.drop_index(
        "uq_referral_reward_resolutions_recovery_source_level",
        table_name="referral_reward_resolutions",
    )
    op.create_index(
        "uq_referral_reward_resolutions_recovery_source_level",
        "referral_reward_resolutions",
        ["selected_source_transaction_id", "selected_level"],
        unique=True,
        postgresql_where=sa.text(
            "decision IN ('RETRY_PROVEN_MISSING', 'CONFIRM_ADMIN_COMPENSATED', "
            "'RETRY_OPERATOR_DIRECTED')"
        ),
    )


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD_SQL)
    op.drop_index(
        "uq_referral_reward_resolutions_recovery_source_level",
        table_name="referral_reward_resolutions",
    )
    op.create_index(
        "uq_referral_reward_resolutions_recovery_source_level",
        "referral_reward_resolutions",
        ["selected_source_transaction_id", "selected_level"],
        unique=True,
        postgresql_where=sa.text(
            "decision IN ('RETRY_PROVEN_MISSING', 'CONFIRM_ADMIN_COMPENSATED')"
        ),
    )
    op.drop_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        type_="check",
    )
    op.create_check_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        PRE_0055_RESOLUTION_CONSTRAINT_SQL,
    )
    op.drop_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        type_="check",
    )
    op.create_check_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        PRE_0055_REWARD_CONSTRAINT_SQL,
    )
    op.drop_column("referral_rewards", "operator_recovery_manifest_sha256")
