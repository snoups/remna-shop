from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.infrastructure.database.constraints import (
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_SQL,
)

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOWNGRADE_RECOVERY_EVIDENCE_GUARD_SQL = """
DO $downgrade_guard$
BEGIN
    LOCK TABLE referral_reward_resolutions IN SHARE MODE;

    IF EXISTS (
        SELECT 1
        FROM referral_reward_resolutions
        WHERE decision IN (
            'RETRY_PROVEN_MISSING',
            'CONFIRM_ADMIN_COMPENSATED',
            'ACK_ADMIN_COMPENSATED_REFUND'
        )
    ) THEN
        RAISE EXCEPTION
            'Migration 0054 downgrade refused: legacy recovery evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$downgrade_guard$;
"""


def upgrade() -> None:
    op.add_column(
        "referral_reward_resolutions",
        sa.Column("selected_provenance", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "referral_reward_resolutions",
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "referral_reward_resolutions",
        sa.Column("selected_source_transaction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "referral_reward_resolutions",
        sa.Column("selected_origin_referral_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "referral_reward_resolutions",
        sa.Column(
            "selected_level",
            postgresql.ENUM(name="referral_level", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "referral_reward_resolutions",
        sa.Column("authorization_manifest_sha256", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_referral_reward_resolutions_selected_source_transaction_id",
        "referral_reward_resolutions",
        "transactions",
        ["selected_source_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_referral_reward_resolutions_selected_origin_referral_id",
        "referral_reward_resolutions",
        "referrals",
        ["selected_origin_referral_id"],
        ["id"],
        ondelete="RESTRICT",
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
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_SQL,
    )


def downgrade() -> None:
    op.execute(DOWNGRADE_RECOVERY_EVIDENCE_GUARD_SQL)
    op.drop_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        type_="check",
    )
    op.create_check_constraint(
        REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
        "referral_reward_resolutions",
        "decision IN ('CONFIRM_ISSUED', 'CANCEL')",
    )
    op.drop_index(
        "uq_referral_reward_resolutions_recovery_source_level",
        table_name="referral_reward_resolutions",
    )
    op.drop_constraint(
        "fk_referral_reward_resolutions_selected_origin_referral_id",
        "referral_reward_resolutions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_referral_reward_resolutions_selected_source_transaction_id",
        "referral_reward_resolutions",
        type_="foreignkey",
    )
    op.drop_column("referral_reward_resolutions", "selected_level")
    op.drop_column("referral_reward_resolutions", "selected_origin_referral_id")
    op.drop_column("referral_reward_resolutions", "selected_source_transaction_id")
    op.drop_column("referral_reward_resolutions", "authorization_manifest_sha256")
    op.drop_column("referral_reward_resolutions", "evidence_sha256")
    op.drop_column("referral_reward_resolutions", "selected_provenance")
