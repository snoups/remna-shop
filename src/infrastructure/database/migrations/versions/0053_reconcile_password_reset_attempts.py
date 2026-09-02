from typing import Sequence, Union

from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The integration branch used revision 0046 for the user-merge schema before
    # upstream assigned 0046 to password_reset_attempts. Install the upstream
    # column for databases that already advanced past that collision (notably
    # old integration revision 0050). Keep a database default only to support
    # short emergency app-only containment while ingress remains disabled.
    # Mixed-version payment/referral traffic is not safe and remains forbidden.
    op.execute(
        """
        DO $password_reset_attempts_type_guard$
        DECLARE
            existing_data_type text;
        BEGIN
            SELECT data_type
            INTO existing_data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'users'
              AND column_name = 'password_reset_attempts';

            IF existing_data_type IS NOT NULL AND existing_data_type <> 'integer' THEN
                RAISE EXCEPTION
                    'Migration 0053 blocked: users.password_reset_attempts has type %',
                    existing_data_type
                    USING ERRCODE = '42804',
                          HINT = 'Convert password_reset_attempts to integer before retrying';
            END IF;
        END;
        $password_reset_attempts_type_guard$
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS password_reset_attempts INTEGER DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN password_reset_attempts SET DEFAULT 0
        """
    )
    op.execute(
        """
        UPDATE users
        SET password_reset_attempts = 0
        WHERE password_reset_attempts IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN password_reset_attempts SET NOT NULL
        """
    )


def downgrade() -> None:
    # This revision may have created the column for an old integration database,
    # or merely verified a column owned by upstream 0046. Keeping the additive
    # column is safe for old code and avoids destructive ownership guessing.
    pass
