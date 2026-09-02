from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.application.dto import SettingsDto
from src.core.enums import Currency
from src.infrastructure.database.dao.settings import SettingsDaoImpl


class _RedisWithoutCachedSettings:
    def __init__(self) -> None:
        self.get = AsyncMock(side_effect=AssertionError("lock-read must bypass Redis"))
        self.setex = AsyncMock(side_effect=AssertionError("lock-read must bypass Redis"))
        self.delete = AsyncMock()

    async def scan_iter(self, *, match: str) -> object:
        if False:
            yield match


def _dao_with_scalar_result(result: object) -> tuple[SettingsDaoImpl, MagicMock]:
    dao = object.__new__(SettingsDaoImpl)
    session = MagicMock()
    session.scalar = AsyncMock(return_value=result)
    dao.session = session
    dao.redis = _RedisWithoutCachedSettings()  # type: ignore[assignment]
    dao.retort = object()  # type: ignore[assignment]
    dao._convert_to_dto = lambda row: row  # type: ignore[method-assign]
    return dao, session


@pytest.mark.asyncio
async def test_get_for_update_bypasses_redis_and_refreshes_locked_settings_row() -> None:
    db_settings = SimpleNamespace(id=1)
    dao, session = _dao_with_scalar_result(db_settings)

    result = await dao.get_for_update()

    assert result is db_settings
    dao.redis.get.assert_not_awaited()
    dao.redis.setex.assert_not_awaited()
    statement = session.scalar.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).upper().split())
    assert "FROM SETTINGS" in sql
    assert "FOR UPDATE" in sql
    assert "NOWAIT" not in sql
    assert "SKIP LOCKED" not in sql
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
async def test_get_for_update_fails_loudly_when_settings_row_is_missing() -> None:
    dao, _ = _dao_with_scalar_result(None)

    with pytest.raises(RuntimeError, match="Settings row is missing"):
        await dao.get_for_update()

    dao.redis.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_settings_update_targets_same_row_and_uses_blocking_update() -> None:
    db_settings = SimpleNamespace(id=7)
    dao, session = _dao_with_scalar_result(db_settings)
    settings = SettingsDto(id=7)
    settings.default_currency = Currency.RUB
    dao._serialize_for_update = lambda *args: {  # type: ignore[method-assign]
        "default_currency": Currency.RUB
    }

    result = await dao.update(settings)

    assert result is db_settings
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).upper().split())
    assert "UPDATE SETTINGS SET DEFAULT_CURRENCY=" in sql
    assert "WHERE SETTINGS.ID =" in sql
    assert 7 in compiled.params.values()
    assert "NOWAIT" not in sql
    assert "SKIP LOCKED" not in sql
    # PostgreSQL UPDATE takes a conflicting row lock on this same primary-key row;
    # without a non-blocking modifier it naturally waits for get_for_update's lock.
