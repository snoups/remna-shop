from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from src.application.dto import UserDto
from src.application.use_cases.auth._codes import hash_email_verification_code
from src.application.use_cases.auth.commands.password import (
    PASSWORD_RESET_MAX_ATTEMPTS,
    ConfirmPasswordReset,
    ConfirmPasswordResetDto,
    RequestPasswordReset,
    RequestPasswordResetDto,
    password_reset_identity,
)
from src.core.utils.time import datetime_now

EMAIL = "User@Example.com"
SECRET = "password-reset-test-secret"


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


@pytest.fixture
def user() -> UserDto:
    code = "123456"
    return UserDto(
        id=1,
        name="User",
        email=EMAIL,
        password_hash="old-password-hash",
        password_reset_code_hash=hash_email_verification_code(code, SECRET),
        password_reset_expires_at=datetime_now() + timedelta(minutes=5),
    )


def make_session(*, reserved: bool = True, attempts: int = 1, locked: bool = True) -> MagicMock:
    session = MagicMock()
    session.reserve_password_reset_request = AsyncMock(return_value=reserved)
    session.increment_password_reset_attempts = AsyncMock(return_value=attempts)
    session.clear_password_reset_attempts = AsyncMock()
    session.acquire_password_reset_lock = AsyncMock(return_value=locked)
    session.release_password_reset_lock = AsyncMock()
    session.revoke_all_user_tokens = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_request_is_generic_and_skips_lookup_when_rate_limited(
    config: SimpleNamespace,
) -> None:
    user_dao = MagicMock()
    user_dao.get_by_email = AsyncMock()
    email_sender = MagicMock(is_enabled=True)
    email_sender.send = AsyncMock()
    session = make_session(reserved=False)
    interactor = RequestPasswordReset(
        config=config,
        uow=FakeUnitOfWork(),
        user_dao=user_dao,
        email_sender=email_sender,
        auth_session=session,
    )

    result = await interactor.system(RequestPasswordResetDto(email=EMAIL))

    assert result.success is True
    user_dao.get_by_email.assert_not_awaited()
    email_sender.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_fails_closed_without_leaking_account_when_redis_is_down(
    config: SimpleNamespace,
) -> None:
    user_dao = MagicMock()
    user_dao.get_by_email = AsyncMock()
    email_sender = MagicMock(is_enabled=True)
    email_sender.send = AsyncMock()
    session = make_session()
    session.reserve_password_reset_request.side_effect = ConnectionError("redis unavailable")
    interactor = RequestPasswordReset(
        config=config,
        uow=FakeUnitOfWork(),
        user_dao=user_dao,
        email_sender=email_sender,
        auth_session=session,
    )

    result = await interactor.system(RequestPasswordResetDto(email=EMAIL))

    assert result.success is True
    user_dao.get_by_email.assert_not_awaited()
    email_sender.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_rejects_attempts_over_limit_before_database_lookup(
    config: SimpleNamespace,
) -> None:
    user_dao = MagicMock()
    user_dao.get_by_email_for_update = AsyncMock()
    session = make_session(attempts=PASSWORD_RESET_MAX_ATTEMPTS + 1)
    interactor = ConfirmPasswordReset(
        config=config,
        uow=FakeUnitOfWork(),
        user_dao=user_dao,
        auth_session=session,
        password_hasher=MagicMock(),
    )

    with pytest.raises(HTTPException) as exc:
        await interactor.system(
            ConfirmPasswordResetDto(email=EMAIL, code="123456", new_password="new-password")
        )

    assert exc.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    user_dao.get_by_email_for_update.assert_not_awaited()
    session.acquire_password_reset_lock.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_rejects_concurrent_use(config: SimpleNamespace) -> None:
    user_dao = MagicMock()
    user_dao.get_by_email_for_update = AsyncMock()
    session = make_session(locked=False)
    interactor = ConfirmPasswordReset(
        config=config,
        uow=FakeUnitOfWork(),
        user_dao=user_dao,
        auth_session=session,
        password_hasher=MagicMock(),
    )

    with pytest.raises(HTTPException) as exc:
        await interactor.system(
            ConfirmPasswordResetDto(email=EMAIL, code="123456", new_password="new-password")
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    user_dao.get_by_email_for_update.assert_not_awaited()
    session.release_password_reset_lock.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_code_is_preserved_when_lock_release_fails(
    config: SimpleNamespace, user: UserDto
) -> None:
    user_dao = MagicMock()
    user_dao.get_by_email_for_update = AsyncMock(return_value=user)
    user_dao.update = AsyncMock()
    session = make_session()
    session.release_password_reset_lock.side_effect = ConnectionError("redis unavailable")
    interactor = ConfirmPasswordReset(
        config=config,
        uow=FakeUnitOfWork(),
        user_dao=user_dao,
        auth_session=session,
        password_hasher=MagicMock(),
    )

    with pytest.raises(HTTPException) as exc:
        await interactor.system(
            ConfirmPasswordResetDto(email=EMAIL, code="999999", new_password="new-password")
        )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    user_dao.update.assert_not_awaited()
    session.release_password_reset_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_confirmation_is_single_use_and_revokes_sessions(
    config: SimpleNamespace, user: UserDto
) -> None:
    uow = FakeUnitOfWork()
    user_dao = MagicMock()
    user_dao.get_by_email_for_update = AsyncMock(return_value=user)
    user_dao.update = AsyncMock(side_effect=lambda value: value)
    session = make_session()
    password_hasher = MagicMock()
    password_hasher.verify.return_value = False
    password_hasher.hash.return_value = "new-password-hash"
    interactor = ConfirmPasswordReset(
        config=config,
        uow=uow,
        user_dao=user_dao,
        auth_session=session,
        password_hasher=password_hasher,
    )

    result = await interactor.system(
        ConfirmPasswordResetDto(email=EMAIL, code="123456", new_password="new-password")
    )

    assert result.password_hash == "new-password-hash"
    assert result.password_reset_code_hash is None
    assert result.password_reset_expires_at is None
    assert result.token_version == 1
    assert uow.commits == 1
    session.revoke_all_user_tokens.assert_awaited_once_with(user.id)
    session.clear_password_reset_attempts.assert_awaited_once()
    session.release_password_reset_lock.assert_awaited_once()


def test_password_reset_identity_is_normalized_and_does_not_expose_email() -> None:
    upper = password_reset_identity(EMAIL, SECRET)
    lower = password_reset_identity(f"  {EMAIL.lower()}  ", SECRET)

    assert upper == lower
    assert EMAIL.lower() not in upper
    assert len(upper) == 64
