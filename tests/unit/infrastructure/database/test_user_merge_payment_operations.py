from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from src.application.common.dao.user_merge import (
    EmailConflictResolution,
    PaymentConflictResolution,
    TelegramConflictResolution,
    UserMergePaymentOperationConflictError,
    UserMergeReferralAttributionConflictError,
    UserMergeTargetConflictError,
)
from src.infrastructure.database.dao.user_merge import UserMergeDaoImpl


def _user(user_id: int, *, merged_into_user_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email=None,
        telegram_id=None,
        is_email_verified=False,
        current_subscription_id=None,
        merged_into_user_id=merged_into_user_id,
    )


def test_identity_resolution_only_suppresses_explicitly_confirmed_conflicts() -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    source = _user(11)
    target = _user(22)
    source.email = "source@example.com"
    target.email = "target@example.com"
    source.telegram_id = 111
    target.telegram_id = 222

    assert dao._validate(source, target) == [
        "Both users have different emails",
        "Both users have different Telegram accounts",
    ]
    assert (
        dao._validate(
            source,
            target,
            email_resolution=EmailConflictResolution.KEEP_TARGET,
            telegram_resolution=TelegramConflictResolution.KEEP_SOURCE,
        )
        == []
    )


@pytest.mark.parametrize(
    (
        "source_email",
        "source_verified",
        "target_email",
        "target_verified",
        "expected",
    ),
    [
        (
            "source@example.com",
            True,
            "target@example.com",
            False,
            ("target@example.com", False),
        ),
        (
            "source@example.com",
            True,
            None,
            False,
            ("source@example.com", True),
        ),
        (
            "same@example.com",
            True,
            "same@example.com",
            False,
            ("same@example.com", True),
        ),
        (
            "source@example.com",
            False,
            "target@example.com",
            True,
            ("target@example.com", True),
        ),
    ],
)
def test_merge_email_verification_follows_the_selected_address(
    source_email: str | None,
    source_verified: bool,
    target_email: str | None,
    target_verified: bool,
    expected: tuple[str | None, bool],
) -> None:
    assert UserMergeDaoImpl._resolve_merged_email_identity(
        source_email=source_email,
        source_verified=source_verified,
        target_email=target_email,
        target_verified=target_verified,
    ) == expected


def test_payment_resolution_preserves_colliding_operations_without_hiding_subscriptions() -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    source = _user(11)
    target = _user(22)

    assert dao._validate(source, target, payment_operation_duplicates=1) == [
        "Payment idempotency key collision between source and target (1)"
    ]
    assert (
        dao._validate(
            source,
            target,
            payment_operation_duplicates=1,
            payment_resolution=PaymentConflictResolution.REKEY_SOURCE,
        )
        == []
    )

    source.current_subscription_id = 101
    target.current_subscription_id = 202
    assert dao._validate(
        source,
        target,
        payment_operation_duplicates=1,
        payment_resolution=PaymentConflictResolution.REKEY_SOURCE,
    ) == ["Both users have current subscriptions"]


def test_two_current_subscriptions_remain_blocking_with_identity_resolution() -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    source = _user(11)
    target = _user(22)
    source.email = "source@example.com"
    target.email = "target@example.com"
    source.current_subscription_id = 101
    target.current_subscription_id = 202

    assert dao._validate(
        source,
        target,
        email_resolution=EmailConflictResolution.KEEP_TARGET,
        telegram_resolution=TelegramConflictResolution.KEEP_SOURCE,
    ) == ["Both users have current subscriptions"]


@pytest.mark.asyncio
async def test_plan_reports_payment_operation_identity_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    moved = {
        "payment_operations": 2,
        "payment_operation_duplicates": 1,
    }
    monkeypatch.setattr(dao, "_lock_users", AsyncMock(return_value=(_user(11), _user(22))))
    monkeypatch.setattr(dao, "_normalize_stale_payment_work", AsyncMock())
    monkeypatch.setattr(dao, "_lock_nonterminal_referral_rewards", AsyncMock())
    monkeypatch.setattr(dao, "_collect_moved_counts", AsyncMock(return_value=moved))

    plan = await dao.plan(11, 22)

    assert plan.moved == moved
    assert plan.conflicts == ["Payment idempotency key collision between source and target (1)"]


@pytest.mark.asyncio
async def test_replaying_merge_to_same_target_returns_original_stable_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_moved = {
        "subscriptions": 2,
        "transactions": 4,
        "payment_operations": 1,
    }
    session = SimpleNamespace(
        scalar=AsyncMock(return_value={**original_moved, "invalid": True}),
        add=Mock(),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    normalize = AsyncMock()
    collect = AsyncMock()
    monkeypatch.setattr(
        dao,
        "_lock_users",
        AsyncMock(return_value=(_user(11, merged_into_user_id=22), _user(22))),
    )
    monkeypatch.setattr(dao, "_normalize_stale_payment_work", normalize)
    monkeypatch.setattr(dao, "_collect_moved_counts", collect)

    first = await dao.plan(11, 22)
    second = await dao.plan(11, 22)

    assert first == second
    assert first.moved == original_moved
    assert first.conflicts == []
    assert first.target.id == 22
    normalize.assert_not_awaited()
    collect.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_replaying_merge_to_same_target_is_a_write_free_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        scalar=AsyncMock(return_value={"subscriptions": 2}),
        add=Mock(),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    normalize = AsyncMock()
    merge_records = AsyncMock()
    monkeypatch.setattr(
        dao,
        "_lock_users",
        AsyncMock(return_value=(_user(11, merged_into_user_id=22), _user(22))),
    )
    monkeypatch.setattr(dao, "_normalize_stale_payment_work", normalize)
    monkeypatch.setattr(dao, "_merge_records", merge_records)

    result = await dao.merge(
        actor=SimpleNamespace(),  # type: ignore[arg-type]
        source_user_id=11,
        target_user_id=22,
        reason="request retry",
    )

    assert result.moved == {"subscriptions": 2}
    normalize.assert_not_awaited()
    merge_records.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_already_merged_source_cannot_be_redirected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(scalar=AsyncMock(), add=Mock())
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(
        dao,
        "_lock_users",
        AsyncMock(return_value=(_user(11, merged_into_user_id=33), _user(22))),
    )

    with pytest.raises(
        UserMergeTargetConflictError,
        match=r"already merged into user '33'.*cannot be redirected.*'22'",
    ):
        await dao.plan(11, 22)

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_merge_rejects_noncanonical_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        dao,
        "_lock_users",
        AsyncMock(return_value=(_user(11), _user(22, merged_into_user_id=33))),
    )

    with pytest.raises(
        UserMergeTargetConflictError,
        match=r"Target user '22'.*already merged into user '33'",
    ):
        await dao.plan(11, 22)


class UpdateSession:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statements: list[object] = []

    async def execute(self, statement: object) -> SimpleNamespace:
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self.rowcount)


class MergeSession:
    def __init__(self, source: SimpleNamespace) -> None:
        self.source = source
        self.merged_owner_at_flush: list[int | None] = []

    async def flush(self) -> None:
        self.merged_owner_at_flush.append(self.source.merged_into_user_id)


@pytest.mark.asyncio
async def test_payment_operations_transfer_in_one_atomic_update() -> None:
    session = UpdateSession(rowcount=3)
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    moved = {"payment_operations": 99}

    await dao._move_payment_operations(11, 22, moved)

    assert moved["payment_operations"] == 3
    assert len(session.statements) == 1
    sql = str(
        session.statements[0].compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "UPDATE PAYMENT_OPERATIONS SET USER_ID=22" in sql
    assert "PAYMENT_OPERATIONS.USER_ID = 11" in sql
    assert "JSONB_SET" in sql
    assert "ARRAY['USER_ID']" in sql
    assert "TO_JSONB(22)" in sql


@pytest.mark.asyncio
async def test_merge_moves_payment_operations_before_marking_source_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SimpleNamespace(
        id=11,
        email="source@example.com",
        pending_email="pending@example.com",
        email_verification_code_hash="verification",
        email_verification_expires_at=None,
        password_reset_code_hash="reset",
        password_reset_expires_at=None,
        password_hash="password",
        is_email_verified=True,
        subscription_expiration_email_enabled=True,
        subscription_expiration_email_enabled_at=datetime.now(timezone.utc),
        telegram_id=111,
        username="source_telegram",
        name="Source Telegram",
        language="ru",
        personal_discount=15,
        purchase_discount=5,
        points=40,
        is_bot_blocked=True,
        is_rules_accepted=True,
        is_trial_available=False,
        ad_link_id=17,
        current_subscription_id=101,
        token_version=0,
        is_blocked=False,
        merged_into_user_id=None,
        merged_at=None,
    )
    target = SimpleNamespace(
        id=22,
        email="target@example.com",
        pending_email=None,
        email_verification_code_hash=None,
        email_verification_expires_at=None,
        password_reset_code_hash=None,
        password_reset_expires_at=None,
        password_hash=None,
        is_email_verified=False,
        subscription_expiration_email_enabled=False,
        subscription_expiration_email_enabled_at=None,
        telegram_id=222,
        username="target_web",
        name="Target Web",
        language="en",
        personal_discount=10,
        purchase_discount=20,
        points=2,
        is_bot_blocked=False,
        is_rules_accepted=False,
        is_trial_available=True,
        ad_link_id=None,
        current_subscription_id=None,
        token_version=0,
    )
    session = MergeSession(source)
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    transfer_states: list[int | None] = []

    async def move_payment_operations(
        source_user_id: int,
        target_user_id: int,
        moved: dict[str, int],
    ) -> None:
        assert (source_user_id, target_user_id) == (11, 22)
        transfer_states.append(source.merged_into_user_id)
        moved["payment_operations"] = 2

    monkeypatch.setattr(dao, "_move_simple_fk", AsyncMock(return_value=0))
    monkeypatch.setattr(dao, "_move_payment_operations", move_payment_operations)
    monkeypatch.setattr(dao, "_move_referrals", AsyncMock())
    monkeypatch.setattr(dao, "_move_promocode_activations", AsyncMock())
    monkeypatch.setattr(dao, "_move_oauth_providers", AsyncMock())
    moved = {"payment_operations": 2}

    await dao._merge_records(
        source,
        target,
        moved,
        email_resolution=EmailConflictResolution.KEEP_TARGET,
        telegram_resolution=TelegramConflictResolution.KEEP_SOURCE,
    )  # type: ignore[arg-type]

    assert transfer_states == [None]
    assert session.merged_owner_at_flush == [None, 22]
    assert source.merged_into_user_id == 22
    assert source.points == 0
    assert source.personal_discount == 0
    assert source.purchase_discount == 0
    assert source.is_trial_available is False
    assert source.ad_link_id is None
    assert source.subscription_expiration_email_enabled is False
    assert source.subscription_expiration_email_enabled_at is None
    assert target.email == "target@example.com"
    assert target.is_email_verified is False
    assert target.subscription_expiration_email_enabled is False
    assert target.subscription_expiration_email_enabled_at is None
    assert target.telegram_id == 111
    assert target.username == "source_telegram"
    assert target.name == "Source Telegram"
    assert target.language == "ru"
    assert target.is_bot_blocked is True
    assert target.points == 42
    assert target.personal_discount == 15
    assert target.purchase_discount == 20
    assert target.is_rules_accepted is True
    assert target.is_trial_available is False
    assert target.ad_link_id == 17


@pytest.mark.asyncio
async def test_merge_recheck_fails_closed_on_payment_operation_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    count_duplicates = AsyncMock(return_value=2)
    monkeypatch.setattr(dao, "_count_payment_operation_duplicates", count_duplicates)

    with pytest.raises(
        UserMergePaymentOperationConflictError,
        match=r"Payment idempotency key collision.*\(2\)",
    ):
        await dao._assert_no_payment_operation_collisions(11, 22)

    count_duplicates.assert_awaited_once_with(11, 22)


class ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


@pytest.mark.asyncio
async def test_user_merge_locks_referral_graph_before_user_rows() -> None:
    events: list[str] = []

    async def execute(statement: object) -> None:
        events.append("graph")

    async def scalars(statement: object) -> ScalarResult:
        events.append("users")
        return ScalarResult([_user(11), _user(22)])

    session = SimpleNamespace(execute=execute, scalars=scalars)
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]

    source, target = await dao._lock_users(11, 22)

    assert (source.id, target.id) == (11, 22)
    assert events == ["graph", "users"]


@pytest.mark.asyncio
async def test_rekey_source_payment_collision_is_deterministic_and_preserves_row() -> None:
    operation = SimpleNamespace(id=7, idempotency_key="shared-key")
    session = SimpleNamespace(
        scalars=AsyncMock(
            side_effect=[
                ScalarResult([operation]),
                ScalarResult(["shared-key", "occupied-key"]),
            ]
        ),
        flush=AsyncMock(),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]

    await dao._rekey_source_payment_operation_collisions(11, 22)
    first_key = operation.idempotency_key

    assert first_key.startswith("merged-11-7-")
    assert len(first_key) <= 128
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_referral_conflict_allows_shared_referrer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[7, 7]))
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    connected = AsyncMock(return_value=False)
    monkeypatch.setattr(dao, "_referral_accounts_connected", connected)

    assert await dao._count_referral_reward_attribution_conflicts(11, 22) == 0
    connected.assert_awaited_once_with(11, 22)


@pytest.mark.asyncio
async def test_referral_conflict_rejects_different_referrers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[7, 8]))
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=False))

    assert await dao._count_referral_reward_attribution_conflicts(11, 22) == 1


@pytest.mark.asyncio
async def test_referral_conflict_rejects_transitive_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[None, None]))
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=True))

    assert await dao._count_referral_reward_attribution_conflicts(11, 22) == 1


@pytest.mark.asyncio
async def test_referral_move_rejects_connected_accounts_before_any_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        scalar=AsyncMock(),
        execute=AsyncMock(),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=True))

    with pytest.raises(
        UserMergeReferralAttributionConflictError,
        match="referral cycle",
    ):
        await dao._move_referrals(11, 22, {})

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_merge_rejects_pending_reward_before_transaction_owner_can_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = UserMergeDaoImpl(SimpleNamespace())  # type: ignore[arg-type]
    count_nonterminal = AsyncMock(return_value=1)
    monkeypatch.setattr(dao, "_count", count_nonterminal)

    with pytest.raises(
        UserMergeReferralAttributionConflictError,
        match="nonterminal referral rewards",
    ):
        # This fail-closed guard covers a source PENDING ON_FIRST intent even if
        # target already owns an older paid transaction. Transaction.user_id can
        # therefore never change underneath the eligibility query.
        await dao._assert_no_active_referral_reward_work(11, 22)

    predicate = count_nonterminal.await_args.args[1]
    predicate_sql = str(
        predicate.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "NOT IN ('ISSUED', 'SUPERSEDED')" in predicate_sql


@pytest.mark.asyncio
async def test_merge_reassigns_terminal_reward_history_without_deleting_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[None, None]),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=False))

    await dao._move_referrals(11, 22, {})

    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).upper()
        for call in session.execute.await_args_list
    ]
    reward_update = next(sql for sql in statements if "UPDATE REFERRAL_REWARDS" in sql)
    assert "SET USER_ID=22" in reward_update
    assert "REFERRAL_REWARDS.USER_ID = 11" in reward_update
    assert "DELETE" not in "\n".join(statements)


@pytest.mark.asyncio
@pytest.mark.parametrize(("source_user_id", "target_user_id"), [(11, 22), (22, 11)])
async def test_merge_keeps_shared_referrer_history_without_duplicate_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    source_user_id: int,
    target_user_id: int,
) -> None:
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[7, 7]),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=False))

    await dao._move_referrals(source_user_id, target_user_id, {})

    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).upper()
        for call in session.execute.await_args_list
    ]
    assert len(statements) == 2
    assert any(f"SET REFERRER_ID={target_user_id}" in sql for sql in statements)
    assert any("UPDATE REFERRAL_REWARDS" in sql for sql in statements)
    assert all(f"SET REFERRED_ID={target_user_id}" not in sql for sql in statements)


@pytest.mark.asyncio
async def test_merge_rejects_different_referrers_before_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[7, 8]),
        execute=AsyncMock(),
    )
    dao = UserMergeDaoImpl(session)  # type: ignore[arg-type]
    monkeypatch.setattr(dao, "_referral_accounts_connected", AsyncMock(return_value=False))

    with pytest.raises(
        UserMergeReferralAttributionConflictError,
        match="different referral attribution",
    ):
        await dao._move_referrals(11, 22, {})

    session.execute.assert_not_awaited()
