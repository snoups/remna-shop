from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # env.py enables transaction_per_migration. Consequently, the ACCESS
    # EXCLUSIVE lock used to add these NOT VALID constraints in 0057 has been
    # released before either table scan begins. VALIDATE CONSTRAINT uses SHARE
    # UPDATE EXCLUSIVE and permits ordinary SELECT/INSERT/UPDATE/DELETE traffic.
    # Bounds are deliberately generous for the small users table but keep a
    # conflicting maintenance operation or anomalous scan from hanging rollout.
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("SET LOCAL statement_timeout = '5min'"))
    op.execute(
        sa.text(
            """
            ALTER TABLE public.users
            VALIDATE CONSTRAINT ck_users_subscription_email_consent_eligible
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE public.users
            VALIDATE CONSTRAINT ck_users_subscription_email_consent_timestamp
            """
        )
    )


def downgrade() -> None:
    # PostgreSQL has no ALTER CONSTRAINT ... NOT VALID operation. Keeping an
    # already validated CHECK constraint is backward-compatible with 0057 and
    # avoids a disruptive drop/recreate cycle. A subsequent downgrade of 0057
    # removes both constraints before dropping their columns.
    pass
