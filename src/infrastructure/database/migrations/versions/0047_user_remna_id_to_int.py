from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Panel 3.2.x users are identified by a numeric id. Rows created against
    # the 2.x API hold a UUID here and cannot be converted; they become the
    # REMNA_ID_UNLINKED sentinel (-1) and are re-linked to the numeric id at
    # application startup (SubscriptionRelinker).
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        existing_type=postgresql.UUID(),
        type_=sa.Integer(),
        postgresql_using=(
            "CASE WHEN user_remna_id::text ~ '^[0-9]+$' "
            "THEN user_remna_id::text::integer ELSE -1 END"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        existing_type=sa.Integer(),
        type_=postgresql.UUID(),
        postgresql_using="user_remna_id::text::uuid",
    )
