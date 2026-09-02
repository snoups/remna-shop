from types import SimpleNamespace

import pytest

from src.infrastructure.database.dao.user import UserDaoImpl


class ReferralCodeSession:
    def __init__(self, users: list[object | None]) -> None:
        self.users = iter(users)
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object | None:
        self.statements.append(statement)
        return next(self.users)


def _repository(session: ReferralCodeSession) -> UserDaoImpl:
    repository = object.__new__(UserDaoImpl)
    repository.session = session  # type: ignore[assignment]
    repository._convert_to_dto = lambda user: user  # type: ignore[method-assign]
    return repository


@pytest.mark.asyncio
async def test_old_referral_code_resolves_to_final_merge_target() -> None:
    old_owner = SimpleNamespace(id=11, merged_into_user_id=22)
    intermediate = SimpleNamespace(id=22, merged_into_user_id=33)
    canonical = SimpleNamespace(id=33, merged_into_user_id=None)
    session = ReferralCodeSession([old_owner, intermediate, canonical])

    result = await _repository(session).get_by_referral_code("OLD-CODE")

    assert result is canonical
    assert len(session.statements) == 3


@pytest.mark.asyncio
async def test_cyclic_referral_code_merge_chain_fails_closed() -> None:
    first = SimpleNamespace(id=11, merged_into_user_id=22)
    second = SimpleNamespace(id=22, merged_into_user_id=11)
    session = ReferralCodeSession([first, second, first])

    result = await _repository(session).get_by_referral_code("CYCLIC-CODE")

    assert result is None
    assert len(session.statements) == 3
