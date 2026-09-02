import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from remnapy import RemnawaveSDK

from src.application.dto import RemnaSubscriptionDto
from src.application.use_cases.remnawave.commands.synchronization import (
    SyncRemnaUser,
    SyncRemnaUserDto,
)
from src.application.use_cases.subscription.commands.management import (
    AddSubscriptionDuration,
    AddSubscriptionDurationDto,
)
from src.application.use_cases.subscription.commands.set_plan import (
    SetUserSubscription,
    SetUserSubscriptionDto,
)
from src.core.enums import Role
from src.infrastructure.services.remnawave import RemnawaveImpl


class _UnitOfWork:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> "_UnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _MutationLock:
    def __init__(self) -> None:
        self.user_ids: list[int] = []

    def hold(self, user_id: int) -> "_MutationLock":
        self.user_ids.append(user_id)
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.ADMIN, Role.DEV, Role.OWNER])
async def test_legacy_recovery_gate_pauses_manual_duration_changes(role: Role) -> None:
    use_case = AddSubscriptionDuration(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        _MutationLock(),  # type: ignore[arg-type]
        SimpleNamespace(referral_reward_legacy_recovery_enabled=True),
    )

    with pytest.raises(ValueError, match="paused during legacy referral recovery"):
        await use_case._execute(  # type: ignore[arg-type]
            SimpleNamespace(role=role),
            AddSubscriptionDurationDto(user_id=7, days=14),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.ADMIN, Role.DEV, Role.OWNER])
async def test_legacy_recovery_gate_pauses_manual_subscription_replacement(
    role: Role,
) -> None:
    use_case = SetUserSubscription(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        _MutationLock(),  # type: ignore[arg-type]
        SimpleNamespace(referral_reward_legacy_recovery_enabled=True),
    )

    with pytest.raises(ValueError, match="paused during legacy referral recovery"):
        await use_case._execute(  # type: ignore[arg-type]
            SimpleNamespace(role=role),
            SetUserSubscriptionDto(user_id=7, plan_id=3, duration=30),
        )


@pytest.mark.asyncio
async def test_panel_sync_always_uses_fenced_snapshot_with_equal_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_id = UUID("00000000-0000-0000-0000-000000000042")
    old_time = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    stale = SimpleNamespace(
        uuid=remote_id,
        telegram_id=42,
        updated_at=old_time,
        expire_at=old_time + timedelta(days=10),
    )
    latest = SimpleNamespace(
        uuid=remote_id,
        telegram_id=42,
        updated_at=old_time,
        expire_at=old_time + timedelta(days=30),
    )
    local_subscription = SimpleNamespace(
        expire_at=stale.expire_at,
        changed_data={},
    )
    user = SimpleNamespace(id=7, log="user", remna_name="user")

    monkeypatch.setattr(
        RemnaSubscriptionDto,
        "from_remna_user",
        classmethod(lambda cls, value: SimpleNamespace(expire_at=value.expire_at)),
    )

    def apply_sync(target: SimpleNamespace, source: SimpleNamespace) -> SimpleNamespace:
        target.expire_at = source.expire_at
        target.changed_data = {"expire_at": source.expire_at}
        return target

    remnawave = SimpleNamespace(
        get_user_by_uuid=AsyncMock(return_value=latest),
        apply_sync=Mock(side_effect=apply_sync),
    )
    subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=local_subscription),
        update=AsyncMock(),
    )
    lock = _MutationLock()
    use_case = SyncRemnaUser(
        _UnitOfWork(),  # type: ignore[arg-type]
        SimpleNamespace(
            get_by_remna_uuid=AsyncMock(return_value=user),
            get_by_telegram_id=AsyncMock(),
        ),
        subscription_dao,
        SimpleNamespace(default_locale="ru"),
        remnawave,
        SimpleNamespace(),
        lock,  # type: ignore[arg-type]
    )

    changed = await use_case._execute(  # type: ignore[arg-type]
        SimpleNamespace(log="system"),
        SyncRemnaUserDto(remna_user=stale, creating=False),
    )

    assert changed is True
    assert lock.user_ids == [7]
    assert local_subscription.expire_at == latest.expire_at
    remnawave.apply_sync.assert_called_once()
    assert remnawave.apply_sync.call_args.args[1].expire_at == latest.expire_at


@pytest.mark.asyncio
async def test_remnawave_full_update_has_lower_level_mutation_fence() -> None:
    lock = _MutationLock()
    response = SimpleNamespace(username="user", uuid=UUID(int=42), telegram_id=42)
    sdk = SimpleNamespace(users=SimpleNamespace(update_user=AsyncMock(return_value=response)))
    remnawave = RemnawaveImpl(sdk, lock)  # type: ignore[arg-type]
    remnawave._build_update_request = Mock(return_value=SimpleNamespace(username="user"))  # type: ignore[method-assign]

    result = await remnawave.update_user(  # type: ignore[arg-type]
        user=SimpleNamespace(id=7),
        uuid=UUID(int=42),
        subscription=SimpleNamespace(),
    )

    assert result is response
    assert lock.user_ids == [7]


@pytest.mark.asyncio
async def test_referral_expiry_update_serializes_only_uuid_status_and_expiry() -> None:
    lock = _MutationLock()
    remote_id = UUID("00000000-0000-0000-0000-000000000042")
    expire_at = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    response = SimpleNamespace(username="user", uuid=remote_id, telegram_id=42)
    sdk = SimpleNamespace(users=SimpleNamespace(update_user=AsyncMock(return_value=response)))
    remnawave = RemnawaveImpl(sdk, lock)  # type: ignore[arg-type]

    result = await remnawave.reactivate_referral_expiry(
        user_id=7,
        uuid=remote_id,
        expire_at=expire_at,
    )

    request = sdk.users.update_user.await_args.args[0]
    assert request.model_fields_set == {"uuid", "expire_at", "status"}
    assert request.model_dump(exclude_unset=True, by_alias=True, mode="json") == {
        "uuid": str(remote_id),
        "status": "ACTIVE",
        "expireAt": "2026-09-01T12:30:00Z",
    }
    assert result is response
    assert lock.user_ids == [7]


@pytest.mark.asyncio
async def test_referral_expiry_update_sends_only_uuid_status_and_expiry_on_wire() -> None:
    remote_id = UUID("00000000-0000-0000-0000-000000000042")
    expire_at = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "uuid": str(remote_id),
                "id": 42,
                "shortUuid": "short-uuid",
                "username": "user",
                "status": "ACTIVE",
                "expireAt": "2026-09-01T12:30:00Z",
                "trojanPassword": "trojan-password",
                "vlessUuid": str(remote_id),
                "ssPassword": "ss-password",
                "createdAt": "2026-08-01T00:00:00Z",
                "updatedAt": "2026-09-01T12:30:00Z",
                "subscriptionUrl": "https://subscription.example/user",
                "activeInternalSquads": [],
                "userTraffic": {
                    "usedTrafficBytes": 0,
                    "lifetimeUsedTrafficBytes": 0,
                },
            },
        )

    async with httpx.AsyncClient(
        base_url="https://panel.example/api",
        transport=httpx.MockTransport(handler),
    ) as client:
        remnawave = RemnawaveImpl(RemnawaveSDK(client=client), _MutationLock())

        result = await remnawave.reactivate_referral_expiry(
            user_id=7,
            uuid=remote_id,
            expire_at=expire_at,
        )

    assert result.uuid == remote_id
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/users"
    assert json.loads(request.content) == {
        "uuid": str(remote_id),
        "status": "ACTIVE",
        "expireAt": "2026-09-01T12:30:00Z",
    }
