# Legacy referral reward remediation — 2026-08-22

This is the PII-free operator record for the owner-directed remediation of the
remaining legacy `EXTRA_DAYS` rewards. Times are UTC.

## Decision boundary

The retained application logs do not cover the complete period from January to
5 August. Consequently, absence of an administrator event is not forensic proof
that an old side effect never happened. The owner explicitly chose the
customer-favouring business rule: a fully covering `ADMIN`, `DEV`, or `OWNER`
duration grant counts as compensation; otherwise the legacy reward is granted.

This action is recorded as `RETRY_OPERATOR_DIRECTED`, not
`RETRY_PROVEN_MISSING`. It does not invent a historical referral-policy snapshot.

## Administrator-duration audit

Every retained successful duration mutation was matched to every member of the
original 768-row cohort. Positive administrator grants are allocated FIFO to
already-earned rewards, each day is consumed at most once, a reward is covered
only in full, and surplus is not carried to a future reward. Later subtractions
reduce the most recent administrator tranches first.

- Six `OWNER` grants totaling 107 days cover the seven already resolved rewards
  `398`, `399`, `507`, `637`, `638`, `897`, and `932` (98 days, 9 unused).
- No retained `ADMIN`, `DEV`, or `OWNER` addition covers any of the remaining
  759 rewards.
- The one retained `Set subscription ... duration 30` event belongs to a user
  outside the cohort. It is also an absolute subscription replacement, not an
  additive duration grant, so it is never entered into FIFO allocation.

The canonical audit object is
`src/infrastructure/recovery_manifests/legacy_referral_rewards_2026-08-22.v2.audit.json`.
Its sorted-key compact-JSON SHA-256 is
`dfac82651078009491e19be3d01f0af2a7c6e709b82f414a28754951c20b8beb`.

## User-merge lineage audit

Every current and historical identity alias in the merge lineage of the
remaining cohort was checked. Seventy rewards (910 days for 21 recipients)
touch 16 direct real merge audits and one additional transitive audit. All 70
resolve to a canonical current inbound target; none names a merge source,
merged-onward target, missing source, inconsistent marker, or non-canonical
tombstone. The full 17-edge lineage digest is
`d79e035d3f47489b664d1a15a4fbc59dbbbd341735c4f0b6ae413680a9536977`.

The administrator-duration audit was repeated across all 33 current and
historical aliases in that lineage. It found no positive administrator event
for those recipients. No new eligible administrator mutation was retained
between the original snapshot and the final lineage audit at
`2026-08-22T07:46:11.171Z`.

The manifest pins the exact direct real merge-audit IDs touching each reward's
locked participants. Runtime recovery permits only a canonical current inbound
target with that exact frozen set; a new merge, removed edge, changed marker,
outbound participant, or damaged tombstone is a fail-closed drift condition.

## Payment-source reconstruction

All 759 rewards were independently joined to the exact historical referral
chain and nearest terminal payment evidence inside the allowed five-minute
window. Actual delays are 0–17 seconds and there are no ties or source/level
collisions.

| Evidence class | Rewards | Days | Decision |
| --- | ---: | ---: | --- |
| Local `COMPLETED`, legacy `MANUAL_REQUIRED` | 745 | 9,247 | Operator-directed retry |
| Local `COMPLETED`, fulfillment `SUCCEEDED` | 13 | 147 | Operator-directed retry |
| Local `FAILED`, provider-proven paid | 1 | 14 | Pinned provider-evidence retry |

There are no refunded, test, free, or trial sources. The set represents 595
unique paid transactions: 365 `NEW`, 254 `CHANGE`, and 140 `RENEW`; 585 rewards
are first-level 14-day rewards and 174 are second-level 7-day rewards.

Reward `65` is the only provider-evidence exception. Its local YooKassa
transaction became `FAILED` 142 ms after the reward was created, but a read-only
YooKassa verification returned HTTP 200, `succeeded`, `paid=true`, and refunded
amount `0.00 RUB` at `2026-08-22T08:18:06+00:00`. The local and provider
payment identifiers matched; the evidence stores only the SHA-256 of their
canonical string form. The canonical redacted evidence SHA-256 is
`16c080ccfd92d6adc1e82f56214fd71190aca28077942a625a991a1544ff935e`.
The redacted evidence object is tracked at
`src/infrastructure/recovery_manifests/legacy_referral_rewards_2026-08-22.v2.provider-rr65.json`.
The provider must be checked again immediately before the reward worker starts.

## Delivery inventory

At the frozen delivery snapshot:

| Current subscription shape | Recipients | Rewards | Days |
| --- | ---: | ---: | ---: |
| Safe paid `ACTIVE` or `EXPIRED` | 196 | 664 | 8,225 |
| Trial | 25 | 70 | 847 |
| No current subscription | 6 | 13 | 182 |
| `DISABLED` | 3 | 12 | 154 |

Safe rows are delivered using the durable target-first worker. The other 95
rows remain a durable deferred entitlement and must not extend a trial, create a
subscription implicitly, or reactivate a deliberately disabled subscription.

## One-shot manifest

The v2 manifest contains exactly 759 entries and 9,408 days. Each entry freezes
the reward, recipient, stored referral, amount, timestamp, payment source,
origin referral, level, validation class, evidence digest, and operator reason.
It deliberately leaves the reward's historical policy fields null.

- Path:
  `src/infrastructure/recovery_manifests/legacy_referral_rewards_2026-08-22.v2.json`
- Canonical sorted-key compact-JSON SHA-256:
  `85bd8c980abc52f6457c015f17ae635f86e3f5c42e8dc1105f6dfc82292fb23c`
- Source export SHA-256:
  `5acaddd1e01886e68d1e4a28f7b82770e875a787fcb153f4c4d346b0f2014be1`

The recovery gate remains disabled by default. Enabling it requires the absolute
manifest path and exact canonical digest. Disable the gate and recreate the API
as soon as all entries have been consumed. While the gate is enabled, the bot
also rejects administrator duration additions and subscription replacements so
the audited allocation cannot race with a manual grant.

## Controlled apply

1. Take and verify a fresh PostgreSQL backup and restore it into a disposable
   database. Rehearse migration `0055`, manifest loading, and all database-only
   transitions there. Keep the worker and scheduler disabled and block or mock
   Remnawave egress: a rehearsal must never execute an external expiry update.
2. Deploy the tested image while leaving the current bot online until the image,
   migration, manifest, and rollback assets are ready.
3. Stop only the referral worker/scheduler, apply migration `0055`, start the new
   API, and verify `/health`, Telegram `/start`, payment creation, and signed
   Remnawave webhook handling.
4. Enable the exact one-shot manifest. Recompute the unresolved cohort, source
   tuples, merge history, refund state, timestamps, amounts, and digest. Stop if
   anything differs.
5. Reverify reward `65` at YooKassa. Apply it as the canary, run the reward worker,
   and verify local and Remnawave expiry against the stored absolute target.
6. Apply the remaining exact manifest entries, start the worker, and monitor each
   bounded batch. Per-row historical customer notifications are suppressed by
   the durable operator marker.
7. Confirm the 664 immediately deliverable rows are issued and the remaining 95
   are deferred with their exact entitlement intact. Re-scan administrator logs
   for the operation window and resolve any collision before continuing.
8. Disable the recovery gate, verify bot/payment health again, and retain the
   manifest, audit object, database backup, image digest, and final result report.

Before the first Remnawave side effect, the database and image can be restored as
a unit. After any external expiry update, never restore only the database: stop
the worker and reconcile forward from the stored baseline and absolute target.
