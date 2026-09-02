from typing import Sequence, Union

from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRIGGER_FUNCTION = "enforce_payment_operation_active_user"
_TRIGGER = "trg_payment_operations_active_user"
_USER_MERGE_TRIGGER_FUNCTION = "enforce_user_merge_without_payment_operations"
_USER_MERGE_TRIGGER = "trg_users_merge_without_payment_operations"


def upgrade() -> None:
    op.drop_constraint(
        "payment_operations_user_id_fkey",
        "payment_operations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_payment_operations_user_id_users",
        "payment_operations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        f"""
        CREATE FUNCTION {_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            owner_merged_into_user_id users.merged_into_user_id%TYPE;
        BEGIN
            SELECT merged_into_user_id
              INTO owner_merged_into_user_id
              FROM users
             WHERE id = NEW.user_id
               FOR KEY SHARE;

            IF owner_merged_into_user_id IS NOT NULL THEN
                RAISE EXCEPTION 'payment operations cannot belong to merged users'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_payment_operations_active_user';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE INSERT OR UPDATE OF user_id ON payment_operations
        FOR EACH ROW
        EXECUTE FUNCTION {_TRIGGER_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_USER_MERGE_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.merged_into_user_id IS NOT NULL
               AND OLD.merged_into_user_id IS DISTINCT FROM NEW.merged_into_user_id
               AND EXISTS (
                   SELECT 1
                     FROM payment_operations
                    WHERE user_id = NEW.id
               )
            THEN
                RAISE EXCEPTION
                    'cannot merge user while payment operations still reference the source'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_merged_users_have_no_payment_operations';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    # CREATE TRIGGER takes a table lock on users. Once acquired, the validation
    # below cannot race an old application instance completing a legacy merge;
    # after commit, every such merge is protected by the trigger.
    op.execute(
        f"""
        CREATE TRIGGER {_USER_MERGE_TRIGGER}
        BEFORE UPDATE OF merged_into_user_id ON users
        FOR EACH ROW
        EXECUTE FUNCTION {_USER_MERGE_TRIGGER_FUNCTION}()
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            stranded_count bigint;
        BEGIN
            SELECT count(*)
              INTO stranded_count
              FROM payment_operations po
              JOIN users merged_owner ON merged_owner.id = po.user_id
             WHERE merged_owner.merged_into_user_id IS NOT NULL;

            IF stranded_count > 0 THEN
                RAISE EXCEPTION
                    'migration 0048 blocked: % payment operations belong to merged users',
                    stranded_count
                    USING ERRCODE = '23514',
                          HINT = 'Move payment_operations to active targets, then retry',
                          CONSTRAINT = 'ck_merged_users_have_no_payment_operations';
            END IF;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_USER_MERGE_TRIGGER} ON users")
    op.execute(f"DROP FUNCTION IF EXISTS {_USER_MERGE_TRIGGER_FUNCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON payment_operations")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}()")
    op.drop_constraint(
        "fk_payment_operations_user_id_users",
        "payment_operations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "payment_operations_user_id_fkey",
        "payment_operations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
