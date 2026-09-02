from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from src.application.dto import UserDto
from src.application.use_cases.auth.commands.generic_email import (
    EMAIL_AUTH_ATTEMPT_LIMIT,
    CompleteGenericEmailAuth,
    CompleteGenericEmailAuthDto,
    StartGenericEmailAuth,
    StartGenericEmailAuthDto,
    email_auth_identity,
)

EMAIL = "User@Example.com"
SECRET = "generic-email-auth-test-secret"


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def config() -> SimpleNamespace:
    return SimpleNamespace(
        crypt_key=SecretStr(SECRET),
        email=SimpleNamespace(verification_code_ttl_minutes=10),
    )


def make_session(*, reserved: bool = True, attempts: int = 1, consumed: bool = True) -> MagicMock:
    session = MagicMock()
    session.reserve_email_auth_request = AsyncMock(return_value=reserved)
    session.store_email_auth_challenge = AsyncMock()
    session.increment_email_auth_attempts = AsyncMock(return_value=attempts)
    session.consume_email_auth_challenge = AsyncMock(return_value=consumed)
    session.clear_email_auth_attempts = AsyncMock()
    return session


def make_complete(
    config: SimpleNamespace,
    *,
    user: UserDto | None,
    session: MagicMock | None = None,
) -> tuple[CompleteGenericEmailAuth, MagicMock, MagicMock, FakeUnitOfWork, MagicMock]:
    user_dao = MagicMock()
    user_dao.get_by_email = AsyncMock(return_value=user)
    user_dao.update = AsyncMock(side_effect=lambda value: value)
    password_hasher = MagicMock()
    password_hasher.verify.return_value = True
    password_hasher.hash.return_value = "new-password-hash"
    register = MagicMock()
    register.system = AsyncMock()
    uow = FakeUnitOfWork()
    auth_session = session or make_session()
    interactor = CompleteGenericEmailAuth(
        config=config,
        uow=uow,
        user_dao=user_dao,
        auth_session=auth_session,
        password_hasher=password_hasher,
        register_email_user=register,
    )
    return interactor, user_dao, password_hasher, uow, register


@pytest.mark.asyncio
async def test_start_is_generic_and_never_queries_account_state(config: SimpleNamespace) -> None:
    sender = MagicMock(is_enabled=True)
    sender.send = AsyncMock()
    session = make_session()
    interactor = StartGenericEmailAuth(config=config, email_sender=sender, auth_session=session)

    result = await interactor.system(StartGenericEmailAuthDto(email=EMAIL))

    assert result.success is True
    identity = email_auth_identity(EMAIL, SECRET)
    session.reserve_email_auth_request.assert_awaited_once()
    assert session.reserve_email_auth_request.await_args.args[0] == identity
    session.store_email_auth_challenge.assert_awaited_once()
    sender.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_fails_closed_with_generic_response_when_redis_is_down(
    config: SimpleNamespace,
) -> None:
    sender = MagicMock(is_enabled=True)
    sender.send = AsyncMock()
    session = make_session()
    session.reserve_email_auth_request.side_effect = ConnectionError("redis unavailable")
    interactor = StartGenericEmailAuth(config=config, email_sender=sender, auth_session=session)

    result = await interactor.system(StartGenericEmailAuthDto(email=EMAIL))

    assert result.success is True
    session.store_email_auth_challenge.assert_not_awaited()
    sender.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_code_and_exhausted_budget_stop_before_database(
    config: SimpleNamespace,
) -> None:
    invalid_session = make_session(consumed=False)
    invalid, invalid_dao, _, _, _ = make_complete(config, user=None, session=invalid_session)
    with pytest.raises(HTTPException) as invalid_exc:
        await invalid.system(
            CompleteGenericEmailAuthDto(email=EMAIL, code="000000", password="password-1")
        )
    assert invalid_exc.value.status_code == status.HTTP_400_BAD_REQUEST
    invalid_dao.get_by_email.assert_not_awaited()

    limited_session = make_session(attempts=EMAIL_AUTH_ATTEMPT_LIMIT + 1)
    limited, limited_dao, _, _, _ = make_complete(config, user=None, session=limited_session)
    with pytest.raises(HTTPException) as limited_exc:
        await limited.system(
            CompleteGenericEmailAuthDto(email=EMAIL, code="123456", password="password-1")
        )
    assert limited_exc.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    limited_session.consume_email_auth_challenge.assert_not_awaited()
    limited_dao.get_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_password_is_verified_only_after_single_use_email_proof(
    config: SimpleNamespace,
) -> None:
    user = UserDto(id=1, email=EMAIL, name="User", password_hash="existing-hash")
    interactor, user_dao, hasher, uow, register = make_complete(config, user=user)

    result = await interactor.system(
        CompleteGenericEmailAuthDto(email=EMAIL, code="123456", password="password-1")
    )

    assert result.is_email_verified is True
    hasher.verify.assert_called_once_with("password-1", "existing-hash")
    hasher.hash.assert_not_called()
    register.system.assert_not_awaited()
    user_dao.update.assert_awaited_once()
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_passwordless_legacy_user_gets_first_password_after_email_proof(
    config: SimpleNamespace,
) -> None:
    user = UserDto(id=2, email=EMAIL, name="Telegram User", password_hash=None)
    interactor, _, hasher, _, _ = make_complete(config, user=user)

    result = await interactor.system(
        CompleteGenericEmailAuthDto(email=EMAIL, code="123456", password="password-1")
    )

    assert result.password_hash == "new-password-hash"
    assert result.is_email_verified is True
    hasher.verify.assert_not_called()
    hasher.hash.assert_called_once_with("password-1")


@pytest.mark.asyncio
async def test_unknown_email_registers_only_after_email_proof(config: SimpleNamespace) -> None:
    registered = UserDto(id=3, email=EMAIL, name="New User", password_hash="new-hash")
    interactor, user_dao, _, uow, register = make_complete(config, user=None)
    register.system.return_value = registered

    result = await interactor.system(
        CompleteGenericEmailAuthDto(email=EMAIL, code="123456", password="password-1")
    )

    assert result.is_email_verified is True
    register.system.assert_awaited_once()
    user_dao.update.assert_awaited_once_with(registered)
    assert uow.commits == 1


def test_email_auth_identity_is_normalized_and_private() -> None:
    upper = email_auth_identity(EMAIL, SECRET)
    lower = email_auth_identity(f"  {EMAIL.lower()}  ", SECRET)

    assert upper == lower
    assert EMAIL.lower() not in upper
    assert len(upper) == 64
