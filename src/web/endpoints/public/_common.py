import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

import jwt
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import Depends, HTTPException, Request, Response, status

from src.application.common.dao import UserDao
from src.application.common.dao.auth import AuthSessionDao
from src.application.dto import UserDto
from src.core.config import AppConfig
from src.core.constants import AUTH_ACCESS_TOKEN_TTL_SECONDS, AUTH_REFRESH_TOKEN_TTL_SECONDS
from src.web.schemas import AuthResponse


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    token_version: int


def _normalize_decimal_str(value: Decimal) -> str:
    if value == value.to_integral():
        return str(int(value))
    normalized = value.quantize(Decimal("0.01")).normalize()
    return format(normalized, "f")


def generate_access_token(user_id: int, token_version: int, key: str) -> tuple[str, datetime]:
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(seconds=AUTH_ACCESS_TOKEN_TTL_SECONDS)
    token = jwt.encode(
        {"sub": user_id, "ver": token_version, "iat": now, "exp": exp},
        key,
        algorithm="HS256",
    )
    return token, exp


def decode_access_token(token: str, key: str) -> AccessTokenClaims:
    payload = jwt.decode(token, key, algorithms=["HS256"], options={"verify_sub": False})
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as e:
        raise jwt.InvalidTokenError("Invalid 'sub' claim") from e
    try:
        token_version = int(payload.get("ver", 0))
    except (TypeError, ValueError) as e:
        raise jwt.InvalidTokenError("Invalid 'ver' claim") from e
    return AccessTokenClaims(user_id=user_id, token_version=token_version)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=AUTH_ACCESS_TOKEN_TTL_SECONDS,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=AUTH_REFRESH_TOKEN_TTL_SECONDS,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", httponly=True, secure=True, samesite="lax")
    response.delete_cookie("refresh_token", httponly=True, secure=True, samesite="lax")


async def issue_session(
    user: UserDto,
    config: AppConfig,
    auth_session: AuthSessionDao,
) -> tuple[str, str, AuthResponse]:
    if config.jwt_secret is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret not configured",
        )
    access_token, expires_at = generate_access_token(
        user.id,
        user.token_version,
        config.jwt_secret.get_secret_value(),
    )
    refresh_token = secrets.token_urlsafe(32)
    refresh_expires_at = datetime.now(tz=timezone.utc) + timedelta(
        seconds=AUTH_REFRESH_TOKEN_TTL_SECONDS
    )
    await auth_session.store_refresh_token(
        token=refresh_token,
        user_id=user.id,
        ttl=AUTH_REFRESH_TOKEN_TTL_SECONDS,
    )
    return (
        access_token,
        refresh_token,
        AuthResponse(
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
        ),
    )


# NOTE: The `FromDishka[...] = None` defaults are a required workaround for the
# dishka-fastapi integration: FastAPI inspects the signature and needs a default for
# non-path/query params, while dishka overwrites the value at call time. The `None`
# is never observed at runtime; the `type: ignore[assignment]` silences the mismatch.
@inject
async def _get_current_user(
    request: Request,
    user_dao: FromDishka[UserDao] = None,  # type: ignore[assignment]
    config: FromDishka[AppConfig] = None,  # type: ignore[assignment]
) -> UserDto:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        if config.jwt_secret is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT secret not configured",
            )
        claims = decode_access_token(token, config.jwt_secret.get_secret_value())
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    user = await user_dao.get_by_id(claims.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if claims.token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
    return user


CurrentUser = Annotated[UserDto, Depends(_get_current_user)]
