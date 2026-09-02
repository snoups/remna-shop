from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires a unique target for the deferred owner-preserving FK below.
    op.create_unique_constraint(
        "uq_transactions_id_user_id",
        "transactions",
        ["id", "user_id"],
    )
    op.add_column(
        "transactions",
        sa.Column("cancellation_reason", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE transactions
           SET cancellation_reason = 'LEGACY_UNKNOWN'
         WHERE status = 'CANCELED'
        """
    )
    op.create_check_constraint(
        "ck_transactions_cancellation_reason",
        "transactions",
        "(status = 'CANCELED' AND cancellation_reason IN "
        "('PROVIDER', 'LOCAL_TIMEOUT', 'LEGACY_UNKNOWN')) OR "
        "(status <> 'CANCELED' AND cancellation_reason IS NULL)",
    )
    fulfillment_status_enum = postgresql.ENUM(
        "NOT_STARTED",
        "PROCESSING",
        "SUCCEEDED",
        "MANUAL_REQUIRED",
        name="transaction_fulfillment_status",
    )
    fulfillment_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "transactions",
        sa.Column(
            "fulfillment_status",
            postgresql.ENUM(name="transaction_fulfillment_status", create_type=False),
            server_default="NOT_STARTED",
            nullable=False,
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_last_error", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("fulfillment_alert_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "fulfillment_alert_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "fulfillment_alert_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "fulfillment_alert_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Never infer fulfillment for legacy COMPLETED rows: the old flow committed that
    # status before the external subscription side effect. They require operator review.
    op.execute(
        """
        UPDATE transactions
           SET fulfillment_status = 'MANUAL_REQUIRED',
               fulfillment_started_at = updated_at,
               fulfillment_last_error = 'LEGACY_COMPLETED_WITHOUT_PROOF',
               fulfillment_alerted_at = updated_at
         WHERE status IN ('COMPLETED', 'FAILED')
        """
    )
    op.create_check_constraint(
        "ck_transactions_fulfillment_state",
        "transactions",
        "(fulfillment_status = 'NOT_STARTED' "
        "AND fulfillment_token_hash IS NULL "
        "AND fulfillment_lease_expires_at IS NULL "
        "AND fulfillment_started_at IS NULL "
        "AND fulfillment_completed_at IS NULL "
        "AND status IN ('PENDING', 'CANCELED', 'REFUNDED')) OR "
        "(fulfillment_status = 'PROCESSING' "
        "AND fulfillment_token_hash IS NOT NULL "
        "AND fulfillment_lease_expires_at IS NOT NULL "
        "AND fulfillment_started_at IS NOT NULL "
        "AND fulfillment_completed_at IS NULL "
        "AND status IN ('COMPLETED', 'REFUNDED')) OR "
        "(fulfillment_status = 'SUCCEEDED' "
        "AND fulfillment_token_hash IS NULL "
        "AND fulfillment_lease_expires_at IS NULL "
        "AND fulfillment_started_at IS NOT NULL "
        "AND fulfillment_completed_at IS NOT NULL "
        "AND status IN ('COMPLETED', 'REFUNDED')) OR "
        "(fulfillment_status = 'MANUAL_REQUIRED' "
        "AND fulfillment_lease_expires_at IS NULL "
        "AND fulfillment_started_at IS NOT NULL "
        "AND fulfillment_completed_at IS NULL "
        "AND status IN ('COMPLETED', 'FAILED', 'REFUNDED'))",
    )
    op.create_index(
        "ix_transactions_fulfillment_queue",
        "transactions",
        [
            "fulfillment_status",
            "fulfillment_lease_expires_at",
            "fulfillment_alert_next_attempt_at",
        ],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION guard_transaction_owner_move_during_fulfillment()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
               AND (OLD.fulfillment_status = 'PROCESSING'
                    OR OLD.fulfillment_token_hash IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot move transaction owner during payment fulfillment';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transactions_owner_fulfillment_guard
        BEFORE UPDATE OF user_id ON transactions
        FOR EACH ROW
        EXECUTE FUNCTION guard_transaction_owner_move_during_fulfillment()
        """
    )
    # During a rolling deploy, pre-reconciliation workers still write only the legacy
    # status columns.
    # Normalize those writes into an explicit ambiguous state instead of rejecting the
    # transaction after the old worker may already have acknowledged the webhook.
    op.execute(
        """
        CREATE FUNCTION normalize_legacy_transaction_status_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status = 'COMPLETED'
               AND (
                    NEW.fulfillment_status = 'NOT_STARTED'
                    OR (
                        TG_OP = 'UPDATE'
                        AND OLD.status IN ('PENDING', 'FAILED')
                        AND NEW.fulfillment_status IS NOT DISTINCT FROM OLD.fulfillment_status
                        AND NEW.fulfillment_token_hash
                            IS NOT DISTINCT FROM OLD.fulfillment_token_hash
                        AND NEW.fulfillment_started_at
                            IS NOT DISTINCT FROM OLD.fulfillment_started_at
                        AND NEW.fulfillment_lease_expires_at
                            IS NOT DISTINCT FROM OLD.fulfillment_lease_expires_at
                        AND NEW.fulfillment_completed_at
                            IS NOT DISTINCT FROM OLD.fulfillment_completed_at
                    )
               ) THEN
                NEW.fulfillment_status := 'PROCESSING';
                NEW.fulfillment_token_hash :=
                    '5c0d46b7897c7ecb3e5885d567a8eac2f181cad4f08442072162f75368f95890';
                NEW.fulfillment_started_at := COALESCE(
                    NEW.fulfillment_started_at,
                    clock_timestamp()
                );
                NEW.fulfillment_lease_expires_at := clock_timestamp() + interval '30 minutes';
                NEW.fulfillment_completed_at := NULL;
                NEW.fulfillment_last_error := 'LEGACY_WORKER_UNFENCED_ACTIVE';
                NEW.fulfillment_alerted_at := NULL;
            ELSIF NEW.status = 'FAILED'
                  AND NEW.fulfillment_status = 'NOT_STARTED' THEN
                NEW.fulfillment_status := 'MANUAL_REQUIRED';
                NEW.fulfillment_token_hash := NULL;
                NEW.fulfillment_started_at := COALESCE(
                    NEW.fulfillment_started_at,
                    clock_timestamp()
                );
                NEW.fulfillment_lease_expires_at := NULL;
                NEW.fulfillment_completed_at := NULL;
                NEW.fulfillment_last_error := 'LEGACY_WORKER_UNFENCED_FAILED';
                NEW.fulfillment_alerted_at := NULL;
            ELSIF TG_OP = 'UPDATE'
                  AND OLD.fulfillment_status = 'PROCESSING'
                  AND OLD.fulfillment_token_hash =
                      '5c0d46b7897c7ecb3e5885d567a8eac2f181cad4f08442072162f75368f95890'
                  AND NEW.status = 'FAILED' THEN
                NEW.fulfillment_status := 'MANUAL_REQUIRED';
                NEW.fulfillment_token_hash := NULL;
                NEW.fulfillment_lease_expires_at := NULL;
                NEW.fulfillment_completed_at := NULL;
                NEW.fulfillment_last_error := 'LEGACY_WORKER_FULFILLMENT_FAILED';
                NEW.fulfillment_alerted_at := NULL;
            ELSIF TG_OP = 'UPDATE'
                  AND OLD.fulfillment_status = 'PROCESSING'
                  AND OLD.fulfillment_token_hash =
                      '5c0d46b7897c7ecb3e5885d567a8eac2f181cad4f08442072162f75368f95890'
                  AND NEW.status = 'REFUNDED' THEN
                NEW.fulfillment_last_error := 'LEGACY_WORKER_REFUND_DURING_FULFILLMENT';
            END IF;

            IF NEW.status = 'CANCELED' AND NEW.cancellation_reason IS NULL THEN
                NEW.cancellation_reason := 'LEGACY_UNKNOWN';
            ELSIF NEW.status <> 'CANCELED' THEN
                NEW.cancellation_reason := NULL;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transactions_legacy_status_compatibility
        BEFORE INSERT OR UPDATE OF status ON transactions
        FOR EACH ROW
        EXECUTE FUNCTION normalize_legacy_transaction_status_write()
        """
    )
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column(
            "gateway_type",
            postgresql.ENUM(name="payment_gateway_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="transaction_status", create_type=False),
            nullable=False,
        ),
        sa.Column("selected_payment_method", sa.String(length=64), nullable=True),
        sa.Column("processing_token_hash", sa.String(length=64), nullable=True),
        sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processing_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("processing_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_last_error", sa.String(length=64), nullable=True),
        sa.Column("manual_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'CANCELED', 'REFUNDED')",
            name="ck_payment_webhook_events_status",
        ),
        sa.CheckConstraint(
            "selected_payment_method IS NULL OR gateway_type = 'PLATEGA'",
            name="ck_payment_webhook_events_selected_method",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payment_id",
            "gateway_type",
            "status",
            name="uq_payment_webhook_events_identity",
        ),
    )
    op.create_index(
        "ix_payment_webhook_events_pending",
        "payment_webhook_events",
        [
            "manual_required_at",
            "processing_next_attempt_at",
            "processing_lease_expires_at",
            "created_at",
            "id",
        ],
        unique=False,
    )

    op.add_column("payment_operations", sa.Column("transaction_id", sa.Integer(), nullable=True))
    op.add_column(
        "payment_operations",
        sa.Column("gateway_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "resolved_payment_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "provider_request_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column("provider_owner_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "provider_result_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "recovery_mode",
            sa.String(length=32),
            server_default="MANUAL_REQUIRED",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column("provider_replay_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "reconcile_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_last_error", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column("reconcile_alert_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "reconcile_alert_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "reconcile_alert_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "reconcile_alert_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.drop_constraint(
        "ck_payment_operations_status",
        "payment_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payment_operations_status",
        "payment_operations",
        "status IN ('CLAIMED', 'PROCESSING', 'SUCCEEDED', 'UNKNOWN', 'MANUAL_REQUIRED')",
    )
    op.drop_constraint(
        "ck_payment_operations_lease",
        "payment_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payment_operations_lease",
        "payment_operations",
        "((status IN ('CLAIMED', 'PROCESSING') AND lease_expires_at IS NOT NULL) "
        "OR (status IN ('SUCCEEDED', 'UNKNOWN', 'MANUAL_REQUIRED') "
        "AND lease_expires_at IS NULL))",
    )

    # Perform the legacy link backfill before installing the deferred owner FK.
    # Updating payment_operations after that FK exists queues deferred trigger events;
    # PostgreSQL then rejects subsequent ALTER TABLE statements in this migration.
    # Only an exact, owner-matching payment id saved in the stable public response is
    # proof that an old successful operation belongs to a transaction. Never infer by
    # amount, time, plan, or adjacency.
    op.execute(
        """
        WITH exact_candidates AS (
            SELECT po.id AS operation_id,
                   t.id AS transaction_id,
                   count(*) OVER (PARTITION BY t.id) AS transaction_match_count
              FROM payment_operations AS po
              JOIN transactions AS t
                ON t.user_id = po.user_id
               AND t.payment_id::text = po.response ->> 'payment_id'
             WHERE po.transaction_id IS NULL
               AND po.response IS NOT NULL
               AND jsonb_typeof(po.response) = 'object'
               AND po.response ? 'payment_id'
        )
        UPDATE payment_operations AS po
           SET transaction_id = candidate.transaction_id
          FROM exact_candidates AS candidate
         WHERE po.id = candidate.operation_id
           AND candidate.transaction_match_count = 1
        """
    )

    # A public SUCCEEDED response must include the exact owner-linked transaction.
    # Rows that cannot be proven by payment id remain available for manual review.
    op.execute(
        """
        UPDATE payment_operations
           SET status = 'MANUAL_REQUIRED'
         WHERE status = 'SUCCEEDED'
           AND transaction_id IS NULL
        """
    )

    op.create_check_constraint(
        "ck_payment_operations_succeeded_transaction",
        "payment_operations",
        "status <> 'SUCCEEDED' OR (transaction_id IS NOT NULL AND response IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_payment_operations_recovery_mode",
        "payment_operations",
        "recovery_mode IN ('MANUAL_REQUIRED', 'LOCAL', 'YOOKASSA_REPLAY')",
    )
    op.create_check_constraint(
        "ck_payment_operations_gateway_type",
        "payment_operations",
        "gateway_type IS NULL OR gateway_type IN ("
        "'TELEGRAM_STARS', 'YOOKASSA', 'YOOMONEY', 'VALUTIX', 'CRYPTOMUS', "
        "'HELEKET', 'CRYPTOPAY', 'FREEKASSA', 'MULENPAY', 'PAYMASTER', "
        "'PLATEGA', 'ROBOKASSA', 'ROLLYPAY', 'URLPAY', 'WATA')",
    )
    op.create_check_constraint(
        "ck_payment_operations_reconcile_lease",
        "payment_operations",
        "((reconcile_token_hash IS NULL AND reconcile_lease_expires_at IS NULL) "
        "OR (reconcile_token_hash IS NOT NULL AND reconcile_lease_expires_at IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_payment_operations_reconcile_attempt_count",
        "payment_operations",
        "reconcile_attempt_count >= 0",
    )
    op.create_unique_constraint(
        "uq_payment_operations_transaction_id",
        "payment_operations",
        ["transaction_id"],
    )
    op.create_foreign_key(
        "fk_payment_operations_transaction_owner",
        "payment_operations",
        "transactions",
        ["transaction_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_payment_operations_reconcile_queue",
        "payment_operations",
        ["status", "reconcile_next_attempt_at", "reconcile_lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_operations_manual_alerts",
        "payment_operations",
        [
            "status",
            "reconcile_alerted_at",
            "reconcile_alert_next_attempt_at",
            "reconcile_alert_lease_expires_at",
            "id",
        ],
        unique=False,
    )
    op.create_table(
        "payment_runtime_control",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "legacy_rollout_gate_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_payment_runtime_control_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO payment_runtime_control (id, legacy_rollout_gate_active) VALUES (1, true)"
    )
    op.create_index(
        "ix_transactions_user_created_id",
        "transactions",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION guard_payment_operation_owner_move_during_execution()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
               AND (OLD.status IN ('CLAIMED', 'PROCESSING')
                    OR OLD.reconcile_token_hash IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot move payment operation owner during execution';
            END IF;
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
               AND NEW.resolved_payment_snapshot IS NOT NULL THEN
                IF jsonb_typeof(NEW.resolved_payment_snapshot) <> 'object' THEN
                    RAISE EXCEPTION 'cannot move malformed payment recovery snapshot';
                END IF;
                NEW.resolved_payment_snapshot := jsonb_set(
                    NEW.resolved_payment_snapshot,
                    ARRAY['user_id']::text[],
                    to_jsonb(NEW.user_id),
                    true
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_operations_owner_execution_guard
        BEFORE UPDATE OF user_id ON payment_operations
        FOR EACH ROW
        EXECUTE FUNCTION guard_payment_operation_owner_move_during_execution()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_user_merge_during_payment_work()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.merged_into_user_id IS DISTINCT FROM OLD.merged_into_user_id
               AND EXISTS (
                    SELECT 1
                      FROM payment_runtime_control
                     WHERE id = 1 AND legacy_rollout_gate_active
               ) THEN
                RAISE EXCEPTION 'user merge disabled during payment rollout gate';
            END IF;
            IF NEW.merged_into_user_id IS DISTINCT FROM OLD.merged_into_user_id
               AND NEW.merged_into_user_id IS NOT NULL
               AND (
                    EXISTS (
                        SELECT 1
                          FROM payment_operations po
                         WHERE po.user_id IN (OLD.id, NEW.merged_into_user_id)
                           AND (po.status IN ('CLAIMED', 'PROCESSING')
                                OR po.reconcile_token_hash IS NOT NULL)
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM transactions t
                         WHERE t.user_id IN (OLD.id, NEW.merged_into_user_id)
                           AND (t.fulfillment_status = 'PROCESSING'
                                OR t.fulfillment_token_hash IS NOT NULL)
                    )
               ) THEN
                RAISE EXCEPTION 'cannot merge user during active payment work';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_users_payment_work_merge_guard
        BEFORE UPDATE OF merged_into_user_id ON users
        FOR EACH ROW
        EXECUTE FUNCTION guard_user_merge_during_payment_work()
        """
    )

    # Pre-reconciliation workers do not know transaction_id. Preserve rolling
    # compatibility by
    # deriving it only from the exact stable response payment id and owner. An
    # unprovable or duplicate link fails the old status update instead of publishing
    # a success that the new API cannot safely replay.
    op.execute(
        """
        CREATE FUNCTION link_legacy_succeeded_payment_operation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            matched_transaction_id integer;
            matched_count integer;
            matched_is_free boolean;
            matched_fulfillment_proven boolean;
        BEGIN
            IF NEW.status = 'SUCCEEDED' THEN
                IF NEW.response IS NULL
                   OR jsonb_typeof(NEW.response) <> 'object'
                   OR jsonb_typeof(NEW.response -> 'payment_id') <> 'string' THEN
                    RAISE EXCEPTION 'successful payment operation lacks exact payment id';
                END IF;

                SELECT min(t.id), count(*)
                  INTO matched_transaction_id, matched_count
                  FROM transactions t
                 WHERE t.user_id = NEW.user_id
                   AND t.payment_id::text = NEW.response ->> 'payment_id';

                IF matched_count <> 1 THEN
                    RAISE EXCEPTION 'successful payment operation has no unique owner match';
                END IF;
                IF NEW.transaction_id IS NULL THEN
                    NEW.transaction_id := matched_transaction_id;
                ELSIF NEW.transaction_id <> matched_transaction_id THEN
                    RAISE EXCEPTION 'successful payment operation transaction mismatch';
                END IF;

                SELECT ((t.pricing ->> 'final_amount')::numeric = 0),
                       (t.fulfillment_status = 'SUCCEEDED'
                        AND t.fulfillment_completed_at IS NOT NULL)
                  INTO matched_is_free, matched_fulfillment_proven
                  FROM transactions t
                 WHERE t.id = matched_transaction_id;

                IF (NEW.recovery_mode = 'LOCAL' OR matched_is_free)
                   AND NOT matched_fulfillment_proven THEN
                    UPDATE transactions t
                       SET fulfillment_status = 'SUCCEEDED',
                           fulfillment_token_hash = NULL,
                           fulfillment_lease_expires_at = NULL,
                           fulfillment_completed_at = clock_timestamp(),
                           fulfillment_last_error = NULL
                     WHERE t.id = matched_transaction_id
                       AND t.fulfillment_status = 'PROCESSING'
                       AND t.fulfillment_token_hash =
                           '5c0d46b7897c7ecb3e5885d567a8eac2f181cad4f08442072162f75368f95890';
                    GET DIAGNOSTICS matched_count = ROW_COUNT;
                    IF matched_count <> 1 THEN
                        RAISE EXCEPTION 'free payment operation lacks fulfillment proof';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_operations_legacy_success_compatibility
        BEFORE INSERT OR UPDATE OF status, response, transaction_id
        ON payment_operations
        FOR EACH ROW
        EXECUTE FUNCTION link_legacy_succeeded_payment_operation()
        """
    )

    # Existing ambiguous operations lack a persisted exact provider request and therefore
    # must remain manual. Existing successful rows stay replayable through their response.
    op.execute(
        """
        UPDATE payment_operations
           SET status = 'MANUAL_REQUIRED'
         WHERE status = 'UNKNOWN'
           AND resolved_payment_snapshot IS NULL
           AND provider_result_snapshot IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_operations_legacy_success_compatibility "
        "ON payment_operations"
    )
    op.execute("DROP FUNCTION IF EXISTS link_legacy_succeeded_payment_operation()")
    op.execute("DROP TRIGGER IF EXISTS trg_users_payment_work_merge_guard ON users")
    op.execute("DROP FUNCTION IF EXISTS guard_user_merge_during_payment_work()")
    op.drop_table("payment_runtime_control")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_operations_owner_execution_guard "
        "ON payment_operations"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS guard_payment_operation_owner_move_during_execution()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_transactions_owner_fulfillment_guard ON transactions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_transaction_owner_move_during_fulfillment()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_transactions_legacy_status_compatibility ON transactions"
    )
    op.execute("DROP FUNCTION IF EXISTS normalize_legacy_transaction_status_write()")
    op.drop_index(
        "ix_payment_webhook_events_pending",
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")
    op.drop_index("ix_transactions_fulfillment_queue", table_name="transactions")
    op.drop_index("ix_transactions_user_created_id", table_name="transactions")
    op.drop_index(
        "ix_payment_operations_manual_alerts",
        table_name="payment_operations",
    )
    op.drop_index(
        "ix_payment_operations_reconcile_queue",
        table_name="payment_operations",
    )
    op.drop_constraint(
        "fk_payment_operations_transaction_owner",
        "payment_operations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_payment_operations_transaction_id",
        "payment_operations",
        type_="unique",
    )
    op.drop_constraint(
        "ck_payment_operations_succeeded_transaction",
        "payment_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_operations_reconcile_attempt_count",
        "payment_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_operations_reconcile_lease",
        "payment_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_operations_gateway_type",
        "payment_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_operations_recovery_mode",
        "payment_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_operations_lease",
        "payment_operations",
        type_="check",
    )
    # MANUAL_REQUIRED cannot be represented before this migration. Conservatively retain
    # its ambiguity.
    op.execute("UPDATE payment_operations SET status = 'UNKNOWN' WHERE status = 'MANUAL_REQUIRED'")
    op.create_check_constraint(
        "ck_payment_operations_lease",
        "payment_operations",
        "((status IN ('CLAIMED', 'PROCESSING') AND lease_expires_at IS NOT NULL) "
        "OR (status IN ('SUCCEEDED', 'UNKNOWN') AND lease_expires_at IS NULL))",
    )
    op.drop_constraint(
        "ck_payment_operations_status",
        "payment_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payment_operations_status",
        "payment_operations",
        "status IN ('CLAIMED', 'PROCESSING', 'SUCCEEDED', 'UNKNOWN')",
    )

    for column in (
        "reconcile_last_error",
        "reconcile_alerted_at",
        "reconcile_alert_token_hash",
        "reconcile_alert_lease_expires_at",
        "reconcile_alert_attempt_count",
        "reconcile_alert_next_attempt_at",
        "reconcile_last_attempt_at",
        "reconcile_next_attempt_at",
        "reconcile_attempt_count",
        "reconcile_lease_expires_at",
        "reconcile_token_hash",
        "provider_replay_expires_at",
        "recovery_mode",
        "provider_result_snapshot",
        "provider_owner_hash",
        "provider_request_snapshot",
        "resolved_payment_snapshot",
        "gateway_type",
        "transaction_id",
    ):
        op.drop_column("payment_operations", column)

    op.drop_constraint(
        "ck_transactions_fulfillment_state",
        "transactions",
        type_="check",
    )
    for column in (
        "fulfillment_alert_next_attempt_at",
        "fulfillment_alert_attempt_count",
        "fulfillment_alert_lease_expires_at",
        "fulfillment_alert_token_hash",
        "fulfillment_alerted_at",
        "fulfillment_last_error",
        "fulfillment_completed_at",
        "fulfillment_lease_expires_at",
        "fulfillment_started_at",
        "fulfillment_token_hash",
        "fulfillment_status",
    ):
        op.drop_column("transactions", column)
    postgresql.ENUM(name="transaction_fulfillment_status").drop(
        op.get_bind(),
        checkfirst=True,
    )
    op.drop_constraint(
        "ck_transactions_cancellation_reason",
        "transactions",
        type_="check",
    )
    op.drop_column("transactions", "cancellation_reason")
    op.drop_constraint("uq_transactions_id_user_id", "transactions", type_="unique")
