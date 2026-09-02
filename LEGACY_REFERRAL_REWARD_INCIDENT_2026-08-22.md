# Legacy referral reward incident — 2026-08-22

This document is the PII-free operator record for the production legacy
`EXTRA_DAYS` reconciliation. Times are UTC. It does not authorize bulk replay.

## Frozen cohort

- Snapshot: `2026-08-22T02:10:22.883505Z`, PostgreSQL LSN `0/F986EEE8`.
- Rows: `768` rewards for `232` recipients, totaling `9,527` days.
- Shape: every row was `MANUAL_REQUIRED`, `is_issued=false`,
  `manual_cause=LEGACY_AMBIGUOUS_ISSUANCE`, incident version `1`, with no source,
  target, resolution, or backfill audit.
- Cohort ID SHA-256: `bfc831ebe586bdd8afb7f61971c9c43f3061ab382643e8575cb8a74f076d594b`.
- Semantic shape SHA-256: `74620a4c0ca44a8ff0b927d5c7c6b9a379b58e8ff6e5eb75ea2d5ce6dc064fb7`.

## Decision

| Classification | Reward IDs | Action |
| --- | --- | --- |
| `PROVEN_NOT_APPLIED` | `1478`, `1486` | Attribute exactly and retry through the durable worker |
| `ADMIN_COMPENSATED` | `398`, `399`, `507`, `637`, `638`, `897`, `932` | Confirm issued without another side effect |
| `AMBIGUOUS` | remaining `759` | Keep fenced; do not issue or resolve |

Rewards `1342` and `1343` have a proven failed original attempt, but remain
`AMBIGUOUS` because retained logs have a `2026-07-22` through `2026-08-04` gap
that prevents exclusion of a later manual grant.

## Proven missing rewards

Both sources are paid, non-test YooKassa `NEW` transactions with completed and
successful fulfillment, no refund, no merge, no durable collision, and no earlier
paid transaction for the payer.

| Reward | Source transaction | Origin referral | Level | Days | Canonical evidence SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `1478` | `8889` | `1678` | `FIRST` | `14` | `77df9afa8552b92f7626cd504afd310f5e3043453b69c9f4959f77304d0a8cbe` |
| `1486` | `8978` | `1618` | `SECOND` | `7` | `d9c636cf422093dcbdfb4b84a39111e2531086152f3eeed854973638b9124657` |

Each log bundle proves `Invalid expire time` before the local subscription update
and before any Remnawave call. Continuous retained logs from the failures through
the frozen audit show no later `SYSTEM`, `ADMIN`, `DEV`, or `OWNER` duration grant
to either recipient.

The historical policy is bracketed by unchanged production snapshots from
`2026-08-10T17:30:00Z` and `2026-08-15T21:00:00Z`:
`ON_FIRST_PAYMENT`, `EXTRA_DAYS`, `AMOUNT`, level 1 = `14`, level 2 = `7`.

## Administrator compensation

Six successful `OWNER` grants on `2026-08-15` added
`30+30+30+7+3+7 = 107` days to one recipient. Chronological FIFO allocation uses
each granted day once and fully covers seven earlier 14-day rewards (`98` days).
The remaining `9` days are not carried to another or future reward.

| Reward | Candidate source transaction | Candidate origin referral | Level |
| --- | --- | --- | --- |
| `398` | `3987` | `788` | `FIRST` |
| `399` | `3988` | `956` | `FIRST` |
| `507` | `4505` | `1025` | `FIRST` |
| `637` | `5224` | `956` | `FIRST` |
| `638` | `5225` | `1025` | `FIRST` |
| `897` | `6235` | `1347` | `FIRST` |
| `932` | `6365` | `1366` | `FIRST` |

All candidate payments are completed, paid, non-test YooKassa transactions
without a recorded refund or durable collision. Migration 0049 deliberately left
these older sources at legacy fulfillment state `MANUAL_REQUIRED` with no
`fulfillment_completed_at`; their immutable migration-0049
`fulfillment_started_at` timestamps place the reward rows in the exact historical
issuance window. The successful OWNER grants independently prove the reward side
effect. Exact source tuples are retained as recovery evidence, but the seven
legacy rows stay unattributed: the historical accrual label is not independently
provable for four `NEW` payments, and confirmation must not fabricate a policy
snapshot.

- Canonical OWNER log bundle SHA-256:
  `9432f17979bfdf5075a3573fc51a4576ee4332aa6c93e545a72f90207602f761`.
- Canonical log + DB FIFO coverage SHA-256:
  `fb3dd384f6b42c2885056d9647f4842054052ea8fae349ae88810afd8e8995a1`.

## Canonicalization

Evidence bundles use UTF-8 and LF. Each full record is normalized as sorted-key
compact JSON with source, UTC millisecond timestamp, logger level/name, actor role,
amount, and normalized message. Actor, target, Remnawave UUID, and local user IDs
are replaced with namespaced full SHA-256 values. Lines are lexicographically
sorted, joined with LF and one final LF, then hashed with SHA-256.

## Stop conditions

Do not apply recovery if the cohort identity changes; a selected reward is no
longer incident version `1` and unresolved; attribution, source status, policy,
subscription identity, or evidence hash drifts; a refund/merge/collision appears;
or the request is not an exact idempotent replay of this incident.

## One-shot authorization manifest

The PII-free canonical v1 manifest is tracked at
`src/infrastructure/recovery_manifests/legacy_referral_rewards_2026-08-22.v1.json`.
Its canonical sorted-key compact-JSON SHA-256 is
`51284b6c833968bf4e855de30fabe4616a616ab320d000fba399c6f280cf3506`.

Production must keep the recovery gate disabled by default. During the bounded
incident only, configure the absolute container path
`/opt/remnashop/src/infrastructure/recovery_manifests/legacy_referral_rewards_2026-08-22.v1.json`
and independently pin the digest above with
`REFERRAL_REWARD_LEGACY_RECOVERY_MANIFEST_PATH` and
`REFERRAL_REWARD_LEGACY_RECOVERY_MANIFEST_SHA256`. Only then set
`REFERRAL_REWARD_LEGACY_RECOVERY_ENABLED=true`. Every payload must be copied
exactly from one manifest entry. Disable the gate immediately after all nine
decisions are consumed or the incident is stopped; keeping the file in the
image alone does not authorize recovery.

Remnawave exposes no conditional update/ETag for expiry. The worker therefore
holds the local mutation lock, verifies the exact remote UUID and baseline
expiry, sends a narrow PATCH containing only UUID, `ACTIVE`, and the absolute
target expiry, and verifies the exact response plus a read-after-write. An
operator must stop the worker if another system can concurrently mutate the
same remote expiry; an ambiguous PATCH is never retried automatically.
