from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from src.infrastructure.database.dao.user import UserDaoImpl

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _dao() -> tuple[UserDaoImpl, SimpleNamespace]:
    session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(id=17)))
    conversion = SimpleNamespace(get_converter=lambda *args: lambda value: value)
    dao = UserDaoImpl(
        session,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        conversion,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    return dao, session


def _sql(session: SimpleNamespace) -> str:
    statement = session.scalar.await_args.args[0]
    return str(statement.compile(dialect=postgresql.dialect())).upper()


async def test_enable_is_an_atomic_current_row_eligibility_update() -> None:
    dao, session = _dao()

    await dao.set_subscription_expiration_email_preference(
        17,
        enabled=True,
    )

    sql = _sql(session)
    assert "USERS.ID =" in sql
    assert "USERS.EMAIL IS NOT NULL" in sql
    assert "USERS.IS_EMAIL_VERIFIED IS TRUE" in sql
    assert "USERS.IS_BLOCKED IS FALSE" in sql
    assert "USERS.MERGED_INTO_USER_ID IS NULL" in sql
    assert "CASE WHEN (USERS.SUBSCRIPTION_EXPIRATION_EMAIL_ENABLED IS TRUE)" in sql
    assert "THEN USERS.SUBSCRIPTION_EXPIRATION_EMAIL_ENABLED_AT" in sql
    assert "ELSE CLOCK_TIMESTAMP()" in sql


async def test_disable_is_unconditional_and_always_revocable() -> None:
    dao, session = _dao()

    await dao.set_subscription_expiration_email_preference(
        17,
        enabled=False,
    )

    sql = _sql(session)
    where_sql = sql.split(" RETURNING", maxsplit=1)[0]
    assert "USERS.ID =" in where_sql
    assert "USERS.EMAIL IS NOT NULL" not in where_sql
    assert "USERS.IS_EMAIL_VERIFIED" not in where_sql
    assert "USERS.IS_BLOCKED" not in where_sql
    assert "USERS.MERGED_INTO_USER_ID" not in where_sql
