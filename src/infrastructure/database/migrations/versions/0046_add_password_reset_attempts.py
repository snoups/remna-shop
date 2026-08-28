from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("users", "password_reset_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "password_reset_attempts")
