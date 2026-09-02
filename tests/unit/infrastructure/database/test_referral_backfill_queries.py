from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from src.core.enums import TransactionFulfillmentStatus, TransactionStatus
from src.infrastructure.database.dao.referral import ReferralDaoImpl
from src.infrastructure.database.dao.transaction import TransactionDaoImpl


class _Scalars:
    def all(self) -> list[object]:
        return []


class _TransactionSession:
    def __init__(self) -> None:
        self.executed_statements: list[object] = []
        self.scalar_statements: list[object] = []
        self.scalars_statements: list[object] = []

    async def execute(self, statement: object) -> SimpleNamespace:
        self.executed_statements.append(statement)
        return SimpleNamespace(rowcount=1)

    async def scalar(self, statement: object) -> None:
        self.scalar_statements.append(statement)

    async def scalars(self, statement: object) -> _Scalars:
        self.scalars_statements.append(statement)
        return _Scalars()


def _compiled(statement: object) -> tuple[str, dict[str, object]]:
    result = statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    return " ".join(str(result).upper().split()), result.params


def _flat_values(params: dict[str, object]) -> list[object]:
    values: list[object] = []
    for value in params.values():
        values.extend(value if isinstance(value, list) else [value])
    return values


@pytest.mark.asyncio
async def test_historical_inventory_selects_only_successful_paid_nontrial_sources() -> None:
    session = _TransactionSession()
    dao = TransactionDaoImpl.__new__(TransactionDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_dto_list = lambda rows: rows  # type: ignore[method-assign]

    await dao.list_historical_referral_reward_sources(limit=25, offset=50)

    sql, params = _compiled(session.scalars_statements[0])
    values = _flat_values(params)
    assert "TRANSACTIONS.STATUS IN" in sql
    assert TransactionStatus.COMPLETED in values
    assert TransactionStatus.REFUNDED not in values
    assert "FULFILLMENT_STATUS" in sql
    assert TransactionFulfillmentStatus.SUCCEEDED in values
    assert "IS_TEST IS FALSE" in sql
    assert "final_amount" in values
    assert "CAST" in sql and ">" in sql
    assert "is_trial" in values
    assert "false" in values
    where_sql = sql.split(" WHERE ", 1)[1].split(" ORDER BY", 1)[0]
    assert "PURCHASE_TYPE" not in where_sql
    assert "ORDER BY TRANSACTIONS.FULFILLMENT_COMPLETED_AT, TRANSACTIONS.ID" in sql


@pytest.mark.asyncio
async def test_explicit_backfill_sources_are_row_locked_and_revalidated() -> None:
    session = _TransactionSession()
    dao = TransactionDaoImpl.__new__(TransactionDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_dto_list = lambda rows: rows  # type: ignore[method-assign]

    await dao.get_historical_referral_reward_sources([91, 77, 91], for_update=True)

    sql, params = _compiled(session.scalars_statements[0])
    values = _flat_values(params)
    assert "TRANSACTIONS.ID IN" in sql
    assert params[next(key for key in params if key.startswith("id_1"))] == [77, 91]
    assert "FOR UPDATE" in sql
    assert TransactionStatus.COMPLETED in values
    assert TransactionStatus.REFUNDED not in values


@pytest.mark.asyncio
async def test_first_paid_history_excludes_trial_but_includes_refunded_first_purchase() -> None:
    session = _TransactionSession()
    dao = TransactionDaoImpl.__new__(TransactionDaoImpl)
    dao.session = session  # type: ignore[assignment]

    await dao.get_first_successful_paid_transaction_id(9)

    sql, params = _compiled(session.scalar_statements[0])
    values = _flat_values(params)
    assert TransactionStatus.COMPLETED in values
    assert TransactionStatus.REFUNDED in values
    assert "final_amount" in values
    assert "is_trial" in values
    assert "false" in values
    assert TransactionFulfillmentStatus.SUCCEEDED in values
    assert TransactionFulfillmentStatus.MANUAL_REQUIRED in values
    assert "LEGACY_COMPLETED_WITHOUT_PROOF" in values
    assert "FULFILLMENT_STARTED_AT IS NOT NULL" in sql
    assert "FULFILLMENT_TOKEN_HASH IS NULL" in sql
    assert "FULFILLMENT_LEASE_EXPIRES_AT IS NULL" in sql
    where_sql = sql.split(" WHERE ", 1)[1].split(" ORDER BY", 1)[0]
    assert "PURCHASE_TYPE" not in where_sql
    assert "ORDER BY CASE" in sql
    assert "TRANSACTIONS.FULFILLMENT_STARTED_AT" in sql
    assert "TRANSACTIONS.UPDATED_AT" not in sql


@pytest.mark.asyncio
async def test_refund_preserves_exact_0049_legacy_provenance_marker() -> None:
    session = _TransactionSession()
    dao = TransactionDaoImpl.__new__(TransactionDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert await dao.mark_refund_manual_required(UUID(int=42))

    sql, params = _compiled(session.executed_statements[0])
    values = _flat_values(params)
    assert "UPDATE TRANSACTIONS" in sql
    assert "CASE WHEN" in sql
    assert "FULFILLMENT_STATUS" in sql
    assert TransactionFulfillmentStatus.MANUAL_REQUIRED in values
    assert "LEGACY_COMPLETED_WITHOUT_PROOF" in values
    assert "REFUND_DURING_UNPROVEN_FULFILLMENT" in values
    assert "FULFILLMENT_STARTED_AT IS NOT NULL" in sql
    assert "FULFILLMENT_TOKEN_HASH IS NULL" in sql
    assert "FULFILLMENT_LEASE_EXPIRES_AT IS NULL" in sql
    assert TransactionStatus.REFUNDED in values


@pytest.mark.asyncio
async def test_legacy_ambiguity_fence_includes_issued_and_unissued_rows() -> None:
    class _ReferralSession:
        def __init__(self) -> None:
            self.statement: object | None = None

        async def scalar(self, statement: object) -> None:
            self.statement = statement

    session = _ReferralSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]

    assert not await dao.has_legacy_ambiguous_reward(
        referral_ids=[101, 202],
        recipient_user_ids=[2, 3],
    )

    sql, _ = _compiled(session.statement)
    assert "SOURCE_TRANSACTION_ID IS NULL" in sql
    assert "REFERRAL_ID IN" in sql
    assert "USER_ID IN" in sql
    assert "IS_ISSUED" not in sql
    assert "STATE" not in sql


@pytest.mark.asyncio
async def test_partial_chain_check_loads_full_durable_reward_snapshots() -> None:
    session = _TransactionSession()
    dao = ReferralDaoImpl.__new__(ReferralDaoImpl)
    dao.session = session  # type: ignore[assignment]
    dao._convert_to_reward_list = lambda rows: rows  # type: ignore[method-assign]

    assert await dao.get_rewards_by_source_transaction(77) == []

    sql, params = _compiled(session.scalars_statements[0])
    assert "SELECT REFERRAL_REWARDS.ID" in sql
    assert "REFERRAL_REWARDS.ACCRUAL_STRATEGY_SNAPSHOT" in sql
    assert "REFERRAL_REWARDS.REWARD_STRATEGY" in sql
    assert "REFERRAL_REWARDS.CONFIG_VALUE" in sql
    assert "REFERRAL_REWARDS.SOURCE_TRANSACTION_ID" in sql
    assert 77 in params.values()
    assert "ORDER BY REFERRAL_REWARDS.LEVEL, REFERRAL_REWARDS.ID" in sql
