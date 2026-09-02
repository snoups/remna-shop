from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import SecretStr

from src.application.dto import UserDto
from src.application.use_cases.auth.commands.email import (
    RequestEmailVerification,
    RequestEmailVerificationDto,
)


class FakeUnitOfWork:
    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None


async def test_new_verification_target_clears_any_previous_reminder_consent() -> None:
    actor = UserDto(
        id=17,
        name="User",
        email=None,
        is_email_verified=False,
        subscription_expiration_email_enabled=True,
        subscription_expiration_email_enabled_at=datetime(
            2026, 8, 24, tzinfo=timezone.utc
        ),
    )
    user_dao = SimpleNamespace(
        get_by_email=AsyncMock(return_value=None),
        update=AsyncMock(side_effect=lambda current: current),
    )
    sender = SimpleNamespace(is_enabled=True, send=AsyncMock())
    config = SimpleNamespace(
        crypt_key=SecretStr("test-secret"),
        email=SimpleNamespace(verification_code_ttl_minutes=15),
    )
    use_case = RequestEmailVerification(
        config,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
    )

    await use_case(
        actor,
        RequestEmailVerificationDto(email="new@example.org"),
    )

    assert actor.pending_email == "new@example.org"
    assert actor.is_email_verified is False
    assert actor.subscription_expiration_email_enabled is False
    assert actor.subscription_expiration_email_enabled_at is None
    sender.send.assert_awaited_once()
