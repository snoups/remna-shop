import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

from src.application.dto import LegacyReferralRewardRecoveryDto, ReferralRewardDto
from src.core.enums import (
    LegacyReferralRewardRecoveryAction,
    LegacyReferralRewardSourceValidation,
    PaymentGatewayType,
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardStrategy,
    ReferralRewardType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.infrastructure.database.constraints import (
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_SQL,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL,
)
from src.infrastructure.database.dao.referral import ReferralDaoImpl
from src.infrastructure.database.models import (
    Referral,
    ReferralReward,
    ReferralRewardBackfillAudit,
    ReferralRewardResolution,
    Transaction,
)
from src.infrastructure.database.referral_reward_source import (
    normalized_admin_compensated_source_evidence_at,
    normalized_admin_compensated_source_predicate,
)


def _capture_migration(monkeypatch: pytest.MonkeyPatch, migration: Any) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def recorder(name: str) -> Any:
        def record(*args: object, **kwargs: object) -> None:
            calls.append((name, args, kwargs))

        return record

    for name in (
        "add_column",
        "alter_column",
        "create_check_constraint",
        "create_foreign_key",
        "create_index",
        "create_table",
        "create_unique_constraint",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "drop_table",
        "execute",
    ):
        monkeypatch.setattr(migration.op, name, recorder(name))
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.postgresql.ENUM,
        "create",
        lambda self, *args, **kwargs: calls.append(("create_enum", (self.name, *args), kwargs)),
    )
    monkeypatch.setattr(
        migration.postgresql.ENUM,
        "drop",
        lambda self, *args, **kwargs: calls.append(("drop_enum", (self.name, *args), kwargs)),
    )
    return calls


def test_0052_backfills_legacy_ambiguity_and_installs_durable_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0052_make_referral_rewards_durable"
    )
    calls = _capture_migration(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0052"
    assert migration.down_revision == "0051"
    executed = "\n".join(str(args[0]) for name, args, _ in calls if name == "execute")
    assert "LEGACY_AMBIGUOUS_ISSUANCE" in executed
    assert "manual_incident_version = CASE WHEN is_issued THEN 0 ELSE 1 END" in executed
    assert "manual_cause = CASE WHEN is_issued THEN NULL" in executed
    assert "MANUAL_REQUIRED" in executed
    assert "CASE WHEN is_issued THEN 'ISSUED'" in executed
    created_enums = [args[0] for name, args, _ in calls if name == "create_enum"]
    assert created_enums == [
        "referral_accrual_strategy",
        "referral_reward_strategy",
        "referral_reward_state",
    ]
    first_add_column = next(i for i, call in enumerate(calls) if call[0] == "add_column")
    assert all(calls.index(call) < first_add_column for call in calls if call[0] == "create_enum")

    state_column = next(
        args[1] for name, args, _ in calls if name == "add_column" and args[1].name == "state"
    )
    assert state_column.type.name == "referral_reward_state"
    assert state_column.type.create_type is False
    assert str(state_column.server_default.arg) == "'MANUAL_REQUIRED'::referral_reward_state"
    assert ReferralReward.__table__.c.state.server_default is None

    foreign_keys = {args[0]: kwargs for name, args, kwargs in calls if name == "create_foreign_key"}
    assert foreign_keys["referral_rewards_referral_id_fkey"]["ondelete"] == "RESTRICT"
    assert foreign_keys["referral_rewards_source_transaction_id_fkey"]["ondelete"] == "RESTRICT"
    assert foreign_keys["referral_rewards_origin_referral_id_fkey"]["ondelete"] == "RESTRICT"
    assert foreign_keys["referral_rewards_target_subscription_id_fkey"]["ondelete"] == "RESTRICT"

    unique = next(
        args
        for name, args, _ in calls
        if name == "create_unique_constraint"
        and args[0] == "uq_referral_rewards_source_transaction_origin_level"
    )
    assert unique[2] == ["source_transaction_id", "origin_referral_id", "level"]

    indexes = {args[0]: (args, kwargs) for name, args, kwargs in calls if name == "create_index"}
    first_where = str(
        indexes["uq_referral_rewards_first_payment_origin_level"][1]["postgresql_where"]
    )
    assert indexes["uq_referral_rewards_first_payment_origin_level"][0][2] == [
        "origin_referral_id",
        "level",
    ]
    assert first_where == "accrual_strategy = 'ON_FIRST_PAYMENT'"
    assert indexes["uq_referral_rewards_processing_recipient"][0][2] == ["user_id"]

    check = next(
        str(args[2])
        for name, args, _ in calls
        if name == "create_check_constraint"
        and args[0] == REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME
    )
    assert check == REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_SQL

    issued_first_check = next(
        str(args[2])
        for name, args, _ in calls
        if name == "create_check_constraint"
        and args[0] == "ck_referral_rewards_issued_first_payment_claimed"
    )
    assert "state != 'ISSUED'" in issued_first_check
    assert "accrual_strategy_snapshot IS NULL" in issued_first_check
    assert "accrual_strategy = 'ON_FIRST_PAYMENT'" in issued_first_check

    model_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in ReferralReward.__table__.constraints
        if hasattr(constraint, "sqltext")
    }
    assert check == REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_SQL
    assert (
        model_checks[REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME]
        == REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_V2_SQL
    )
    assert model_checks["ck_referral_rewards_issued_first_payment_claimed"] == issued_first_check

    resolution_table = next(
        args
        for name, args, _ in calls
        if name == "create_table" and args[0] == "referral_reward_resolutions"
    )
    resolution_sql = " ".join(
        f"{value} {getattr(value, 'sqltext', '')}" for value in resolution_table[1:]
    )
    assert "operator_reference" in resolution_sql
    assert "resolved_by" in resolution_sql
    assert "resolved_at" in resolution_sql
    assert "reason" in resolution_sql
    assert "allow_drift" in resolution_sql
    assert "observed_subscription_id" in resolution_sql
    assert "observed_remote_uuid" in resolution_sql
    assert "observed_expire_at" in resolution_sql
    assert "incident_version" in resolution_sql
    assert "source_status" in resolution_sql
    assert "CONFIRM_ISSUED" in resolution_sql

    backfill_table = next(
        args
        for name, args, _ in calls
        if name == "create_table" and args[0] == "referral_reward_backfill_audits"
    )
    backfill_sql = " ".join(
        f"{value} {getattr(value, 'sqltext', '')}" for value in backfill_table[1:]
    )
    assert "request_hash" in backfill_sql
    assert "operator_identity" in backfill_sql
    assert "operator_reference" in backfill_sql
    assert "reason" in backfill_sql
    assert "source_transaction_ids" in backfill_sql
    assert "config_snapshot" in backfill_sql
    assert "preview_snapshot" in backfill_sql
    assert "PREVIEWED" in backfill_sql
    assert "APPLIED" in backfill_sql
    backfill_constraint_names = {getattr(value, "name", None) for value in backfill_table[1:]}
    assert "uq_referral_reward_backfill_audits_request_hash" in backfill_constraint_names

    backfill_indexes = [
        args[0]
        for name, args, _ in calls
        if name == "create_index" and "backfill_audits" in str(args[0])
    ]
    assert backfill_indexes == ["ix_referral_reward_backfill_audits_request_hash"]

    migration.downgrade()
    dropped_enums = [args[0] for name, args, _ in calls if name == "drop_enum"]
    assert dropped_enums == [
        "referral_reward_state",
        "referral_reward_strategy",
        "referral_accrual_strategy",
    ]


def test_0052_downgrade_first_guards_all_durable_evidence_but_allows_legacy_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0052_make_referral_rewards_durable"
    )
    calls = _capture_migration(monkeypatch, migration)

    migration.downgrade()

    assert calls[0][0] == "execute"
    guard_sql = str(calls[0][1][0]).upper()
    assert "LOCK TABLE" in guard_sql
    assert "IN SHARE MODE" in guard_sql
    assert "FROM REFERRAL_REWARD_RESOLUTIONS" in guard_sql
    assert "FROM REFERRAL_REWARD_BACKFILL_AUDITS" in guard_sql
    assert "FROM REFERRAL_REWARDS" in guard_sql
    assert "WHERE SOURCE_TRANSACTION_ID IS NOT NULL" in guard_sql
    assert guard_sql.count("RAISE EXCEPTION") == 3
    assert calls[1][0] == "drop_index"


def test_model_preserves_attribution_and_serializes_processing_per_recipient() -> None:
    referral_fk = next(
        fk
        for fk in ReferralReward.__table__.foreign_key_constraints
        if {column.name for column in fk.columns} == {"referral_id"}
    )
    origin_fk = next(
        fk
        for fk in ReferralReward.__table__.foreign_key_constraints
        if {column.name for column in fk.columns} == {"origin_referral_id"}
    )
    assert referral_fk.ondelete == "RESTRICT"
    assert origin_fk.ondelete == "RESTRICT"
    assert "delete" not in Referral.rewards.property.cascade
    assert "delete-orphan" not in Referral.rewards.property.cascade

    indexes = {index.name: index for index in ReferralReward.__table__.indexes}
    processing = indexes["uq_referral_rewards_processing_recipient"]
    assert processing.unique is True
    assert [column.name for column in processing.columns] == ["user_id"]
    assert str(processing.dialect_options["postgresql"]["where"]) == "state = 'PROCESSING'"


def test_backfill_audit_model_matches_migration_uniqueness_and_evidence_shape() -> None:
    table = ReferralRewardBackfillAudit.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    assert "ck_referral_reward_backfill_audits_status" in constraint_names
    assert "uq_referral_reward_backfill_audits_request_hash" in constraint_names
    assert {column.name for column in table.columns} >= {
        "request_hash",
        "status",
        "operator_identity",
        "operator_reference",
        "reason",
        "source_transaction_ids",
        "config_snapshot",
        "preview_snapshot",
        "applied_at",
    }
    request_hash_index = next(
        index
        for index in table.indexes
        if index.name == "ix_referral_reward_backfill_audits_request_hash"
    )
    assert [column.name for column in request_hash_index.columns] == ["request_hash"]


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _OneCandidateScalars:
    def all(self) -> list[int]:
        return [2883]


class _ClaimSession:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.scalar_statements: list[object] = []
        self.scalar_queries: list[object] = []

    async def execute(self, statement: object) -> SimpleNamespace:
        self.executed.append(statement)
        return SimpleNamespace(rowcount=0)

    async def scalars(
        self,
        statement: object,
    ) -> _EmptyScalars | _OneCandidateScalars:
        self.scalar_statements.append(statement)
        return _EmptyScalars()

    async def scalar(self, statement: object) -> None:
        self.scalar_queries.append(statement)
        return None


class _OneCandidateClaimSession(_ClaimSession):
    async def scalars(self, statement: object) -> _OneCandidateScalars | _EmptyScalars:
        self.scalar_statements.append(statement)
        if len(self.scalar_statements) == 1:
            return _OneCandidateScalars()
        return _EmptyScalars()


class _ClaimableCandidateSession(_OneCandidateClaimSession):
    async def scalar(self, statement: object) -> int:
        self.scalar_queries.append(statement)
        return 8123


@pytest.mark.asyncio
async def test_manual_reward_listing_applies_stable_limit_and_offset() -> None:
    session = _ClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_reward_list = lambda rows: rows  # type: ignore[method-assign]

    assert await dao.get_manual_required_rewards(limit=25, offset=50) == []

    sql = str(
        session.scalar_statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "MANUAL_REQUIRED" in sql
    assert "ORDER BY REFERRAL_REWARDS.UPDATED_AT ASC, REFERRAL_REWARDS.ID" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


@pytest.mark.asyncio
async def test_worker_manualizes_ambiguous_extra_days_and_locks_recipient_rows() -> None:
    session = _ClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    rewards = await dao.claim_pending_rewards(
        token_hash="a" * 64,
        lease_for=timedelta(minutes=5),
        limit=100,
    )

    assert rewards == []

    def statement_with_value(value: str) -> object:
        return next(
            statement
            for statement in session.executed
            if value in statement.compile(dialect=postgresql.dialect()).params.values()  # type: ignore[attr-defined]
        )

    ambiguous = statement_with_value("EXTRA_DAYS_AMBIGUOUS_LEASE_EXPIRED")
    ambiguous_sql = str(ambiguous.compile(dialect=postgresql.dialect())).upper()  # type: ignore[attr-defined]
    ambiguous_params = ambiguous.compile(dialect=postgresql.dialect()).params  # type: ignore[attr-defined]
    assert "TARGET_EXPIRE_AT IS NOT NULL" in ambiguous_sql
    assert "PROCESSING_LEASE_EXPIRES_AT" in ambiguous_sql
    assert "EXTRA_DAYS_AMBIGUOUS_LEASE_EXPIRED" in ambiguous_params.values()

    pending_refund = statement_with_value("SOURCE_REFUNDED_BEFORE_REWARD_ISSUANCE")
    processing_refund = statement_with_value("SOURCE_REFUNDED_DURING_REWARD_ISSUANCE")
    issued_refund = statement_with_value("SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE")
    assert (
        ReferralRewardState.SUPERSEDED
        in pending_refund.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect()
        ).params.values()
    )
    assert (
        ReferralRewardState.MANUAL_REQUIRED
        in processing_refund.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect()
        ).params.values()
    )
    assert (
        ReferralRewardState.MANUAL_REQUIRED
        in issued_refund.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect()
        ).params.values()
    )
    processing_refund_sql = str(
        processing_refund.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    issued_refund_sql = str(
        issued_refund.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert "MANUAL_INCIDENT_VERSION +" in processing_refund_sql
    assert "MANUAL_INCIDENT_VERSION +" in issued_refund_sql
    assert "REFERRAL_REWARD_RESOLUTIONS" in issued_refund_sql
    assert "INCIDENT_VERSION" in issued_refund_sql
    assert "SOURCE_STATUS" in issued_refund_sql
    assert "SELECTED_SOURCE_TRANSACTION_ID" in issued_refund_sql
    assert "ADMIN_COMPENSATED_REWARD_SOURCE" in issued_refund_sql
    assert "CONFIRM_ADMIN_COMPENSATED" in str(
        issued_refund.compile(dialect=postgresql.dialect()).params
    )
    assert "NOT (EXISTS" in issued_refund_sql

    invalid_operator_source = statement_with_value("OPERATOR_RECOVERY_SOURCE_NOT_ELIGIBLE")
    invalid_operator_compiled = invalid_operator_source.compile(  # type: ignore[attr-defined]
        dialect=postgresql.dialect()
    )
    invalid_operator_sql = str(invalid_operator_compiled).upper()
    assert "NOT (EXISTS" in invalid_operator_sql
    assert "OPERATOR_RECOVERY_VALID_SOURCE" in invalid_operator_sql
    assert "RETRY_OPERATOR_DIRECTED" in invalid_operator_compiled.params.values()
    assert "OPERATOR_RECOVERY_MANIFEST_SHA256 IS NOT NULL" in invalid_operator_sql
    assert "MANUAL_INCIDENT_VERSION +" in invalid_operator_sql
    assert "PROCESSING_TOKEN_HASH=" in invalid_operator_sql
    assert "PROCESSING_LEASE_EXPIRES_AT=" in invalid_operator_sql
    assert "NEXT_ATTEMPT_AT=" in invalid_operator_sql
    assert "MANUAL_ALERTED_AT=" in invalid_operator_sql
    assert ReferralRewardState.MANUAL_REQUIRED in invalid_operator_compiled.params.values()

    admin_earlier = statement_with_value("FIRST_PAYMENT_ADMIN_COMPENSATED")
    admin_earlier_compiled = admin_earlier.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    admin_earlier_sql = str(admin_earlier_compiled).upper()
    assert "SELECTED_SOURCE_TRANSACTION_ID" in admin_earlier_sql
    assert "SELECTED_ORIGIN_REFERRAL_ID" in admin_earlier_sql
    assert "SELECTED_LEVEL" in admin_earlier_sql
    assert "SUPERSEDING_ADMIN_COMPENSATED_TRANSACTION" in admin_earlier_sql
    assert "CONFIRM_ADMIN_COMPENSATED" in admin_earlier_compiled.params.values()
    assert "source_fulfillment_status" in admin_earlier_compiled.params.values()
    assert "source_evidence_timestamp_kind" in admin_earlier_compiled.params.values()
    assert "FULFILLMENT_STARTED_AT" in admin_earlier_sql
    assert "FULFILLMENT_LAST_ERROR" not in admin_earlier_sql
    assert "SUPERSEDING_ADMIN_COMPENSATED_TRANSACTION.UPDATED_AT" not in admin_earlier_sql
    assert ReferralRewardState.SUPERSEDED in admin_earlier_compiled.params.values()
    assert "MANUAL_CAUSE IN" in admin_earlier_sql
    assert any(
        isinstance(value, (list, tuple))
        and "ADMIN_COMPENSATED_EARLIER_PAYMENT" in value
        and "LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW" in value
        for value in admin_earlier_compiled.params.values()
    )

    earlier_reward = statement_with_value("FIRST_PAYMENT_EARLIER_REWARD_EXISTS")
    earlier_reward_compiled = earlier_reward.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    earlier_reward_sql = str(earlier_reward_compiled).upper()
    assert ReferralRewardState.SUPERSEDED in earlier_reward_compiled.params.values()
    assert "SUPERSEDING_OPERATOR_DIRECTED_RESOLUTION" in earlier_reward_sql
    assert "SUPERSEDING_OPERATOR_DIRECTED_TRANSACTION" in earlier_reward_sql
    assert "RETRY_OPERATOR_DIRECTED" in earlier_reward_compiled.params.values()
    assert "SELECTED_ORIGIN_REFERRAL_ID" in earlier_reward_sql
    assert "SELECTED_LEVEL" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD_SOURCE" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.SOURCE_TRANSACTION_ID IS NULL" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.STATE" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.IS_ISSUED IS TRUE" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.ISSUED_AT IS NOT NULL" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.REFERRAL_ID = REFERRAL_REWARDS.REFERRAL_ID" in (
        earlier_reward_sql
    )
    assert "EMITTED_LEGACY_REWARD.USER_ID = REFERRAL_REWARDS.USER_ID" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD.CREATED_AT" in earlier_reward_sql
    assert "EMITTED_LEGACY_REWARD_SOURCE.FULFILLMENT_STARTED_AT" in earlier_reward_sql
    assert "SUPERSEDED_REWARD_SOURCE.FULFILLMENT_COMPLETED_AT" in earlier_reward_sql
    assert "LEGACY_COMPLETED_WITHOUT_PROOF" in earlier_reward_compiled.params.values()
    assert "LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW" in (earlier_reward_compiled.params.values())

    legacy_earlier = next(
        statement
        for statement in session.executed
        if "LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW"
        in statement.compile(dialect=postgresql.dialect()).params.values()  # type: ignore[attr-defined]
        and "SUPERSEDING_EARLIER_TRANSACTION"
        in str(statement.compile(dialect=postgresql.dialect())).upper()  # type: ignore[attr-defined]
    )
    legacy_earlier_compiled = legacy_earlier.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    legacy_earlier_sql = str(legacy_earlier_compiled).upper()
    assert "SUPERSEDING_EARLIER_TRANSACTION" in legacy_earlier_sql
    assert "FULFILLMENT_STARTED_AT" in legacy_earlier_sql
    assert "LEGACY_COMPLETED_WITHOUT_PROOF" in legacy_earlier_compiled.params.values()
    assert "SUPERSEDING_EARLIER_TRANSACTION.UPDATED_AT" not in legacy_earlier_sql

    earlier_supersede = statement_with_value("FIRST_PAYMENT_EARLIER_SUCCESS")
    earlier_supersede_sql = str(
        earlier_supersede.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    earlier_supersede_params = earlier_supersede.compile(  # type: ignore[attr-defined]
        dialect=postgresql.dialect()
    ).params
    assert "SUPERSEDING_EARLIER_TRANSACTION" in earlier_supersede_sql
    assert "SOURCE_TRANSACTION_ID" in earlier_supersede_sql
    assert "FIRST_PAYMENT_EARLIER_SUCCESS" in earlier_supersede_params.values()

    recipient_compiled = session.scalar_statements[0].compile(dialect=postgresql.dialect())
    recipient_lock_sql = str(recipient_compiled).upper()
    assert "FROM USERS" in recipient_lock_sql
    assert "FOR UPDATE SKIP LOCKED" in recipient_lock_sql
    assert "EARLIER_SUCCESSFUL_TRANSACTION" in recipient_lock_sql
    assert "FULFILLMENT_COMPLETED_AT" in recipient_lock_sql
    assert "FULFILLMENT_STARTED_AT" in recipient_lock_sql
    assert "LEGACY_COMPLETED_WITHOUT_PROOF" in recipient_compiled.params.values()
    assert "EARLIER_SUCCESSFUL_TRANSACTION.UPDATED_AT" not in recipient_lock_sql
    assert "REFUNDED" in str(recipient_compiled.params).upper()
    assert "NOT (EXISTS" in recipient_lock_sql
    assert "ADMIN_COMPENSATED_EARLIER_TRANSACTION" in recipient_lock_sql


@pytest.mark.asyncio
async def test_worker_rechecks_processing_reward_after_recipient_lock() -> None:
    session = _OneCandidateClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.claim_pending_rewards(
        token_hash="a" * 64,
        lease_for=timedelta(minutes=5),
        limit=100,
    ) == []

    assert len(session.scalar_queries) == 1
    compiled = session.scalar_queries[0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled).upper()
    assert "REFERRAL_REWARDS.USER_ID = 2883" in sql
    assert "NOT (EXISTS" in sql
    assert "PROCESSING_REWARD_FOR_LOCKED_USER" in sql
    assert "PROCESSING_REWARD_FOR_LOCKED_USER.USER_ID = 2883" in sql
    assert "PROCESSING_REWARD_FOR_LOCKED_USER.STATE = 'PROCESSING'" in sql


@pytest.mark.asyncio
async def test_claim_transition_revalidates_mutable_candidate_conditions() -> None:
    session = _ClaimableCandidateSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_reward_list = lambda rows: rows  # type: ignore[method-assign]

    assert await dao.claim_pending_rewards(
        token_hash="a" * 64,
        lease_for=timedelta(minutes=5),
        limit=100,
    ) == []

    assert len(session.scalar_statements) == 2
    claim_update = session.scalar_statements[1].compile(
        dialect=postgresql.dialect(),
    )
    claim_update_sql = str(claim_update).upper()
    assert "UPDATE REFERRAL_REWARDS" in claim_update_sql
    assert "REFERRAL_REWARDS.ID IN" in claim_update_sql
    assert ReferralRewardState.PENDING in claim_update.params.values()
    assert ReferralRewardState.RETRY_WAITING in claim_update.params.values()
    assert "REWARD_SOURCE_TRANSACTION" in claim_update_sql
    assert "PROCESSING_REWARD_DURING_CLAIM_UPDATE" in claim_update_sql
    assert "PROCESSING_REWARD_DURING_CLAIM_UPDATE.ID != REFERRAL_REWARDS.ID" in claim_update_sql


def test_admin_compensated_on_first_fence_uses_immutable_resolution_provenance() -> None:
    resolution = aliased(
        ReferralRewardResolution,
        name="normalized_admin_resolution",
    )
    source = aliased(Transaction, name="normalized_admin_source")
    evidence_at = normalized_admin_compensated_source_evidence_at(resolution, source)
    statement = (
        select(resolution.id)
        .select_from(resolution)
        .join(source, source.id == resolution.selected_source_transaction_id)
        .where(
            *normalized_admin_compensated_source_predicate(resolution, source),
            evidence_at.is_not(None),
        )
    )

    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled).upper()
    params = compiled.params.values()

    assert "SELECTED_PROVENANCE" in sql
    assert "FULFILLMENT_STARTED_AT" in sql
    assert "FULFILLMENT_COMPLETED_AT" in sql
    assert "FULFILLMENT_LAST_ERROR" not in sql
    assert "NORMALIZED_ADMIN_SOURCE.UPDATED_AT" not in sql
    assert "CONFIRM_ADMIN_COMPENSATED" in params
    assert "source_fulfillment_status" in params
    assert "source_evidence_timestamp_kind" in params
    assert "fulfillment_started_at" in params


@pytest.mark.asyncio
async def test_refund_incident_versioning_reopens_only_after_nonrefund_resolution() -> None:
    session = _ClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    await dao.claim_pending_rewards(
        token_hash="a" * 64,
        lease_for=timedelta(minutes=5),
        limit=1,
    )

    issued_refund = next(
        statement
        for statement in session.executed
        if "SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE"
        in statement.compile(dialect=postgresql.dialect()).params.values()  # type: ignore[attr-defined]
    )
    compiled = issued_refund.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled).upper()
    # A prior ambiguity resolution records source_status=COMPLETED and therefore
    # does not satisfy this fence: the later refund increments a new incident.
    # Resolving that refund records REFUNDED for the current version, so all later
    # sweeps satisfy the correlated EXISTS and remain stable.
    assert "REFERRAL_REWARD_RESOLUTIONS.INCIDENT_VERSION = " in sql
    assert "REFERRAL_REWARDS.MANUAL_INCIDENT_VERSION" in sql
    assert "REFERRAL_REWARD_RESOLUTIONS.SOURCE_STATUS" in sql
    assert TransactionStatus.REFUNDED.value in compiled.params.values()
    assert "MANUAL_INCIDENT_VERSION +" in sql

    manual_rollover = next(
        statement
        for statement in session.executed
        if "MANUAL_CAUSE NOT IN" in str(statement.compile(dialect=postgresql.dialect())).upper()  # type: ignore[attr-defined]
    )
    rollover_sql = str(manual_rollover.compile(dialect=postgresql.dialect())).upper()  # type: ignore[attr-defined]
    assert "MANUAL_INCIDENT_VERSION +" in rollover_sql
    assert "LAST_ERROR=" not in rollover_sql


@pytest.mark.asyncio
async def test_refund_sweep_reopens_admin_compensation_via_normalized_source() -> None:
    session = _ClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    await dao.claim_pending_rewards(
        token_hash="a" * 64,
        lease_for=timedelta(minutes=5),
        limit=1,
    )

    issued_refund = next(
        statement
        for statement in session.executed
        if "SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE"
        in statement.compile(dialect=postgresql.dialect()).params.values()  # type: ignore[attr-defined]
    )
    compiled = issued_refund.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled).upper()
    assert "ADMIN_COMPENSATED_REWARD_SOURCE" in sql
    assert "SELECTED_SOURCE_TRANSACTION_ID" in sql
    assert "REFERRAL_REWARD_RESOLUTIONS.REWARD_ID = REFERRAL_REWARDS.ID" in sql
    assert "CONFIRM_ADMIN_COMPENSATED" in compiled.params.values()
    assert ReferralRewardState.ISSUED in compiled.params.values()
    assert ReferralRewardState.MANUAL_REQUIRED in compiled.params.values()
    assert "MANUAL_INCIDENT_VERSION +" in sql
    assert "REFUND_DETECTED_AT" in sql


@pytest.mark.asyncio
async def test_attribution_fence_locks_payer_and_referrers_in_user_id_order() -> None:
    session = _ClaimSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    await dao.lock_referral_attribution(9, (5, 2, 5))

    users_sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    referrals_sql = str(
        session.executed[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "USERS.ID IN (2, 5, 9)" in users_sql
    assert "ORDER BY USERS.ID" in users_sql
    assert "FOR UPDATE" in users_sql
    assert "REFERRALS.REFERRED_ID IN (2, 5, 9)" in referrals_sql
    assert "ORDER BY REFERRALS.ID" in referrals_sql
    assert "FOR UPDATE" in referrals_sql


class _DumpRetort:
    def dump(self, reward: ReferralRewardDto) -> dict[str, object]:
        return {
            "id": reward.id,
            "user_id": reward.user_id,
            "type": reward.type,
            "amount": reward.amount,
            "is_issued": reward.is_issued,
            "referral_id": reward.referral_id,
            "source_transaction_id": reward.source_transaction_id,
            "origin_referral_id": reward.origin_referral_id,
            "level": reward.level,
            "accrual_strategy_snapshot": reward.accrual_strategy_snapshot,
            "accrual_strategy": reward.accrual_strategy,
            "reward_strategy": reward.reward_strategy,
            "config_value": reward.config_value,
            "state": reward.state,
            "attempt_count": reward.attempt_count,
            "next_attempt_at": None,
            "processing_token_hash": None,
            "processing_lease_expires_at": None,
            "last_error": None,
            "manual_alerted_at": None,
            "refund_detected_at": None,
            "manual_incident_version": reward.manual_incident_version,
            "manual_cause": reward.manual_cause,
            "issued_at": None,
            "target_subscription_id": None,
            "baseline_expire_at": None,
            "target_expire_at": None,
            "operator_recovery_manifest_sha256": None,
            "created_at": None,
            "updated_at": None,
        }


class _ScalarSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        return self.values.pop(0)


@pytest.mark.asyncio
async def test_reward_for_update_refreshes_the_locked_identity_map_row() -> None:
    reward = SimpleNamespace(id=8)
    session = _ScalarSession([reward])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_reward_dto = lambda row: row  # type: ignore[method-assign]

    assert await dao.get_reward_by_id(8, for_update=True) is reward

    statement = session.statements[0]
    sql = str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "REFERRAL_REWARDS.ID = 8" in sql
    assert "FOR UPDATE" in sql
    assert statement.get_execution_options()["populate_existing"] is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_idempotent_create_only_returns_the_exact_same_intent() -> None:
    exact = SimpleNamespace(id=91)
    session = _ScalarSession([None, None, exact])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao.retort = _DumpRetort()  # type: ignore[assignment]
    dao._convert_to_reward_dto = lambda row: row  # type: ignore[method-assign]
    reward = ReferralRewardDto(
        user_id=2,
        referral_id=999,
        type=ReferralRewardType.POINTS,
        amount=10,
        source_transaction_id=77,
        origin_referral_id=101,
        level=ReferralLevel.SECOND,
        accrual_strategy=ReferralAccrualStrategy.ON_FIRST_PAYMENT,
        reward_strategy=ReferralRewardStrategy.AMOUNT,
        config_value=10,
    )

    result = await dao.create_reward(reward, referral_id=202)

    assert result is exact
    recovery_fence = session.statements[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    recovery_decisions = next(
        value for value in recovery_fence.params.values() if isinstance(value, list)
    )
    assert set(recovery_decisions) == {
        "RETRY_PROVEN_MISSING",
        "CONFIRM_ADMIN_COMPENSATED",
        "RETRY_OPERATOR_DIRECTED",
    }
    insert_params = session.statements[1].compile(dialect=postgresql.dialect()).params  # type: ignore[attr-defined]
    assert 202 in insert_params.values()
    assert 999 not in insert_params.values()
    insert_sql = str(
        session.statements[1].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert "CREATED_AT" not in insert_sql
    assert "UPDATED_AT" not in insert_sql
    exact_sql = str(session.statements[2].compile(dialect=postgresql.dialect())).upper()  # type: ignore[attr-defined]
    assert "SOURCE_TRANSACTION_ID" in exact_sql
    assert "ORIGIN_REFERRAL_ID" in exact_sql
    assert "LEVEL" in exact_sql


@pytest.mark.asyncio
@pytest.mark.parametrize("attempted_level", [ReferralLevel.FIRST, ReferralLevel.SECOND])
async def test_rr65_l1_recovery_freezes_all_later_normal_levels(
    attempted_level: ReferralLevel,
) -> None:
    session = _ScalarSession([65])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao.retort = _DumpRetort()  # type: ignore[assignment]
    reward = ReferralRewardDto(
        user_id=62,
        referral_id=41,
        type=ReferralRewardType.EXTRA_DAYS,
        amount=14,
        source_transaction_id=1761,
        origin_referral_id=41,
        level=attempted_level,
        accrual_strategy_snapshot=ReferralAccrualStrategy.ON_EACH_PAYMENT,
        accrual_strategy=ReferralAccrualStrategy.ON_EACH_PAYMENT,
        reward_strategy=ReferralRewardStrategy.AMOUNT,
        config_value=14,
        state=ReferralRewardState.PENDING,
    )

    assert await dao.create_reward(reward, referral_id=41) is None
    assert len(session.statements) == 1
    compiled = session.statements[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled).upper()
    assert "REFERRAL_REWARD_RESOLUTIONS" in sql
    assert "SELECTED_SOURCE_TRANSACTION_ID" in sql
    assert "SELECTED_LEVEL" not in sql
    assert 1761 in compiled.params.values()
    decisions = next(value for value in compiled.params.values() if isinstance(value, list))
    assert "RETRY_OPERATOR_DIRECTED" in decisions


@pytest.mark.asyncio
async def test_manual_resolver_locks_source_transaction_before_decision() -> None:
    reward = SimpleNamespace(
        source_transaction_id=77,
        operator_recovery_manifest_sha256=None,
    )
    session = _ScalarSession([reward, TransactionStatus.REFUNDED])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    status = await dao.lock_manual_reward_source_status(8)

    assert status == TransactionStatus.REFUNDED
    sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    reward_lock_sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "REFERRAL_REWARDS.ID = 8" in reward_lock_sql
    assert "FOR UPDATE" in reward_lock_sql
    assert "TRANSACTIONS.ID = 77" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_manual_operator_resolution_locks_its_selected_source_by_digest() -> None:
    reward = SimpleNamespace(
        source_transaction_id=None,
        operator_recovery_manifest_sha256="m" * 64,
    )
    session = _ScalarSession([reward, TransactionStatus.REFUNDED])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    status = await dao.lock_manual_reward_source_status(65)

    assert status == TransactionStatus.REFUNDED
    sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "RETRY_OPERATOR_DIRECTED" in sql
    assert "AUTHORIZATION_MANIFEST_SHA256" in sql
    assert "REFERRAL_REWARD_RESOLUTIONS.REWARD_ID = 65" in sql
    assert "FOR UPDATE OF TRANSACTIONS" in sql


@pytest.mark.asyncio
async def test_side_effect_eligibility_locks_successful_source_transaction() -> None:
    reward = SimpleNamespace(
        source_transaction_id=77,
        operator_recovery_manifest_sha256=None,
        manual_incident_version=0,
    )
    session = _ScalarSession([reward, 77])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.lock_reward_source_if_eligible(
        8,
        token_hash="t" * 64,
    )

    sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    reward_lock_sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "REFERRAL_REWARDS.ID = 8" in reward_lock_sql
    assert "PROCESSING_TOKEN_HASH" in reward_lock_sql
    assert "FOR UPDATE" in reward_lock_sql
    assert "FOR UPDATE" in sql
    assert "TRANSACTIONS.STATUS IN ('COMPLETED')" in sql
    assert "TRANSACTIONS.FULFILLMENT_STATUS = 'SUCCEEDED'" in sql
    assert "TRANSACTIONS.IS_TEST IS FALSE" in sql
    assert "FINAL_AMOUNT" in sql
    assert "IS_TRIAL" in sql


@pytest.mark.asyncio
async def test_operator_side_effect_eligibility_uses_pinned_resolution_source_class() -> None:
    reward = SimpleNamespace(
        source_transaction_id=None,
        operator_recovery_manifest_sha256="m" * 64,
        manual_incident_version=4,
    )
    session = _ScalarSession([reward, 1761])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.lock_reward_source_if_eligible(65, token_hash="t" * 64)

    sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "RETRY_OPERATOR_DIRECTED" in sql
    assert "SOURCE_VALIDATION" in sql
    assert "PROVIDER_SUCCEEDED" in sql
    assert "TRANSACTIONS.STATUS = 'FAILED'" in sql
    assert "TRANSACTIONS.GATEWAY_TYPE = 'YOOKASSA'" in sql
    assert "AUTHORIZATION_MANIFEST_SHA256" in sql
    assert "INCIDENT_VERSION = 4" in sql
    assert "FOR UPDATE OF TRANSACTIONS" in sql


class _PointsSession:
    def __init__(self, reward_transition: int | None) -> None:
        self.reward_transition = reward_transition
        self.scalar_statement: object | None = None
        self.execute_statements: list[object] = []

    async def scalar(self, statement: object) -> int | None:
        self.scalar_statement = statement
        return self.reward_transition

    async def execute(self, statement: object) -> SimpleNamespace:
        self.execute_statements.append(statement)
        return SimpleNamespace(rowcount=1)


@pytest.mark.asyncio
async def test_points_increment_is_fenced_by_same_atomic_state_transition() -> None:
    session = _PointsSession(8)
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    issued = await dao.issue_points_reward(
        8,
        user_id=2,
        amount=10,
        token_hash="t" * 64,
    )

    assert issued is True
    reward_sql = str(
        session.scalar_statement.compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
    ).upper()
    points_sql = str(
        session.execute_statements[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert "PROCESSING_TOKEN_HASH" in reward_sql
    assert "STATE" in reward_sql
    assert "USERS.POINTS +" in points_sql

    replay_session = _PointsSession(None)
    replay_dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    replay_dao.session = replay_session  # type: ignore[assignment]
    assert not await replay_dao.issue_points_reward(
        8,
        user_id=2,
        amount=10,
        token_hash="t" * 64,
    )
    assert replay_session.execute_statements == []


class _ResolutionSession:
    def __init__(self, scalar_values: list[object]) -> None:
        self.scalar_values = scalar_values
        self.scalar_statements: list[object] = []
        self.added: list[object] = []
        self.executed: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.scalar_statements.append(statement)
        return self.scalar_values.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def execute(self, statement: object) -> SimpleNamespace:
        self.executed.append(statement)
        return SimpleNamespace(rowcount=1)


class _ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class _FullRecoverySession(_ResolutionSession):
    def __init__(
        self,
        scalar_values: list[object],
        *,
        reward: object,
        source: object,
        origin: object,
        participant_ids: list[int],
        participant_merge_audit_ids: list[int] | None = None,
    ) -> None:
        super().__init__(scalar_values)
        self.reward = reward
        self.source = source
        self.origin = origin
        self.participant_ids = participant_ids
        self.scalar_row_values = [
            participant_ids,
            participant_merge_audit_ids or [],
        ]

    async def get(self, model: object, object_id: int) -> object:
        if model is ReferralReward:
            return self.reward
        if model.__name__ == "Transaction":  # type: ignore[union-attr]
            return self.source
        if model is Referral:
            return self.origin
        raise AssertionError((model, object_id))

    async def scalars(self, statement: object) -> _ScalarRows:
        return _ScalarRows(self.scalar_row_values.pop(0))


def _recovery(
    action: LegacyReferralRewardRecoveryAction = (
        LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING
    ),
) -> LegacyReferralRewardRecoveryDto:
    retry = action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING
    return LegacyReferralRewardRecoveryDto(
        reward_id=8,
        action=action,
        expected_version=1,
        source_transaction_id=77,
        origin_referral_id=101,
        level=ReferralLevel.FIRST,
        expected_reward_amount=3,
        accrual_strategy_snapshot=(ReferralAccrualStrategy.ON_FIRST_PAYMENT if retry else None),
        reward_strategy=ReferralRewardStrategy.AMOUNT if retry else None,
        config_value=3 if retry else None,
        operator_reference="OWNER/TICKET-123",
        reason="Exact durable evidence",
        evidence_sha256="a" * 64,
        authorization_manifest_sha256="d" * 64,
    )


def _operator_recovery(
    reward: SimpleNamespace,
) -> LegacyReferralRewardRecoveryDto:
    return replace(
        _recovery(LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED),
        expected_user_id=reward.user_id,
        expected_referral_id=reward.referral_id,
        expected_created_at=reward.created_at,
        source_validation=LegacyReferralRewardSourceValidation.LOCAL_COMPLETED,
    )


def _recovery_entities() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    fulfilled_at = datetime.now(timezone.utc)
    reward = SimpleNamespace(
        id=8,
        referral_id=101,
        user_id=2,
        type=ReferralRewardType.EXTRA_DAYS,
        amount=3,
        is_issued=False,
        state=ReferralRewardState.MANUAL_REQUIRED,
        source_transaction_id=None,
        origin_referral_id=None,
        level=None,
        accrual_strategy_snapshot=None,
        accrual_strategy=None,
        reward_strategy=None,
        config_value=None,
        attempt_count=0,
        next_attempt_at=None,
        processing_token_hash=None,
        processing_lease_expires_at=None,
        last_error="LEGACY_AMBIGUOUS_ISSUANCE",
        manual_incident_version=1,
        manual_cause="LEGACY_AMBIGUOUS_ISSUANCE",
        issued_at=None,
        target_subscription_id=None,
        baseline_expire_at=None,
        target_expire_at=None,
        refund_detected_at=None,
        created_at=fulfilled_at + timedelta(minutes=1),
    )
    source = SimpleNamespace(
        id=77,
        user_id=7,
        status=TransactionStatus.COMPLETED,
        fulfillment_status=TransactionFulfillmentStatus.SUCCEEDED,
        is_test=False,
        pricing={"final_amount": "100.00"},
        plan_snapshot={"is_trial": False, "duration": 30},
        created_at=fulfilled_at - timedelta(minutes=1),
        updated_at=fulfilled_at,
        fulfillment_completed_at=fulfilled_at,
        fulfillment_started_at=fulfilled_at - timedelta(seconds=1),
        fulfillment_last_error=None,
        fulfillment_token_hash=None,
        fulfillment_lease_expires_at=None,
        purchase_type=PurchaseType.NEW,
    )
    origin = SimpleNamespace(
        id=101,
        referrer_id=2,
        referred_id=7,
        created_at=fulfilled_at - timedelta(days=1),
    )
    return reward, source, origin


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING,
        LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
    ],
)
async def test_legacy_recovery_locks_and_audits_exact_candidate(
    action: LegacyReferralRewardRecoveryAction,
) -> None:
    recovery = _recovery(action)
    reward, source, origin = _recovery_entities()
    if action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
        reward.created_at = source.fulfillment_completed_at - timedelta(milliseconds=35)
    else:
        source.fulfillment_status = TransactionFulfillmentStatus.MANUAL_REQUIRED
        source.fulfillment_completed_at = None
        source.fulfillment_last_error = "LEGACY_COMPLETED_WITHOUT_PROOF"
        source.fulfillment_started_at = reward.created_at - timedelta(seconds=1)
        source.updated_at = reward.created_at + timedelta(days=30)
    scalar_values: list[object] = [
        None,  # advisory lock
        None,  # no existing resolution
        None,  # no other resolution incident
        None,  # no L2 parent hint
        None,  # no real user merge
        reward,
        source,
        origin,
        origin,
        None,  # no durable collision
        None,  # no normalized recovery collision
    ]
    if action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
        scalar_values.extend((None, None))  # no earlier source / ON_FIRST winner
    session = _FullRecoverySession(
        scalar_values,
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.recover_legacy_extra_days_reward(recovery)

    assert session.scalar_values == []
    resolution = session.added[0]
    assert isinstance(resolution, ReferralRewardResolution)
    assert resolution.decision == action.value
    assert resolution.evidence_sha256 == "a" * 64
    assert resolution.selected_provenance["request"]["source_transaction_id"] == 77
    assert resolution.selected_provenance["selected"] == {
        "payer_user_id": 7,
        "recipient_user_id": 2,
        "stored_reward_referral_id": 101,
        "recipient_referral_id": 101,
        "stored_reward_referral_shape": "DIRECT_ORIGIN",
        "reward_type": "EXTRA_DAYS",
        "reward_amount": 3,
        "legacy_reward_created_at": reward.created_at.isoformat(),
        "origin_referral_created_at": origin.created_at.isoformat(),
        "source_purchase_type": "NEW",
        "source_fulfillment_status": source.fulfillment_status.value,
        "source_fulfillment_completed_at": (
            source.fulfillment_completed_at.isoformat()
            if source.fulfillment_completed_at is not None
            else None
        ),
        "source_evidence_timestamp_kind": (
            "fulfillment_completed_at"
            if source.fulfillment_completed_at is not None
            else "fulfillment_started_at"
        ),
        "source_evidence_timestamp": (
            source.fulfillment_completed_at or source.fulfillment_started_at
        ).isoformat(),
    }
    assert resolution.selected_source_transaction_id == 77
    assert resolution.selected_origin_referral_id == 101
    assert resolution.selected_level == ReferralLevel.FIRST
    assert resolution.authorization_manifest_sha256 == "d" * 64
    assert len(session.executed) == 1
    if action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
        earlier_statement = next(
            statement
            for statement in session.scalar_statements
            if "legacy_recovery_earlier_source"
            in str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
        )
        earlier_compiled = earlier_statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
        earlier_sql = str(earlier_compiled).upper()
        assert "CASE" in earlier_sql
        assert "FULFILLMENT_STARTED_AT" in earlier_sql
        assert "LEGACY_RECOVERY_EARLIER_SOURCE.UPDATED_AT" not in earlier_sql
        assert "FULFILLMENT_LAST_ERROR" in earlier_sql
        assert "LEGACY_COMPLETED_WITHOUT_PROOF" in earlier_compiled.params.values()


@pytest.mark.asyncio
async def test_operator_recovery_keeps_reward_source_less_and_audits_validation_class() -> None:
    reward, source, origin = _recovery_entities()
    recovery = _operator_recovery(reward)
    session = _FullRecoverySession(
        [None, None, None, None, None, reward, source, origin, origin, None, None],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.recover_legacy_extra_days_reward(recovery)

    resolution = session.added[0]
    assert resolution.decision == "RETRY_OPERATOR_DIRECTED"
    assert resolution.selected_source_transaction_id == 77
    assert resolution.selected_provenance["request"]["source_validation"] == "LOCAL_COMPLETED"
    assert resolution.selected_provenance["request"][
        "expected_participant_merge_audit_ids"
    ] == []
    assert resolution.selected_provenance["selected"]["source_validation"] == "LOCAL_COMPLETED"
    assert resolution.selected_provenance["selected"]["participant_merge_audit_ids"] == []
    values = ReferralDaoImpl._legacy_recovery_transition_values(
        recovery,
        source_transaction_id=77,
        origin_referral_id=101,
        issued_at=None,
    )
    assert values["state"] == ReferralRewardState.PENDING
    assert values["operator_recovery_manifest_sha256"] == "d" * 64
    for field in (
        "source_transaction_id",
        "origin_referral_id",
        "level",
        "accrual_strategy_snapshot",
        "accrual_strategy",
        "reward_strategy",
        "config_value",
    ):
        assert field not in values


def test_provider_succeeded_class_accepts_only_failed_yookassa_shape() -> None:
    _, source, _ = _recovery_entities()
    source.status = TransactionStatus.FAILED
    source.gateway_type = PaymentGatewayType.YOOKASSA
    source.fulfillment_status = TransactionFulfillmentStatus.MANUAL_REQUIRED
    source.fulfillment_completed_at = None
    source.fulfillment_token_hash = None
    source.fulfillment_lease_expires_at = None

    ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
        source,
        LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED,
        LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED,
    )

    source.gateway_type = PaymentGatewayType.YOOMONEY
    with pytest.raises(ValueError, match="failed local YooKassa"):
        ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
            source,
            LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED,
            LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_referral_id", "stored_shape"),
    [
        (1618, "DIRECT_ORIGIN"),
        (1014, "PARENT_RECIPIENT"),
    ],
)
async def test_legacy_second_recovery_accepts_both_exact_historical_shapes(
    stored_referral_id: int,
    stored_shape: str,
) -> None:
    recovery = replace(
        _recovery(),
        reward_id=1486,
        source_transaction_id=8978,
        origin_referral_id=1618,
        level=ReferralLevel.SECOND,
        expected_reward_amount=7,
        config_value=7,
    )
    reward, source, origin = _recovery_entities()
    reward.id = 1486
    reward.referral_id = stored_referral_id
    reward.amount = 7
    source.id = 8978
    reward.created_at = source.fulfillment_completed_at - timedelta(milliseconds=23)
    origin.id = 1618
    origin.referrer_id = 3
    parent = SimpleNamespace(
        id=1014,
        referrer_id=2,
        referred_id=3,
        created_at=origin.created_at - timedelta(days=1),
    )
    session = _FullRecoverySession(
        [
            None,  # advisory lock
            None,  # no exact resolution
            None,  # no other resolution
            parent,  # L2 parent hint
            None,  # no real merge
            reward,
            source,
            origin,
            origin,  # locked direct referral
            parent,  # locked parent referral
            None,  # no durable collision
            None,  # no normalized recovery collision
            None,  # no earlier paid source
            None,  # no ON_FIRST winner
        ],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 3, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.recover_legacy_extra_days_reward(recovery)

    resolution = session.added[0]
    assert resolution.selected_provenance["selected"]["stored_reward_referral_id"] == (
        stored_referral_id
    )
    assert resolution.selected_provenance["selected"]["recipient_referral_id"] == 1014
    assert resolution.selected_provenance["selected"]["stored_reward_referral_shape"] == (
        stored_shape
    )
    assert resolution.selected_source_transaction_id == 8978
    assert resolution.selected_origin_referral_id == 1618
    assert resolution.selected_level == ReferralLevel.SECOND
    assert session.scalar_values == []


@pytest.mark.asyncio
async def test_legacy_recovery_rejects_any_real_participant_merge() -> None:
    recovery = _recovery()
    reward, source, origin = _recovery_entities()
    session = _FullRecoverySession(
        [None, None, None, None, 901],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    with pytest.raises(ValueError, match="user-merge history"):
        await dao.recover_legacy_extra_days_reward(recovery)

    assert session.added == []
    assert session.executed == []


def test_operator_recovery_pins_exact_real_participant_merge_ids() -> None:
    statement = ReferralDaoImpl._operator_recovery_participant_merge_audit_ids_query(
        {2, 7}
    )
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled).upper()

    assert "USER_MERGE_AUDIT.DRY_RUN IS FALSE" in sql
    assert "USER_MERGE_AUDIT.SOURCE_USER_ID IN" in sql
    assert "USER_MERGE_AUDIT.TARGET_USER_ID IN" in sql
    assert "ORDER BY USER_MERGE_AUDIT.ID" in sql
    assert sorted(compiled.params["source_user_id_1"]) == [2, 7]
    assert sorted(compiled.params["target_user_id_1"]) == [2, 7]


@pytest.mark.asyncio
async def test_operator_recovery_accepts_exact_pinned_merge_ids_and_audits_them() -> None:
    reward, source, origin = _recovery_entities()
    recovery = replace(
        _operator_recovery(reward),
        expected_participant_merge_audit_ids=(3, 17),
    )
    session = _FullRecoverySession(
        [None, None, None, None, None, reward, source, origin, origin, None, None],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
        participant_merge_audit_ids=[3, 17],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.recover_legacy_extra_days_reward(recovery)

    resolution = session.added[0]
    assert resolution.selected_provenance["request"][
        "expected_participant_merge_audit_ids"
    ] == [3, 17]
    assert resolution.selected_provenance["selected"][
        "participant_merge_audit_ids"
    ] == [3, 17]


@pytest.mark.asyncio
async def test_operator_recovery_rejects_participant_merge_id_drift_before_lineage_guard() -> None:
    reward, source, origin = _recovery_entities()
    recovery = replace(
        _operator_recovery(reward),
        expected_participant_merge_audit_ids=(3,),
    )
    session = _FullRecoverySession(
        [None, None, None, None],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
        participant_merge_audit_ids=[3, 17],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    with pytest.raises(ValueError, match="merge history drifted"):
        await dao.recover_legacy_extra_days_reward(recovery)

    assert session.scalar_values == []
    assert session.added == []
    assert session.executed == []


def test_operator_recovery_merge_guard_allows_only_canonical_inbound_targets() -> None:
    statement = ReferralDaoImpl._operator_recovery_merge_conflict_query({2, 7})
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled).upper()

    # Dry runs carry no lineage authority. Every real edge touching a frozen
    # participant is inspected, while a participant in the source role always
    # fails the query.
    assert "USER_MERGE_AUDIT.DRY_RUN IS FALSE" in sql
    assert "USER_MERGE_AUDIT.SOURCE_USER_ID = USERS.ID" in sql
    assert "USER_MERGE_AUDIT.TARGET_USER_ID = USERS.ID" in sql

    # A participant must still be the current target. Its inbound source must
    # point exactly to it and retain the canonical source-tombstone shape.
    assert "USERS.MERGED_INTO_USER_ID IS NOT NULL" in sql
    assert "USERS.MERGED_AT IS NOT NULL" in sql
    assert (
        "LEGACY_RECOVERY_MERGE_SOURCE.MERGED_INTO_USER_ID "
        "IS DISTINCT FROM USERS.ID"
    ) in sql
    assert "LEGACY_RECOVERY_MERGE_SOURCE.MERGED_AT IS NULL" in sql
    assert "LEGACY_RECOVERY_MERGE_SOURCE.IS_BLOCKED IS NOT TRUE" in sql
    assert "LEGACY_RECOVERY_MERGE_SOURCE.TELEGRAM_ID IS NOT NULL" in sql
    assert "LEGACY_RECOVERY_MERGE_SOURCE.EMAIL IS NOT NULL" in sql
    assert "LEGACY_RECOVERY_MERGE_SOURCE.CURRENT_SUBSCRIPTION_ID IS NOT NULL" in sql
    assert "LEGACY_RECOVERY_MERGE_MARKER_SOURCE.MERGED_INTO_USER_ID = USERS.ID" in sql
    assert "NOT (EXISTS" in sql
    assert sorted(compiled.params["id_1"]) == [2, 7]


def _operator_merge_conflicts(
    *,
    users: list[dict[str, object]],
    audits: list[dict[str, object]],
    participant_ids: set[int],
) -> set[int]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    merged_into_user_id INTEGER,
                    merged_at TEXT,
                    is_blocked BOOLEAN NOT NULL,
                    telegram_id INTEGER,
                    email TEXT,
                    current_subscription_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_merge_audit (
                    id INTEGER PRIMARY KEY,
                    source_user_id INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    dry_run BOOLEAN NOT NULL
                )
                """
            )
        )
        if users:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, merged_into_user_id, merged_at, is_blocked,
                        telegram_id, email, current_subscription_id
                    ) VALUES (
                        :id, :merged_into_user_id, :merged_at, :is_blocked,
                        :telegram_id, :email, :current_subscription_id
                    )
                    """
                ),
                users,
            )
        if audits:
            connection.execute(
                text(
                    """
                    INSERT INTO user_merge_audit (
                        id, source_user_id, target_user_id, dry_run
                    ) VALUES (:id, :source_user_id, :target_user_id, :dry_run)
                    """
                ),
                audits,
            )
        conflicts = connection.execute(
            ReferralDaoImpl._operator_recovery_merge_conflict_query(participant_ids)
        ).scalars()
        return set(conflicts)


def _merge_user(
    user_id: int,
    *,
    merged_into_user_id: int | None = None,
    canonical_source: bool = False,
) -> dict[str, object]:
    return {
        "id": user_id,
        "merged_into_user_id": merged_into_user_id,
        "merged_at": "2026-08-01T00:00:00+00:00" if merged_into_user_id is not None else None,
        "is_blocked": canonical_source,
        "telegram_id": None,
        "email": None,
        "current_subscription_id": None,
    }


@pytest.mark.parametrize(
    ("users", "audits", "expected"),
    [
        pytest.param([_merge_user(10)], [], set(), id="participant-without-merge"),
        pytest.param(
            [
                _merge_user(1, merged_into_user_id=10, canonical_source=True),
                _merge_user(2, merged_into_user_id=10, canonical_source=True),
                _merge_user(10),
            ],
            [
                {"id": 1, "source_user_id": 1, "target_user_id": 10, "dry_run": False},
                {"id": 2, "source_user_id": 2, "target_user_id": 10, "dry_run": False},
            ],
            set(),
            id="multiple-canonical-inbound",
        ),
        pytest.param(
            [
                _merge_user(10, merged_into_user_id=20, canonical_source=True),
                _merge_user(20),
            ],
            [{"id": 1, "source_user_id": 10, "target_user_id": 20, "dry_run": False}],
            {10},
            id="participant-outbound",
        ),
        pytest.param(
            [_merge_user(10)],
            [{"id": 1, "source_user_id": 999, "target_user_id": 10, "dry_run": False}],
            {10},
            id="missing-source-row",
        ),
        pytest.param(
            [
                _merge_user(1, merged_into_user_id=10, canonical_source=True),
                _merge_user(10),
            ],
            [],
            {10},
            id="missing-real-audit",
        ),
        pytest.param(
            [
                _merge_user(1, merged_into_user_id=20, canonical_source=True),
                _merge_user(10),
                _merge_user(20),
            ],
            [{"id": 1, "source_user_id": 1, "target_user_id": 10, "dry_run": False}],
            {10},
            id="inconsistent-source-target-marker",
        ),
    ],
)
def test_operator_recovery_merge_guard_semantics(
    users: list[dict[str, object]],
    audits: list[dict[str, object]],
    expected: set[int],
) -> None:
    assert _operator_merge_conflicts(
        users=users,
        audits=audits,
        participant_ids={10},
    ) == expected


@pytest.mark.asyncio
async def test_operator_recovery_rejects_noncanonical_merge_lineage() -> None:
    reward, source, origin = _recovery_entities()
    recovery = _operator_recovery(reward)
    session = _FullRecoverySession(
        [None, None, None, None, 901],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    with pytest.raises(ValueError, match="non-canonical user-merge history"):
        await dao.recover_legacy_extra_days_reward(recovery)

    assert session.added == []
    assert session.executed == []


def test_legacy_recovery_requires_exact_0052_shape_and_source_window() -> None:
    recovery = _recovery()
    reward, source, _ = _recovery_entities()

    ReferralDaoImpl._validate_0052_legacy_reward_shape(reward, recovery)  # type: ignore[arg-type]
    ReferralDaoImpl._validate_legacy_reward_source_window(  # type: ignore[arg-type]
        reward,
        source.fulfillment_completed_at,
    )

    # The legacy writer inserted the reward immediately before marking the
    # transaction fulfilled, so a small negative delta is valid evidence.
    reward.created_at = source.fulfillment_completed_at - timedelta(milliseconds=35)
    ReferralDaoImpl._validate_legacy_reward_source_window(  # type: ignore[arg-type]
        reward,
        source.fulfillment_completed_at,
    )

    reward.last_error = None
    with pytest.raises(ValueError, match="exact unresolved 0052"):
        ReferralDaoImpl._validate_0052_legacy_reward_shape(reward, recovery)  # type: ignore[arg-type]
    reward.last_error = "LEGACY_AMBIGUOUS_ISSUANCE"
    with pytest.raises(ValueError, match="exact unresolved 0052"):
        ReferralDaoImpl._validate_0052_legacy_reward_shape(  # type: ignore[arg-type]
            reward,
            replace(recovery, expected_version=2),
        )
    reward.created_at = source.fulfillment_completed_at + timedelta(minutes=5, seconds=1)
    with pytest.raises(ValueError, match="outside the proven fulfillment window"):
        ReferralDaoImpl._validate_legacy_reward_source_window(  # type: ignore[arg-type]
            reward,
            source.fulfillment_completed_at,
        )

    reward.created_at = source.fulfillment_completed_at - timedelta(minutes=5, seconds=1)
    with pytest.raises(ValueError, match="outside the proven fulfillment window"):
        ReferralDaoImpl._validate_legacy_reward_source_window(  # type: ignore[arg-type]
            reward,
            source.fulfillment_completed_at,
        )


def test_legacy_recovery_source_validation_is_action_specific() -> None:
    _, source, _ = _recovery_entities()

    ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
        source,
        LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING,
    )

    source.fulfillment_status = TransactionFulfillmentStatus.MANUAL_REQUIRED
    source.fulfillment_completed_at = None
    source.fulfillment_last_error = "LEGACY_COMPLETED_WITHOUT_PROOF"
    ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
        source,
        LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
    )
    assert ReferralDaoImpl._legacy_recovery_source_evidence_timestamp(source) == (
        "fulfillment_started_at",
        source.fulfillment_started_at,
    )

    source.updated_at = source.fulfillment_started_at + timedelta(days=90)
    assert ReferralDaoImpl._legacy_recovery_source_evidence_timestamp(source) == (
        "fulfillment_started_at",
        source.fulfillment_started_at,
    )

    with pytest.raises(ValueError, match="succeeded source"):
        ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
            source,
            LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING,
        )

    source.fulfillment_last_error = "DIFFERENT_LEGACY_ERROR"
    with pytest.raises(ValueError, match="exact legacy manual-required"):
        ReferralDaoImpl._validate_legacy_recovery_source(  # type: ignore[arg-type]
            source,
            LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
        )


@pytest.mark.asyncio
async def test_on_first_legacy_retry_rejects_non_new_source() -> None:
    recovery = _recovery()
    reward, source, origin = _recovery_entities()
    source.purchase_type = PurchaseType.RENEW
    session = _FullRecoverySession(
        [
            None,
            None,
            None,
            None,
            None,
            reward,
            source,
            origin,
            origin,
            None,
            None,
        ],
        reward=reward,
        source=source,
        origin=origin,
        participant_ids=[2, 7],
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    with pytest.raises(ValueError, match="requires a NEW purchase"):
        await dao.recover_legacy_extra_days_reward(recovery)

    assert session.added == []
    assert session.executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING,
        LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
    ],
)
async def test_legacy_recovery_exact_replay_is_strict_and_side_effect_free(
    action: LegacyReferralRewardRecoveryAction,
) -> None:
    recovery = _recovery(action)
    existing = SimpleNamespace(
        decision=action.value,
        selected_provenance={
            "request": ReferralDaoImpl._legacy_recovery_request_provenance(recovery)
        },
        operator_reference=recovery.operator_reference,
        resolved_by=recovery.resolved_by,
        reason=recovery.reason,
        evidence_sha256=recovery.evidence_sha256,
        allow_drift=False,
        selected_source_transaction_id=recovery.source_transaction_id,
        selected_origin_referral_id=recovery.origin_referral_id,
        selected_level=recovery.level,
        authorization_manifest_sha256=recovery.authorization_manifest_sha256,
    )
    session = _ResolutionSession([None, existing])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert not await dao.recover_legacy_extra_days_reward(recovery)
    assert session.added == []
    assert session.executed == []

    conflict_session = _ResolutionSession(
        [None, SimpleNamespace(**(existing.__dict__ | {"evidence_sha256": "b" * 64}))]
    )
    conflict_dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    conflict_dao.session = conflict_session  # type: ignore[assignment]
    with pytest.raises(ValueError, match="different provenance or evidence"):
        await conflict_dao.recover_legacy_extra_days_reward(recovery)


@pytest.mark.asyncio
async def test_legacy_recovery_rejects_another_resolution_incident() -> None:
    session = _ResolutionSession([None, None, 123])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    with pytest.raises(ValueError, match="another resolution incident"):
        await dao.recover_legacy_extra_days_reward(_recovery())

    assert session.added == []
    assert session.executed == []


def test_admin_compensation_transition_preserves_legacy_null_provenance() -> None:
    issued_at = datetime.now(timezone.utc)
    values = ReferralDaoImpl._legacy_recovery_transition_values(
        _recovery(LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED),
        source_transaction_id=77,
        origin_referral_id=101,
        issued_at=issued_at,
    )

    assert values["state"] == ReferralRewardState.ISSUED
    assert values["is_issued"] is True
    assert values["issued_at"] == issued_at
    for field in (
        "source_transaction_id",
        "origin_referral_id",
        "level",
        "accrual_strategy_snapshot",
        "accrual_strategy",
        "reward_strategy",
        "config_value",
    ):
        assert field not in values


def test_retry_transition_installs_exact_durable_provenance() -> None:
    recovery = _recovery()
    values = ReferralDaoImpl._legacy_recovery_transition_values(
        recovery,
        source_transaction_id=77,
        origin_referral_id=101,
        issued_at=None,
    )

    assert values["state"] == ReferralRewardState.PENDING
    assert values["is_issued"] is False
    assert values["source_transaction_id"] == 77
    assert values["origin_referral_id"] == 101
    assert values["level"] == ReferralLevel.FIRST
    assert values["accrual_strategy_snapshot"] == ReferralAccrualStrategy.ON_FIRST_PAYMENT
    assert values["accrual_strategy"] == ReferralAccrualStrategy.ON_FIRST_PAYMENT
    assert values["reward_strategy"] == ReferralRewardStrategy.AMOUNT
    assert values["config_value"] == 3


@pytest.mark.asyncio
async def test_admin_compensation_refund_ack_reuses_normalized_source_and_keeps_issued() -> None:
    detected_at = datetime.now(timezone.utc)
    reward = SimpleNamespace(
        state=ReferralRewardState.MANUAL_REQUIRED,
        manual_incident_version=2,
        type=ReferralRewardType.EXTRA_DAYS,
        is_issued=True,
        source_transaction_id=None,
        origin_referral_id=None,
        level=None,
        target_subscription_id=None,
        baseline_expire_at=None,
        target_expire_at=None,
        manual_cause="SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE",
        refund_detected_at=detected_at,
        accrual_strategy_snapshot=None,
        accrual_strategy=None,
    )
    admin_evidence = SimpleNamespace(
        selected_source_transaction_id=3987,
        selected_origin_referral_id=788,
        selected_level=ReferralLevel.FIRST,
        authorization_manifest_sha256="d" * 64,
    )
    session = _ResolutionSession(
        [
            reward,
            None,
            admin_evidence,
            TransactionStatus.REFUNDED,
        ]
    )
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.resolve_manual_reward(
        398,
        expected_version=2,
        confirm_issued=False,
        operator_reference="INC-REF-20260822/REFUND-RR-398",
        resolved_by="ADMIN_API",
        reason="Acknowledged later refund after independently proven OWNER coverage",
        source_status=TransactionStatus.REFUNDED,
        ack_admin_compensated_refund=True,
    )

    resolution = session.added[0]
    assert isinstance(resolution, ReferralRewardResolution)
    assert resolution.decision == "ACK_ADMIN_COMPENSATED_REFUND"
    assert resolution.source_status == TransactionStatus.REFUNDED.value
    assert resolution.selected_source_transaction_id == 3987
    assert resolution.selected_origin_referral_id == 788
    assert resolution.selected_level == ReferralLevel.FIRST
    assert resolution.authorization_manifest_sha256 == "d" * 64
    assert resolution.selected_provenance is None
    assert resolution.evidence_sha256 is None
    update_sql = str(
        session.executed[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert (
        ReferralRewardState.ISSUED
        in session.executed[0]
        .compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect()
        )
        .params.values()
    )
    assert "COALESCE" in update_sql


@pytest.mark.asyncio
async def test_admin_compensation_source_lock_uses_normalized_recovery_evidence() -> None:
    reward = SimpleNamespace(
        source_transaction_id=None,
        operator_recovery_manifest_sha256=None,
    )
    session = _ResolutionSession([reward, TransactionStatus.REFUNDED])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.lock_manual_reward_source_status(398) == TransactionStatus.REFUNDED

    fallback = session.scalar_statements[1].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(fallback).upper()
    assert "REFERRAL_REWARD_RESOLUTIONS" in sql
    assert "SELECTED_SOURCE_TRANSACTION_ID" in sql
    assert "FOR UPDATE OF TRANSACTIONS" in sql
    assert "CONFIRM_ADMIN_COMPENSATED" in fallback.params.values()


@pytest.mark.asyncio
async def test_manual_resolution_is_audited_idempotently_and_preserves_cause() -> None:
    reward = SimpleNamespace(
        state=ReferralRewardState.MANUAL_REQUIRED,
        manual_incident_version=1,
        accrual_strategy_snapshot=None,
        accrual_strategy=None,
    )
    session = _ResolutionSession([reward, None])
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.resolve_manual_reward(
        8,
        expected_version=1,
        confirm_issued=True,
        operator_reference="alice/TICKET-123",
        resolved_by="ADMIN_API",
        reason="Verified external target",
        source_status=TransactionStatus.REFUNDED,
    )

    resolution = session.added[0]
    assert isinstance(resolution, ReferralRewardResolution)
    assert resolution.decision == "CONFIRM_ISSUED"
    assert resolution.operator_reference == "alice/TICKET-123"
    assert resolution.incident_version == 1
    assert resolution.source_status == TransactionStatus.REFUNDED.value
    assert resolution.allow_drift is False
    update_sql = str(
        session.executed[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert "LAST_ERROR" not in update_sql
    assert "COALESCE" in update_sql

    existing = SimpleNamespace(
        decision="CONFIRM_ISSUED",
        operator_reference="alice/TICKET-123",
        resolved_by="ADMIN_API",
        reason="Verified external target",
        allow_drift=False,
    )
    replay_session = _ResolutionSession(
        [SimpleNamespace(state=ReferralRewardState.ISSUED), existing]
    )
    replay_dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    replay_dao.session = replay_session  # type: ignore[assignment]
    assert await replay_dao.resolve_manual_reward(
        8,
        expected_version=1,
        confirm_issued=True,
        operator_reference="alice/TICKET-123",
        resolved_by="ADMIN_API",
        reason="Verified external target",
        allow_drift=False,
    )
    assert replay_session.added == []
    assert replay_session.executed == []

    conflict_session = _ResolutionSession(
        [SimpleNamespace(state=ReferralRewardState.ISSUED), existing]
    )
    conflict_dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    conflict_dao.session = conflict_session  # type: ignore[assignment]
    assert not await conflict_dao.resolve_manual_reward(
        8,
        expected_version=1,
        confirm_issued=False,
        operator_reference="bob/TICKET-999",
        resolved_by="ADMIN_API",
        reason="Different decision",
    )

    cancel_session = _ResolutionSession(
        [
            SimpleNamespace(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=1,
                accrual_strategy_snapshot=None,
                accrual_strategy=None,
            ),
            None,
        ]
    )
    cancel_dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    cancel_dao.session = cancel_session  # type: ignore[assignment]
    assert await cancel_dao.resolve_manual_reward(
        9,
        expected_version=1,
        confirm_issued=False,
        operator_reference="alice/TICKET-124",
        resolved_by="ADMIN_API",
        reason="Verified rollback",
    )
    cancel_sql = str(
        cancel_session.executed[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    ).upper()
    assert "ISSUED_AT" not in cancel_sql
