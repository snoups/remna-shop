from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bound every DDL lock acquisition, including locks on the existing tables
    # referenced by the new foreign keys. A queued strong lock can form a lock
    # convoy and stall otherwise compatible traffic. Failing this additive
    # revision is safe: its transaction rolls back, 0057 is not stamped, and
    # the old runtime remains compatible so deployment can retry.
    op.execute(sa.text("SET LOCAL lock_timeout = '2s'"))

    op.create_table(
        "subscription_email_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("expire_at_snapshot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_token_hash", sa.String(length=64), nullable=True),
        sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('UTC', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('UTC', now())"),
        ),
        sa.CheckConstraint(
            "days_before IN (1, 3, 7)",
            name="ck_subscription_email_reminder_days_before",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'RETRY_WAITING', "
            "'SENT', 'CANCELED', 'FAILED')",
            name="ck_subscription_email_reminder_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_subscription_email_reminder_attempt_count",
        ),
        sa.CheckConstraint(
            "((state = 'PROCESSING' AND processing_token_hash IS NOT NULL "
            "AND processing_lease_expires_at IS NOT NULL) OR "
            "(state <> 'PROCESSING' AND processing_token_hash IS NULL "
            "AND processing_lease_expires_at IS NULL))",
            name="ck_subscription_email_reminder_processing_fence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "subscription_id",
            "expire_at_snapshot",
            "days_before",
            name="uq_subscription_email_reminder_identity",
        ),
    )
    op.create_index(
        "ix_subscription_email_reminders_user_id",
        "subscription_email_reminders",
        ["user_id"],
    )
    op.create_index(
        "ix_subscription_email_reminders_subscription_id",
        "subscription_email_reminders",
        ["subscription_id"],
    )
    op.create_index(
        "ix_subscription_email_reminders_due",
        "subscription_email_reminders",
        ["state", "next_attempt_at", "due_at"],
        postgresql_where=sa.text(
            "state IN ('PENDING', 'RETRY_WAITING', 'PROCESSING')"
        ),
    )
    op.create_index(
        "ix_subscription_email_reminders_terminal_retention",
        "subscription_email_reminders",
        ["updated_at", "id"],
        postgresql_where=sa.text(
            "state IN ('SENT', 'CANCELED', 'FAILED')"
        ),
    )

    # This database-owned invariant keeps email changes rollback-compatible
    # with pre-0057 application images. Older code does not know about consent
    # columns; the trigger clears them before the CHECK constraints evaluate.
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.clear_subscription_email_consent_on_identity_change()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog
            AS $function$
            BEGIN
                IF NEW.email IS DISTINCT FROM OLD.email
                   OR NEW.is_email_verified IS NOT TRUE THEN
                    NEW.subscription_expiration_email_enabled := false;
                    NEW.subscription_expiration_email_enabled_at := NULL;
                END IF;
                RETURN NEW;
            END;
            $function$
            """
        )
    )

    # Take the strongest ACCESS EXCLUSIVE lock on users only after all work on
    # the new, empty outbox table has completed. PostgreSQL keeps DDL locks
    # until this migration transaction commits, so placing these fast metadata
    # changes last minimizes that lock window.
    #
    op.add_column(
        "users",
        sa.Column(
            "subscription_expiration_email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="public",
    )
    op.add_column(
        "users",
        sa.Column(
            "subscription_expiration_email_enabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="public",
    )
    # NOT VALID still enforces each constraint for all new writes, but avoids
    # scanning the existing users table while ACCESS EXCLUSIVE is held. The
    # separate 0058 revision validates both constraints in its own transaction
    # under PostgreSQL's weaker SHARE UPDATE EXCLUSIVE lock.
    op.execute(
        sa.text(
            """
            ALTER TABLE public.users
            ADD CONSTRAINT ck_users_subscription_email_consent_eligible
            CHECK (
                NOT subscription_expiration_email_enabled
                OR (email IS NOT NULL AND is_email_verified IS TRUE)
            ) NOT VALID
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE public.users
            ADD CONSTRAINT ck_users_subscription_email_consent_timestamp
            CHECK (
                (subscription_expiration_email_enabled
                 AND subscription_expiration_email_enabled_at IS NOT NULL)
                OR
                (NOT subscription_expiration_email_enabled
                 AND subscription_expiration_email_enabled_at IS NULL)
            ) NOT VALID
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_users_clear_subscription_email_consent
            BEFORE UPDATE OF email, is_email_verified ON public.users
            FOR EACH ROW
            EXECUTE FUNCTION public.clear_subscription_email_consent_on_identity_change()
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_email_reminders_terminal_retention",
        table_name="subscription_email_reminders",
    )
    op.drop_index(
        "ix_subscription_email_reminders_due",
        table_name="subscription_email_reminders",
    )
    op.drop_index(
        "ix_subscription_email_reminders_subscription_id",
        table_name="subscription_email_reminders",
    )
    op.drop_index(
        "ix_subscription_email_reminders_user_id",
        table_name="subscription_email_reminders",
    )
    op.drop_table("subscription_email_reminders")
    op.execute(
        sa.text(
            """
            DROP TRIGGER IF EXISTS trg_users_clear_subscription_email_consent
            ON public.users
            """
        )
    )
    op.execute(
        sa.text(
            """
            DROP FUNCTION IF EXISTS
            public.clear_subscription_email_consent_on_identity_change()
            """
        )
    )
    op.drop_constraint(
        "ck_users_subscription_email_consent_timestamp",
        "users",
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        "ck_users_subscription_email_consent_eligible",
        "users",
        type_="check",
        schema="public",
    )
    op.drop_column(
        "users",
        "subscription_expiration_email_enabled_at",
        schema="public",
    )
    op.drop_column(
        "users",
        "subscription_expiration_email_enabled",
        schema="public",
    )
