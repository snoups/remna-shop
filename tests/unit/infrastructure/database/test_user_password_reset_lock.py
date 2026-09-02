from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.infrastructure.database.dao.user import UserDaoImpl


@pytest.mark.asyncio
async def test_password_reset_user_lookup_locks_database_row() -> None:
    repository = object.__new__(UserDaoImpl)
    repository.session = MagicMock()
    repository.session.scalar = AsyncMock(return_value=None)

    result = await repository.get_by_email_for_update("user@example.com")

    assert result is None
    statement = repository.session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
