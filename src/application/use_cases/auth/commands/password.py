import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.email_sender import EmailSender
from src.application.common.password_hasher import PasswordHasher
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.use_cases.auth._codes import (
    check_email_resend_cooldown,
    generate_email_verification_code,
    hash_email_verification_code,
)
from src.core.config import AppConfig
from src.core.constants import (
    EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
    EMAIL_PASSWORD_RESET_BODY_TEMPLATE,
    EMAIL_PASSWORD_RESET_SUBJECT,
)
from src.core.utils.time import datetime_now

PASSWORD_RESET_MAX_ATTEMPTS = 5
PASSWORD_RESET_ATTEMPT_WINDOW_SECONDS = 15 * 60
PASSWORD_RESET_LOCK_SECONDS = 60


def password_reset_identity(email: str, secret: str) -> str:
    normalized_email = email.strip().casefold()
    return hmac.new(secret.encode(), normalized_email.encode(), hashlib.sha256).hexdigest()


@dataclass
class ChangePasswordDto:
    current_password: str
    new_password: str


class ChangePassword(Interactor[ChangePasswordDto, UserDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        auth_session: AuthSessionDao,
        password_hasher: PasswordHasher,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.auth_session = auth_session
        self.password_hasher = password_hasher

    async def _execute(self, actor: UserDto, data: ChangePasswordDto) -> UserDto:
        if not self.password_hasher.verify(data.current_password, actor.password_hash or ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is invalid",
            )
        if self.password_hasher.verify(data.new_password, actor.password_hash or ""):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="New password must be different from current password",
            )

        actor.password_hash = self.password_hasher.hash(data.new_password)
        actor.token_version += 1

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during password update",
                )
            await self.uow.commit()

        await self.auth_session.revoke_all_user_tokens(actor.id)
        return updated


@dataclass
class RequestPasswordResetDto:
    email: str


@dataclass
class PasswordResetRequested:
    success: bool = True


class RequestPasswordReset(Interactor[RequestPasswordResetDto, PasswordResetRequested]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        email_sender: EmailSender,
        auth_session: AuthSessionDao,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.email_sender = email_sender
        self.auth_session = auth_session

    async def _execute(
        self, actor: UserDto, data: RequestPasswordResetDto
    ) -> PasswordResetRequested:
        identity_hash = password_reset_identity(
            data.email, self.config.crypt_key.get_secret_value()
        )
        try:
            reserved = await self.auth_session.reserve_password_reset_request(
                identity_hash, EMAIL_CODE_RESEND_COOLDOWN_SECONDS
            )
        except Exception:
            logger.warning("Password reset request limiter is unavailable")
            return PasswordResetRequested()
        if not reserved:
            return PasswordResetRequested()

        user = await self.user_dao.get_by_email(data.email)
        if not user or not user.password_hash or user.is_blocked:
            return PasswordResetRequested()

        if not self.email_sender.is_enabled:
            logger.warning("Password reset requested, but email delivery is disabled")
            return PasswordResetRequested()

        try:
            check_email_resend_cooldown(
                user.password_reset_expires_at,
                self.config.email.verification_code_ttl_minutes,
                EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
                datetime_now(),
            )
        except HTTPException:
            return PasswordResetRequested()

        code = generate_email_verification_code()
        expires_at = datetime_now() + timedelta(
            minutes=self.config.email.verification_code_ttl_minutes
        )

        try:
            await self.email_sender.send(
                to=data.email,
                subject=EMAIL_PASSWORD_RESET_SUBJECT,
                body=EMAIL_PASSWORD_RESET_BODY_TEMPLATE.format(
                    code=code, minutes=self.config.email.verification_code_ttl_minutes
                ),
            )
        except Exception as e:
            logger.warning(
                "Password reset email delivery failed (error_type={error_type})",
                error_type=type(e).__name__,
            )
            return PasswordResetRequested()

        user.password_reset_code_hash = hash_email_verification_code(
            code, self.config.crypt_key.get_secret_value()
        )
        user.password_reset_expires_at = expires_at
        user.password_reset_attempts = 0

        async with self.uow:
            updated = await self.user_dao.update(user)
            if not updated:
                logger.warning("User disappeared during password reset request")
                return PasswordResetRequested()
            await self.uow.commit()

        await self.auth_session.clear_password_reset_attempts(identity_hash)

        return PasswordResetRequested()


@dataclass
class ConfirmPasswordResetDto:
    email: str
    code: str
    new_password: str


class ConfirmPasswordReset(Interactor[ConfirmPasswordResetDto, UserDto]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        auth_session: AuthSessionDao,
        password_hasher: PasswordHasher,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.auth_session = auth_session
        self.password_hasher = password_hasher

    async def _execute(self, actor: UserDto, data: ConfirmPasswordResetDto) -> UserDto:
        secret = self.config.crypt_key.get_secret_value()
        identity_hash = password_reset_identity(data.email, secret)
        attempts = await self.auth_session.increment_password_reset_attempts(
            identity_hash, PASSWORD_RESET_ATTEMPT_WINDOW_SECONDS
        )
        if attempts > PASSWORD_RESET_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password reset attempts",
            )

        lock_token = secrets.token_urlsafe(24)
        locked = await self.auth_session.acquire_password_reset_lock(
            identity_hash, lock_token, PASSWORD_RESET_LOCK_SECONDS
        )
        if not locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Password reset is already in progress",
            )

        try:
            async with self.uow:
                user = await self.user_dao.get_by_email_for_update(data.email)
                if not user or not user.password_hash or user.is_blocked:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid or expired reset code",
                    )

                if not user.password_reset_code_hash or not user.password_reset_expires_at:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Password reset was not requested",
                    )
                if user.password_reset_expires_at < datetime_now():
                    raise HTTPException(
                        status_code=status.HTTP_410_GONE,
                        detail="Password reset code has expired",
                    )

                incoming_hash = hash_email_verification_code(data.code, secret)
                if not hmac.compare_digest(incoming_hash, user.password_reset_code_hash):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid or expired reset code",
                    )

                if self.password_hasher.verify(data.new_password, user.password_hash):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="New password must be different from current password",
                    )

                user.password_hash = self.password_hasher.hash(data.new_password)
                user.password_reset_code_hash = None
                user.password_reset_expires_at = None
                user.password_reset_attempts = 0
                user.token_version += 1

                updated = await self.user_dao.update(user)
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found during password reset",
                    )
                await self.uow.commit()
        finally:
            try:
                await self.auth_session.release_password_reset_lock(identity_hash, lock_token)
            except Exception:
                logger.warning("Password reset lock release failed; waiting for lock expiry")

        await self.auth_session.revoke_all_user_tokens(user.id)
        await self.auth_session.clear_password_reset_attempts(identity_hash)
        return updated
