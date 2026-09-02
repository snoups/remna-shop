# Referral reward manual recovery

## Rollout and rollback safety

Deploy migration 0052 without mixed application versions:

1. Drain traffic and stop all old web processes and reward workers; verify none
   remain connected or running.
2. Apply migration 0052.
3. Deploy and start only the new web and worker version.
4. After the new deployment is healthy, set
   `REFERRAL_REWARD_BACKFILL_ENABLED=true` and restart/redeploy only that new
   version before invoking preview or apply.

Do not run old and new Remnashop processes against the migrated database at the
same time. Once durable reward traffic or historical backfill begins, migration
0052 is forward-only. Its downgrade refuses to remove the schema when any
`referral_reward_resolutions` row, any `referral_reward_backfill_audits` row, or
any `referral_rewards.source_transaction_id` value exists. A downgrade is only
permitted before those durable records exist; legacy-only reward rows with a
null `source_transaction_id` do not trip the guard. Never delete provenance or
audit evidence to bypass this protection. Recover forward or restore the entire
database from a consistent pre-0052 backup instead.

Rewards in `MANUAL_REQUIRED` must never be replayed blindly. An `EXTRA_DAYS`
timeout or expired worker lease can mean that Remnawave applied the absolute
target even though Remnashop did not persist completion.

1. List cases with `GET /api/v1/admin/referral-rewards/manual` using the admin
   API key. The worker emits a one-shot critical log for newly visible cases.
2. Match `source_transaction_id`, recipient `user_id`, stored
   `target_subscription_id`, `baseline_expire_at`, and `target_expire_at` to the
   payment record, database state, Remnawave audit, and current panel state.
3. When the effect is proven applied, call
   `POST /api/v1/admin/referral-rewards/{id}/resolve` with
   `{"resolution":"CONFIRM_ISSUED","expected_version":3,`
   `"operator_reference":"alice/TICKET-123",`
   `"reason":"Verified target expiry in Remnawave audit"}`.
4. Use `CANCEL` only after proving the effect was not applied (or after an
   explicit audited rollback):
   `{"resolution":"CANCEL","expected_version":3,`
   `"operator_reference":"alice/TICKET-123",`
   `"reason":"Verified remote baseline after rollback"}`.

If a replacement subscription or later state drift makes those strict checks
inconclusive, an operator may add `"allow_drift":true` only after recording the
external audit evidence in `operator_reference` and `reason`. The decision stores
the observed current subscription id, remote UUID, and expiry as an immutable
evidence snapshot. The default remains fail-closed.

`expected_version` is mandatory and comes from `manual_incident_version` in the
admin listing. Each distinct ambiguity/refund increments this version and has its
own `manual_cause`; the same `(reward_id, incident_version)` decision is
idempotent. A stale version returns a conflict. A later refund after an earlier
ambiguity was confirmed opens a new incident, while a resolved refund incident
does not reopen on every sweep.

The resolver never adds points or days. It records an append-only audited
decision in `referral_reward_resolutions`; an identical request is idempotent,
while conflicting evidence is rejected. For `EXTRA_DAYS`, both confirmation and
cancellation require the current panel expiry to match the relevant durable
target exactly unless an explicit audited drift override is supplied. A later
renewal or promotion is not causal proof that this reward reached Remnawave.

An `ON_FIRST_PAYMENT` row can be confirmed only if it already owns the durable
first-payment claim marker. A marker-less manual row must be canceled/reconciled
at its source and left to normal atomic winner selection; manually claiming the
marker risks a duplicate first-payment grant.

## Proven legacy EXTRA_DAYS recovery

Migration 0054 adds a narrowly scoped recovery path for the exact unresolved
legacy shape created by migration 0052. Take and verify a full database backup,
restore it into a disposable PostgreSQL instance, and rehearse the 0053 → 0054
migration and every approved recovery request before touching production. Do not
invoke the endpoint until the new API and reward worker version is deployed.

Use `POST /api/v1/admin/referral-rewards/{id}/recover-legacy` only after an
independent transaction, attribution, audit-log, account-merge, and current-state
review proves one of these mutually exclusive outcomes:

- `RETRY_PROVEN_MISSING`: the original effect provably did not happen. Supply
  the exact historical source transaction, origin referral, level, accrual
  strategy, reward strategy, and configured value. The existing row becomes a
  durable `PENDING` intent; it is delivered by the normal worker and is not
  applied directly by the endpoint.
- `CONFIRM_ADMIN_COMPENSATED`: an administrator already added enough days to
  cover the reward. Do not supply or invent a policy snapshot. The existing row
  becomes `ISSUED`, retains null source/policy fields so it continues to block
  unsafe historical backfill, and produces no Remnawave side effect.

The endpoint is disabled by default and startup fails closed if it is enabled
without all three exact settings:

- `REFERRAL_REWARD_LEGACY_RECOVERY_ENABLED=true`;
- an absolute `REFERRAL_REWARD_LEGACY_RECOVERY_MANIFEST_PATH` to a reviewed,
  tracked manifest in the deployed image;
- `REFERRAL_REWARD_LEGACY_RECOVERY_MANIFEST_SHA256` equal to the canonical
  manifest digest.

Only payloads listed byte-for-byte semantically in that manifest are authorized.
Disable the gate and recreate the API immediately after the approved rows are
recorded. Both actions require the exact expected reward amount, a lowercase
SHA-256 digest of the immutable evidence bundle, an operator reference, a reason,
the exact incident version, and the proven candidate source/referral/level. The
DAO serializes recovery with historical backfill, locks every participant and
candidate row, rejects merged accounts, source collisions, attribution drift,
and conflicting replays. It stores the normalized candidate in the append-only
resolution even when an admin-compensated reward intentionally retains null
source/policy fields. An identical request is idempotent. Once any legacy
recovery evidence exists, migration 0054 cannot be downgraded; recover forward
or restore the complete pre-0054 backup.

For `RETRY_PROVEN_MISSING`, keep the reward worker stopped while recording the
approved intents. Start it only after verifying the stored provenance and audit
rows. The worker supports safe non-trial `ACTIVE` and `EXPIRED` subscriptions:
it uses `max(previous_expiry, grant_started_at) + reward_days`, verifies the
remote UUID, expiry, and status before writing, and requires an exact active
read-after-write. The panel write is a narrow PATCH containing only UUID, ACTIVE
status, and the absolute expiry target; it never replays a stale full profile.
Any drift enters manual review instead of retrying blindly.

### Operator-directed legacy batch (manifest v2)

`RETRY_OPERATOR_DIRECTED` is the source-audited, policy-neutral path for the
remaining 2026-08-22 cohort. It never fabricates an accrual or reward-policy
snapshot. Each v2 manifest entry instead freezes the legacy reward row
(recipient, referral, amount, creation time and incident version), the matched
payment source/origin/level, the evidence class, and the evidence digest. The DAO
re-locks the complete attribution chain, payment, reward and merge participants,
rejects source/level collisions and row drift, then records the source only in
the append-only resolution. The reward itself remains source/policy-null and is
made `PENDING` with the manifest SHA-256 as a durable operator-authorization
marker. The normal worker accepts such a source-less row only when that marker
matches its exact resolution.

Any consuming legacy recovery resolution freezes that payment source for all
later normal reward creation, not only the recovered level. The frozen manifest
is the complete historically authorized level set; a delayed reconciliation
must not synthesize an additional level from the current referral chain or
policy. Both live assignment and historical backfill share the attribution-user
fence with recovery. A backfill that observes the cross-table fence after its
preview rolls the whole apply transaction back instead of recording a partial or
falsely applied batch.

The two source classes are deliberately narrow:

- `LOCAL_COMPLETED` requires a still-completed, paid, non-test, non-trial source
  with either durable success or the exact migration-0049 legacy fulfillment
  shape. Its entry evidence must equal the top-level frozen audit digest.
- `PROVIDER_SUCCEEDED` is pinned only to reward `65`, source `1761`, YooKassa,
  and the redacted provider artifact digest
  `16c080ccfd92d6adc1e82f56214fd71190aca28077942a625a991a1544ff935e`.
  Its last read-only check was `2026-08-22T08:18:06+00:00`; local and provider
  identifiers matched and the artifact pins the SHA-256 of their canonical
  string form. Recheck the payment immediately before starting the worker; any
  status, paid amount, identifier, or refund drift is a stop condition.

Seventy entries touch a verified user-merge lineage. Their 33 current and
historical aliases were included in the administrator-duration audit, with no
positive event found for the remaining cohort. Each manifest entry pins the
exact sorted real merge-audit IDs touching its locked participants. The DAO
then verifies that exact set and accepts only canonical current inbound targets;
new edges, outbound or merged-onward participants, missing audit/source rows,
marker drift, and damaged source tombstones fail closed. The full transitive
lineage is frozen in the audit artifact with SHA-256
`d79e035d3f47489b664d1a15a4fbc59dbbbd341735c4f0b6ae413680a9536977`.

The tracked v2 artifacts are:

- `legacy_referral_rewards_2026-08-22.v2.audit.json`, canonical SHA-256
  `dfac82651078009491e19be3d01f0af2a7c6e709b82f414a28754951c20b8beb`;
- `legacy_referral_rewards_2026-08-22.v2.provider-rr65.json`, canonical SHA-256
  `16c080ccfd92d6adc1e82f56214fd71190aca28077942a625a991a1544ff935e`;
- `legacy_referral_rewards_2026-08-22.v2.json`, 759 entries / 9408 days,
  canonical SHA-256
  `85bd8c980abc52f6457c015f17ae635f86e3f5c42e8dc1105f6dfc82292fb23c`.

Apply the exact entries through
`POST /api/v1/admin/referral-rewards/recover-legacy-batch` while the recovery
gate points at that absolute v2 path and digest. Rows commit one at a time: a
timeout leaves a safe prefix, and replaying the identical batch is idempotent.
Keep the worker stopped until all resolutions and authorization markers are
verified, then start it. Operator-directed delivery suppresses per-row customer
success/failure notifications; rows without a currently safe paid subscription
remain durable retries. A refund before delivery supersedes the row, while a
refund during/after delivery enters manual review. Manual confirmation re-locks
the source through the matching manifest digest and cannot confirm a refunded
source without the existing audited drift override.

`ON_FIRST_PAYMENT` means the first-ever successfully fulfilled paid non-trial,
non-test transaction. A later refund does not reopen eligibility. Pending rewards
for a refunded source are safely superseded; a refund during processing or after
issuance enters manual review for explicit clawback handling. Exact migration
0049 legacy completed/refunded sources conservatively remain prior-payment
blockers even without modern fulfillment proof. If a normalized
`CONFIRM_ADMIN_COMPENSATED` source is later refunded, resolve its new incident
only with the explicit `ACK_ADMIN_COMPENSATED_REFUND` decision after independent
review; the acknowledgement preserves the issued/admin-compensated history and
does not grant days again. The refund transition preserves the exact immutable
migration-0049 marker, so later `ON_FIRST_PAYMENT` selection cannot forget an
ambiguous earlier paid source. A never-applied later EXTRA_DAYS intent fenced as
`ADMIN_COMPENSATED_EARLIER_PAYMENT` may be closed only with a no-drift `CANCEL`;
that exact cancellation does not probe or mutate Remnawave. Other targetless
EXTRA_DAYS incidents remain fail-closed.

## Historical reward backfill

Historical rewards are recovered through an explicit, audited
**inventory → preview → apply** workflow. Set `BASE_URL` to the Remnashop origin
and send the admin API key in `X-API-Key` for every request.

The flag defaults to false. Inventory remains read-only while disabled, but
preview and apply return `503 Service Unavailable`; never bypass that rollout
gate or enable it while any pre-0052 process is running.

1. Inventory eligible historical source transactions. This step is read-only and
   does not create reward intents:

   ```bash
   curl -sS \
     -H "X-API-Key: $API_KEY" \
     "$BASE_URL/api/v1/admin/referral-rewards/backfill/inventory?limit=100&offset=0"
   ```

2. Select and independently verify the exact `source_transaction_id` values,
   then persist an audited preview with the operator identity, external reference,
   and reason:

   ```bash
   curl -sS -X POST \
     -H "X-API-Key: $API_KEY" \
     -H "Content-Type: application/json" \
     "$BASE_URL/api/v1/admin/referral-rewards/backfill/preview" \
     -d '{
       "source_transaction_ids": [77, 91],
       "operator_identity": "alice",
       "operator_reference": "TICKET-135",
       "reason": "Verified missing durable intents against payment records"
     }'
   ```

   Save the returned `preview_id` and the complete `config_snapshot`. Review every
   transaction, generated intent, and error. Continue only when `can_apply` is
   `true` and the preview exactly matches the approved incident scope.
   `*_REFERRAL_POSTDATES_PAYMENT` means attribution did not exist when payment
   completed. `PARTIAL_EXISTING_INTENTS_MANUAL_REVIEW` means one reward level
   already has a different durable policy snapshot. Both are intentionally
   fail-closed and must not be forced through backfill.

3. Apply the same source IDs and operator evidence, copying the complete config
   object from the preview response into `expected_config_snapshot`:

   ```bash
   curl -sS -X POST \
     -H "X-API-Key: $API_KEY" \
     -H "Content-Type: application/json" \
     "$BASE_URL/api/v1/admin/referral-rewards/backfill/31/apply" \
     -d '{
       "source_transaction_ids": [77, 91],
       "operator_identity": "alice",
       "operator_reference": "TICKET-135",
       "reason": "Verified missing durable intents against payment records",
       "expected_config_snapshot": {
         "enabled": true,
         "max_level": 2,
         "accrual_strategy": "ON_FIRST_PAYMENT",
         "reward_type": "POINTS",
         "reward_strategy": "AMOUNT",
         "reward_config": {"1": 10, "2": 5}
       }
     }'
   ```

Apply locks and recomputes eligibility and attribution, then rejects any drift
from the persisted preview. An identical successfully applied request is an
idempotent audit replay; it does not create the reward intents again. If config,
source IDs, operator evidence, or eligibility changed, create a new preview.

**Never replay a legacy ambiguous reward.** If inventory or preview reports
`LEGACY_AMBIGUOUS_REWARD_REQUIRES_RESOLUTION`, the old process may already have
applied the points or days without recording completion. Do not include that
transaction in an apply request and do not create a reward manually. Reconcile
the external effect and database evidence through the manual-resolution process
above; historical backfill must remain fail-closed for this case.
