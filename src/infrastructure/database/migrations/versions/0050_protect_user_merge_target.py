from typing import Sequence, Union

from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRIGGER_FUNCTION = "enforce_user_merge_target_immutable"
_TRIGGER = "trg_users_merged_target_immutable"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.merged_into_user_id IS NOT NULL
               AND NEW.merged_into_user_id IS DISTINCT FROM OLD.merged_into_user_id
            THEN
                RAISE EXCEPTION
                    'an existing user merge target cannot be changed'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_users_merged_target_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OF merged_into_user_id ON users
        FOR EACH ROW
        EXECUTE FUNCTION {_TRIGGER_FUNCTION}()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON users")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}()")
