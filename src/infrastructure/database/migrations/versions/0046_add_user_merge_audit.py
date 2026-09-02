from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046_user_merge"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("merged_into_user_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_users_merged_into_user_id",
        "users",
        ["merged_into_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_users_merged_into_user_id_users",
        "users",
        "users",
        ["merged_into_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "user_merge_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("source_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("moved", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_merge_audit_actor_user_id",
        "user_merge_audit",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_merge_audit_source_user_id",
        "user_merge_audit",
        ["source_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_merge_audit_target_user_id",
        "user_merge_audit",
        ["target_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_merge_audit_target_user_id", table_name="user_merge_audit")
    op.drop_index("ix_user_merge_audit_source_user_id", table_name="user_merge_audit")
    op.drop_index("ix_user_merge_audit_actor_user_id", table_name="user_merge_audit")
    op.drop_table("user_merge_audit")
    op.drop_constraint("fk_users_merged_into_user_id_users", "users", type_="foreignkey")
    op.drop_index("ix_users_merged_into_user_id", table_name="users")
    op.drop_column("users", "merged_at")
    op.drop_column("users", "merged_into_user_id")
