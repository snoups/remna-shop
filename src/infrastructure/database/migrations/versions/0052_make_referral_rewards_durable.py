from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.infrastructure.database.constraints import (
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_SQL,
)

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOWNGRADE_DURABLE_DATA_GUARD_SQL = """
DO $downgrade_guard$
BEGIN
    -- Keep the check valid until the transaction finishes: concurrent durable
    -- writes must not slip in between this guard and the destructive drops.
    LOCK TABLE
        referral_reward_resolutions,
        referral_reward_backfill_audits,
        referral_rewards
        IN SHARE MODE;

    IF EXISTS (SELECT 1 FROM referral_reward_resolutions) THEN
        RAISE EXCEPTION
            'Migration 0052 downgrade refused: referral reward resolutions exist'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (SELECT 1 FROM referral_reward_backfill_audits) THEN
        RAISE EXCEPTION
            'Migration 0052 downgrade refused: referral reward backfill audits exist'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM referral_rewards
        WHERE source_transaction_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            'Migration 0052 downgrade refused: durable referral reward provenance exists'
            USING ERRCODE = '55000';
    END IF;
END;
$downgrade_guard$;
"""


def upgrade() -> None:
    accrual_strategy = postgresql.ENUM(
        "ON_FIRST_PAYMENT",
        "ON_EACH_PAYMENT",
        name="referral_accrual_strategy",
    )
    reward_strategy = postgresql.ENUM(
        "AMOUNT",
        "PERCENT",
        name="referral_reward_strategy",
    )
    reward_state = postgresql.ENUM(
        "PENDING",
        "PROCESSING",
        "RETRY_WAITING",
        "ISSUED",
        "MANUAL_REQUIRED",
        "SUPERSEDED",
        name="referral_reward_state",
    )
    accrual_strategy.create(op.get_bind(), checkfirst=True)
    reward_strategy.create(op.get_bind(), checkfirst=True)
    reward_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "referral_rewards",
        sa.Column("source_transaction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("origin_referral_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column(
            "level",
            postgresql.ENUM(name="referral_level", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "referral_rewards",
        sa.Column(
            "accrual_strategy_snapshot",
            postgresql.ENUM(name="referral_accrual_strategy", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "referral_rewards",
        sa.Column(
            "accrual_strategy",
            postgresql.ENUM(name="referral_accrual_strategy", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "referral_rewards",
        sa.Column(
            "reward_strategy",
            postgresql.ENUM(name="referral_reward_strategy", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("referral_rewards", sa.Column("config_value", sa.Integer(), nullable=True))
    op.add_column(
        "referral_rewards",
        sa.Column(
            "state",
            postgresql.ENUM(name="referral_reward_state", create_type=False),
            nullable=True,
            # Intentionally migration-only rolling-deploy safety: an old process
            # still inserts only legacy columns. Fence that row for review; an old
            # is_issued-only update is then rejected by the durable state check.
            server_default=sa.text("'MANUAL_REQUIRED'::referral_reward_state"),
        ),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("processing_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("last_error", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("manual_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("refund_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("manual_incident_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("manual_cause", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("target_subscription_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("baseline_expire_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("target_expire_at", sa.DateTime(timezone=True), nullable=True),
    )

    # An unissued legacy row is ambiguous: older code could grant the side effect and
    # crash before flipping is_issued. Never replay it automatically.
    op.execute(
        "UPDATE referral_rewards SET "
        "state = CASE WHEN is_issued THEN 'ISSUED'::referral_reward_state "
        "ELSE 'MANUAL_REQUIRED'::referral_reward_state END, "
        "issued_at = CASE WHEN is_issued THEN updated_at ELSE NULL END, "
        "last_error = CASE WHEN is_issued THEN NULL ELSE 'LEGACY_AMBIGUOUS_ISSUANCE' END"
        ", manual_incident_version = CASE WHEN is_issued THEN 0 ELSE 1 END"
        ", manual_cause = CASE WHEN is_issued THEN NULL ELSE 'LEGACY_AMBIGUOUS_ISSUANCE' END"
    )
    op.alter_column("referral_rewards", "state", nullable=False)

    op.drop_constraint(
        "referral_rewards_referral_id_fkey",
        "referral_rewards",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "referral_rewards_referral_id_fkey",
        "referral_rewards",
        "referrals",
        ["referral_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "referral_rewards_source_transaction_id_fkey",
        "referral_rewards",
        "transactions",
        ["source_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "referral_rewards_origin_referral_id_fkey",
        "referral_rewards",
        "referrals",
        ["origin_referral_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "referral_rewards_target_subscription_id_fkey",
        "referral_rewards",
        "subscriptions",
        ["target_subscription_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_referral_rewards_source_transaction_id",
        "referral_rewards",
        ["source_transaction_id"],
    )
    op.create_index(
        "ix_referral_rewards_origin_referral_id",
        "referral_rewards",
        ["origin_referral_id"],
    )
    op.create_index(
        "ix_referral_rewards_target_subscription_id",
        "referral_rewards",
        ["target_subscription_id"],
    )
    op.create_unique_constraint(
        "uq_referral_rewards_source_transaction_origin_level",
        "referral_rewards",
        ["source_transaction_id", "origin_referral_id", "level"],
    )
    op.create_index(
        "uq_referral_rewards_first_payment_origin_level",
        "referral_rewards",
        ["origin_referral_id", "level"],
        unique=True,
        postgresql_where=sa.text("accrual_strategy = 'ON_FIRST_PAYMENT'"),
    )
    op.create_index(
        "uq_referral_rewards_processing_recipient",
        "referral_rewards",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'PROCESSING'"),
    )
    op.create_index(
        "ix_referral_rewards_retryable",
        "referral_rewards",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("state IN ('PENDING', 'RETRY_WAITING', 'PROCESSING')"),
    )
    op.create_check_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_SQL,
    )
    op.create_check_constraint(
        "ck_referral_rewards_issued_first_payment_claimed",
        "referral_rewards",
        "state != 'ISSUED' OR accrual_strategy_snapshot IS NULL "
        "OR accrual_strategy_snapshot != 'ON_FIRST_PAYMENT' "
        "OR accrual_strategy = 'ON_FIRST_PAYMENT'",
    )
    op.create_table(
        "referral_reward_resolutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reward_id", sa.Integer(), nullable=False),
        sa.Column("incident_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("operator_reference", sa.String(length=256), nullable=False),
        sa.Column("resolved_by", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column(
            "allow_drift",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("observed_subscription_id", sa.Integer(), nullable=True),
        sa.Column("observed_remote_uuid", sa.String(length=64), nullable=True),
        sa.Column("observed_expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_status", sa.String(length=32), nullable=True),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('CONFIRM_ISSUED', 'CANCEL')",
            name="ck_referral_reward_resolutions_decision",
        ),
        sa.ForeignKeyConstraint(
            ["reward_id"],
            ["referral_rewards.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reward_id",
            "incident_version",
            name="uq_referral_reward_resolutions_reward_incident",
        ),
    )
    op.create_index(
        "ix_referral_reward_resolutions_reward_id",
        "referral_reward_resolutions",
        ["reward_id"],
    )
    op.create_table(
        "referral_reward_backfill_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("operator_identity", sa.String(length=128), nullable=False),
        sa.Column("operator_reference", sa.String(length=256), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("source_transaction_ids", postgresql.JSONB(), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("preview_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PREVIEWED', 'APPLIED')",
            name="ck_referral_reward_backfill_audits_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_hash",
            name="uq_referral_reward_backfill_audits_request_hash",
        ),
    )
    op.create_index(
        "ix_referral_reward_backfill_audits_request_hash",
        "referral_reward_backfill_audits",
        ["request_hash"],
    )


def downgrade() -> None:
    # 0052 becomes forward-only as soon as durable provenance or audit evidence
    # exists. This must remain the first operation in downgrade.
    op.execute(DOWNGRADE_DURABLE_DATA_GUARD_SQL)
    op.drop_index(
        "ix_referral_reward_backfill_audits_request_hash",
        table_name="referral_reward_backfill_audits",
    )
    op.drop_table("referral_reward_backfill_audits")
    op.drop_index(
        "ix_referral_reward_resolutions_reward_id",
        table_name="referral_reward_resolutions",
    )
    op.drop_table("referral_reward_resolutions")
    op.drop_constraint(
        "ck_referral_rewards_issued_first_payment_claimed",
        "referral_rewards",
        type_="check",
    )
    op.drop_constraint(
        REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
        "referral_rewards",
        type_="check",
    )
    op.drop_index("ix_referral_rewards_retryable", table_name="referral_rewards")
    op.drop_index(
        "ix_referral_rewards_target_subscription_id",
        table_name="referral_rewards",
    )
    op.drop_index(
        "uq_referral_rewards_processing_recipient",
        table_name="referral_rewards",
    )
    op.drop_index(
        "uq_referral_rewards_first_payment_origin_level",
        table_name="referral_rewards",
    )
    op.drop_constraint(
        "uq_referral_rewards_source_transaction_origin_level",
        "referral_rewards",
        type_="unique",
    )
    op.drop_index(
        "ix_referral_rewards_origin_referral_id",
        table_name="referral_rewards",
    )
    op.drop_index(
        "ix_referral_rewards_source_transaction_id",
        table_name="referral_rewards",
    )
    op.drop_constraint(
        "referral_rewards_source_transaction_id_fkey",
        "referral_rewards",
        type_="foreignkey",
    )
    op.drop_constraint(
        "referral_rewards_origin_referral_id_fkey",
        "referral_rewards",
        type_="foreignkey",
    )
    op.drop_constraint(
        "referral_rewards_target_subscription_id_fkey",
        "referral_rewards",
        type_="foreignkey",
    )
    op.drop_constraint(
        "referral_rewards_referral_id_fkey",
        "referral_rewards",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "referral_rewards_referral_id_fkey",
        "referral_rewards",
        "referrals",
        ["referral_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for column in (
        "target_expire_at",
        "baseline_expire_at",
        "target_subscription_id",
        "issued_at",
        "manual_cause",
        "manual_incident_version",
        "refund_detected_at",
        "manual_alerted_at",
        "last_error",
        "processing_lease_expires_at",
        "processing_token_hash",
        "next_attempt_at",
        "attempt_count",
        "state",
        "config_value",
        "reward_strategy",
        "accrual_strategy",
        "accrual_strategy_snapshot",
        "level",
        "origin_referral_id",
        "source_transaction_id",
    ):
        op.drop_column("referral_rewards", column)
    postgresql.ENUM(name="referral_reward_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="referral_reward_strategy").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="referral_accrual_strategy").drop(op.get_bind(), checkfirst=True)
