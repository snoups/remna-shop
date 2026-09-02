# Clean Pay payment recovery rollout

This runbook applies to the Clean Pay companion migrations and application changes in
Remnashop. The rollout is a measured maintenance operation. It is **not** a
zero-downtime or mixed-version deployment: an old HTTP process or Taskiq worker can
read a transaction before a user merge and finish an unfenced side effect after the
merge. Database triggers limit the damage of legacy writes, but they cannot make that
external side effect race safe.

## Preconditions

- Pin one reviewed Remnashop commit and use the same image for HTTP, Taskiq workers,
  and the scheduler.
- Confirm that the database backup and restore procedure has been tested.
- Schedule a maintenance window and stop new payment ingress before taking the backup.
- Record the current Alembic revision, application image digest, row counts, and table
  sizes for `users`, `transactions`, and `payment_operations`.
- Check available disk space for PostgreSQL WAL and the backup.
- Measure the expected lock window on a production-sized restored copy. The migration
  adds constraints/indexes and updates the existing payment ledger; do not estimate
  this from an empty database.

Useful read-only checks:

```sql
SELECT version_num FROM alembic_version;
SELECT count(*) FROM transactions;
SELECT count(*) FROM payment_operations;
SELECT pg_size_pretty(pg_total_relation_size('transactions'));
SELECT pg_size_pretty(pg_total_relation_size('payment_operations'));
```

## Rollout sequence

1. Put the public payment entrypoints into maintenance mode at the load balancer.
2. Stop **all** old Remnashop HTTP replicas, Taskiq workers, and Taskiq scheduler
   processes. Do not leave a canary or a previous replica running.
3. Drain the broker and verify that no old payment task is executing. Check the
   orchestrator and `pg_stat_activity`; a process is not considered stopped merely
   because it stopped receiving traffic.
4. Take and verify a PostgreSQL backup. Keep the previous image digest and deployment
   configuration available.
5. Apply the Alembic migrations once, from the pinned new image. Keep the maintenance
   window active while the DDL and ledger backfill run.
6. Verify the new schema and the rollout gate:

   ```sql
   SELECT version_num FROM alembic_version;
   SELECT * FROM payment_runtime_control WHERE id = 1;
   SELECT count(*) FROM payment_webhook_events;
   SELECT status, count(*) FROM payment_operations GROUP BY status ORDER BY status;
   SELECT fulfillment_status, count(*)
     FROM transactions
    GROUP BY fulfillment_status
    ORDER BY fulfillment_status;
   ```

   `legacy_rollout_gate_active` must still be `true`. While it is true, user merges
   fail closed.
7. Start the new HTTP replicas, Taskiq workers, and scheduler from the exact same
   image. Do not restore payment ingress yet.
8. Verify application health, broker connectivity, and the public capability endpoint
   `GET /api/v1/public/subscription/capabilities`. Confirm that both the webhook replay
   sweep and the payment-operation alert sweep can run.
9. Exercise one non-billable lookup and a controlled provider test. Verify that the
   transaction history page, exact transaction lookup, public operation lookup, and
   admin reconciliation endpoint return the documented contract.
10. Inspect the manual queues before enabling merges:

    ```sql
    SELECT id, user_id, status, reconcile_last_error,
           reconcile_token_hash IS NOT NULL AS owner_frozen
      FROM payment_operations
     WHERE status = 'MANUAL_REQUIRED'
     ORDER BY id;

    SELECT id, payment_id, status, fulfillment_last_error,
           fulfillment_token_hash IS NOT NULL AS owner_frozen
      FROM transactions
     WHERE fulfillment_status = 'MANUAL_REQUIRED'
     ORDER BY id;

    SELECT id, payment_id, gateway_type, status, processing_last_error,
           manual_required_at, alerted_at
      FROM payment_webhook_events
     WHERE manual_required_at IS NOT NULL
     ORDER BY id;
    ```

11. Only after every running component is confirmed on the new revision, disable the
    rollout gate in a short explicit transaction:

    ```sql
    BEGIN;
    SELECT * FROM payment_runtime_control WHERE id = 1 FOR UPDATE;
    UPDATE payment_runtime_control
       SET legacy_rollout_gate_active = false
     WHERE id = 1 AND legacy_rollout_gate_active = true;
    COMMIT;
    ```

12. Restore payment ingress gradually and monitor provider errors, reconciliation
    retries, webhook inbox age, manual queues, and notification delivery.

## Manual/fenced rows

A non-null `reconcile_token_hash` or `fulfillment_token_hash` on a manual row is an
intentional owner freeze. It means a worker crossed an external side-effect boundary
and exceeded its lease. Automated code must not clear that token or move the owner.
An operator must compare the provider state, local transaction, subscription state,
and audit logs before recording a resolution. Preserve an audit record of the evidence
and SQL used; never bulk-clear these tokens.

Unknown providers and gateways without an exact recovery implementation remain
`MANUAL_REQUIRED`. YooKassa is the only automatic provider replay supported by this
change.

## Rollback

1. Re-enable maintenance mode and set `legacy_rollout_gate_active = true`.
2. Stop and drain every new HTTP, worker, and scheduler process.
3. Capture the current database and manual queues before changing anything.
4. Prefer rolling the application image back while **keeping the additive schema and
   compatibility triggers**. Do not run the Alembic downgrade after new recovery,
   fulfillment, or webhook-inbox data has been created; it would discard evidence and
   fencing state.
5. If the database itself must be restored, restore the verified pre-rollout backup as
   one coordinated operation with the previous application image and broker state.
6. Keep user merges disabled until all components and queues are again consistent.

The legacy compatibility triggers intentionally turn old unfenced terminal writes into
ambiguous/manual states. That is a containment mechanism for emergency rollback, not
authorization to run old and new versions together during normal rollout.
