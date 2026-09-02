from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: Union[str, None] = "0046_user_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "operation IN ('PURCHASE', 'EXTEND')",
            name="ck_payment_operations_operation",
        ),
        sa.CheckConstraint(
            "status IN ('CLAIMED', 'PROCESSING', 'SUCCEEDED', 'UNKNOWN')",
            name="ck_payment_operations_status",
        ),
        sa.CheckConstraint(
            "((status IN ('CLAIMED', 'PROCESSING') AND lease_expires_at IS NOT NULL) "
            "OR (status IN ('SUCCEEDED', 'UNKNOWN') AND lease_expires_at IS NULL))",
            name="ck_payment_operations_lease",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_key"),
        sa.UniqueConstraint(
            "user_id",
            "operation",
            "idempotency_key",
            name="uq_payment_operations_identity",
        ),
    )
    op.create_index(
        "ix_payment_operations_status_updated_at",
        "payment_operations",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_operations_user_id",
        "payment_operations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payment_operations_user_id", table_name="payment_operations")
    op.drop_index(
        "ix_payment_operations_status_updated_at",
        table_name="payment_operations",
    )
    op.drop_table("payment_operations")
