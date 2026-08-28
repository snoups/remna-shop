from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        existing_type=postgresql.UUID(),
        type_=sa.Integer(),
        postgresql_using="user_remna_id::text::integer",
    )


def downgrade() -> None:
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        existing_type=sa.Integer(),
        type_=postgresql.UUID(),
        postgresql_using="user_remna_id::text::uuid",
    )
