from typing import Sequence, Union

from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FINALIZED_CONSTRAINT = "ck_payment_runtime_control_rollout_finalized"

_ACTIVE_PAYMENT_WORK_GUARD = """
CREATE OR REPLACE FUNCTION guard_user_merge_during_payment_work()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
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
$$
"""

_ROLLOUT_AND_ACTIVE_PAYMENT_WORK_GUARD = """
CREATE OR REPLACE FUNCTION guard_user_merge_during_payment_work()
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
$$
"""


def upgrade() -> None:
    # 0049 deliberately failed closed while legacy and reconciliation-aware workers
    # could overlap. By 0051 every supported worker uses the reconciled payment model,
    # so retain only the per-user active-work fence and permanently retire the global
    # deployment gate. Keep the singleton table for one compatibility release because
    # older deployment tooling still verifies it.
    op.execute(
        "UPDATE payment_runtime_control "
        "SET legacy_rollout_gate_active = false "
        "WHERE id = 1"
    )
    op.alter_column(
        "payment_runtime_control",
        "legacy_rollout_gate_active",
        server_default="false",
    )
    op.create_check_constraint(
        _FINALIZED_CONSTRAINT,
        "payment_runtime_control",
        "legacy_rollout_gate_active = false",
    )
    op.execute(_ACTIVE_PAYMENT_WORK_GUARD)


def downgrade() -> None:
    # Restoring a pre-0051 binary also restores its fail-closed rolling-deploy guard.
    op.drop_constraint(
        _FINALIZED_CONSTRAINT,
        "payment_runtime_control",
        type_="check",
    )
    op.alter_column(
        "payment_runtime_control",
        "legacy_rollout_gate_active",
        server_default="true",
    )
    op.execute(_ROLLOUT_AND_ACTIVE_PAYMENT_WORK_GUARD)
    op.execute(
        "UPDATE payment_runtime_control "
        "SET legacy_rollout_gate_active = true "
        "WHERE id = 1"
    )
