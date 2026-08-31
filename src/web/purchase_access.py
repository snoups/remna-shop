from fastapi import HTTPException, status

from src.application.dto import UserDto
from src.core.enums import AuthType


def assert_web_payment_allowed(user: UserDto) -> None:
    """Allow Telegram-auth subscription actions without weakening email auth."""
    if user.auth_type == AuthType.TELEGRAM or user.is_email_verified:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Email must be verified before purchasing or extending a subscription",
    )
